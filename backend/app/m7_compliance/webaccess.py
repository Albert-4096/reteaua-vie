"""R22-B: the web-accessibility row of GET /api/compliance, from OUR measured axe run.

The run record is `$DATA_DIR/evidence/axe-run.json` (tool, version, date, pages, widths, violations),
written from the R22-F run. The row never says more than the run measured: an automatic axe scan of
the console and the QR stop page in their default state is not a WCAG audit. Directive (UE) 2016/2102
applies to public-sector bodies; how Romania transposed it is „de verificat”: the Legi archive does
not hold the act, so we cite none.
"""

from __future__ import annotations

import json

from app.config import get_settings
from app.models.base import I18n
from app.models.v2 import Obligation

ID = "WEB-ACCESS"
ACT = "Directiva (UE) 2016/2102"


def evidence() -> dict | None:
    p = get_settings().data_dir / "evidence" / "axe-run.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def obligation() -> Obligation:
    ev = evidence()
    req = I18n(ro="Accesibilitatea site-urilor și aplicațiilor mobile ale organismelor din sectorul public",
               en="Accessibility of public-sector websites and mobile apps")
    owner = I18n(ro="Organismele din sectorul public (Primăria, STPT)", en="Public-sector bodies (City Hall, STPT)")
    transp_ro = ("Transpunerea în România: de verificat (arhiva Legi, consultată la 14 nov 2026, nu conține actul). "
                 "Nu este un audit WCAG: doar o verificare automată.")
    transp_en = ("Romanian transposition: to be verified (the Legi archive, checked 14 Nov 2026, does not hold the act). "
                 "Not a WCAG audit: an automatic check only.")
    if ev is None:
        return Obligation(id=ID, act=ACT, requirement=req, deadline=None, owner=owner, status="missing", coveredBy=[],
                          note=I18n(ro="Nicio rulare măsurată a consolei și a paginii QR. " + transp_ro,
                                    en="No measured run of the console and the QR page. " + transp_en))
    n_pages, n_widths, v = len(ev["pages"]), len(ev["widths"]), int(ev["violations"])
    day = str(ev["runAt"])[:10].split("-")
    when = f"{day[2]}.{day[1]}.{day[0]}"
    widths = " și ".join(f"{w} px" for w in ev["widths"])
    widths_en = " and ".join(f"{w} px" for w in ev["widths"])
    ro = (f"Rulare măsurată de noi la {when}: {ev['tool']} {ev['toolVersion']} ({'reguli implicite: WCAG 2.0/2.1 A și AA plus bune practici' if 'default' in ev['ruleSet'] else ev['ruleSet']}), {n_pages} pagini "
          f"(consola, pașii 0–5, și pagina QR a stației) la {widths}, în starea implicită: {v} încălcări "
          f"({ev.get('violationsBefore', 0)} înainte de corecții). Limite: {'; '.join(ev.get('limitsRo') or ev.get('limits', []))}. {transp_ro}")
    en = (f"Run measured by us on {ev['runAt'][:10]}: {ev['tool']} {ev['toolVersion']} ({ev['ruleSet']}), {n_pages} pages "
          f"(the console steps 0-5 and the stop QR page) at {widths_en}, default state: {v} violations "
          f"({ev.get('violationsBefore', 0)} before the fixes). Limits: see the Romanian note. {transp_en}")
    # an automatic scan can show a problem, never full compliance: 0 violations is `partial`, not `covered`
    return Obligation(id=ID, act=ACT, requirement=req, deadline=None, owner=owner,
                      status="partial" if v == 0 else "missing", coveredBy=[], note=I18n(ro=ro, en=en))
