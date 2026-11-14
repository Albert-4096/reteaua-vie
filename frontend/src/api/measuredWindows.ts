// L2-F: GET /api/closures/{id}/windows/measured?hours=8 (CONTRACT v2.32). May answer 202; apiGet polls the job.
import { apiGet, type I18n, type Provenance } from "./client";

export type MeasuredWindow = {
  window: { start: string; end: string };
  rank: number;
  departuresLost: number;
  detourMinutes: number | null;
  detourMinutesLow: number | null;
  detourMinutesHigh: number | null;
  conclusive: boolean;
};

export type MeasuredWindowsReport = {
  closureId: string;
  status: "ok" | "fara_inregistrare" | "fara_ocolire" | "neconcludent";
  note: I18n | null;
  label: I18n | null;
  candidates: MeasuredWindow[];
  method: I18n;
  provenance: Provenance[];
};

export const measuredWindows = (closureId: string, onPending?: () => void) =>
  apiGet<MeasuredWindowsReport>(
    `/api/closures/${encodeURIComponent(closureId)}/windows/measured?hours=8`,
    onPending,
  );
