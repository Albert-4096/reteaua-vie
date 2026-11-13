// Typed GETs for the v2 endpoints (CONTRACT „v2 endpoints, by demo step”), on the shared client.
// D-011: real /api only. Paths marked J may answer 202; apiGet polls the job and calls onPending.
import { apiGet } from "./client";
import type { components } from "./schema";

type S = components["schemas"];
export type Overview = S["Overview"];
export type ClosureSummary = S["ClosureSummary"];
export type LayerCollection = S["LayerCollection"];
export type BikeImpact = S["BikeImpact"];
export type ParkingImpact = S["ParkingImpact"];
export type AccessImpact = S["AccessImpact"];
export type DetourLoad = S["DetourLoad"];
export type Conflict = S["Conflict"];
export type ReportSummary = S["ReportSummary"];
export type WindowSuggestion = S["WindowSuggestion"];
export type Scenario = S["Scenario"];
export type ScenarioImpact = S["ScenarioImpact"];
export type ScenarioCompare = S["ScenarioCompare"];
export type LiveCheck = S["LiveCheck"];
export type ComplianceReport = S["ComplianceReport"];
export type HistoryRow = S["HistoryRow"];
export type IndicatorSet = S["IndicatorSet"];
export type ExportFile = S["ExportFile"];
export type LayerName = "bike" | "parking" | "destinations" | "population";

const enc = encodeURIComponent;
const cl = (id: string, rest: string) => `/api/closures/${enc(id)}/${rest}`;
type OnPending = () => void;

export const v2 = {
  overview: () => apiGet<Overview>("/api/overview"),
  layer: (name: LayerName) => apiGet<LayerCollection>(`/api/layers/${name}`),
  vehicles: () => apiGet<LayerCollection>("/api/live/vehicles"),
  bike: (id: string) => apiGet<BikeImpact>(cl(id, "bike")),
  parking: (id: string) => apiGet<ParkingImpact>(cl(id, "parking")),
  access: (id: string, onPending?: OnPending) =>
    apiGet<AccessImpact>(cl(id, "access?dest=hospital&minutes=30"), onPending),
  detourLoad: (id: string, onPending?: OnPending) => apiGet<DetourLoad>(cl(id, "detour-load"), onPending),
  conflicts: (id: string) => apiGet<Conflict[]>(cl(id, "conflicts")),
  reports: (id: string) => apiGet<ReportSummary>(cl(id, "reports")),
  windows: (id: string, hours: number, onPending?: OnPending) =>
    apiGet<WindowSuggestion>(cl(id, `windows?hours=${hours}`), onPending),
  scenarios: (closureId: string) => apiGet<Scenario[]>(`/api/scenarios?closureId=${enc(closureId)}`),
  compare: (a: string, b: string, onPending?: OnPending) =>
    apiGet<ScenarioCompare>(`/api/scenarios/compare?a=${enc(a)}&b=${enc(b)}`, onPending),
  live: (id: string) => apiGet<LiveCheck>(cl(id, "live")),
  compliance: () => apiGet<ComplianceReport>("/api/compliance"),
  history: () => apiGet<HistoryRow[]>("/api/history"),
  indicators: () => apiGet<IndicatorSet>("/api/indicators"),
  exports: () => apiGet<ExportFile[]>("/api/exports"),
};
