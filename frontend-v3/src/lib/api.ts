import { useEffect, useState } from "react";
import type { FeatureCollection, MultiPolygon, Point, LineString, MultiLineString } from "geojson";

export type Zone = { slug: string; name: string; residents: number | null };
export type Vehicle = {
  vehicleId: string;
  routeId: string;
  headsign?: string;
  delaySec?: number | null;
  updatedAt?: string;
};
export type MissingRoute = {
  routeId: string;
  shortName: string;
  longName: string;
  mode: string;
  state: string;
  tripsInService: number;
  tripsObserved: number;
  firstMissedTrip?: { stopName: string; scheduledTime: string } | null;
};
export type Closure = {
  id: string;
  title: { ro: string; en: string };
  status: string;
  geometry?: LineString | MultiLineString;
  routeIds: string[];
  sourceText?: string;
};
export type Impact = {
  totals: { stopsSuspended: number; departuresLost: number; routesAffected: number; residentsLosingStop: number };
  window: { start: string; end: string };
};
export type WindowCandidate = {
  window: { start: string; end: string };
  departuresLost: number;
  rank: number;
};
export type Windows = { candidates: WindowCandidate[]; baselineDeparturesLost: number };

export const api = {
  zones: () => get<FeatureCollection<MultiPolygon, Zone>>("/api/layers/coverage"),
  vehicles: () => get<FeatureCollection<Point, Vehicle>>("/api/live/vehicles"),
  streets: () => get<FeatureCollection<LineString, { id: string; name: string | null }>>("/api/layers/streets"),
  missing: () => get<{ window: { start: string; end: string }; routes: MissingRoute[] }>("/api/live/missing"),
  closure: (id: string) => get<Closure>(`/api/closures/${id}`),
  impact: (id: string) => get<Impact>(`/api/closures/${id}/impact`),
  windows: (id: string) => get<Windows>(`/api/closures/${id}/windows`),
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json() as Promise<T>;
}

/** Fetch once (or every `everyMs`), keep the last good value. */
export function useApi<T>(load: () => Promise<T>, everyMs?: number, key = "") {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const run = () =>
      load()
        .then((d) => alive && (setData(d), setError(null)))
        .catch((e: Error) => alive && setError(e.message));
    run();
    const t = everyMs ? window.setInterval(run, everyMs) : undefined;
    return () => {
      alive = false;
      if (t) window.clearInterval(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, everyMs]);
  return { data, error };
}

export const fmt = new Intl.NumberFormat("ro-RO");

/** All vertices of a closure, whatever its geometry type. */
export const closurePoints = (c: Closure): number[][] =>
  !c.geometry ? [] : c.geometry.type === "MultiLineString" ? c.geometry.coordinates.flat() : c.geometry.coordinates;
export const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Bucharest" });
