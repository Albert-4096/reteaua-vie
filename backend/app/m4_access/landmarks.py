"""R28: which of the City Hall's tourist-guide landmarks lose their nearest stop in a closure.

For each landmark (/api/mobile/pois, name exactly as given) the nearest stop of the feed in
force that has any scheduled call, in a straight line. The landmark "loses" it when that stop
is one of the closure's lost rows (conflicts._lost). `nearestServed` is the nearest stop that
keeps its service, so a poster can say where to get off instead. Distances are straight-line.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from app.common import gtfs, state
from app.common.city import load_landmarks
from app.common.errors import ApiError, not_found
from app.common.geo import project_lonlats
from app.m1_disruption import conflicts as cf
from app.models.base import I18n
from app.models.v2 import LandmarkImpact, LandmarkItem, LandmarkStop


def landmark_impact(closure_id: str) -> LandmarkImpact:
    try:
        closure = state.read("closures", closure_id)
    except ValueError:
        closure = None
    if closure is None:
        raise not_found(f"No closure {closure_id}.")
    analysis = state.read("closures", closure_id, state.PART_ANALYSIS)
    if analysis is None:
        raise ApiError(409, "ANALYSIS_MISSING", f"Closure {closure_id} has not been analysed yet (POST /analyze).")
    got = load_landmarks()
    if got is None:
        raise ApiError(503, "DATA_UNAVAILABLE", "Landmarks file missing: pois.json (fetch_city.py --only pois).")
    landmarks, p = got
    lost = set(cf._lost(analysis))
    f = gtfs.feed()
    called = set(f.stop_times.stop_id)
    st = f.stops[f.stops.stop_id.isin(called)].reset_index(drop=True)
    ids, names = st.stop_id.astype(str).tolist(), st.stop_name.tolist()
    xy = project_lonlats(zip(st.stop_lon.astype(float), st.stop_lat.astype(float)))
    keep = np.array([i not in lost for i in ids])
    all_tree = cKDTree(xy)
    served_tree = cKDTree(xy[keep]) if keep.any() else None
    served_idx = np.nonzero(keep)[0]
    pts = project_lonlats((lm.lon, lm.lat) for lm in landmarks)

    def stop(i: int, d: float) -> LandmarkStop:
        return LandmarkStop(stopId=ids[i], name=names[i], meters=int(round(d)))

    items = []
    for lm, pt in zip(landmarks, pts):
        d, i = all_tree.query(pt)
        ns = stop(int(i), float(d))
        served = None
        if served_tree is not None:
            d2, j = served_tree.query(pt)
            served = stop(int(served_idx[int(j)]), float(d2))
        items.append(LandmarkItem(id=lm.id, name=lm.name, nameEn=lm.nameEn, address=lm.address, nearestStop=ns,
                                  losesService=ids[int(i)] in lost, nearestServed=served))
    n = sum(1 for x in items if x.losesService)
    items.sort(key=lambda x: (not x.losesService, x.name))
    ro = f"{n} obiective din ghidul turistic al Primăriei pierd stația cea mai apropiată." if n != 1 else \
        "1 obiectiv din ghidul turistic al Primăriei pierde stația cea mai apropiată."
    en = f"{n} landmarks of the City Hall's tourist guide lose their nearest stop." if n != 1 else \
        "1 landmark of the City Hall's tourist guide loses its nearest stop."
    return LandmarkImpact(closureId=closure_id, total=len(items), losingNearestStop=n, items=items,
                          summary=I18n(ro=ro, en=en), provenance=[p, f.provenance])
