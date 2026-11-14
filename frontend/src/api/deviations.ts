// CONTRACT v2.29 / v2.36: GET /api/live/deviations (default: the last 60 min of the real clock).
// extraKm is kilometres. The UI never turns it into money.
import { apiGet, type I18n, type Provenance } from "./client";

export type DeviationTrack = {
  tripId: string;
  vehicleId: string;
  start: string;
  end: string;
  reports: number;
  maxDistanceM: number;
  extraKm: number;
  coordinates: [number, number][];
};

export type DeviationGroup = {
  routeId: string;
  shortName: string | null;
  mode: string | null;
  directionId: number | null;
  street: string | null;
  nearStop: string | null;
  classification: "anuntata" | "fara_anunt";
  label: I18n;
  closureId: string | null;
  notice: { postId: number | null; url: string | null; title: string | null } | null;
  runs: number;
  trips: number;
  tripsSeen: number;
  share: number | null;
  firstAt: string;
  lastAt: string;
  maxDistanceM: number;
  extraKm: number;
  tracks: DeviationTrack[];
};

export type Deviations = {
  window: { start: string; end: string };
  status: "ok" | "inregistrare_incompleta";
  thresholds: {
    offRouteMeters: number;
    minReports: number;
    terminalMeters: number;
    depotMeters: number;
    maxReportAgeSec: number;
    beforeTripMinutes: number;
    afterTripMinutes: number;
    standingMinutes: number;
    standingMetresPerSecond: number;
    gpsLossMinutes: number;
  };
  reports: number;
  counts: {
    runs: number;
    ignoredGpsLoss: number;
    ignoredOffSchedule: number;
    ignoredStanding: number;
    ignoredTerminal: number;
    ignoredDepot: number;
    kept: number;
    announced: number;
    unannounced: number;
  };
  groups: DeviationGroup[];
  provenance: Provenance[];
};

export const DEVIATIONS_KEY = "live:deviations";

export const fetchDeviations = () => apiGet<Deviations>("/api/live/deviations");

function lineOf(coordinates: [number, number][] | undefined): [number, number][] | null {
  const clean = (coordinates ?? []).filter(
    (p) => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]),
  );
  if (clean.length < 2) return null;
  return clean.map((p) => [p[0], p[1]]);
}

/** One LineString per recorded off-route track. An incomplete answer still keeps the tracks it did return. */
export function deviationTracks(data: Deviations | undefined): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const features: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  for (const group of data?.groups ?? []) {
    for (const track of group.tracks ?? []) {
      const coordinates = lineOf(track.coordinates);
      if (!coordinates) continue;
      features.push({
        type: "Feature",
        geometry: { type: "LineString", coordinates },
        properties: {
          routeId: group.routeId,
          shortName: group.shortName,
          tripId: track.tripId,
          classification: group.classification,
        },
      });
    }
  }
  return { type: "FeatureCollection", features };
}
