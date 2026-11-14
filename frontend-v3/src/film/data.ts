import { useEffect, useMemo, useState } from "react";
import type { Feature, FeatureCollection, LineString, MultiPolygon, Point } from "geojson";
import { api, closurePoints, type Closure, type Impact, type MissingRoute, type Vehicle, type Windows, type Zone } from "@/lib/api";
import { dotGrid, fitProjection, type Projector } from "@/lib/geo";
import { loadNetwork, type Network } from "@/lib/network";

export const FILM_CLOSURE = "cl_20261108_16dec";
export const W = 1100;

export type FilmData = {
  zones: FeatureCollection<MultiPolygon, Zone>;
  streets: FeatureCollection<LineString, { id: string; name: string | null }>;
  vehicles: FeatureCollection<Point, Vehicle>;
  missing: MissingRoute[];
  closure: Closure;
  impact: Impact;
  windows: Windows;
  net: Network;
};

export function useFilmData() {
  const [data, setData] = useState<FilmData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    setError(null);
    Promise.all([
      api.zones(), api.streets(), api.vehicles(), api.missing(),
      api.closure(FILM_CLOSURE), api.impact(FILM_CLOSURE), api.windows(FILM_CLOSURE), loadNetwork(),
    ])
      .then(([zones, streets, vehicles, missing, closure, impact, windows, net]) =>
        setData({ zones, streets, vehicles, missing: missing.routes, closure, impact, windows, net }))
      .catch((e: Error) => setError(e.message));
  }, [attempt]);
  return { data, error, retry: () => setAttempt((n) => n + 1) };
}

export type Geo = {
  p: Projector;
  cityDots: string;
  streets: string;
  crop: { x: number; y: number; w: number; h: number };
  cropDots: string;
  seg: [number, number][];
  vehicles: { id: string; x: number; y: number }[];
  lines: { id: string; d: string; color: string; tram: boolean; affected: boolean }[];
};

const dotsPath = (dots: { x: number; y: number }[], r: number) =>
  dots.map(({ x, y }) => `M${(x - r).toFixed(1)} ${y.toFixed(1)}a${r} ${r} 0 1 0 ${r * 2} 0a${r} ${r} 0 1 0 ${-r * 2} 0`).join("");

/** Project everything once: the whole city, a close crop around the closure, and the closed stretch of street. */
export function useGeo(d: FilmData | null): Geo | null {
  return useMemo(() => {
    if (!d) return null;
    const feats = d.zones.features as Feature<MultiPolygon, Zone>[];
    const p = fitProjection(feats, W);
    const cityDots = dotsPath(dotGrid(feats, p, 9), 2.1);
    const streets = d.streets.features
      .map((f) => "M" + f.geometry.coordinates.map(([lon, lat]) => `${p.x(lon).toFixed(1)} ${p.y(lat).toFixed(1)}`).join("L"))
      .join("");

    const cc = closurePoints(d.closure).length ? closurePoints(d.closure) : [[21.2192, 45.7487]];
    const [mlon, mlat] = cc[Math.floor(cc.length / 2)];
    const mx = p.x(mlon), my = p.y(mlat);

    // The closed stretch: the transit street nearest to the closure, cut to ~250 m around it.
    let best: [number, number][] = [];
    let bestD = Infinity;
    for (const f of d.streets.features) {
      const pts = f.geometry.coordinates.map(([lon, lat]) => [p.x(lon), p.y(lat)] as [number, number]);
      const dmin = Math.min(...pts.map(([x, y]) => Math.hypot(x - mx, y - my)));
      if (dmin < bestD) { bestD = dmin; best = pts; }
    }
    let seg = best.filter(([x, y]) => Math.hypot(x - mx, y - my) < 22);
    if (seg.length < 2) seg = [[mx - 10, my], [mx + 10, my]];

    const w = 150, h = w * (522 / 820);
    const crop = { x: mx - w / 2, y: my - h / 2, w, h };
    const cropDots = dotsPath(dotGrid(feats, p, 2.4, { x0: crop.x - 4, y0: crop.y - 4, x1: crop.x + w + 4, y1: crop.y + h + 4 }), 0.55);

    const vehicles = d.vehicles.features.map((v) => ({ id: v.properties.vehicleId, x: p.x(v.geometry.coordinates[0]), y: p.y(v.geometry.coordinates[1]) }));
    const affected = new Set(d.closure.routeIds);
    const lines = d.net.paths
      .filter((x) => x.directionId === 0 && d.net.byId.has(x.routeId))
      .map((x) => {
        const r = d.net.byId.get(x.routeId)!;
        return { id: x.routeId, color: `#${r.color}`, tram: r.type === 0, affected: affected.has(x.routeId),
          d: "M" + x.geometry.coordinates.map(([lon, lat]) => `${p.x(lon).toFixed(1)} ${p.y(lat).toFixed(1)}`).join("L") };
      })
      .sort((a, b) => Number(a.affected) - Number(b.affected));
    return { p, cityDots, streets, crop, cropDots, seg, vehicles, lines };
  }, [d]);
}
