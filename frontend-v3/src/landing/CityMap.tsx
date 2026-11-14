import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { createTimeline, svg as animeSvg, utils } from "animejs";
import type { Feature, MultiPolygon } from "geojson";
import { api, closurePoints, fmt, hhmm, useApi, type Closure, type Zone } from "@/lib/api";
import { dotGrid, fitProjection, type Projector } from "@/lib/geo";
import { FAMILIES, modeName, useNetwork } from "@/lib/network";
import { cn } from "@/lib/utils";
import { Count } from "@/app/ui";

const W = 1100;
const STEP = 7;
const R = 1.7;
const CENTRE: [number, number] = [21.2257, 45.7537]; // Piața Victoriei
type FamilyId = (typeof FAMILIES)[number]["id"];
const DRAW_ORDER: FamilyId[] = ["tram", "trolley", "bus", "express", "metro"];
const Z_ORDER: FamilyId[] = ["metro", "bus", "express", "trolley", "tram"]; // trams on top, as on the street

function zoneDotsPath(dots: { x: number; y: number }[]) {
  return dots.map(({ x, y }) => `M${x - R} ${y}a${R} ${R} 0 1 0 ${R * 2} 0a${R} ${R} 0 1 0 ${-R * 2} 0`).join("");
}
function polygonPath(g: MultiPolygon, p: Projector) {
  return g.coordinates
    .map((poly) => poly.map((ring) => "M" + ring.map(([lon, lat]) => `${p.x(lon).toFixed(1)} ${p.y(lat).toFixed(1)}`).join("L") + "Z").join(""))
    .join("");
}

type Props = { closures?: Closure[]; className?: string };

/**
 * Timișoara, live. The neighbourhoods come up as a dot field shaded by population (GHSL model), then the
 * 58 lines draw themselves in STPT's colours (anime.js timeline), then the works and the vehicles from the
 * live feed appear (Motion). Every 15 s each vehicle glides to its new position and sends a ping.
 */
