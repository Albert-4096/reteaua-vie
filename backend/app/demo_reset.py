"""Demo reset: take a published work back to "not published yet", so Publish can be shown again.

    cd repo/backend && DATA_DIR=/srv/unihack/app/data uv run python -m app.demo_reset            # the hero work
    cd repo/backend && DATA_DIR=/srv/unihack/app/data uv run python -m app.demo_reset <closureId>

It removes only what Publish wrote: the publish record (and its feed validation) and the `published`
status. The closure, its analysis, the decisions a person took and the impact stay as they are, and the
evidence journal keeps every act, the earlier publish included. The alert leaves the feeds at once,
because they are read from the publish records on every call. Prepared cases that the platform shows
as already published (E3, Mocioni) are refused unless `--force` is given.

It also removes every work that is not one of the three prepared ones: "Lucrare nouă" saves a draft
each time a notice is pasted, and a draft somebody published would stay in the alert feeds. Pass
`--keep-drafts` to leave those works alone. The prepared works are never deleted.

The answers a person gave are part of the demo start too: one changed answer on the hero turns
16 stops / 2,262 departures into other numbers, and Publish does not undo it. So the reset puts the
work's closure files (closure, analysis, decisions, impact) back as the golden copy has them:

    ... python -m app.demo_reset --save-golden   # once, while the work is as the demo should start

The golden copy lives in DATA_DIR/demo-golden (private data, never in the repo). Without one, the
reset says so and leaves the answers as they are. `--keep-answers` skips the restore.

A feed validation that finishes after its publish record is gone leaves its result alone in
state/published (seen 15 Nov, written by a test whose temp state had already been taken down).
Each reset removes such leftovers, so two resets in a row always end on the same files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile

HERO = "cl_20261108_16dec"
# The prepared works of the demo. Nothing below deletes them.
SEEDED = ("cl_20261102_mocioni", "cl_20261107_e3", HERO)
# Where a work leaves files under its id: state, and caches that are rebuilt on demand.
_STATE_KINDS = ("closures", "published", "scenarios", "scans", "triage", "checkin")
_CACHE_GLOBS = (("r5/gtfs", "patched_{id}_*"), ("detour", "*{id}*"), ("audio", "*{id}*"), ("posters", "*{id}*"))


def remove_added_works(keep: tuple[str, ...] = SEEDED) -> list[str]:
    """Delete every work that is not in `keep`: its closure files, its publish record (so its alert
    leaves the feeds), its scenarios and scans, and its caches. Returns the ids removed, sorted."""
    from app import config
    from app.common import state

    settings = config.get_settings()
    removed = []
    for cid in state.list_ids("closures"):
        # never an id whose file pattern could also match a prepared work
        if cid in keep or not cid.startswith("cl_") or any(cid in k or k in cid for k in keep):
            continue
        with state.locked():
            for kind in _STATE_KINDS:
                folder = settings.state_dir / kind
                if folder.is_dir():
                    for path in folder.glob(f"*{cid}*"):
                        if path.is_file():
                            path.unlink(missing_ok=True)
        for sub, pattern in _CACHE_GLOBS:
            folder = settings.cache_dir / sub
            if folder.is_dir():
                for path in folder.glob(pattern.format(id=cid)):
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)
        removed.append(cid)
    return removed


def _closure_files(folder, closure_id: str) -> list:
    """The work's own files in a folder: <id>.json and its parts <id>.<part>.json, nothing of another id."""
    return sorted([*folder.glob(f"{closure_id}.json"), *folder.glob(f"{closure_id}.*.json")])


def _golden_dir():
    from app import config

    return config.get_settings().data_dir / "demo-golden" / "closures"


def save_golden(closure_id: str = HERO) -> list[str]:
    """Keep the work's closure files as the state every reset returns to. Returns the file names.
    Raises LookupError for an unknown closure, PermissionError for a published one (the demo
    starts before Publish)."""
    from app import config
    from app.common import state

    closure = state.read("closures", closure_id)
    if closure is None:
        raise LookupError(f"unknown closure: {closure_id}")
    if closure.get("status") == "published" or state.exists("published", closure_id):
        raise PermissionError(f"{closure_id} is published; reset it first, the golden copy is the work before Publish")
    golden = _golden_dir()
    golden.mkdir(parents=True, exist_ok=True)
    with state.locked():
        for old in _closure_files(golden, closure_id):
            old.unlink()
        files = _closure_files(config.get_settings().state_dir / "closures", closure_id)
        for path in files:
            shutil.copyfile(path, golden / path.name)
    return [p.name for p in files]


