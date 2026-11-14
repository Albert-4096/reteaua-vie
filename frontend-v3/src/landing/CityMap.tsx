import { useMemo, useState } from "react";
import { motion } from "motion/react";
import type { Feature, MultiPolygon } from "geojson";
import { api, closurePoints, fmt, hhmm, useApi, type Closure, type Zone } from "@/lib/api";
import { dotGrid, fitProjection, type Projector } from "@/lib/geo";

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

type Props = {
  closures?: Closure[];
  showVehicles?: boolean;
  className?: string;
};

/** Timișoara as a dot grid of its 40 neighbourhoods, with live vehicles gliding between 15 s positions. */
export function CityMap({ closures = [], showVehicles = true, className }: Props) {
  const zones = useApi(api.zones);
  const vehicles = useApi(api.vehicles, showVehicles ? 15000 : undefined);
  const [hover, setHover] = useState<number | null>(null);

  const geo = useMemo(() => {
    if (!zones.data) return null;
    const feats = zones.data.features as Feature<MultiPolygon, Zone>[];
    const p = fitProjection(feats, W);
    const dots = dotGrid(feats, p, STEP);
    const byZone = feats.map((_, i) => zoneDotsPath(dots.filter((d) => d.zone === i)));
    const outlines = feats.map((f) => polygonPath(f.geometry, p));
    return { feats, p, byZone, outlines };
  }, [zones.data]);

  if (!geo) {
    return (
      <div className={className} aria-busy="true">
        <div className="aspect-[1100/820] w-full animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  const { feats, p, byZone, outlines } = geo;
  const hz = hover != null ? feats[hover].properties : null;
  const vs = vehicles.data?.features ?? [];
  const updated = vs[0]?.properties.updatedAt;

  return (
    <div className={className}>
      <svg viewBox={`0 0 ${p.width} ${p.height}`} className="block h-auto w-full" role="img"
        aria-label="Harta Timișoarei: cele 40 de cartiere ca puncte și vehiculele din datele live">
        {byZone.map((d, i) => (
          <path key={i} d={d} fill={hover === i ? "var(--green)" : "var(--dot-strong)"} opacity={hover === i ? 0.55 : 0.5}
            style={{ transition: "fill 200ms, opacity 200ms" }} />
        ))}
        {outlines.map((d, i) => (
          <path key={i} d={d} fill="transparent" stroke="none" onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)} />
        ))}

        {closures.map((c) => {
          const pts = closurePoints(c);
          if (!pts?.length) return null;
          const [lon, lat] = pts[Math.floor(pts.length / 2)];
          const x = p.x(lon), y = p.y(lat);
          return (
            <g key={c.id} pointerEvents="none">
              <motion.circle cx={x} cy={y} fill="var(--amber)" initial={{ r: 6, opacity: 0.5 }}
                animate={{ r: [6, 22], opacity: [0.45, 0] }} transition={{ duration: 2.4, repeat: Infinity, ease: "easeOut" }} />
              <circle cx={x} cy={y} r={6} fill="var(--amber)" stroke="white" strokeWidth={2} />
            </g>
          );
        })}

        {vs.map((v) => {
          const [lon, lat] = v.geometry.coordinates;
          return (
            <motion.circle key={v.properties.vehicleId} r={4.2} fill="var(--green)" stroke="white" strokeWidth={1.6}
              pointerEvents="none" cx={p.x(lon)} cy={p.y(lat)} initial={false} animate={{ cx: p.x(lon), cy: p.y(lat) }}
              transition={{ duration: 14, ease: "linear" }} />
          );
        })}
      </svg>

      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-full bg-green ring-2 ring-white" />
          <span className="tabular">{vs.length ? `${fmt.format(vs.length)} vehicule acum` : "vehicule live"}</span>
          {updated && <span className="tabular">· {hhmm(updated)}</span>}
        </span>
        {closures.length > 0 && (
          <span className="inline-flex items-center gap-2">
            <span className="size-2.5 rounded-full bg-amber ring-2 ring-white" />
            {closures.length} lucrări în platformă
          </span>
        )}
        <span className="min-h-5 tabular text-foreground/80" aria-live="polite">
          {hz ? `${hz.name}${hz.residents ? ` · ${fmt.format(Math.round(hz.residents / 100) * 100)} locuitori (model GHSL 2020)` : ""}` : ""}
        </span>
      </div>
    </div>
  );
}