export function CityMap({ closures = [], className }: Props) {
  const zones = useApi(api.zones);
  const vehicles = useApi(api.vehicles, 15000);
  const net = useNetwork();
  const reduce = useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const played = useRef(false);
  const [inView, setInView] = useState(false);
  const [stage, setStage] = useState<0 | 1 | 2>(0); // 0 hidden, 1 drawing, 2 live
  const [hoverZone, setHoverZone] = useState<number | null>(null);
  const [hoverLine, setHoverLine] = useState<string | null>(null);
  const [hoverClosure, setHoverClosure] = useState<string | null>(null);
  const [only, setOnly] = useState<FamilyId | null>(null);

  const geo = useMemo(() => {
    if (!zones.data) return null;
    const feats = zones.data.features as Feature<MultiPolygon, Zone>[];
    const p = fitProjection(feats, W);
    const dots = dotGrid(feats, p, STEP);
    const cx = p.x(CENTRE[0]), cy = p.y(CENTRE[1]);
    const zs = feats.map((f, i) => {
      const mine = dots.filter((d) => d.zone === i);
      const mx = mine.reduce((s, d) => s + d.x, 0) / (mine.length || 1);
      const my = mine.reduce((s, d) => s + d.y, 0) / (mine.length || 1);
      return { d: zoneDotsPath(mine), outline: polygonPath(f.geometry, p), dens: (f.properties.residents ?? 0) / Math.max(mine.length, 1), dist: Math.hypot(mx - cx, my - cy) };
    });
    const maxD = Math.max(...zs.map((z) => z.dens), 1);
    const maxR = Math.max(...zs.map((z) => z.dist), 1);
    // shade: sqrt of density so the outskirts stay visible; dist: 0 at the centre, 1 at the farthest zone
    return { feats, p, zs: zs.map((z) => ({ ...z, op: +(0.14 + 0.5 * Math.sqrt(z.dens / maxD)).toFixed(3), dist: z.dist / maxR })) };
  }, [zones.data]);

  const lines = useMemo(() => {
    if (!geo || !net) return [];
    const famOf = (r: { type: number; shortName: string }) => FAMILIES.find((f) => f.test(r as never))?.id ?? "bus";
    const all = net.paths
      .filter((x) => x.directionId === 0 && net.byId.has(x.routeId))
      .map((x) => {
        const r = net.byId.get(x.routeId)!;
        const d = "M" + x.geometry.coordinates.map(([lon, lat]) => `${geo.p.x(lon).toFixed(1)} ${geo.p.y(lat).toFixed(1)}`).join("L");
        return { id: x.routeId, r, d, fam: famOf(r) as FamilyId, order: 0 };
      });
    let k = 0;
    for (const f of DRAW_ORDER) for (const l of all) if (l.fam === f) l.order = k++;
    return all.sort((a, b) => Z_ORDER.indexOf(a.fam) - Z_ORDER.indexOf(b.fam));
  }, [geo, net]);

  const counts = useMemo(() => {
    const c = new Map<FamilyId, number>();
    for (const l of lines) c.set(l.fam, (c.get(l.fam) ?? 0) + 1);
    return c;
  }, [lines]);

  // start once, when the map is on screen and both the zones and the lines are in
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setInView(true), { threshold: 0.2 });
    io.observe(el);
    return () => io.disconnect();
  }, [zones.data]); // the skeleton and the map are different elements

  const ready = !!geo && lines.length > 0;
  useEffect(() => {
    const root = svgRef.current;
    if (!ready || !inView || played.current || !root) return;
    played.current = true;
    const zoneEls = [...root.querySelectorAll<SVGPathElement>(".rv-zone")];
    const lineEls = [...root.querySelectorAll<SVGPathElement>(".rv-line")];
    if (reduce) {
      zoneEls.forEach((z) => z.setAttribute("opacity", z.dataset.op!));
      root.classList.remove("rv-pre");
      setStage(2);
      return;
    }
    const order = lineEls.map((el) => Number(el.dataset.order));
    const op = zoneEls.map((el) => Number(el.dataset.op));
    const dist = zoneEls.map((el) => Number(el.dataset.dist));
    const drawables = animeSvg.createDrawable(lineEls);
    utils.set(zoneEls, { opacity: 0 });
    utils.set(drawables, { draw: "0 0" });
    root.classList.remove("rv-pre");
    setStage(1);
    const tl = createTimeline()
      .add(zoneEls, { opacity: (_t?: unknown, i = 0) => op[i], duration: 900, ease: "outQuad", delay: (_t?: unknown, i = 0) => dist[i] * 1000 }, 0)
      .add(drawables, { draw: ["0 0", "0 1"], duration: 1500, ease: "inOutQuad", delay: (_t?: unknown, i = 0) => order[i] * 26 }, 450)
      .call(() => setStage(2), 2300);
    return () => { tl.pause(); };
  }, [ready, inView, reduce]);

  if (!geo) {
    return (
      <div ref={wrap} className={className} aria-busy="true">
        <div className="h-[46rem] w-full animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  const { feats, p, zs } = geo;
  const hz = hoverZone != null ? feats[hoverZone].properties : null;
  const hl = hoverLine ? net?.byId.get(hoverLine) : null;
  const hc = hoverClosure ? closures.find((c) => c.id === hoverClosure) : null;
  const focus = hc ? new Set(hc.routeIds) : hoverLine ? new Set([hoverLine]) : null;
  const vs = (vehicles.data?.features ?? []).filter((v) => !only || lines.find((l) => l.id === v.properties.routeId)?.fam === only);
  const updated = vehicles.data?.features[0]?.properties.updatedAt;
  const live = stage === 2;

  return (
    <div ref={wrap} className={cn("grid items-start gap-8 lg:grid-cols-[17.5rem_1fr] lg:gap-10", className)}>
      <aside className="flex flex-col gap-7">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-accent-foreground">
            <span className="relative flex size-2.5" aria-hidden>
              <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/60" />
              <span className="relative inline-flex size-2.5 rounded-full bg-primary" />
            </span>
            În direct
          </div>
          <div className="tabular mt-2 text-[3.25rem] font-semibold leading-none tracking-tight">
            {vehicles.data ? <Count value={vehicles.data.features.length} /> : "–"}
          </div>
          <div className="mt-2 text-[0.95rem] text-foreground/80">vehicule STPT în mișcare acum</div>
          <div className="mt-1 text-xs text-muted-foreground">
            date live ale Primăriei{updated ? `, ${hhmm(updated)}` : ""} · noi poziții la 15 s
          </div>
        </div>

        <div role="group" aria-label="Arată doar un tip de linie">
          <div className="mb-2 text-sm font-medium">Liniile, în culorile STPT</div>
          <ul className="space-y-0.5">
            {net && FAMILIES.map((f) => {
              const r = net.routes.find(f.test);
              if (!r) return null;
              const on = only === f.id;
              return (
                <li key={f.id}>
                  <button type="button" aria-pressed={on} onClick={() => setOnly(on ? null : f.id)}
                    className={cn("flex h-9 w-full items-center gap-3 rounded-lg px-2.5 text-left text-sm transition-[background-color,color,opacity] duration-200",
                      on ? "bg-foreground text-background" : "text-foreground/85 hover:bg-muted",
                      only && !on && "opacity-50")}>
                    <span className="h-1.5 w-6 shrink-0 rounded-full" style={{ background: `#${r.color}` }} />
                    <span className="flex-1">{f.label}</span>
                    <span className={cn("tabular text-xs", on ? "text-background/70" : "text-muted-foreground")}>{counts.get(f.id) ?? 0}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {closures.length > 0 && (
          <div>
            <div className="mb-2 text-sm font-medium">Lucrări în platformă</div>
            <ul className="space-y-0.5">
              {closures.map((c) => (
                <li key={c.id}>
                  <a href={`/app/planifici?c=${encodeURIComponent(c.id)}`}
                    onPointerEnter={() => setHoverClosure(c.id)} onPointerLeave={() => setHoverClosure(null)}
                    onFocus={() => setHoverClosure(c.id)} onBlur={() => setHoverClosure(null)}
                    className={cn("flex items-start gap-3 rounded-lg px-2.5 py-2 text-sm leading-snug transition-colors duration-200",
                      hoverClosure === c.id ? "bg-closure-soft text-closure-ink" : "text-foreground/85 hover:bg-muted")}>
                    <span className="mt-1 size-2.5 shrink-0 rounded-full bg-closure ring-2 ring-white" />
                    <span className="line-clamp-2">{c.title.ro}</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="h-[4.5rem] overflow-hidden text-sm leading-relaxed" aria-live="polite">
          {hc ? <span>Liniile afectate de lucrare rămân colorate pe hartă.</span>
            : hl ? <span className="font-medium">{modeName(hl)} {hl.shortName} · {hl.longName}</span>
            : hz ? <span><span className="font-medium">{hz.name}</span>{hz.residents ? ` · ${fmt.format(Math.round(hz.residents / 100) * 100)} locuitori (model GHSL 2020)` : ""}</span>
            : <span className="text-muted-foreground">Punctele mai închise: cartiere mai populate (model GHSL 2020). Treceți peste o linie, un cartier sau o lucrare.</span>}
        </p>
      </aside>

      <div className="relative">
        <svg ref={svgRef} viewBox={`0 0 ${p.width} ${p.height}`} className="rv-pre mx-auto block h-auto max-h-[46rem] w-full" role="img"
          aria-label="Harta Timișoarei: cartierele după populație, liniile STPT în culorile lor, lucrările și vehiculele din datele live">
          <defs>
            <radialGradient id="rv-fade" cx="0.5" cy="0.5" r="0.5">
              <stop offset="0.74" stopColor="#fff" />
              <stop offset="1" stopColor="#000" />
            </radialGradient>
            <mask id="rv-edge" maskUnits="userSpaceOnUse" x="0" y="0" width={p.width} height={p.height}>
              <rect width={p.width} height={p.height} fill="url(#rv-fade)" />
            </mask>
          </defs>

          {zs.map((z, i) => (
            <path key={i} className="rv-zone" d={z.d} data-op={z.op} data-dist={z.dist.toFixed(3)}
              fill={hoverZone === i ? "var(--green)" : "var(--foreground)"} style={{ transition: "fill 200ms" }} />
          ))}
          {zs.map((z, i) => (
            <path key={`o${i}`} d={z.outline} fill="transparent" onPointerEnter={() => setHoverZone(i)} onPointerLeave={() => setHoverZone(null)} />
          ))}

          <g mask="url(#rv-edge)" fill="none" strokeLinecap="round" strokeLinejoin="round">
            {lines.map((l) => {
              const w = l.fam === "tram" ? 3.4 : l.fam === "metro" ? 2 : 2.4;
              const on = focus?.has(l.id);
              const dim = (focus && !on) || (only && l.fam !== only);
              return (
                <g key={l.id} opacity={dim ? 0.1 : 1} style={{ transition: "opacity 260ms" }} pointerEvents="none">
                  <path className="rv-line" data-order={l.order} d={l.d} stroke="var(--card)" strokeWidth={w + 2.6} />
                  <path className="rv-line" data-order={l.order} d={l.d} stroke={`#${l.r.color}`} strokeWidth={w + (on ? 1.8 : 0)}
                    style={{ transition: "stroke-width 200ms" }} />
                </g>
              );
            })}
            {lines.map((l) => (
              <path key={`h${l.id}`} d={l.d} stroke="transparent" strokeWidth={10}
                onPointerEnter={() => setHoverLine(l.id)} onPointerLeave={() => setHoverLine(null)} />
            ))}
          </g>

          {live && closures.map((c, i) => {
            const pts = closurePoints(c);
            if (!pts.length) return null;
            const [lon, lat] = pts[Math.floor(pts.length / 2)];
            const x = p.x(lon), y = p.y(lat);
            return (
              <motion.g key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, ease: "easeOut", delay: i * 0.1 }}
                className="cursor-pointer"
                onPointerEnter={() => setHoverClosure(c.id)} onPointerLeave={() => setHoverClosure(null)}
                onClick={() => location.assign(`/app/planifici?c=${encodeURIComponent(c.id)}`)}>
                <motion.circle cx={x} cy={y} fill="none" stroke="var(--closure)" strokeWidth={1.5}
                  initial={{ r: 7, opacity: 0.4 }} animate={{ r: 20, opacity: 0 }}
                  transition={{ duration: 3, repeat: Infinity, repeatDelay: 1.5, ease: "easeOut" }} />
                <circle cx={x} cy={y} r={14} fill="transparent" />
                <circle cx={x} cy={y} r={7.5} fill="var(--closure)" stroke="white" strokeWidth={2.6} />
              </motion.g>
            );
          })}

          <g mask="url(#rv-edge)" pointerEvents="none">
            {live && vs.map((v, i) => {
              const [lon, lat] = v.geometry.coordinates;
              const x = p.x(lon), y = p.y(lat);
              const col = `#${net?.byId.get(v.properties.routeId)?.color ?? "16201c"}`;
              const dim = focus && !focus.has(v.properties.routeId);
              return (
                <g key={v.properties.vehicleId} opacity={dim ? 0.15 : 1} style={{ transition: "opacity 260ms" }}>
                  {/* each dot glides to its new position over the 15 s until the next one */}
                  <motion.g initial={{ x, y, opacity: 0 }} animate={{ x, y, opacity: 1 }}
                    transition={{ x: { duration: 14, ease: "linear" }, y: { duration: 14, ease: "linear" }, opacity: { duration: 0.8, delay: (i % 30) * 0.02 } }}>
                    <circle cx={0} cy={0} r={3.4} fill={col} stroke="white" strokeWidth={1.2} />
                  </motion.g>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
    </div>
  );
}
