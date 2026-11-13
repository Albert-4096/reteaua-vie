"""A4 stop poster, PDF (SPEC §6.1 item 14).

One poster per affected stop: the title „Stație nedeservită / Stop not
served”, the stop name in 48 pt, the line badges in the city's route colours,
the window, the nearest served stop with its walking distance and a mini map
(SVG polylines of the network, no tiles), the RO and EN alert text, a 5 cm QR
code to the stop's alert page, and a footer with source and date.

Rendered with WeasyPrint and the bundled Noto Sans (repo/backend/fonts, OFL).
PDFs are cached in $DATA_DIR/cache/posters/ by a hash of the rendered HTML.
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import math
from functools import lru_cache
from pathlib import Path
from string import Template

import qrcode
import qrcode.image.svg
from shapely.geometry import LineString, MultiLineString, box

from app import config
from app.cases.catalog import CASES_BY_CLOSURE
from app.common import state
from app.common.city import load_network
from app.common.errors import not_found
from app.common.geo import lonlat_to_xy, to_metric
from app.common.timeutil import parse_iso
from app.m1_disruption.alerts import (
    build_alerts,
    closure_description,
    is_open_end,
    is_suspended,
    lines_phrase,
    pick_nearest,
    window_text,
)
from app.m1_disruption.publish import analysis_or_409, closure_or_404
from app.models.v1 import Alert

BACKEND_DIR = Path(__file__).resolve().parents[2]
FONTS_DIR = BACKEND_DIR / "fonts"
TEMPLATES = Path(__file__).resolve().parent / "templates"

WALK_METERS_PER_MIN = 80  # 4.8 km/h, the walking speed SPEC §6.2 uses

MAP_W, MAP_H = 840, 600   # SVG user units for an 84 x 60 mm box


@lru_cache(maxsize=1)
def _template() -> Template:
    return Template((TEMPLATES / "poster.html").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _css() -> str:
    return (TEMPLATES / "poster.css").read_text(encoding="utf-8")


def _e(text: str | None) -> str:
    return html.escape(text or "", quote=True)


# --- colours ---------------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _clean_hex(value: str | None, default: str) -> str:
    v = (value or "").lstrip("#")
    return v.lower() if len(v) == 6 and all(c in "0123456789abcdefABCDEF" for c in v) else default


def badge_colors(route: dict) -> tuple[str, str]:
    """Background = the city's route colour. Text = the city's text colour when it reaches
    4.5:1 contrast (WCAG AA), else black or white, whichever reads better."""
    bg = _clean_hex(route.get("color"), "555555")
    fg = _clean_hex(route.get("textColor"), "ffffff")
    if contrast(bg, fg) < 4.5:
        fg = "000000" if contrast(bg, "000000") >= contrast(bg, "ffffff") else "ffffff"
    return bg, fg


def _badges(route_ids: list[str], small: bool = False) -> str:
    net = load_network()
    out = []
    for rid in route_ids:
        route = net.route_by_id.get(rid) or {"shortName": rid}
        bg, fg = badge_colors(route)
        cls = "badge small" if small else "badge"
        out.append(f'<span class="{cls}" style="background:#{bg};color:#{fg}">{_e(route.get("shortName"))}</span>')
    return "".join(out)


# --- mini map --------------------------------------------------------------------------


def _scale_step(span_m: float) -> int:
    for step in (50, 100, 200, 250, 500, 1000):
        if step >= span_m / 5:
            return step
    return 1000


def mini_map_svg(stop_lonlat: list[float], served_lonlat: list[float] | None,
                 highlight_routes: set[str]) -> tuple[str, int]:
    """SVG of the network around the stop: grey lines, the affected lines in their colour,
    the stop (red), the nearest served stop (green) and a straight dashed walking line.
    Returns (svg, scale bar length in metres)."""
    pts = [lonlat_to_xy(*stop_lonlat[:2])]
    if served_lonlat:
        pts.append(lonlat_to_xy(*served_lonlat[:2]))
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    dx = max(abs(p[0] - cx) for p in pts) * 2
    dy = max(abs(p[1] - cy) for p in pts) * 2
    ext_x = max(dx * 1.7, 450.0)
    ext_y = max(ext_x * MAP_H / MAP_W, dy * 1.7)
    ext_x = ext_y * MAP_W / MAP_H
    minx, maxx = cx - ext_x / 2, cx + ext_x / 2
    miny, maxy = cy - ext_y / 2, cy + ext_y / 2
    k = MAP_W / ext_x
    frame = box(minx, miny, maxx, maxy)

    def sx(x: float) -> float:
        return round((x - minx) * k, 1)

    def sy(y: float) -> float:
        return round((maxy - y) * k, 1)

    def poly(line: LineString) -> str:
        return " ".join(f"{sx(x)},{sy(y)}" for x, y in line.coords)

    net = load_network()
    grey, coloured = [], []
    for (rid, _did), line in net.path_lines.items():
        clipped = to_metric(line).intersection(frame)
        if clipped.is_empty:
            continue
        parts = [clipped] if isinstance(clipped, LineString) else (
            list(clipped.geoms) if isinstance(clipped, MultiLineString) else
            [g for g in getattr(clipped, "geoms", []) if isinstance(g, LineString)])
        for part in parts:
            if len(part.coords) < 2:
                continue
            if rid in highlight_routes:
                bg, _ = badge_colors(net.route_by_id.get(rid) or {})
                coloured.append(f'<polyline points="{poly(part)}" fill="none" stroke="#{bg}" '
                                f'stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>')
            else:
                grey.append(f'<polyline points="{poly(part)}" fill="none" stroke="#c4c4c0" '
                            f'stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
    marks = []
    (x0, y0) = pts[0]
    if served_lonlat:
        (x1, y1) = pts[1]
        marks.append(f'<line x1="{sx(x0)}" y1="{sy(y0)}" x2="{sx(x1)}" y2="{sy(y1)}" stroke="#111" '
                     f'stroke-width="4" stroke-dasharray="12 9" stroke-linecap="round"/>')
        marks.append(f'<circle cx="{sx(x1)}" cy="{sy(y1)}" r="19" fill="#0b7a3b" stroke="#fff" stroke-width="5"/>')
        marks.append(f'<polyline points="{sx(x1) - 9},{sy(y1)} {sx(x1) - 2},{sy(y1) + 7} {sx(x1) + 10},{sy(y1) - 7}" '
                     f'fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')
    marks.append(f'<circle cx="{sx(x0)}" cy="{sy(y0)}" r="21" fill="#b00020" stroke="#fff" stroke-width="5"/>')
    marks.append(f'<path d="M{sx(x0) - 8},{sy(y0) - 8} L{sx(x0) + 8},{sy(y0) + 8} M{sx(x0) + 8},{sy(y0) - 8} '
                 f'L{sx(x0) - 8},{sy(y0) + 8}" stroke="#fff" stroke-width="5" stroke-linecap="round"/>')
    step = _scale_step(ext_x)
    bar = step * k
    scale = (f'<rect x="20" y="{MAP_H - 38}" width="{bar + 16:.1f}" height="26" fill="#fff" opacity="0.85"/>'
             f'<line x1="28" y1="{MAP_H - 22}" x2="{28 + bar:.1f}" y2="{MAP_H - 22}" stroke="#111" stroke-width="5"/>'
             f'<line x1="28" y1="{MAP_H - 30}" x2="28" y2="{MAP_H - 14}" stroke="#111" stroke-width="4"/>'
             f'<line x1="{28 + bar:.1f}" y1="{MAP_H - 30}" x2="{28 + bar:.1f}" y2="{MAP_H - 14}" stroke="#111" stroke-width="4"/>')
    north = (f'<path d="M{MAP_W - 34},20 L{MAP_W - 20},56 L{MAP_W - 34},48 L{MAP_W - 48},56 Z" fill="#111"/>')
    svg = (f'<svg class="map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MAP_W} {MAP_H}" '
           f'preserveAspectRatio="xMidYMid meet" role="img">'
           + "".join(grey) + "".join(coloured) + "".join(marks) + scale + north + "</svg>")
    return svg, step


# --- QR ------------------------------------------------------------------------------


def qr_data_uri(url: str) -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2,
                       image_factory=qrcode.image.svg.SvgPathImage)
    qr.add_data(url)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image().save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# --- poster ----------------------------------------------------------------------------


def _stop_alert(closure: dict, analysis: dict, stop_id: str) -> Alert | None:
    """The published alert of this stop when the closure is published, else a fresh one."""
    published = state.read("published", closure["id"])
    alerts = ([Alert.model_validate(a) for a in published.get("alerts") or []] if published
              else build_alerts(closure, analysis))
    target = f"_stop_{stop_id}"
    return next((a for a in alerts if a.id.endswith(target)), None)


def _source_line(closure: dict, analysis: dict) -> tuple[str, str]:
    case = CASES_BY_CLOSURE.get(closure["id"])
    if case is not None:
        url = closure.get("sourceUrl") or case.source_url() or "stpt.ro"
        host = url.split("//", 1)[-1].split("/", 1)[0] or "stpt.ro"
        ro = f"anunțul STPT nr. {case.post_id}, {host}"
        en = f"STPT notice no. {case.post_id}, {host}"
    elif closure.get("sourceUrl"):
        ro = en = closure["sourceUrl"]
    else:
        ro, en = "închidere introdusă în Rețeaua Vie", "closure entered in Rețeaua Vie"
    return ro, en


def poster_html(closure_id: str, stop_id: str) -> str:
    closure = closure_or_404(closure_id)
    analysis = analysis_or_409(closure_id)
    rows = [r for r in analysis.get("stops") or [] if str(r["stopId"]) == str(stop_id) and is_suspended(r)]
    if not rows:
        raise not_found(f"Stop {stop_id!r} is not suspended by closure {closure_id!r}.", "STOP_NOT_AFFECTED")
    alert = _stop_alert(closure, analysis, str(stop_id))
    if alert is None:
        raise not_found(f"No alert for stop {stop_id!r} in closure {closure_id!r}.", "STOP_NOT_AFFECTED")

    net = load_network()
    first = rows[0]
    stop = net.stop_by_id.get(str(stop_id)) or {}
    name = first.get("name") or stop.get("name") or str(stop_id)
    location = first.get("location") or stop.get("location")
    route_ids = sorted({r["routeId"] for r in rows},
                       key=lambda rid: (len((net.route_by_id.get(rid) or {}).get("shortName", rid)), rid))
    shorts = [(net.route_by_id.get(r) or {}).get("shortName", r) for r in route_ids]
    nearest = pick_nearest(rows, str(stop_id))
    still_served = bool(nearest and str(nearest.get("stopId")) == str(stop_id))

    start, end = parse_iso(closure["window"]["start"]), parse_iso(closure["window"]["end"])
    open_end = is_open_end(closure)

    if still_served:
        near_label = 'Stația rămâne deservită de <span class="en">/ Still served by</span>'
        near_name = _e(lines_phrase([(net.route_by_id.get(r) or {}).get("shortName", r)
                                     for r in nearest.get("routeIds") or []], "ro"))
        near_distance = ""
        near_badges = _badges(list(nearest.get("routeIds") or []), small=True)
        served = None
    elif nearest:
        dist = nearest.get("distanceMeters")
        if dist is not None:
            meters = int(round(float(dist) / 10.0) * 10)
            minutes = max(1, math.ceil(float(dist) / WALK_METERS_PER_MIN))
            near_distance = (f"{meters} m pe jos, circa {minutes} min "
                             f'<span class="en">/ {meters} m on foot, about {minutes} min</span>')
        else:
            near_distance = 'distanța: necunoscută <span class="en">/ distance unknown</span>'
        near_name = _e(nearest.get("name"))
        if nearest.get("name") == name:
            near_name += ('<div class="value">altă stație cu același nume '
                          '<span class="en">/ another stop with the same name</span></div>')
        near_badges = _badges(list(nearest.get("routeIds") or []), small=True)
        served = nearest.get("location")
    else:
        near_name = 'necunoscută <span class="en">/ unknown</span>'
        near_distance, near_badges, served = "", "", None
    if not still_served:
        near_label = 'Cea mai apropiată stație deservită <span class="en">/ Nearest served stop</span>'
    if still_served:
        kicker = 'Linii care nu opresc aici <span class="en">/ Lines not stopping here</span>'
    else:
        kicker = 'Stație nedeservită <span class="en">/ Stop not served</span>'

    map_svg, step = mini_map_svg(location, served, set(route_ids))
    legend = '<span class="dot" style="background:#b00020"></span>Stația aceasta <span class="en">/ this stop</span>'
    if served:
        legend += (' · <span class="dot" style="background:#0b7a3b"></span>stația deservită '
                   '<span class="en">/ served stop</span><br>linie punctată: direcția de mers, nu traseul exact'
                   ' <span class="en">/ dashed: walking direction, not the exact path</span>')
    legend += f'<br>bara de scară = {step} m <span class="en">/ scale bar = {step} m</span>'

    src_ro, src_en = _source_line(closure, analysis)
    feed_version = analysis.get("feedVersion") or "necunoscută"
    generated = config.now()
    simulated = config.get_settings().demo_now is not None
    stamp = generated.strftime("%d.%m.%Y %H:%M")
    footer_ro = (f"Sursa: {_e(src_ro)}. Orar: SMTT GTFS {_e(feed_version)}. Afiș generat de Rețeaua Vie "
                 f"(demo UniHack 8, nu document oficial STPT) la {stamp}" + (" (ora simulată)." if simulated else "."))
    footer_en = (f"Source: {_e(src_en)}. Timetable: SMTT GTFS {_e(feed_version)}. Poster generated by Rețeaua Vie "
                 f"(UniHack 8 demo, not an official STPT document) on {stamp}" + (" (simulated time)." if simulated else "."))

    lines_label = _e(lines_phrase(shorts, "ro")) + f' <span class="en">/ {_e(lines_phrase(shorts, "en"))}</span>'
    return _template().substitute(
        title=_e(f"Afiș stație: {name}"),
        kicker=kicker,
        near_label=near_label,
        css=_css(),
        stop_name=_e(name),
        badges=_badges(route_ids),
        lines_label=lines_label,
        window_ro=_e(window_text(start, end, "ro", open_end)),
        window_en=_e(window_text(start, end, "en", open_end)),
        near_name=near_name,
        near_distance=near_distance,
        near_badges=near_badges,
        map_svg=map_svg,
        legend=legend,
        header_ro=_e(alert.headerText.ro),
        description_ro=_e(closure_description(closure, "ro")),
        header_en=_e(alert.headerText.en),
        description_en=_e(closure_description(closure, "en")),
        qr_src=qr_data_uri(alert.url),
        url=_e(alert.url),
        footer_ro=footer_ro,
        footer_en=footer_en,
    )


def render_pdf(html_text: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html_text, base_url=str(FONTS_DIR) + "/").write_pdf()


def poster_pdf(closure_id: str, stop_id: str) -> bytes:
    html_text = poster_html(closure_id, stop_id)
    key = hashlib.sha256(html_text.encode("utf-8")).hexdigest()[:24]
    cache = config.get_settings().cache_dir / "posters" / f"{closure_id}_{key}.pdf"
    if cache.is_file():
        return cache.read_bytes()
    pdf = render_pdf(html_text)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(pdf)
    tmp.replace(cache)
    return pdf
