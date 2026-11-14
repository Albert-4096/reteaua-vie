import { useMemo, useState } from "react";
import { motion } from "motion/react";
import type { Feature, MultiPolygon } from "geojson";
import { api, closurePoints, fmt, hhmm, useApi, type Closure, type Zone } from "@/lib/api";
import { dotGrid, fitProjection, type Projector } from "@/lib/geo";
import { FAMILIES, modeName, useNetwork } from "@/lib/network";

const W = 1100;
const STEP = 7;
const R = 1.65;

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
 * Timișoara as a dot grid of its 40 neighbourhoods, the transit lines in STPT's own colours,
 * and the vehicles in the live data gliding between their 15 s positions.
 */
export function CityMap({ closures = [], className }: Props) {
  const zones = useApi(api.zones);
  const vehicles = useApi(api.vehicles, 15000);
  const net = useNetwork();
  const [hoverZone, setHoverZone] = useState<number | null>(null);
  const [hoverLine, setHoverLine] = useState<string | null>(null);

  const geo = useMemo(() => {
    if (!zones.data) return null;
    const feats = zones.data.features as Feature<MultiPolygon, Zone>[];
    const p = fitProjection(feats, W);
    const dots = dotGrid(feats, p, STEP);
    const byZone = feats.map((_, i) => zoneDotsPath(dots.filter((d) => d.zone === i)));
    const outlines = feats.map((f) => polygonPath(f.geometry, p));
    return { feats, p, byZone, outlines };
  }, [zones.data]);

  const lines = useMemo(() => {
    if (!geo || !net) return [];
    const order = (t: number) => (t === 0 ? 2 : t === 11 ? 1 : 0); // trams on top, as on the street
    return net.paths
      .filter((x) => x.directionId === 0)
      .map((x) => {
        const r = net.byId.get(x.routeId)!;
        const d = "M" + x.geometry.coordinates.map(([lon, lat]) => `${geo.p.x(lon).toFixed(1)} ${geo.p.y(lat).toFixed(1)}`).join("L");
        return { id: x.routeId, r, d };
      })
      .filter((l) => l.r)
      .sort((a, b) => order(a.r.type) - order(b.r.type));
  }, [geo, net]);

  if (!geo) {
    return (
      <div className={className} aria-busy="true">
        <div className="aspect-[1100/820] w-full animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  const { feats, p, byZone, outlines } = geo;
  const hz = hoverZone != null ? feats[hoverZone].properties : null;
  const hl = hoverLine ? net?.byId.get(hoverLine) : null;
  const vs = vehicles.data?.features ?? [];
  const updated = vs[0]?.properties.updatedAt;

  return (
    <div className={className}>
      <svg viewBox={`0 0 ${p.width} ${p.height}`} className="block h-auto w-full" role="img"
        aria-label="Harta Timișoarei: cele 40 de cartiere, liniile de transport în culorile STPT și vehiculele din datele live">
        {byZone.map((d, i) => (
          <path key={i} d={d} fill={hoverZone === i ? "var(--green)" : "var(--dot-strong)"} opacity={hoverZone === i ? 0.5 : 0.42}
            style={{ transition: "fill 200ms, opacity 200ms" }} />
        ))}
        {outlines.map((d, i) => (
          <path key={i} d={d} fill="transparent" onPointerEnter={() => setHoverZone(i)} onPointerLeave={() => setHoverZone(null)} />
        ))}

        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {lines.map((l) => {
            const on = hoverLine === l.id;
            const dim = hoverLine != null && !on;
            return (
              <path key={l.id} d={l.d} stroke={`#${l.r.color}`} strokeWidth={(l.r.type === 0 ? 3 : 2) + (on ? 1.6 : 0)}
                opacity={dim ? 0.12 : on ? 1 : 0.62} style={{ transition: "opacity 200ms, stroke-width 200ms" }} pointerEvents="none" />
            );
          })}
          {lines.map((l) => (
            <path key={`hit-${l.id}`} d={l.d} stroke="transparent" strokeWidth={9}
              onPointerEnter={() => setHoverLine(l.id)} onPointerLeave={() => setHoverLine(null)} />
          ))}
        </g>

        {closures.map((c) => {
          const pts = closurePoints(c);
          if (!pts.length) return null;
          const [lon, lat] = pts[Math.floor(pts.length / 2)];
          const x = p.x(lon), y = p.y(lat);
          return (
            <g key={c.id} pointerEvents="none">
              <motion.circle cx={x} cy={y} fill="var(--closure)" initial={{ r: 6, opacity: 0.5 }}
                animate={{ r: [6, 24], opacity: [0.5, 0] }} transition={{ duration: 2.4, repeat: Infinity, ease: "easeOut" }} />
              <circle cx={x} cy={y} r={6.5} fill="var(--closure)" stroke="white" strokeWidth={2.2} />
            </g>
          );
        })}

        {vs.map((v) => {
          const [lon, lat] = v.geometry.coordinates;
          return (
            <motion.circle key={v.properties.vehicleId} r={4} fill="var(--foreground)" stroke="white" strokeWidth={1.8}
              pointerEvents="none" cx={p.x(lon)} cy={p.y(lat)} initial={false} animate={{ cx: p.x(lon), cy: p.y(lat) }}
              transition={{ duration: 14, ease: "linear" }} />
          );
        })}
      </svg>

      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
        {net && FAMILIES.map((f) => {
          const r = net.routes.find(f.test);
          return r ? (
            <span key={f.id} className="inline-flex items-center gap-2">
              <span className="h-1 w-5 rounded-full" style={{ background: `#${r.color}` }} />{f.label}
            </span>
          ) : null;
        })}
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-full bg-foreground ring-2 ring-white" />
          <span className="tabular">{vs.length ? `${fmt.format(vs.length)} vehicule acum` : "vehicule live"}{updated ? ` · ${hhmm(updated)}` : ""}</span>
        </span>
        {closures.length > 0 && (
          <span className="inline-flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-closure ring-2 ring-white" />{closures.length} lucrări
          </span>
        )}
      </div>
      <p className="mt-2 min-h-6 tabular text-[0.95rem] text-foreground" aria-live="polite">
        {hl ? `${modeName(hl)} ${hl.shortName} · ${hl.longName}`
          : hz ? `${hz.name}${hz.residents ? ` · ${fmt.format(Math.round(hz.residents / 100) * 100)} locuitori (model GHSL 2020)` : ""}`
          : <span className="text-muted-foreground">Treceți cu mouse-ul peste o linie sau un cartier.</span>}
      </p>
    </div>
  );
}