def restore_golden(closure_id: str = HERO) -> dict | None:
    """Put the work's closure files back as the golden copy has them. None when there is no golden
    copy, else {"restored": [files that differed], "removed": [parts the golden copy does not have]}."""
    from app import config
    from app.common import state

    golden = _closure_files(_golden_dir(), closure_id)
    if not golden:
        return None
    folder = config.get_settings().state_dir / "closures"
    folder.mkdir(parents=True, exist_ok=True)
    restored, removed = [], []
    with state.locked():
        for src in golden:
            dst = folder / src.name
            if dst.is_file() and dst.read_bytes() == src.read_bytes():
                continue
            fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=folder)
            with os.fdopen(fd, "wb") as fh:
                fh.write(src.read_bytes())
            os.chmod(tmp, state.FILE_MODE)
            os.replace(tmp, dst)  # readers see the old file or the new one, never half of it
            restored.append(src.name)
        names = {p.name for p in golden}
        for extra in _closure_files(folder, closure_id):
            if extra.name not in names:
                extra.unlink()
                removed.append(extra.name)
    return {"restored": restored, "removed": removed}


def remove_orphan_publish_parts() -> list[str]:
    """Delete publish parts (a late feed validation) that have no publish record beside them."""
    from app import config
    from app.common import state

    folder = config.get_settings().state_dir / "published"
    gone = []
    if folder.is_dir():
        with state.locked():
            records = {p.name[:-5] for p in folder.glob("*.json") if "." not in p.name[:-5]}
            for path in sorted(folder.glob("*.*.json")):
                if path.name.split(".")[0] not in records:
                    path.unlink(missing_ok=True)
                    gone.append(path.name)
    return gone


def unpublish(closure_id: str, force: bool = False) -> dict:
    """Returns {closureId, wasPublished, status}. Raises LookupError for an unknown closure,
    PermissionError for a reconstructed (pre-published) case without `force`."""
    from app.common import state

    closure = state.read("closures", closure_id)
    if closure is None:
        raise LookupError(f"unknown closure: {closure_id}")
    record = state.read("published", closure_id)
    if record and record.get("reconstructed") and not force:
        raise PermissionError(f"{closure_id} is a prepared case shown as published; pass --force to unpublish it")
    was = record is not None or closure.get("status") == "published"  # a validation file alone is not a publish
    state.delete("published", closure_id)  # the record and its parts (validation)
    if closure.get("status") == "published":
        state.update("closures", closure_id, lambda old: {**(old or closure), "status": "analyzed"})
    return {"closureId": closure_id, "wasPublished": was, "status": "analyzed"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Take a published work back to 'analyzed' (demo reset).")
    ap.add_argument("closure_id", nargs="?", default=HERO)
    ap.add_argument("--force", action="store_true", help="also unpublish a prepared, pre-published case")
    ap.add_argument("--keep-drafts", action="store_true", help="do not remove the works added after the prepared ones")
    ap.add_argument("--keep-answers", action="store_true", help="do not restore the work's answers from the golden copy")
    ap.add_argument("--save-golden", action="store_true",
                    help="save the work as it is now as the state every reset returns to, then stop")
    args = ap.parse_args()
    if args.save_golden:
        try:
            names = save_golden(args.closure_id)
        except (LookupError, PermissionError) as exc:
            raise SystemExit(str(exc)) from None
        print(f"{args.closure_id}: golden copy saved ({len(names)} files: {', '.join(names)})")
        return
    if not args.keep_drafts:
        gone = remove_added_works()
        print(f"removed {len(gone)} added work(s)" + (": " + ", ".join(gone) if gone else ""))
    # the files first, then the publish record: a reset then also repairs a closure file that went missing
    back = None if args.keep_answers else restore_golden(args.closure_id)
    late = remove_orphan_publish_parts()
    if late:
        print(f"removed {len(late)} validation file(s) with no publish record: {', '.join(late)}")
    try:
        out = unpublish(args.closure_id, args.force)
    except (LookupError, PermissionError) as exc:
        raise SystemExit(str(exc)) from None
    print(f"{out['closureId']}: {'unpublished' if out['wasPublished'] else 'was not published'}, status {out['status']}")
    if args.keep_answers:
        pass
    elif back is None:
        print(f"{args.closure_id}: NO golden copy, the answers are left as they are (run --save-golden once)")
    elif back["restored"] or back["removed"]:
        print(f"{args.closure_id}: answers restored from the golden copy ({', '.join(back['restored'] + back['removed'])})")
    else:
        print(f"{args.closure_id}: answers already as in the golden copy")


if __name__ == "__main__":
    main()
