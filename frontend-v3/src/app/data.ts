import { useState } from "react";
import type { FeatureCollection, LineString, Point } from "geojson";
import { useApi, type Closure, type MissingRoute } from "@/lib/api";

export type I18n = { ro: string; en: string };
export type Window = { start: string; end: string };
export type Provenance = { source: string; url: string | null; version: string | null; fetchedAt: string; note: string | null };

export type RouteAction = { routeId: string; directionId: 0 | 1 | null; action: "suspended" | "shortened" | "diverted" | string; stopNames: string[] | null };
export type TempRoute = { shortName: string; mode: string; streets: string[]; geometry?: LineString };
export type ClosureSummary = Closure & {
  window: Window;
  zoneSlugs: string[];
  stopsSuspended: number;
  departuresLost: number;
  publishedAt: string | null;
  sourceText?: string | null;
  sourceUrl?: string | null;
  routeActions?: RouteAction[] | null;
  temporaryRoutes?: TempRoute[] | null;
  locationNote?: I18n | null;
};

export type MissingRow = MissingRoute & { decision?: { decision: string } | null };
export type Missing = { window: Window; status: string; routes: MissingRow[] };
export type Overview = {
  at: string;
  activeClosures: ClosureSummary[];
  upcomingClosures: ClosureSummary[];
  ghostDeparturesToday: number | null;
  missingLines: { prepared: { window: Window; case: { label: I18n } | null; rows: MissingRow[] } };
  vehiclesLive: number;
  vehiclesAt: string;
  compliance: { covered: number; partial: number; missing: number };
};

export type Nearest = { stopId: string; name: string; distanceMeters: number };
export type AnalysisStop = {
  stopId: string;
  name: string;
  location: [number, number];
  routeId: string;
  routeShortName: string;
  directionId: 0 | 1;
  headsign: string;
  state: "affected" | "unsure" | string;
  departuresLost: number;
  confirmed: boolean | null;
  nearestServed: Nearest | null;
};
export type DecisionRow = { stopId: string; routeId: string; directionId: 0 | 1 };
export type DecisionGroup = { id: string; routeId: string; question: I18n; reason: I18n; suggested: string | null; rows: DecisionRow[] };
export type Analysis = { stops: AnalysisStop[]; routes: { routeId: string; shortName: string; stopsAffected: number }[]; unsureCount: number; decisionGroups: DecisionGroup[]; provenance: Provenance[] };

export type Impact = {
  totals: { stopsSuspended: number; departuresLost: number; routesAffected: number; residentsLosingStop: number | null };
  window: Window;
  byZone: { slug: string; name: string; stopsSuspended: number; departuresLost: number; residentsLosingStop: number | null }[];
  method: I18n;
};
export type NoticeStop = { stopId: string; name: string; nearestServed: Nearest | null };
export type NoticeSection = { routeId: string; shortName: string; mode: string; directionId: 0 | 1 | null; headsign: string | null; action: string; stopsNotServed: NoticeStop[] };
export type GeneratedNotice = { status: "draft" | "final" | string; unsureCount: number; text: I18n; sections: NoticeSection[]; stopsWithNoService: NoticeStop[]; sourceText: string | null; sourceUrl: string | null; mapUrl: string | null };

export type WindowCandidate = { window: Window; departuresLost: number; rank: number; conflicts: number };
export type Windows = { candidates: WindowCandidate[]; baselineDeparturesLost: number; method: I18n; searchFrom: string; searchTo: string; hours: number };
export type Conflict = { closureId: string; otherClosureId: string; otherTitle: I18n; overlap: Window; kind: string; routeIds: string[] };
export type Notice = { id: string; zoneName: string; title: I18n; body: I18n; stopIds: string[]; routeIds: string[]; publishedAt: string | null };
export type ExportFile = { name: string; format: string; standard: string; url: string; updatedAt: string | null };
export type Alert = { id: string; closureId: string; effect: string; headerText: I18n; descriptionText: I18n; informedEntity: { routeId?: string; stopId?: string }[] };
export type Obligation = { id: string; act: string; requirement: I18n; deadline: string; owner: I18n; status: "covered" | "partial" | "missing" | string; coveredBy: string[]; note: I18n };
export type Indicator = { code: string; name: I18n; value: number; unit: string; scope: string };
export type HistoryRow = { closureId: string; title: I18n; window: Window; publishedAt: string; stopsSuspended: number; departuresLost: number; routeIds: string[]; leadHours: number | null; sourceUrl: string };

