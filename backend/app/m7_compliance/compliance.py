"""EU obligations and what OUR exports cover (SPEC §6.7): GET /api/compliance.

The status always describes the exports of Rețeaua Vie, never the City Hall: „acoperit de
exporturile Rețeaua Vie”. Statuses come from the SPEC table (Albert reviews them before the
pitch); deadlines from the team's checked facts (EU acts). `coveredBy` is computed from the
exports the running API serves: an obligation whose exports are all missing becomes `missing`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app import config
from app.common import provenance as prov
from app.common.timeutil import iso
from app.m7_compliance.exports import available
from app.models.base import I18n
from app.models.v2 import ComplianceCounts, ComplianceReport, Obligation

COVERED_BY_US = "acoperit de exporturile Rețeaua Vie"
COVERED_BY_US_EN = "covered by the Rețeaua Vie exports"


@dataclass(frozen=True)
class Rule:
    id: str
    act: str
    requirement: I18n
    deadline: str | None
    owner: I18n
    status: str                 # SPEC §6.7 table, for our exports
    exports: tuple[str, ...]    # export names that carry it
    why: I18n                   # SPEC §6.7 "Why"


RULES: tuple[Rule, ...] = (
    Rule("MMTIS", "Reg. delegat (UE) 2017/1926, mod. 2024/490",
         I18n(ro="Date de călătorie multimodale prin punctul național de acces: perturbări, istoricul întârzierilor, "
                 "parcări (doar date deja digitale)",
              en="Multimodal travel data through the National Access Point: disruptions, delay history, parking "
                 "(only data that is already digital)"),
         "2025-12-01",
         I18n(ro="Autoritățile și operatorii de transport (Primăria, STPT)",
              en="Transport authorities and operators (City Hall, STPT)"),
         "partial", ("alerts.pb", "history.json", "nap-metadata.json"),
         I18n(ro="Perturbările da, istoricul întârzierilor nu. Termene: parcări 1 dec 2024, istoric întârzieri "
                 "1 dec 2025, date dinamice 1 dec 2028.",
              en="Disruptions yes, delay history no. Deadlines: parking 1 Dec 2024, delay history 1 Dec 2025, "
                 "dynamic data 1 Dec 2028.")),
    Rule("RTTI", "Reg. delegat (UE) 2022/670",
         I18n(ro="Închideri, lucrări și măsuri temporare de circulație, în format digital",
              en="Closures, roadworks and temporary traffic measures, in digital form"),
         None,
         I18n(ro="Administratorul drumului (Primăria)", en="The road authority (City Hall)"),
         "covered", ("datex.xml",),
         I18n(ro="Închiderile în DATEX II. Termen: etapizat până în 2028.",
              en="Closures in DATEX II. Deadline: phased until 2028.")),
    Rule("TEN-T", "Reg. (UE) 2024/1679 + 2026/1554",
         I18n(ro="Plan de mobilitate urbană durabilă (PMUD) pentru nodurile urbane și 11 indicatori (HO.3, AC.1 etc.)",
              en="Sustainable urban mobility plan (SUMP) for urban nodes and 11 indicators (HO.3, AC.1 etc.)"),
         "2027-12-31",
         I18n(ro="Nodul urban (Primăria)", en="The urban node (City Hall)"),
         "partial", ("indicators.json",),
         I18n(ro="Doar indicatorii pe care îi calculăm (stații, acces la 400 m, AC.1, piste, P&R). Lista LAU: "
                 "31 dec 2026.",
              en="Only the indicators we compute (stops, 400 m access, AC.1, bike ways, P&R). LAU list: "
                 "31 Dec 2026.")),
    Rule("AFIR-20", "AFIR (infrastructura pentru combustibili alternativi), art. 20",
         I18n(ro="Datele stațiilor de încărcare publice în DATEX II", en="Public charging point data in DATEX II"),
         "2026-04-14",
         I18n(ro="Operatorii stațiilor de încărcare", en="Charging point operators"),
         "missing", (),
         I18n(ro="Nu exportăm stații de încărcare.", en="We export no charging points.")),
    Rule("EPBD-BIKE", "Directiva (UE) 2024/1275 (EPBD)",
         I18n(ro="Parcări pentru biciclete în clădiri (≥ 15% din capacitatea medie sau 10% din cea totală)",
              en="Bicycle parking in buildings (≥ 15% of average or 10% of total capacity)"),
         "2026-05-29",
         I18n(ro="Statul și proprietarii clădirilor", en="The state and building owners"),
         "partial", (),
         I18n(ro="Doar inventarul OSM al rastelelor (stratul de biciclete), nu un export.",
              en="Only the OSM inventory of bike racks (the bike layer), not an export.")),
    Rule("ROAD-SAFETY", "Directiva 2008/96/CE, mod. 2019/1936",
         I18n(ro="Siguranța infrastructurii rutiere: utilizatori vulnerabili, tronsoane periculoase, marcaje",
              en="Road infrastructure safety: vulnerable users, dangerous sections, markings"),
         None,
         I18n(ro="Statul și administratorii drumurilor", en="The state and road authorities"),
         "missing", (),
         I18n(ro="Nu acoperim. Directiva privește mai ales drumurile mari.",
              en="Not covered. The directive is mostly about major roads.")),
    Rule("AIR-QUALITY", "Directiva (UE) 2024/2881",
         I18n(ro="Valori-limită mai stricte pentru calitatea aerului până în 2030",
              en="Stricter air-quality limit values by 2030"),
         "2026-12-11",
         I18n(ro="Statul și autoritățile locale", en="The state and local authorities"),
         "missing", (),
         I18n(ro="Nu acoperim. Termenul este cel de transpunere.", en="Not covered. The deadline is transposition.")),
)


def _note(rule: Rule, status: str, covered_by: list[str], missing: list[str]) -> I18n:
    ro, en = rule.why.ro, rule.why.en or ""
    if status in ("covered", "partial") and covered_by:
        ro = f"{COVERED_BY_US[0].upper()}{COVERED_BY_US[1:]}: {', '.join(covered_by)}. {ro}"
        en = f"{COVERED_BY_US_EN[0].upper()}{COVERED_BY_US_EN[1:]}: {', '.join(covered_by)}. {en}"
    if missing:
        ro += f" Export lipsă acum: {', '.join(missing)}."
        en += f" Export missing now: {', '.join(missing)}."
    return I18n(ro=ro, en=en)


def report(mounted_paths: Iterable[str]) -> ComplianceReport:
    served = {e.name for e in available(mounted_paths)}
    obligations = []
    for r in RULES:
        covered_by = [n for n in r.exports if n in served]
        missing = [n for n in r.exports if n not in served]
        status = r.status
        if r.exports and not covered_by:
            status = "missing"   # none of its exports is served right now
        obligations.append(Obligation(id=r.id, act=r.act, requirement=r.requirement, deadline=r.deadline,
                                      owner=r.owner, status=status, coveredBy=covered_by,
                                      note=_note(r, status, covered_by, missing)))
    return ComplianceReport(
        generatedAt=iso(config.real_now()),
        obligations=obligations,
        provenance=[prov.provenance(
            "Rețeaua Vie: acte UE verificate de echipă; statusurile descriu doar exporturile noastre / "
            "EU acts checked by the team; statuses describe our exports only",
            config.real_now(), None, None,
            "Nu este o evaluare a conformității Primăriei / not an assessment of City Hall compliance")],
    )


def counts(mounted_paths: Iterable[str]) -> ComplianceCounts:
    """The three numbers of the overview KPI strip."""
    rep = report(mounted_paths)
    c = {"covered": 0, "partial": 0, "missing": 0}
    for o in rep.obligations:
        c[o.status] += 1
    return ComplianceCounts(**c)
