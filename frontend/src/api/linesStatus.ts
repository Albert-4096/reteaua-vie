// R2 line status (CONTRACT v2.18, GET /api/lines/status). Local type until schema.d.ts is regenerated.
// Shared by the step 0 „Linii” list and the CityApp mock row in step 3.
import { apiGet, type I18n, type Provenance } from "./client";
import { fmtDate, fmtTime, tr } from "../lib/format";

export type LineState = "normala" | "deviata" | "scurtata" | "suspendata" | "linie_temporara" | "fara_vehicul";

export type LineStatus = {
  routeId: string | null;
  shortName: string;
  mode: "autobuz" | "troleibuz" | "tramvai" | null;
  state: LineState;
  label: I18n;
  directionIds: number[] | null;
  since: string | null;
  until: string | null;
  closureId: string | null;
  closureTitle: I18n | null;
  notice: { postId: number | null; url: string | null; title: string | null } | null;
  replacedBy: string[];
  source: string;
  previousState?: string | null;
  serviceConfirmation?: { travelers: number; simulated: boolean; label: I18n } | null;
};

export type LinesStatus = { at: string; since: string | null; lines: LineStatus[]; provenance: Provenance[] };

export function linesStatus(routeId?: string): Promise<LinesStatus> {
  return apiGet<LinesStatus>(`/api/lines/status${routeId ? `?routeId=${encodeURIComponent(routeId)}` : ""}`);
}

/** Strongest first; the order of the step 0 list and the pick of the saved line in the mock. */
export const SEVERITY: LineState[] = ["suspendata", "scurtata", "deviata", "fara_vehicul", "linie_temporara", "normala"];

export const L = {
  title: { ro: "Linii", en: "Lines" },
  allNormal: {
    ro: "Toate liniile circulă normal (din lucrările publicate).",
    en: "All lines run normally (from the published closures).",
  },
  basis: (at: string) => ({
    ro: `Modificări publicate sau serviciu confirmat fără GPS · situația la ${at}`,
    en: `Published changes or confirmed service without GPS · as of ${at}`,
  }),
  source: { ro: "Sursa", en: "Source" },
  // O2/R4 wording: a person confirmed it, STPT did not.
  noVehicle: {
    ro: "fără vehicul în datele live (neconfirmat de STPT)",
    en: "no vehicle in the live data (not confirmed by STPT)",
  },
  untilEnd: { ro: "până la finalizarea lucrărilor", en: "until the works finish" },
  until: (when: string) => ({ ro: `până la ${when}`, en: `until ${when}` }),
  replacedBy: (lines: string) => ({ ro: `înlocuită de ${lines}`, en: `replaced by ${lines}` }),
  insteadOf: (lines: string) => ({ ro: `în locul liniei ${lines}`, en: `instead of line ${lines}` }),
  oneDirection: { ro: "un singur sens", en: "one direction only" },
  notice: (id: number) => ({ ro: `anunț STPT ${id}`, en: `STPT notice ${id}` }),
  // CityApp mock row
  saved: { ro: "Linia ta salvată", en: "Your saved line" },
  normal: { ro: "circulă normal", en: "runs normally" },
  take: (lines: string) => ({ ro: `ia ${lines}`, en: `take ${lines}` }),
  or: { ro: " sau ", en: " or " },
};

export function stateLabel(l: LineStatus): string {
  return l.state === "fara_vehicul" ? tr(L.noVehicle) : tr(l.label);
}

/** „18:00” on the day of `at`, else „31 decembrie 2026, 23:59”. */
export function untilText(until: string, at: string): string {
  return fmtDate(until) === fmtDate(at) ? fmtTime(until) : `${fmtDate(until)}, ${fmtTime(until)}`;
}

/** The colour class that goes with the state word (the word is always there). */
export function stateClass(s: LineState): string {
  return s === "suspendata" ? "st-lost" : s === "normala" || s === "linie_temporara" ? "" : "st-unsure";
}