type Effect = { n: number; addedSec: number | null; low: number | null; high: number | null; verdict: string; text: I18n };
export type DelayEffect = { status: string; total: Effect | null; stretches: { routeId: string; shortName: string; directionId: 0 | 1; fromStop: string; toStop: string; effect: Effect }[]; method: I18n };
export type LiveCheck = {
  summary: { vehiclesSeen: number | null; stopsSkipped: number | null; stopsServedAnyway: number | null; stopsUnknown: number | null };
  label: I18n | null;
  note: I18n | null;
  method: I18n;
  recordedFrom: string | null;
  recordedTo: string | null;
};
/* ---------- what only the recording can say (the City Hall live feed, kept every 15 s) ---------- */
export type Recording = { from: string; to: string; hours: number; label: I18n };
export type LineReliability = {
  routeId: string;
  shortName: string;
  punctuality: { trips: number; medianSec: number | null; early: number | null; onTime: number | null; late: number | null; veryLate: number | null; conclusive: boolean };
  headway: { pairs: number; medianRealMin: number | null; medianSchedMin: number | null };
  trips: { scheduled: number; observed: number; missed: number; share: number | null };
  hours: { hour: number; trips: { scheduled: number; observed: number } }[];
};
export type Reliability = { recording: Recording; lines: LineReliability[]; caveat: I18n; method: I18n };
export type Deviation = {
  routeId: string; shortName: string; street: string | null; nearStop: string | null; classification: string; label: I18n;
  trips: number; tripsSeen: number; firstAt: string; lastAt: string; maxDistanceM: number; tracks: { coordinates: [number, number][] }[];
};
export type Deviations = { window: Window; status: string; groups: Deviation[] };
type Sec = { sec: number | null; low: number | null; high: number | null; n: number; conclusive: boolean };
export type DetourCost = {
  status: string; label: I18n; finding: I18n | null; method: I18n;
  stretches: { routeId: string; shortName: string; directionId: 0 | 1; after: { stopNames: string[] }; planned: { after: Sec }; measured: Sec | null; estimated: Sec | null }[];
  totals: { measuredVsPlanned: Sec; estimateError: Sec } | null;
};
export type MeasuredWindows = { status: string; label: I18n; note: I18n | null; candidates: { window: Window; rank: number }[] };
export type Registry = { entries: { date: string; final: boolean; chainHash: string; recording: { firstAt: string | null; lastAt: string | null; healthyShare: number | null }; lines: { routeId: string; tripsScheduledInRecording: number; tripsSeen: number; kmEstimated: number | null }[] }[] };

export type LineStatus = { routeId: string; shortName: string; mode: string; state: string; label: I18n; closureId: string | null; closureTitle: I18n | null };
export type LiveVehicle = { vehicleId: string; routeId: string; directionId: 0 | 1 | null; stopId: string | null; status: string | null; delaySec: number | null; headsign: string | null; updatedAt: string };
export type Vehicles = FeatureCollection<Point, LiveVehicle>;

/**
 * The rail, the panel and the map often ask for the same thing in the same second. One request serves them all:
 * an answer younger than a few seconds is shared, and any change we send clears the lot.
 */
