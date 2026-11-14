// R5 km not run and the walk between the cut ends (GET /api/closures/{id}/km; not in the generated schema yet).
// Km only, never money. The CSV variant is the export for SMTT.
import { apiGet, type I18n, type Provenance } from "./client";

export type KmLine = {
  routeId: string;
  shortName: string;
  mode: string;
  directionId: number;
  stopsLost: number;
  sectionKm: number;
  trips: number | null;
  kmNotRun: number | null;
};

export type KmTemporary = {
  replacesRouteId?: string | null;
  shortName: string;
  mode: string;
  geometryKm: number | null;
  trips: number | null;
  kmRun: number | null;
  note: I18n;
};

export type KmWalk = {
  routeId: string;
  shortName: string;
  directionId: number;
  fromStop: { stopId: string; name: string };
  toStop: { stopId: string; name: string };
  meters: number;
  minutes: number;
  approximate: boolean;
  sentence: I18n;
};

export type KmReport = {
  closureId: string;
  window: { start: string; end: string };
  timetableVersion: string;
  lines: KmLine[];
  temporary: KmTemporary[];
  walkBetweenEnds: KmWalk[];
  totalKmNotRun: number | null;
  provenance: Provenance[];
};

export const kmPath = (closureId: string) => `/api/closures/${encodeURIComponent(closureId)}/km`;
export const kmCsvPath = (closureId: string) => `${kmPath(closureId)}?format=csv`;
export const km = (closureId: string) => apiGet<KmReport>(kmPath(closureId));
