// CONTRACT v2.26 R19: counts of recorded pothole reports near bus/trolleybus corridors.
import { apiGet, type I18n, type Provenance } from "./client";
import type { LayerCollection } from "./v2";

export type RoadIssueSegment = {
  segmentId: string;
  fromStopId: string;
  fromName: string | null;
  toStopId: string;
  toName: string | null;
  routeIds: string[];
  potholes: number | null;
  departuresPerDay: number | null;
  lengthMeters: number | null;
};
export type RoadIssues = {
  label: I18n;
  recorded: { start: string | null; end: string | null } | null;
  departuresDay: string | null;
  potholesRecorded: number | null;
  potholesOnCorridors: number | null;
  matchMeters: number | null;
  segmentsWithReports: number | null;
  segments: RoadIssueSegment[];
  provenance: Provenance[];
};
export const roadIssues = () => apiGet<RoadIssues>("/api/road-issues?limit=5");
export const roadIssueLayer = () => apiGet<LayerCollection>("/api/layers/road_issues");
