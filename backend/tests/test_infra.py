"""The Docker stack matches SPEC §12: api on 3000, worker, read-only data, no baked secrets."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "infra"


@pytest.fixture(scope="module")
def compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((INFRA / "compose.yml").read_text(encoding="utf-8"))


def _volumes(service: dict) -> dict[str, str]:
    """target -> mode ("ro" or "rw") of the short-syntax volumes."""
    out = {}
    for v in service["volumes"]:
        parts = v.split(":")  # the source may hold ":?" (required variable): read from the right
        if parts[-1] in ("ro", "rw"):
            out[parts[-2]] = parts[-1]
        else:
            out[parts[-1]] = "rw"
    return out


def test_api_and_worker_share_one_image(compose):
    api, worker = compose["services"]["api"], compose["services"]["worker"]
    assert api["image"] == worker["image"]
    assert api["build"]["dockerfile"] == "infra/Dockerfile"
    assert "profiles" not in worker  # `make up` starts it
    assert worker["command"][-1] == "app.precompute"


def test_api_publishes_3000_on_all_interfaces_by_default(compose):
    ports = compose["services"]["api"]["ports"]
    assert ports == ["${RV_BIND:-0.0.0.0}:${RV_PORT:-3000}:3000"]


def test_data_is_read_only_except_state_and_cache(compose):
    for name in ("api", "worker"):
        vols = _volumes(compose["services"][name])
        assert vols == {"/data": "ro", "/data/state": "rw", "/data/cache": "rw"}, name
        assert compose["services"][name]["environment"]["DATA_DIR"] == "/data"


def test_secrets_come_from_env_file_only(compose):
    for name in ("api", "worker"):
        svc = compose["services"][name]
        assert svc["env_file"][0]["path"].startswith("${ENV_FILE")
        assert not any("KEY" in k for k in svc["environment"])
    ignore = (INFRA / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/.env" in ignore and "**/.env.*" in ignore
    dockerfile = (INFRA / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"(?im)^\s*(COPY|ADD)\b.*\.env\b", dockerfile)
    assert not re.search(r"(?i)API_KEY", dockerfile)


def test_image_has_java21_osmium_and_weasyprint_libs():
    dockerfile = (INFRA / "Dockerfile").read_text(encoding="utf-8")
    for pkg in ("openjdk-21-jre-headless", "osmium-tool", "libpango-1.0-0", "libpangoft2-1.0-0",
                "libharfbuzz-subset0", "fonts-noto-core"):
        assert pkg in dockerfile, pkg
    assert '"--host", "0.0.0.0", "--port", "3000"' in dockerfile
    assert "FRONTEND_DIST=/app/frontend/dist" in dockerfile


def test_makefile_has_demo_up_down():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    for target in ("web", "demo", "up", "down"):
        assert re.search(rf"(?m)^{target}:", makefile), target
    assert "up -d --build" in makefile
