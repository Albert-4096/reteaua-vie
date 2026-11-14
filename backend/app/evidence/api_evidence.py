"""R13: GET /api/closures/{id}/journal, /bundle.json, /impact.csv, /windows.csv and GET /api/live/missing.csv."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.common.errors import invalid
from app.common.timeutil import parse_iso
from app.evidence import csvs, journal
from app.m1_disruption import impact as imp

router = APIRouter(tags=["R13 evidence"])


@router.get("/closures/{closure_id}/journal")
def get_journal(closure_id: str) -> dict:
    return journal.journal(closure_id)


@router.get("/closures/{closure_id}/bundle.json")
def get_bundle(closure_id: str, verify: int = Query(0, ge=0, le=1)) -> dict:
    return journal.bundle(closure_id, bool(verify))


@router.get("/closures/{closure_id}/impact.csv")
def impact_csv(closure_id: str):
    i = imp.compute_impact(closure_id)
    rows = [[z.name, z.stopsSuspended, z.departuresLost, z.residentsLosingStop, z.maxExtraWalkMeters] for z in i.byZone]
    t = i.totals
    rows.append(["TOTAL", t.stopsSuspended, t.departuresLost, t.residentsLosingStop, None])
    return csvs.response(f"impact-{closure_id}.csv", ["cartier", "statii_suspendate", "plecari_pierdute", "locuitori_fara_statie",
                                                     "mers_suplimentar_max_m"], rows)


@router.get("/closures/{closure_id}/windows.csv")
def windows_csv(closure_id: str):
    from app.m4_access import windows as win
    win.load_closure(closure_id)
    s = win.suggest(closure_id)
    rows = [[c.rank, c.window.start, c.window.end, c.departuresLost, c.residentsLosingStop, c.conflicts] for c in s.candidates]
    return csvs.response(f"ferestre-{closure_id}.csv", ["loc", "inceput", "sfarsit", "plecari_pierdute", "locuitori_fara_statie",
                                                       "conflicte"], rows)


@router.get("/live/missing.csv")
def missing_csv(from_: str | None = Query(None, alias="from"), to: str | None = Query(None), case: str | None = None):
    from app.live import missing
    if case:
        if case not in missing.CASES:
            raise invalid(f"`case` must be one of {', '.join(missing.CASES)}")
        res = missing.prepared(case)
    else:
        start, end = missing.live_window()
        if to:
            end = parse_iso(to.strip().replace(" ", "+"))
            start = end - missing.DEFAULT_WINDOW
        if from_:
            start = parse_iso(from_.strip().replace(" ", "+"))
        res = missing.detect(start, end)
    rows = [[m["mode"], m["tripsScheduled"], m["tripsWithNoVehicle"], m["share"]] for m in res["byMode"]]
    return csvs.response("linii-fara-vehicul.csv", ["mod", "curse_in_orar", "curse_fara_vehicul_in_datele_live", "pondere"], rows)
