"""GET /api/layers/{layer}: map layers as LayerCollection (CONTRACT v2, step 0).

parking is served here (Timpark zones, streets and lots, city ids and colours); bike,
destinations and population come from their modules, imported lazily. While a module's
function is missing the layer answers 404 NOT_READY, so the UI shows „în lucru”.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable

from fastapi import APIRouter, Query

from app.common.city import parking_layer
from app.common.errors import ApiError, invalid, not_found
from app.models.v2 import LayerCollection

router = APIRouter(tags=["layers"])
log = logging.getLogger("reteaua_vie.layers")

# layer -> (module, function(bbox) -> LayerCollection dict)
MODULE_LAYERS: dict[str, tuple[str, str]] = {
    "bike": ("app.m5_bike.layers", "bike_layer"),
    "destinations": ("app.m4_access.layers", "destinations_layer"),
    "population": ("app.m4_access.layers", "population_layer"),
}


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    """`minLon,minLat,maxLon,maxLat` -> tuple, or None."""
    if not bbox:
        return None
    try:
        parts = tuple(float(x) for x in bbox.split(","))
    except ValueError:
        parts = ()
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise invalid("`bbox` must be minLon,minLat,maxLon,maxLat")
    return parts  # type: ignore[return-value]


@router.get("/layers/parking", response_model=LayerCollection)
def layer_parking(bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat")) -> dict:
    return parking_layer(parse_bbox(bbox))


def _layer_fn(layer: str) -> Callable | None:
    module, attr = MODULE_LAYERS[layer]
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name and module.startswith(e.name):
            return None  # the module is not written yet
        log.exception("layer module %s failed to import", module)
        return None
    except Exception:
        log.exception("layer module %s failed to import", module)
        return None
    fn = getattr(mod, attr, None)
    return fn if callable(fn) else None


@router.get("/layers/{layer}", response_model=LayerCollection)
def layer_other(layer: str, bbox: str | None = Query(None, description="minLon,minLat,maxLon,maxLat")) -> dict:
    if layer not in MODULE_LAYERS:
        raise not_found(f"Unknown layer {layer!r}; use parking, {', '.join(MODULE_LAYERS)}.", "UNKNOWN_LAYER")
    box = parse_bbox(bbox)
    fn = _layer_fn(layer)
    if fn is None:
        raise ApiError(404, "NOT_READY", f"Layer {layer!r} is not served yet (în lucru).")
    return fn(box)
