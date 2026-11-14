import { useEffect, useState } from "react";
import type { LineString } from "geojson";

export type Route = { id: string; shortName: string; longName: string; type: number; color: string; textColor: string };
export type Path = { routeId: string; directionId: number; geometry: LineString };
export type Network = { routes: Route[]; paths: Path[]; byId: Map<string, Route> };

/** The five families STPT colours its lines by, in the city's own colours (GTFS route_color). */
export const FAMILIES = [
  { id: "tram", label: "Tramvai", test: (r: Route) => r.type === 0 },
  { id: "trolley", label: "Troleibuz", test: (r: Route) => r.type === 11 },
  { id: "bus", label: "Autobuz", test: (r: Route) => r.type === 3 && !/^[EM]\d/.test(r.shortName) },
  { id: "express", label: "Expres", test: (r: Route) => /^E\d/.test(r.shortName) },
  { id: "metro", label: "Metropolitan", test: (r: Route) => /^M\d/.test(r.shortName) },
] as const;

/** Readable text on a line colour: GTFS text colours are not always legible (white on tram gold). */
export function inkOn(hex: string) {
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const L = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return (L + 0.05) / 0.063 > 1.05 / (L + 0.05) ? "#16201c" : "#ffffff"; // whichever contrasts more (#16201c ≈ 0.013)
}

export const modeName = (r: Route) => (r.type === 0 ? "Tramvaiul" : r.type === 11 ? "Troleibuzul" : "Autobuzul");

let cache: Promise<Network> | null = null;

export function loadNetwork() {
  cache ??= fetch("/api/network")
    .then((r) => {
      if (!r.ok) throw new Error(`/api/network: ${r.status}`);
      return r.json() as Promise<{ routes: Route[]; paths: Path[] }>;
    })
    .then(({ routes, paths }) => ({ routes, paths: paths.map(({ routeId, directionId, geometry }) => ({ routeId, directionId, geometry })), byId: new Map(routes.map((r) => [r.id, r])) }))
    .catch((e) => {
      cache = null;
      throw e;
    });
  return cache;
}

export function useNetwork() {
  const [net, setNet] = useState<Network | null>(null);
  useEffect(() => {
    let alive = true;
    loadNetwork().then((n) => alive && setNet(n)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return net;
}