const SHARE_MS = 4000;
const recent = new Map<string, { at: number; value: Promise<unknown> }>();
function get<T>(path: string): Promise<T> {
  const hit = recent.get(path);
  if (hit && Date.now() - hit.at < SHARE_MS) return hit.value as Promise<T>;
  const value = fetch(path).then((r) => {
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json() as Promise<T>;
  });
  recent.set(path, { at: Date.now(), value });
  value.catch(() => recent.delete(path));
  return value;
}
async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  recent.clear();
  const r = await fetch(path, { method, headers: body ? { "content-type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    const e = await r.json().catch(() => null);
    throw new Error(e?.error?.message ?? e?.detail ?? `${r.status}`);
  }
  return r.json() as Promise<T>;
}
const enc = encodeURIComponent;

/** Slow analyses answer `{ jobId }` first; wait for the job and hand back its result. */
async function getJob<T>(path: string): Promise<T> {
  const first = await get<T | { jobId: string }>(path);
  if (!first || typeof first !== "object" || !("jobId" in first) || Object.keys(first).length > 2) return first as T;
  for (let i = 0; i < 60; i++) {
    recent.delete(`/api/jobs/${enc(first.jobId)}`);
    const j = await get<{ state: string; result: T | null; error: { message: string } | null }>(`/api/jobs/${enc(first.jobId)}`);
    if (j.state === "done" && j.result) { recent.delete(path); return j.result; }
    if (j.state === "error") throw new Error(j.error?.message ?? "calculul nu a reușit");
    await new Promise((r) => setTimeout(r, 1500));
  }
  recent.delete(path);
  throw new Error("calculul durează prea mult");
}

export const app = {
  overview: () => get<Overview>("/api/overview"),
  closures: () => get<ClosureSummary[]>("/api/closures"),
  closure: (id: string) => get<ClosureSummary>(`/api/closures/${enc(id)}`),
  /** Every work with its geometry (the list alone has none). */
  works: async () => {
    const list = await get<ClosureSummary[]>("/api/closures");
    const full = await Promise.all(list.map((c) => get<ClosureSummary>(`/api/closures/${enc(c.id)}`).catch(() => null)));
    return list.map((c, i) => ({ ...c, ...(full[i] ?? {}), stopsSuspended: c.stopsSuspended, departuresLost: c.departuresLost }));
  },
  impact: (id: string) => get<Impact>(`/api/closures/${enc(id)}/impact`),
  analysis: (id: string) => get<Analysis>(`/api/closures/${enc(id)}/analysis`),
  notice: (id: string) => get<GeneratedNotice>(`/api/closures/${enc(id)}/notice`),
  windows: (id: string) => get<Windows>(`/api/closures/${enc(id)}/windows`),
  conflicts: (id: string) => get<Conflict[]>(`/api/closures/${enc(id)}/conflicts`),
  notices: (id: string) => get<Notice[]>(`/api/closures/${enc(id)}/notices`),
  live: (id: string) => get<LiveCheck>(`/api/closures/${enc(id)}/live`),
  delayEffect: (id: string) => get<DelayEffect>(`/api/closures/${enc(id)}/delay-effect`),
  alerts: () => get<Alert[]>("/api/feed/alerts.json"),
  exports: () => get<ExportFile[]>("/api/exports"),
  missing: () => get<Missing>("/api/live/missing"),
  vehicles: () => get<Vehicles>("/api/live/vehicles"),
  linesStatus: () => get<{ at: string; lines: LineStatus[] }>("/api/lines/status"),
  reliability: () => get<Reliability>("/api/reliability/lines"),
  deviations: () => get<Deviations>("/api/live/deviations"),
  detourCost: (id: string) => getJob<DetourCost>(`/api/closures/${enc(id)}/detour-cost`),
  windowsMeasured: (id: string) => getJob<MeasuredWindows>(`/api/closures/${enc(id)}/windows/measured`),
  registry: () => get<Registry>("/api/registry"),
  compliance: () => get<{ obligations: Obligation[] }>("/api/compliance"),
  indicators: () => get<{ indicators: Indicator[] }>("/api/indicators"),
  history: () => get<HistoryRow[]>("/api/history"),
  decideStops: (id: string, decisions: (DecisionRow & { confirmed: boolean })[]) =>
    send<Analysis>("PATCH", `/api/closures/${enc(id)}/stops`, { decisions }),
  publish: (id: string) => send<unknown>("POST", `/api/closures/${enc(id)}/publish`),
  triage: (routeId: string, window: Window, decision: "confirmat" | "respins", who: string) =>
    send<{ decision: string }>("PATCH", `/api/live/missing/${enc(routeId)}`, { window, decision, reason: null, who, note: null }),
  posterUrl: (id: string, stopId: string) => `/api/closures/${enc(id)}/poster.pdf?stopId=${enc(stopId)}`,
};

/** `useApi` with a way to ask again after something was decided. The last good value stays while it reloads. */
export function useLoad<T>(load: () => Promise<T>, key = "", everyMs?: number) {
  const [rev, setRev] = useState(0);
  const [own, setOwn] = useState<T | null>(null); // an answer the server already gave us (a PATCH returns the new state)
  const r = useApi(load, everyMs, `${key}#${rev}`);
  return { data: own ?? r.data, error: r.error, set: setOwn, reload: () => setRev((x) => x + 1) };
}

const TZ = "Europe/Bucharest";
const part = (iso: string, o: Intl.DateTimeFormatOptions) => new Date(iso).toLocaleString("ro-RO", { timeZone: TZ, ...o });
export const hhmm = (iso: string) => part(iso, { hour: "2-digit", minute: "2-digit" });
export const day = (iso: string) => part(iso, { day: "numeric", month: "short" });
export const weekday = (iso: string) => part(iso, { weekday: "long", day: "numeric", month: "long" });
export const dt = (iso: string) => part(iso, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** A window in the fewest words: one day with its hours, or two dates. */
export function when(w: Window) {
  const sameDay = day(w.start) === day(w.end);
  if (sameDay) return `${part(w.start, { weekday: "short", day: "numeric", month: "short" })}, ${hhmm(w.start)}–${hhmm(w.end)}`;
  return `${day(w.start)} – ${day(w.end)}`;
}

/** Names on the map must not sit on each other: the second label near another one goes below its point. */
export function spread<T extends { lon: number; lat: number }>(labels: T[]): (T & { place: "top" | "bottom" })[] {
  return labels.map((l, i) => {
    const near = labels.slice(0, i).filter((o) => Math.abs(o.lon - l.lon) < 0.02 && Math.abs(o.lat - l.lat) < 0.006).length;
    return { ...l, place: near % 2 ? "bottom" : "top" };
  });
}

/** Where a work stands against the clock. */
export function phase(w: Window, now: string): "urmează" | "în desfășurare" | "încheiată" {
  const t = Date.parse(now);
  return t < Date.parse(w.start) ? "urmează" : t > Date.parse(w.end) ? "încheiată" : "în desfășurare";
}

/** The street of a work, short enough to write on the map: "Bd. 16 Decembrie 1989 – Piața Mocioni". */
export function place(title: string) {
  const hits = title.match(/(Bd\.|Bulevardul|Str\.|Strada|Piața|Calea|Splaiul|Podul)\s+[^,–]+/g) ?? [];
  const names = hits.map((h) => h.replace(/\s+(închisă|închis|deviată)$/, "").trim()).slice(0, 2);
  return names.length ? names.join(" – ") : title.split(",")[0];
}

export const fmt = new Intl.NumberFormat("ro-RO");
/** Romanian counts: "1 stație", "16 stații", "21 de stații". */
export function count(n: number, one: string, many: string) {
  const de = n !== 0 && (n % 100 === 0 || n % 100 >= 20) ? " de" : "";
  return `${fmt.format(n)}${n === 1 ? "" : de} ${n === 1 ? one : many}`;
}
export const uniq = <T,>(xs: T[]) => [...new Set(xs)];
