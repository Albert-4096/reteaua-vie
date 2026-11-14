import type { Closure, Impact, MissingRoute, Windows } from "@/lib/api";

export type I18n = { ro: string; en: string };
export type Window = { start: string; end: string };
export type Provenance = { source: string; url: string | null; version: string | null; fetchedAt: string; note: string | null };

export type ClosureSummary = Closure & {
  window: Window;
  zoneSlugs: string[];
  stopsSuspended: number;
  departuresLost: number;
  publishedAt: string | null;
  reconstructed?: boolean;
  reconstructedNote?: I18n;
};

export type Overview = {
  at: string;
  activeClosures: ClosureSummary[];
  upcomingClosures: ClosureSummary[];
  ghostDeparturesToday: number;
  missingLines: { prepared: { window: Window; case: { label: I18n } | null; rows: Missing["routes"] } };
  vehiclesLive: number;
  vehiclesAt: string;
  compliance: { covered: number; partial: number; missing: number };
};

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
  nearestServed: { name: string; distanceMeters: number } | null;
};
export type DecisionGroup = { id: string; routeId: string; question: I18n; reason: I18n; suggested: string; rows: { stopId: string; routeId: string; directionId: 0 | 1 }[] };
export type Analysis = { stops: AnalysisStop[]; routes: { routeId: string; shortName: string; stopsAffected: number }[]; unsureCount: number; decisionGroups: DecisionGroup[]; provenance: Provenance[] };

export type Conflict = { closureId: string; otherClosureId: string; otherTitle: I18n; overlap: Window; kind: string; routeIds: string[] };
export type Notice = { id: string; zoneName: string; title: I18n; body: I18n; stopIds: string[]; routeIds: string[]; publishedAt: string | null };
export type ExportFile = { name: string; format: string; standard: string; url: string; updatedAt: string | null };
export type Alert = { id: string; closureId: string; effect: string; headerText: I18n; descriptionText: I18n; informedEntity: { routeId?: string; stopId?: string }[] };
export type Obligation = { id: string; act: string; requirement: I18n; deadline: string; owner: I18n; status: "covered" | "partial" | "missing" | string; coveredBy: string[]; note: I18n };
export type Indicator = { code: string; name: I18n; value: number; unit: string; scope: string };
export type HistoryRow = { closureId: string; title: I18n; window: Window; publishedAt: string; stopsSuspended: number; departuresLost: number; routeIds: string[]; leadHours: number | null; sourceUrl: string };
type Effect = { sec: number; low: number; high: number; n: number; conclusive: boolean };
export type DetourCost = { status: string; label: I18n; totals: { measuredVsPlanned: Effect; estimateError: Effect } };
export type Missing = { window: Window; status: string; routes: (MissingRoute & { decision?: { decision: string } | null })[] };

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json() as Promise<T>;
}
async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: body ? { "content-type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) {
    const e = await r.json().catch(() => null);
    throw new Error(e?.error?.message ?? e?.detail ?? `${r.status}`);
  }
  return r.json() as Promise<T>;
}
const enc = encodeURIComponent;

export const app = {
  overview: () => get<Overview>("/api/overview"),
  closures: () => get<ClosureSummary[]>("/api/closures"),
  closure: (id: string) => get<ClosureSummary>(`/api/closures/${enc(id)}`),
  impact: (id: string) => get<Impact>(`/api/closures/${enc(id)}/impact`),
  analysis: (id: string) => get<Analysis>(`/api/closures/${enc(id)}/analysis`),
  windows: (id: string) => get<Windows & { method: I18n; searchFrom: string; searchTo: string }>(`/api/closures/${enc(id)}/windows`),
  conflicts: (id: string) => get<Conflict[]>(`/api/closures/${enc(id)}/conflicts`),
  notices: (id: string) => get<Notice[]>(`/api/closures/${enc(id)}/notices`),
  alerts: () => get<Alert[]>("/api/feed/alerts.json"),
  exports: () => get<ExportFile[]>("/api/exports"),
  missing: () => get<Missing>("/api/live/missing"),
  compliance: () => get<{ obligations: Obligation[] }>("/api/compliance"),
  indicators: () => get<{ indicators: Indicator[] }>("/api/indicators"),
  history: () => get<HistoryRow[]>("/api/history"),
  detourCost: (id: string) => get<DetourCost>(`/api/closures/${enc(id)}/detour-cost`),
  decideStops: (id: string, decisions: { stopId: string; routeId: string; directionId: 0 | 1; confirmed: boolean }[]) =>
    send<unknown>("PATCH", `/api/closures/${enc(id)}/stops`, { decisions }),
  publish: (id: string) => send<unknown>("POST", `/api/closures/${enc(id)}/publish`),
  triage: (routeId: string, window: Window, decision: "confirmat" | "respins" | "nu_stiu", who: string) =>
    send<{ decision: string }>("PATCH", `/api/live/missing/${enc(routeId)}`, { window, decision, reason: null, who, note: null }),
  posterUrl: (id: string, stopId: string) => `/api/closures/${enc(id)}/poster.pdf?stopId=${enc(stopId)}`,
};

export const dt = (iso: string) =>
  new Date(iso).toLocaleString("ro-RO", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Bucharest" });
export const day = (iso: string) => new Date(iso).toLocaleDateString("ro-RO", { day: "numeric", month: "short", timeZone: "Europe/Bucharest" });
