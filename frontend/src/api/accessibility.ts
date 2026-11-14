// R6 step-free vehicles (CONTRACT v2.16; not in the generated schema yet). Step 5 table, step 3 CityApp mock, step 0 layer.
import i18n from "../i18n";
import { apiGet, type I18n, type Provenance } from "./client";

export type Recording = { from: string; to: string; hours: number; label: I18n };
export type HourShare = { hour: number; trips: number; stepFree: number; share: number | null };

export type AccessibleLine = {
  routeId: string;
  shortName: string;
  mode: string;
  trips: number;
  stepFree: number;
  share: number | null;
  unknown: number;
  vehicles: number;
  hours: HourShare[];
};

export type AccessibilityLines = {
  recording: Recording;
  trips: HourShare;
  fleet: { vehicles: number; stepFree: number; share: number | null; unknown: number };
  byHour: HourShare[];
  lines: AccessibleLine[];
  method: I18n;
  caveat: I18n;
  provenance: Provenance[];
};

export type Crossing = { osmId: string; distanceMeters: number; sound: "yes" | "no" | null } | null;

export type StopAccessibility = {
  stopId: string;
  name: string;
  stepFreeWaitMin: number | null;
  anyWaitMin: number | null;
  stepFreeEvents: number;
  allEvents: number;
  nextStepFreeLines: string[];
  crossing: Crossing;
  recording: Recording;
  method: I18n;
  caveat: I18n;
  provenance: Provenance[];
};

export const accessibility = {
  lines: () => apiGet<AccessibilityLines>("/api/accessibility/lines"),
  stop: (stopId: string) => apiGet<StopAccessibility>(`/api/accessibility/stops/${encodeURIComponent(stopId)}`),
};

/** 0.815 → „82 %” (or „81,5 %” with digits = 1); null → null, shown as „necunoscut”. */
export const fmtShare = (s: number | null, digits = 0) =>
  s === null
    ? null
    : new Intl.NumberFormat(i18n.language === "en" ? "en-GB" : "ro-RO", {
        style: "percent",
        maximumFractionDigits: digits,
      }).format(s);
