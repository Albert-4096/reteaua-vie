// Typed reads of the shared /api (CONTRACT.md). Only the fields v2 uses are typed.
import { useEffect, useState } from "react";

export type I18n = { ro: string; en: string };

export type Route = { id: string; shortName: string; longName: string; type: number; color: string; textColor: string };
export type Stop = { id: string; name: string; lat: number; lon: number; routeIds: string[] };
export type Path = { routeId: string; directionId: number; geometry: GeoJSON.LineString };
export type Network = { feedVersion: string; routes: Route[]; stops: Stop[]; paths: Path[] };

export type MissingRoute = {
  routeId: string;
  shortName: string;
  longName: string;
  mode: "autobuz" | "troleibuz" | "tramvai";
  state: "fara_vehicul" | "partial";
  tripsInService: number;
  tripsObserved: number;
  since: string;
  lastSeenAt: string | null;
  firstMissedTrip: { tripId: string; stopId: string; stopName: string; scheduledTime: string } | null;
  decision?: { decision: string; decidedAt: string } | null;
  repeatedDays?: number | null;
};
export type Missing = {
  window: { start: string; end: string };
  status: "ok" | "inregistrare_incompleta";
  routes: MissingRoute[];
  byMode: { mode: string; tripsScheduled: number; tripsWithNoVehicle: number; share: number | null }[];
  recording: { snapshots: number; healthySnapshots: number; healthyShare: number };
};

export type ClosureSummary = {
  id: string;
  title: I18n;
  status: "draft" | "analyzed" | "published";
  window: { start: string; end: string };
  routeIds: string[];
  stopsSuspended: number | null;
  departuresLost: number | null;
  publishedAt: string | null;
  reconstructed?: boolean;
};

export type Overview = {
  at: string;
  activeClosures: ClosureSummary[];
  upcomingClosures: ClosureSummary[];
  ghostDeparturesToday: number | null;
  vehiclesLive: number | null;
  vehiclesAt: string | null;
};

export type Closure = ClosureSummary & { geometry?: GeoJSON.Geometry | null };

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return (await r.json()) as T;
}

export const api = {
  network: () => getJson<Network>("/api/network"),
  missing: () => getJson<Missing>("/api/live/missing"),
  overviewNow: () => getJson<Overview>(`/api/overview?at=${encodeURIComponent(localIso(new Date()))}`),
  closure: (id: string) => getJson<Closure>(`/api/closures/${id}`),
};

/** ISO time with the Bucharest offset, as the API writes it. */
export function localIso(d: Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Bucharest",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    timeZoneName: "longOffset",
  }).formatToParts(d);
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  const off = (p.timeZoneName ?? "GMT+02:00").replace("GMT", "") || "+00:00";
  return `${p.year}-${p.month}-${p.day}T${p.hour === "24" ? "00" : p.hour}:${p.minute}:${p.second}${off}`;
}

export type Load<T> = { data: T | null; error: string | null };

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): Load<T> {
  const [state, set] = useState<Load<T>>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    fn().then(
      (data) => live && set({ data, error: null }),
      (e: unknown) => live && set({ data: null, error: String(e) }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

const fmtTime = new Intl.DateTimeFormat("ro-RO", { timeZone: "Europe/Bucharest", hour: "2-digit", minute: "2-digit" });
const fmtDay = new Intl.DateTimeFormat("ro-RO", { timeZone: "Europe/Bucharest", weekday: "short", day: "numeric", month: "short" });
const fmtDate = new Intl.DateTimeFormat("ro-RO", { timeZone: "Europe/Bucharest", day: "numeric", month: "short" });

export const hhmm = (iso: string) => fmtTime.format(new Date(iso));
export const dayLabel = (iso: string) => fmtDay.format(new Date(iso));
export const dateLabel = (iso: string) => fmtDate.format(new Date(iso));
export const nf = new Intl.NumberFormat("ro-RO");
