"""R9: GET /api/layers/standstill. Lives in `cityapp` so it is mounted before the generic /layers/{layer} route."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.signals import waits

router = APIRouter(tags=["R9 signals"])


@router.get("/layers/standstill")
def get_standstill_layer(limit: int = Query(200, ge=1, le=300)) -> dict:
    """Step 0 layer „Unde stă transportul public”: L4's cells as GeoJSON points (vehicle-minutes standing)."""
    from app.analytics import streets
    try:
        st = streets.standing()
    except RuntimeError:
        from app.common.errors import unavailable
        raise unavailable("În lucru: înregistrarea nu e încă procesată.", code="IN_LUCRU")
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": p["location"]},
              "properties": {k: p[k] for k in ("cellId", "minutes", "minutesPerHour", "vehicles", "lines", "cause", "hours")}}
             for p in st["points"][:limit]]
    return {"type": "FeatureCollection", "layer": "standstill", "features": feats, "recording": st["recording"],
            "label": waits.LABEL.model_dump(), "provenance": st["provenance"]}
