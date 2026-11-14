"""R5: GET /api/closures/{closureId}/km (JSON, or ?format=csv for SMTT)."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Query, Response

from app.cityapp import km

router = APIRouter(tags=["R5 km not run"])


@router.get("/closures/{closure_id}/km")
def get_km(closure_id: str, format: str = Query("json", pattern="^(json|csv)$")):
    rep = km.km_report(closure_id)
    if format == "json":
        return rep
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["inchidere", "mod", "linie", "sens", "statii_lipsa", "km_sectiune", "curse_in_fereastra", "km_nefacuti", "sursa_orar"])
    num = lambda v: "" if v is None else str(v).replace(".", ",")
    for ln in rep["lines"]:
        w.writerow([closure_id, ln["mode"], ln["shortName"], ln["directionId"], ln["stopsLost"], num(ln["sectionKm"]),
                    "" if ln["trips"] is None else ln["trips"], num(ln["kmNotRun"]), f"GTFS SMTT {rep['timetableVersion']}"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="km-{closure_id}.csv"'})
