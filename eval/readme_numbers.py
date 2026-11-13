"""Copy the measured numbers from eval/results/latest.json into README.md.

The README never holds a figure typed by hand: this script rewrites the block between
<!-- numbers:start --> and <!-- numbers:end --> from latest.json, each number with the
sentence that says how it was measured, Romanian first, then English.
A value missing from latest.json is written as „necunoscut” / unknown, never as 0.

    python3 eval/readme_numbers.py           # rewrite the block
    python3 eval/readme_numbers.py --check   # exit 1 if README.md is out of date

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "eval" / "results" / "latest.json"
README = ROOT / "README.md"
START = "<!-- numbers:start -->"
END = "<!-- numbers:end -->"

UNKNOWN = ("necunoscut", "unknown")

# What each independent-gold notice is about (text only; every count comes from latest.json).
GOLD_TOPIC = {
    "11060": ("devierea Mocioni din anunțul 11060", "the Mocioni diversion of 11060"),
    "11062": ("ocolirea podului Polonă din anunțul 11062", "the Polonă bridge detour of 11062"),
    "11058": ("liniile M11, M29 și M30, unde GTFS-ul scoate „Moldovei (Ghiroda)” și renumerotează "
              "„Girație Pod Bega”, ce anunțul 11058 nu menționează",
              "M11, M29 and M30, where the GTFS drops „Moldovei (Ghiroda)” and renumbers "
              "„Girație Pod Bega”, which notice 11058 never mentions"),
}


def num(x: int | float | None, lang: str) -> str:
    if x is None:
        return UNKNOWN[lang == "en"]
    s = f"{x:,}"
    return s.replace(",", ".") if lang == "ro" else s


def pct(x: float | None, lang: str) -> str:
    if x is None:
        return UNKNOWN[lang == "en"]
    s = f"{x * 100:.1f}%"
    return s.replace(".", ",") if lang == "ro" else s


def secs(x: float | None, lang: str) -> str:
    if x is None:
        return UNKNOWN[lang == "en"]
    s = f"{x:.2f} s"
    return s.replace(".", ",") if lang == "ro" else s


def de(n: int | None) -> str:
    """Romanian puts „de” between a number and its noun when the last two digits are 0 or 20-99."""
    return "de " if isinstance(n, int) and n > 0 and (n % 100 == 0 or n % 100 >= 20) else ""


def ymd(compact: str | None) -> str:
    """20261105 -> 2026-11-05."""
    c = compact or ""
    return f"{c[:4]}-{c[4:6]}-{c[6:8]}" if len(c) == 8 and c.isdigit() else (c or "?")


def day(iso: str | None) -> str:
    return iso[:10] if iso else "?"


def hhmm(iso: str | None) -> str:
    return iso[11:16] if iso and len(iso) >= 16 else "?"


def scored(block: dict) -> tuple[int, int, int]:
    """(found, gold rows, false positives) of a strict/lenient score block."""
    return block["tp"], block["tp"] + block["fn"], block["fp"]


def labels_ro(labelled_by: list[str]) -> str:
    if any("human review pending" in s for s in labelled_by):
        return "făcute cu ajutor AI din textul anunțului; verificarea de către un om nu s-a încheiat"
    return "; ".join(labelled_by) or UNKNOWN[0]


def notices_part(d: dict) -> list[str]:
    o = d["overall"]
    n = d["labels"]["count"]
    s_found, s_gold, s_fp = scored(o["strict"])
    l_found, l_gold, l_fp = scored(o["lenient"])
    by = d["labels"]["labelledBy"]
    return [
        f"**Citirea anunțurilor STPT / Reading STPT notices** ({n} anunțuri reale / real notices; "
        f"cheia de răspuns / answer key: {labels_ro(by)} / *{'; '.join(by)}*)",
        "",
        f"- **{s_found} din {s_gold}** {de(s_gold)}rânduri suspendate (stație, linie, sens) găsite sigur, **{s_fp}** "
        f"false (precizie {pct(o['strict']['precision'], 'ro')}, recall {pct(o['strict']['recall'], 'ro')}). "
        f"Cu rândurile marcate „neclar”, pe care le decide funcționarul: {l_found} din {l_gold}, {l_fp} false. "
        "Metoda: `eval/run.py` dă fiecare anunț parserului și analizei M1 și compară rândurile cu cheia "
        "de răspuns; rândurile pe care cheia le lasă nesigure nu se punctează.  \n"
        f"  *{s_found} of {s_gold} suspended (stop, line, direction) rows found as certain, {s_fp} false "
        f"(precision {pct(o['strict']['precision'], 'en')}, recall {pct(o['strict']['recall'], 'en')}). "
        f"Counting the „neclar” (unsure) rows the clerk decides: {l_found} of {l_gold}, {l_fp} false. "
        "Method: `eval/run.py` feeds each notice to the M1 parser and analysis and compares the rows "
        "with the answer key; rows the key leaves uncertain are not scored.*",
        f"- **{pct(o['neclarShare'], 'ro')}** din rândurile găsite merg la „neclar”: platforma nu ghicește, "
        "întreabă funcționarul. Metoda: rânduri „neclar” / toate rândurile găsite, pe toate anunțurile.  \n"
        f"  *{pct(o['neclarShare'], 'en')} of the rows found are sent to „neclar”: the platform does not "
        "guess, it asks the clerk. Method: unsure rows / all rows found, over all notices.*",
    ]


def paste_part(d: dict) -> list[str]:
    o = d["overall"]
    p = o.get("pasteToAlertSeconds") or {}
    idle = [x for x in d["notices"]
            if (x.get("pasteToAlert") or {}).get("seconds") is None
            and not (x["rows"]["affected"] or x["rows"]["unsure"])]
    runs = o.get("gtfsRtValidatorRuns")
    passed = o.get("gtfsRtValidatorPass")
    verdict = {True: ("a trecut", "passed"), False: ("a găsit erori", "found errors"),
               None: ("nu a rulat", "did not run")}[passed]
    rest_ro = f"; celelalte {len(idle)} anunțuri nu au niciun rând de publicat" if idle else ""
    rest_en = f"; the other {len(idle)} notices have no row to publish" if idle else ""
    return [
        f"- **{secs(p.get('median'), 'ro')}** (mediana) de la anunțul lipit la alerta GTFS-RT publicată, "
        f"maximum {secs(p.get('max'), 'ro')}, pe {num(p.get('n'), 'ro')} anunțuri{rest_ro}. Metoda: `eval/run.py` "
        "rulează API-ul în proces, cu ceasul la data anunțului: citește anunțul, analizează, confirmă tot "
        "ce propune platforma, publică și citește `/api/feed/alerts.pb`. Timpul în care un om decide nu "
        "e inclus. Fără nicio cheie LLM sau text-to-speech.  \n"
        f"  *{secs(p.get('median'), 'en')} (median) from pasted notice to published GTFS-RT alert, maximum "
        f"{secs(p.get('max'), 'en')}, over {num(p.get('n'), 'en')} notices{rest_en}. Method: `eval/run.py` "
        "drives the API in-process with the clock at the notice date: parse, analyze, confirm every "
        "proposed row, publish, read `/api/feed/alerts.pb`. The time a person takes to decide is not "
        "included. No LLM or text-to-speech key is used.*",
        f"- Validatorul MobilityData GTFS-RT **{verdict[0]}** pe feedul publicat, la "
        f"{num(runs, 'ro')} rulări (`gtfsRtValidatorPass`).  \n"
        f"  *The MobilityData GTFS-RT validator **{verdict[1]}** on the published feed, "
        f"{num(runs, 'en')} runs.*",
    ]


def gold_part(d: dict) -> list[str]:
    ig = d["overall"]["independentGold"]
    found, gold, fp = scored(ig["strict"])
    rows = {str(x["postId"]): x["independentGold"] for x in d["notices"] if x.get("independentGold")}
    out = [
        f"- **{found} din {gold}** pe referința independentă (rândurile pe care SMTT le-a scos din propriul "
        f"GTFS între versiuni, `eval/gold_gtfs_diff.py`, fără etichete de-ale noastre), {fp} false.  \n"
        f"  *{found} of {gold} on the independent gold (rows SMTT removed from its own GTFS between "
        f"versions, `eval/gold_gtfs_diff.py`, no labels of ours), {fp} false.*",
    ]
    prepared = (ig.get("preparedCases") or {}).get("11060")
    if found == 0 and prepared and "11060" in rows:
        p_found, p_gold, p_fp = scored(prepared["strict"])
        base = rows["11060"]["transition"].split("->")[0]
        feed = d["feed"]["version"]
        parts = [(rows[k]["goldRows"], GOLD_TOPIC.get(k, (f"anunțul {k}", f"notice {k}")))
                 for k in ("11060", "11062", "11058") if k in rows]
        ro_list = ", ".join(f"{n} pentru {t[0]}" for n, t in parts)
        en_list = ", ".join(f"{n} for {t[1]}" for n, t in parts)
        out += [
            f"- De ce calea anunțului are {found} din {gold} aici: evaluarea citește fiecare anunț pe GTFS-ul "
            f"de azi, {feed}, din care SMTT a scos deja aceste {gold} {de(gold)}rânduri stație–linie–sens "
            f"({ro_list}), deci nu mai are ce găsi; cifra independentă onestă este cazul Mocioni pregătit pe "
            f"GTFS-ul în vigoare înainte de lucrări ({base}), care găsește **{p_found} din {p_gold}** "
            f"{de(p_gold)}rânduri, {p_fp} false. "
            "Ca fiecare anunț să fie punctat pe feedul în vigoare la data postării, potrivirea M1 trebuie să "
            "ruleze pe un GTFS mai vechi, ceea ce încă nu poate.  \n"
            f"  *Why the notice path scores {found} of {gold} here: the eval reads every notice against "
            f"today's GTFS {feed}, in which SMTT has already removed those {gold} stop–line–direction rows "
            f"({en_list}), so there is nothing left for it to find; the honest independent figure is the "
            f"prepared Mocioni case, built on the GTFS in force before the works ({base}), which finds "
            f"{p_found} of those {p_gold} rows with {p_fp} false positives. Scoring each notice on the feed in "
            "force at its post date needs the M1 matching to run on an older GTFS, which it cannot do yet.*",
        ]
    return out


def e3_part(d: dict) -> list[str]:
    e = d.get("e3")
    if not e:
        return []
    same = e.get("sameOnEveryWeekdayOfTheWindow")
    same_ro = ", aceeași în fiecare zi lucrătoare a închiderii" if same else ""
    same_en = ", the same on every weekday of the closure" if same else ""
    return [
        f"- **{num(e['figure'], 'ro')}** {de(e['figure'])}{e['label']['ro']}, la {e['stopIdsTotal']} "
        f"{de(e['stopIdsTotal'])}id-uri de stație, ziua {e['date']}{same_ro}. Metoda: `eval/e3_departures.py` numără plecările din `stop_times` ale "
        "curselor E3 care circulă în ziua aceea (`calendar.txt` și `calendar_dates.txt`); ultima stație a "
        "unei curse nu e o plecare; orele de după 24:00 trec în ziua următoare.  \n"
        f"  *{num(e['figure'], 'en')} {e['label']['en']}, at {e['stopIdsTotal']} stop ids, {e['date']}{same_en}. "
        f"Method: {e['method']}*",
    ]


def hero_part(d: dict) -> list[str]:
    h = d.get("hero") or {}
    if h.get("status") != "ok":
        return [f"- Lucrarea demo: {UNKNOWN[0]} / *demo closure: {UNKNOWN[1]}* "
                f"({h.get('status', 'missing')})"]
    w = h["window"]
    win = f"{day(w['start'])} {hhmm(w['start'])}–{hhmm(w['end'])}"
    res_label = h.get("labels", {}).get("residentsLosingStop", "")
    dec = h["decisions"]
    return [
        f"- Lucrarea demo `{h['closureId']}` ({win}): **{num(h['stopsSuspended'], 'ro')}** "
        f"{de(h['stopsSuspended'])}stații fără niciun mijloc de transport, **{num(h['departuresLost'], 'ro')}** "
        f"{de(h['departuresLost'])}plecări pierdute, **{num(h['residentsLosingStop'], 'ro')}** "
        f"{de(h['residentsLosingStop'])}locuitori fără stație la 400 m ({res_label}), "
        f"{num(h['routesAffected'], 'ro')} linii afectate. Metoda: {h['method']['ro']} Deciziile sunt cele din cheia "
        f"de răspuns ({dec['ticked']} bifate, {dec['unticked']} debifate), aplicate pe o copie.  \n"
        f"  *Demo closure ({win}): {num(h['stopsSuspended'], 'en')} stops with no service, "
        f"{num(h['departuresLost'], 'en')} departures lost, {num(h['residentsLosingStop'], 'en')} residents "
        f"losing their stop within 400 m (a model, not a census), {num(h['routesAffected'], 'en')} lines "
        "affected. "
        f"Method: {h['method']['en']} Decisions: {dec['rule']} ({dec['ticked']} ticked, "
        f"{dec['unticked']} unticked), applied to a copy.*",
    ]


def render(d: dict) -> str:
    f = d["feed"]
    head = [
        START,
        "<!-- generated by eval/readme_numbers.py from eval/results/latest.json; do not edit by hand -->",
        f"Toate cifrele de aici vin din `eval/results/latest.json`, scris de `make eval` la {d['generatedAt']} "
        f"(commit `{d['repoCommit']}`), pe GTFS SMTT {f['version']} (valabil {ymd(f['validFrom'])} – "
        f"{ymd(f['validTo'])}, "
        f"sha256 `{f['sha256'][:12]}`), copiate de `eval/readme_numbers.py`. Detalii: "
        "[`eval/README.md`](eval/README.md).  \n"
        "*Every figure here comes from `eval/results/latest.json`, written by `make eval` at the time and "
        "commit above, copied by `eval/readme_numbers.py`. Details: [`eval/README.md`](eval/README.md).*",
        "",
    ]
    errors = d.get("errors") or []
    tail = ([f"- Erori la evaluare / eval errors: {len(errors)} (vezi / see `latest.json`)."]
            if errors else [])
    body = (notices_part(d) + paste_part(d) + gold_part(d) + ["", "**Cifre de impact / Impact figures**", ""]
            + e3_part(d) + hero_part(d) + tail)
    return "\n".join(head + body + [END])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if README.md is out of date")
    args = ap.parse_args()

    block = render(json.loads(LATEST.read_text(encoding="utf-8")))
    text = README.read_text(encoding="utf-8")
    i, j = text.find(START), text.find(END)
    if i < 0 or j < i:
        print(f"{README}: markers {START} ... {END} not found", file=sys.stderr)
        return 2
    new = text[:i] + block + text[j + len(END):]
    if args.check:
        if new != text:
            print("README.md numbers are out of date: run python3 eval/readme_numbers.py", file=sys.stderr)
            return 1
        print("README.md numbers match eval/results/latest.json")
        return 0
    if new != text:
        README.write_text(new, encoding="utf-8")
        print(f"README.md: numbers block rewritten from {LATEST.relative_to(ROOT)}")
    else:
        print("README.md: numbers block already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
