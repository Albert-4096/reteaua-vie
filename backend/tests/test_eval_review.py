"""T6: the human review sheet of the eval labels (eval/review.py): write, tick, read back."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL))

import review  # noqa: E402


def _tick(text: str, key: str, what: str, note: str | None = None) -> str:
    i = text.index(f"<!-- review {key} ")
    j = text.index(f"- [ ] {what}", i)
    text = text[:j] + f"- [x] {what}" + text[j + len(f"- [ ] {what}"):]
    if note:
        k = text.index("Notă: ", j)
        text = text[:k] + f"Notă: {note}" + text[k + len("Notă: "):]
    return text


def test_every_gold_list_is_one_group_with_the_notice_text(tmp_path):
    label = next(lab for lab in review.labels() if lab["postId"] == 11065)
    text = review.render(label, {"335": "Dâmbovița (Bucla)"})
    assert label["noticeText"].splitlines()[0] in text
    sheet = review.parse_sheet(text)
    assert set(sheet["groups"]) == {g["key"] for g in review.groups(label)}
    assert all(g["verdict"] == "open" for g in sheet["groups"].values())
    assert "`335` Dâmbovița (Bucla)" in text


def test_ticks_are_read_back_kept_on_rewrite_and_stale_when_the_label_changes(tmp_path, monkeypatch):
    labels = review.labels()
    label = next(lab for lab in labels if lab["postId"] == 11065)
    ok_key, wrong_key = (g["key"] for g in review.groups(label)[:2])
    for lab in labels:
        (tmp_path / f"{lab['postId']}.md").write_text(review.render(lab, {}), encoding="utf-8")
    path = tmp_path / "11065.md"
    text = _tick(_tick(path.read_text(encoding="utf-8"), ok_key, "ok"), wrong_key, "greșit", "lipsește 341")
    path.write_text(text.replace("Recenzent: \n", "Recenzent: Albert\n", 1), encoding="utf-8")

    got = review.read(tmp_path)
    n = got["notices"]["11065"]
    assert (n["ok"], n["wrong"], n["wrongGroups"], n["reviewer"]) == (1, 1, [wrong_key], "Albert")
    assert got["complete"] is False and got["allOk"] is False

    # rewriting keeps the verdicts and the note
    again = review.render(label, {}, review.parse_sheet(path.read_text(encoding="utf-8")))
    assert review.parse_sheet(again)["groups"][wrong_key] == {
        "hash": review.group_hash(review.groups(label)[1]["stopIds"]), "verdict": "wrong", "note": "lipsește 341"}

    # a label that changes after the review makes the group stale, never silently ok
    changed = copy.deepcopy(label)
    changed["gold"]["routeActions"][0]["suspendedStopIds"].append("999")
    monkeypatch.setattr(review, "labels", lambda: [changed if lab["postId"] == 11065 else lab for lab in labels])
    assert review.read(tmp_path)["notices"]["11065"]["stale"] == 1


def test_no_review_dir_reads_as_null(tmp_path):
    assert review.read(None) is None
    assert review.read(tmp_path / "missing") is None
