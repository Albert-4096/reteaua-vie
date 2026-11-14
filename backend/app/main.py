"""FastAPI entry point.

Routers are discovered: every module named `api*.py` inside a package under
app/ that defines `router` (an APIRouter) is mounted under /api. Other agents
add endpoints by adding such a module; they never need to touch this file.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import ensure_dirs, get_settings
from app.common.errors import ApiError

log = logging.getLogger("reteaua_vie")

APP_DIR = Path(__file__).resolve().parent

STATUS_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "INVALID_INPUT",
    500: "INTERNAL",
    501: "NOT_IMPLEMENTED",
    503: "UNAVAILABLE",
}


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def discover_routers() -> tuple[list[tuple[str, APIRouter]], list[str]]:
    """Import app/<package>/api*.py modules that define `router`.

    A module that fails to import is logged and skipped, so one broken module never
    takes the rest of the API down. Returns (routers, names of the failed modules).
    """
    found: list[tuple[str, APIRouter]] = []
    failed: list[str] = []
    for pkg in sorted(p for p in APP_DIR.iterdir() if (p / "__init__.py").is_file()):
        for mod in pkgutil.iter_modules([str(pkg)]):
            if mod.ispkg or not mod.name.startswith("api"):
                continue
            name = f"app.{pkg.name}.{mod.name}"
            try:
                module = importlib.import_module(name)
            except Exception:
                log.exception("router module %s failed to import; skipped", name)
                failed.append(name)
                continue
            router = getattr(module, "router", None)
            if isinstance(router, APIRouter):
                found.append((name, router))
    return found, failed


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs(get_settings())
    yield


app = FastAPI(
    title="Rețeaua Vie API",
    description="Mobility back office for Timișoara (UniHack 8). All routes under /api.",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url=None,
)

ROUTER_MODULES: list[str] = []
MODULES_FAILED: list[str] = []  # read by GET /api/health (`modulesFailed`)
_routers, _failed = discover_routers()
MODULES_FAILED.extend(_failed)
for _name, _router in _routers:
    try:
        app.include_router(_router, prefix="/api")
    except Exception:
        log.exception("router module %s failed to mount; skipped", _name)
        MODULES_FAILED.append(_name)
        continue
    ROUTER_MODULES.append(_name)


@app.exception_handler(ApiError)
async def _api_error(_req: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req: Request, exc: StarletteHTTPException):
    code = STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    if exc.status_code == 404 and message == "Not Found":
        message = "No such resource."
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message), headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def _validation_error(_req: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg')}")
    return JSONResponse(status_code=422, content=error_body("INVALID_INPUT", "; ".join(parts) or "Invalid input."))


@app.exception_handler(Exception)
async def _internal_error(_req: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content=error_body("INTERNAL", f"{type(exc).__name__}: internal error."))


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def _unknown_api_path(rest: str):
    return JSONResponse(status_code=404, content=error_body("NOT_FOUND", f"Unknown API path: /api/{rest}"))


# --- the built frontend at / (SPEC §12: `make demo` and the Docker image serve one port) ---

FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST") or APP_DIR.parents[1] / "frontend" / "dist")


def mount_frontend(target: FastAPI, dist: Path) -> bool:
    """Serve `dist` at / with an SPA fallback.

    When dist/v1.html exists (the first app, built next to frontend-v3 by `make web`), it
    answers its own routes: /step/* and the QR phone page /a/{closureId}?stop=; every other
    path gets index.html (frontend-v3: / and /app/*). Does nothing when dist/index.html is
    missing (dev: Vite serves the frontend). Never answers under /api: those paths are
    matched by the API routes registered before it.
    """
    index = dist / "index.html"
    v1 = dist / "v1.html"
    if not index.is_file():
        return False
    root = dist.resolve()

    @target.get("/{path:path}", include_in_schema=False)
    async def _frontend(path: str):
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content=error_body("NOT_FOUND", f"Unknown API path: /{path}"))
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return FileResponse(candidate)
        if path in ("step", "v1") or path.startswith(("step/", "a/")):
            if v1.is_file():
                return FileResponse(v1)
        return FileResponse(index)

    return True


FRONTEND_MOUNTED = mount_frontend(app, FRONTEND_DIST)
