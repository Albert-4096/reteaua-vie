"""Shared test setup.

Tests read the real data in $DATA_DIR (default /srv/unihack/app/data). Tests
that need it are skipped when it is missing, so a stranger can still run the
contract tests. Tests that write state get `isolated_state` (a temp state dir).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("DATA_DIR", "/srv/unihack/app/data")
os.environ.setdefault("ENV_FILE", "")

from app import config  # noqa: E402

DATA_DIR = Path(os.environ["DATA_DIR"])
HAS_CITY_DATA = (DATA_DIR / "city-api-2026-11-13" / "transit-network.json").is_file()

needs_data = pytest.mark.skipif(not HAS_CITY_DATA, reason=f"no city data in {DATA_DIR}")


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Point the state store at a temp dir; the real data stays read-only."""
    real = config.get_settings()
    fake = config.Settings(
        env_file=None,
        data_dir=tmp_path,
        live_dir=real.live_dir,
        demo_now=real.demo_now,
        data_freeze=False,
        public_base_url=real.public_base_url,
    )
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    import app.common.state as state_mod

    monkeypatch.setattr(state_mod, "get_settings", lambda: fake)
    config.ensure_dirs(fake)
    yield fake


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
