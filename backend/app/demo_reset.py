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
"""

from __future__ import annotations

import argparse
import shutil

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
    was = state.delete("published", closure_id)  # the record and its parts (validation)
    if closure.get("status") == "published":
        state.update("closures", closure_id, lambda old: {**(old or closure), "status": "analyzed"})
    return {"closureId": closure_id, "wasPublished": bool(was or closure.get("status") == "published"), "status": "analyzed"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Take a published work back to 'analyzed' (demo reset).")
    ap.add_argument("closure_id", nargs="?", default=HERO)
    ap.add_argument("--force", action="store_true", help="also unpublish a prepared, pre-published case")
    ap.add_argument("--keep-drafts", action="store_true", help="do not remove the works added after the prepared ones")
    args = ap.parse_args()
    if not args.keep_drafts:
        gone = remove_added_works()
        print(f"removed {len(gone)} added work(s)" + (": " + ", ".join(gone) if gone else ""))
    try:
        out = unpublish(args.closure_id, args.force)
    except (LookupError, PermissionError) as exc:
        raise SystemExit(str(exc)) from None
    print(f"{out['closureId']}: {'unpublished' if out['wasPublished'] else 'was not published'}, status {out['status']}")


if __name__ == "__main__":
    main()
