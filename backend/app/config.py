"""Runtime configuration.

The app reads outside repo/ only through two env vars: ENV_FILE (an optional
KEY=VALUE file with secrets) and DATA_DIR (the data cache). Values already set
in the process environment win over the env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")

DEFAULT_DEMO_NOW = "2026-11-08T12:00:00+02:00"
DEFAULT_PUBLIC_BASE_URL = "https://unihack.alberyt.xyz"
DEFAULT_DATA_DIR = "/srv/unihack/app/data"

STATE_KINDS = ("closures", "scenarios", "published", "scans")


def load_env_file(path: str | os.PathLike | None) -> int:
    """Load KEY=VALUE lines into os.environ without overriding set values.

    A missing or empty file is fine. Returns how many keys were set.
    Values are never logged.
    """
    if not path:
        return 0
    p = Path(path)
    if not p.is_file():
        return 0
    count = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def _parse_demo_now(raw: str | None) -> datetime | None:
    """`real` (or empty after explicit set) means the real clock: None."""
    value = (raw if raw is not None else DEFAULT_DEMO_NOW).strip()
    if value.lower() in ("", "real", "none", "off"):
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


@dataclass(frozen=True)
class Settings:
    env_file: Path | None
    data_dir: Path
    live_dir: Path
    demo_now: datetime | None
    data_freeze: bool
    public_base_url: str

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def city_dir(self) -> Path:
        return self.data_dir / "city-api-2026-11-13"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = os.environ.get("ENV_FILE") or None
    load_env_file(env_file)
    data_dir = Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR)
    live_dir = Path(os.environ.get("LIVE_DIR") or data_dir / "live")
    return Settings(
        env_file=Path(env_file) if env_file else None,
        data_dir=data_dir,
        live_dir=live_dir,
        demo_now=_parse_demo_now(os.environ.get("DEMO_NOW")),
        data_freeze=os.environ.get("DATA_FREEZE", "").strip() in ("1", "true", "yes"),
        public_base_url=(os.environ.get("PUBLIC_BASE_URL") or DEFAULT_PUBLIC_BASE_URL).rstrip("/"),
    )


def secret(name: str) -> str | None:
    """Read an optional secret (API key). Never log the value."""
    get_settings()  # make sure ENV_FILE is loaded
    value = os.environ.get(name, "").strip()
    return value or None


def now() -> datetime:
    """The app's "now": DEMO_NOW when set, else the real clock, in Bucharest time."""
    s = get_settings()
    if s.demo_now is not None:
        return s.demo_now
    return datetime.now(TZ)


def real_now() -> datetime:
    return datetime.now(TZ)


def ensure_dirs(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    for kind in STATE_KINDS:
        (s.state_dir / kind).mkdir(parents=True, exist_ok=True)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
