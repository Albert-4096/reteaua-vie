// R14: GET /api/registry?from=&to= (not in the generated schema yet). Latest day is a section in step 5.
import { apiGet, type Provenance } from "./client";

export type RegistryRecording = {
  firstAt: string | null;
  lastAt: string | null;
  healthyShare: number | null;
  files: string[];
  l0Complete: boolean;
  comparedUntil: string | null;
};

export type RegistryLine = {
  routeId: string;
  shortName: string | null;
  mode: string | null;
  tripsScheduled: number | null;
  tripsScheduledInRecording: number | null;
  tripsSeen: number | null;
  share: number | null;
  kmEstimated: number | null;
  kmNote: string | null;
};

export type RegistryEntry = {
  date: string;
  final: boolean;
  recording: RegistryRecording;
  lines: RegistryLine[];
  feedVersion?: string | null;
  rawSha256?: string | null;
  rollupSha256?: string | null;
  prevHash?: string | null;
  chainHash?: string | null;
};

export type RegistryDays = {
  entries: RegistryEntry[];
  provenance: Provenance[];
};

/** `from` and `to` are YYYY-MM-DD. Omit both to read every recorded day. */
export function registry(range?: { from?: string; to?: string }, onPending?: () => void) {
  const q = new URLSearchParams();
  if (range?.from) q.set("from", range.from);
  if (range?.to) q.set("to", range.to);
  const s = q.toString();
  return apiGet<RegistryDays>(`/api/registry${s ? `?${s}` : ""}`, onPending);
}
