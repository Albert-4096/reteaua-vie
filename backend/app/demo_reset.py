"""Demo reset: take a published work back to "not published yet", so Publish can be shown again.

    cd repo/backend && DATA_DIR=/srv/unihack/app/data uv run python -m app.demo_reset            # the hero work
    cd repo/backend && DATA_DIR=/srv/unihack/app/data uv run python -m app.demo_reset <closureId>

It removes only what Publish wrote: the publish record (and its feed validation) and the `published`
status. The closure, its analysis, the decisions a person took and the impact stay as they are, and the
evidence journal keeps every act, the earlier publish included. The alert leaves the feeds at once,
because they are read from the publish records on every call. Prepared cases that the platform shows
as already published (E3, Mocioni) are refused unless `--force` is given.
"""

from __future__ import annotations

import argparse

HERO = "cl_20261108_16dec"


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
    args = ap.parse_args()
    try:
        out = unpublish(args.closure_id, args.force)
    except (LookupError, PermissionError) as exc:
        raise SystemExit(str(exc)) from None
    print(f"{out['closureId']}: {'unpublished' if out['wasPublished'] else 'was not published'}, status {out['status']}")


if __name__ == "__main__":
    main()
