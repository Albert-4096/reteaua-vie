// O2 lines with no vehicle (CONTRACT v2.13 MissingLines, Overview.missingLines; not in the generated schema yet).
// Step 0 shows the brief from /api/overview, step 4 the full list for the prepared case.
import { apiGet, type I18n, type Provenance } from "../../api/client";
import type { TriageDecision } from "./MissingTriage";
import type { Overview } from "../../api/v2";

export type MissingRoute = {
  decision?: TriageDecision | null;
  repeatedDays?: number | null;
  serviceConfirmation?: { travelers: number; label: I18n } | null;
  routeId: string;
  shortName: string;
  longName: string;
  mode: string;
  state: "fara_vehicul" | "partial";
  tripsInService: number | null;
  tripsObserved: number | null;
  since: string | null;
  lastSeenAt: string | null;
  firstMissedTrip: { tripId: string; stopId: string; stopName: string | null; scheduledTime: string } | null;
};

type Window = { start: string; end: string };
type CaseLabel = { id: string; label: I18n } | null;
type Status = "ok" | "inregistrare_incompleta";

export type MissingBrief = {
  window: Window;
  status: Status;
  case: CaseLabel;
  count: number | null;
  partialCount: number | null;
  rows: MissingRoute[];
};

export type MissingLines = {
  window: Window;
  status: Status;
  case: CaseLabel;
  recording: { snapshots: number | null; healthySnapshots: number | null; healthyShare: number | null; files: string[] };
  routes: MissingRoute[];
  byMode: { mode: string; tripsScheduled: number | null; tripsWithNoVehicle: number | null; share: number | null }[];
  provenance: Provenance[];
};

export type OverviewWithMissing = Overview & {
  missingLines?: { live: MissingBrief | null; prepared: MissingBrief | null } | null;
};

/** The prepared case: 14 Nov 06:00–10:41, recorded. `?case=l23` opens it in step 4. */
export const MISSING_CASE = "case_l23";
export const MISSING_CASE_KEY = "l23";
export const isMissingCase = (k: string | null) => k === MISSING_CASE_KEY || k === MISSING_CASE;

export const fetchMissing = () => apiGet<MissingLines>(`/api/live/missing?case=${MISSING_CASE}`);

/** The overview mixes every source; a brief's own are its recording window and the detector's method. */
export function briefProvenance(all: Provenance[], b: MissingBrief): Provenance[] {
  return all.filter((p) => p.source.includes("O2") || (p.note ?? "").includes(b.window.start));
}
