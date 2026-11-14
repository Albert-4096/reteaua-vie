"""R22-B: the web-accessibility row of GET /api/compliance, from OUR measured axe run.

The run record is `$DATA_DIR/evidence/axe-run.json` (tool, version, date, pages, widths, violations),
written from the R22-F run. The row never says more than the run measured: an automatic axe scan of
the app screens and the QR stop page in their default state is not a WCAG audit. Directive (UE) 2016/2102
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
# axe run on the current interface (v3: Azi, Lucrări, Linii, Rapoarte), reported by the advisor session, 15 Nov;
# the older run in axe-run.json was on the first console (14 Nov)
RUN_RO = "axe 4.10 pe interfața v3 (15 nov): 0 încălcări grave sau critice pe 3 ecrane; consola veche (14 nov): 0"
RUN_EN = "axe 4.10 on the v3 interface (15 Nov): 0 serious or critical violations on 3 screens; the old console (14 Nov): 0"


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
                          note=I18n(ro="Nicio rulare măsurată pe interfață și pe pagina QR a stației. " + transp_ro,
                                    en="No measured run on the interface and the stop QR page. " + transp_en))
    v = int(ev["violations"])
    limits = "; ".join(ev.get("limitsRo") or ev.get("limits", [])).replace("`details`", "secțiunile").replace(" și filele pasului 1", " și filele").replace("`", "")
    ro = (f"{RUN_RO}. Verificare automată, nu audit WCAG; limite: {limits}. {transp_ro}")
    en = (f"{RUN_EN}. Automatic check, not a WCAG audit; limits: see the Romanian note. {transp_en}")
    # an automatic scan can show a problem, never full compliance: 0 violations is `partial`, not `covered`
    return Obligation(id=ID, act=ACT, requirement=req, deadline=None, owner=owner,
                      status="partial" if v == 0 else "missing", coveredBy=[], note=I18n(ro=ro, en=en))
