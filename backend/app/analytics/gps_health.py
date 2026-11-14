"""A1 (in L3): GPS health per vehicle, from the vehicle reports L0 holds (de-duplicated on (vehicle, updatedAt)).

Two things, both while a vehicle has an active trip (consecutive reports carry the same tripId):
  silent gap   no new report for at least GAP_MIN minutes in the middle of a trip;
  frozen       standing still (moved at most STILL_M m) for at least GAP_MIN minutes without being at a stop
               (status not STOPPED_AT): a stuck position, a breakdown or a jam: we cannot tell which.
The list is for STPT to check a device before the 120-minute tolerance named in the contract is reached.
We do not know that tolerance's exact terms: the number is shown as a countdown, not as a finding.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.analytics import accessibility
from app.common.timeutil import from_unix, iso
from app.models.base import I18n
from app.observed import store

GAP_MIN = 10
CHECK_MIN = 30
TOLERANCE_MIN = 120
STILL_M = 15.0
TTL_SEC = 300

WORDING = I18n(ro="Estimare din datele live, nu raportul oficial.", en="Estimate from the live data, not the official report.")
METHOD = I18n(
    ro=(f"Din rapoartele vehiculelor (fluxul Primăriei), fiecare raport o dată. Pauză: nicio raportare timp de "
        f"{GAP_MIN} min sau mai mult în mijlocul unei curse. Pe loc: poziția s-a mișcat cel mult {STILL_M:.0f} m "
        f"timp de {GAP_MIN} min sau mai mult, în afara unei stații. „De verificat” de la {CHECK_MIN} min; "
        f"„minute până la {TOLERANCE_MIN}” e un numărătoare inversă față de toleranța din contract, ai cărei "
        "termeni exacți sunt de verificat."),
    en=(f"From de-duplicated vehicle reports. Silent gap: no report for {GAP_MIN}+ min mid-trip. Frozen: moved at "
        f"most {STILL_M:.0f} m for {GAP_MIN}+ min between stops. A countdown to the 120-minute tolerance."))
CAVEAT = I18n(
    ro=("O pauză sau un vehicul pe loc nu înseamnă o defecțiune a aparatului: poate fi și un blocaj în trafic sau o "
        "oprire la capăt. Lista e pentru verificare; nu arată vina nimănui."),
    en="A gap or a standing vehicle is not proof of a faulty device: it may be a jam or a layover. A list to check.")
_memo: dict = {}


def _episodes(r: pd.DataFrame, still: bool) -> pd.DataFrame:
    """Longest-run table per vehicle: (vid, start, minutes) of runs of consecutive qualifying report pairs."""
    r = r.sort_values(["vid", "t"]).reset_index(drop=True)
    same = (r["vid"] == r["vid"].shift()) & (r["trip"] == r["trip"].shift())
    dt = r["t"] - r["t"].shift()
    if still:
        dist = np.hypot(r["x"] - r["x"].shift(), r["y"] - r["y"].shift())
        ok = same & (dist <= STILL_M) & (~r["stopped"].astype(bool)) & (~r["stopped"].shift().fillna(True).astype(bool))
        # a still run = consecutive ok pairs; its length = last t - t before the first pair
        run = (~ok).cumsum()
        g = r[ok].assign(run=run[ok], t0=r["t"].shift()[ok]).groupby("run").agg(
            vid=("vid", "first"), start=("t0", "min"), end=("t", "max"))
        g["min"] = (g["end"] - g["start"]) / 60
        return g[g["min"] >= GAP_MIN][["vid", "start", "min"]]
    layover = r["stopped"].astype(bool) & r["stopped"].shift().fillna(False).astype(bool)   # waiting at a stop
    gap = same & (dt >= GAP_MIN * 60) & ~layover
    g = pd.DataFrame({"vid": r["vid"][gap], "start": r["t"].shift()[gap], "min": dt[gap] / 60})
    return g


def report() -> dict:
    stamp = store._stamp()
    hit = _memo.get("r")
    if hit and hit[1] == stamp and time.monotonic() - hit[0] < TTL_SEC:
        return hit[2]
    cov = store.coverage()
    if cov is None:
        raise RuntimeError("L0 has no built hour yet (în lucru)")
    r = store.reports()
    names = accessibility._route_names()
    gaps, frozen = _episodes(r, False), _episodes(r, True)
    last = r.groupby("vid")["t"].max()
    routes = r.groupby("vid")["route"].agg(lambda s: sorted({x for x in s if x}))
    rows = []
    for vid in sorted(set(gaps["vid"]) | set(frozen["vid"])):
        g, f = gaps[gaps["vid"] == vid], frozen[frozen["vid"] == vid]
        gm, fm = (float(g["min"].max()) if len(g) else None), (float(f["min"].max()) if len(f) else None)
        longest = max(x for x in (gm, fm) if x is not None)
        src = g if gm is not None and (fm is None or gm >= fm) else f
        at = float(src.loc[src["min"].idxmax(), "start"])
        rows.append({"vehicleId": str(vid), "routes": [names.get(x, (x, ""))[0] for x in routes.get(vid, [])],
                     "reports": int((r["vid"] == vid).sum()), "lastReportAt": iso(from_unix(float(last[vid]))),
                     "silentGaps": int(len(g)), "longestGapMin": round(gm, 1) if gm is not None else None,
                     "frozenEpisodes": int(len(f)), "longestFrozenMin": round(fm, 1) if fm is not None else None,
                     "longestMin": round(longest, 1), "longestAt": iso(from_unix(at)),
                     "toToleranceMin": round(max(0.0, TOLERANCE_MIN - longest), 1),
                     "status": "de verificat" if longest >= CHECK_MIN else "de urmărit"})
    rows.sort(key=lambda x: -x["longestMin"])
    out = {"recording": accessibility.recording_info(cov["first"], cov["last"]), "gapMin": GAP_MIN, "checkMin": CHECK_MIN,
           "toleranceMin": TOLERANCE_MIN, "vehiclesSeen": int(r["vid"].nunique()), "vehicles": rows,
           "wording": WORDING.model_dump(), "method": METHOD.model_dump(), "caveat": CAVEAT.model_dump(),
           "provenance": [p.model_dump() for p in accessibility.provenances(cov["first"], cov["last"], "orar observat L0")]}
    _memo["r"] = (time.monotonic(), stamp, out)
    return out
