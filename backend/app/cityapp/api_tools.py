"""R3: GET /api/tools.json."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.cityapp import tools

router = APIRouter(tags=["R3 tools for Timi"])


@router.get("/tools.json")
def tools_json(request: Request) -> dict:
    return tools.build(request.app)
