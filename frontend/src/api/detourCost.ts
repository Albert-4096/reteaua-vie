// CONTRACT v2.22: measured detour cost; seconds, medians and 90% bootstrap intervals.
import { apiGet, type I18n, type Provenance } from "./client";

export type Estimate = { sec: number | null; low: number | null; high: number | null; n: number; conclusive: boolean };
export type DetourStretch = {
  routeId: string;
  shortName: string;
  directionId: number;
  kind: "detour" | "start_moved" | "end_moved" | "truncated_start" | "truncated_end";
  before: { stopIds: string[]; stopNames: string[] };
  after: { stopIds: string[]; stopNames: string[] };
  planned: { before: Estimate; after: Estimate; extra: Estimate };
  measured: Estimate | null;
  measuredVsPlanned: Estimate | null;
  estimated: Estimate | null;
  estimateError: Estimate | null;
  coverage: number | null;
  otherRoutes: string[];
  byHour: { hour: number; dayType: string; n: number; measuredSec: number | null; estimatedSec: number | null }[];
};
export type DetourCost = {
  closureId: string;
  status: "ok" | "fara_inregistrare" | "fara_orar_vechi" | "fara_schimbare";
  label: I18n | null;
  finding: I18n | null;
  minTrips: number;
  feedBefore: string | null;
  feedAfter: string | null;
  stretches: DetourStretch[];
  totals: { plannedExtra: Estimate; measuredVsPlanned: Estimate; estimateError: Estimate };
  method: I18n;
  provenance: Provenance[];
};

export const detourCost = (id: string, onPending?: () => void) =>
  apiGet<DetourCost>(`/api/closures/${encodeURIComponent(id)}/detour-cost`, onPending);
