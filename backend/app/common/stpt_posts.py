"""Reader for the recorded STPT notices ($LIVE_DIR/stpt-posts/<id>_<time>.json).

Each file is one WordPress post as the recorder saved it. A post may be saved
more than once (edits); `load_posts()` keeps the newest file per id.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.common import provenance as prov
from app.common.timeutil import parse_iso
from app.config import get_settings
from app.models.base import Provenance

_SUP = re.compile(r"<sup>\s*(\d{2})\s*</sup>", re.I)
_BLOCK = re.compile(r"</(p|h[1-6]|li|div)>|<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t ]+")


@dataclass(frozen=True)
class StptPost:
    id: int
    date: datetime          # post date, Bucharest time
    modified: datetime
    link: str
    title: str
    html: str
    text: str               # plain text, one paragraph per line, "10<sup>00</sup>" -> "10:00"
    categories: list[int]
    path: Path

    def provenance(self) -> Provenance:
        return prov.for_file("STPT, anunț / notice (stpt.ro)", self.path, self.link, str(self.id))


def html_to_text(raw: str) -> str:
    s = _SUP.sub(r":\1", raw)
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub("", s)
    s = html.unescape(s)
    lines = [_SPACES.sub(" ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def posts_dir() -> Path:
    return get_settings().live_dir / "stpt-posts"


def _load(path: Path) -> StptPost:
    d = json.loads(path.read_text(encoding="utf-8"))
    title = html.unescape(_TAG.sub("", d.get("title", {}).get("rendered", ""))).strip()
    body = d.get("content", {}).get("rendered", "")
    return StptPost(
        id=int(d["id"]),
        date=parse_iso(d["date"]),
        modified=parse_iso(d.get("modified") or d["date"]),
        link=d.get("link", ""),
        title=title,
        html=body,
        text=html_to_text(body),
        categories=list(d.get("categories") or []),
        path=path,
    )


@lru_cache(maxsize=1)
def _load_all(signature: tuple) -> dict[int, StptPost]:
    newest: dict[int, StptPost] = {}
    for name, _mtime in signature:
        post = _load(posts_dir() / name)
        old = newest.get(post.id)
        if old is None or post.path.name > old.path.name:
            newest[post.id] = post
    return newest


def load_posts() -> dict[int, StptPost]:
    """{post id: newest saved version}."""
    d = posts_dir()
    if not d.is_dir():
        return {}
    sig = tuple(sorted((p.name, p.stat().st_mtime) for p in d.glob("*.json")))
    return _load_all(sig)


def get_post(post_id: int) -> StptPost | None:
    return load_posts().get(int(post_id))
