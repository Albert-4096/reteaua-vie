// R13-F: GET /api/closures/{id}/journal (CONTRACT v2.34). Acts replayed from the existing logs.
import { apiGet, type I18n, type Provenance } from "./client";

export type JournalEntry = {
  n: number;
  at: string;
  kind: string;
  role: string | null;
  summary: I18n;
  feedVersion: string;
  numbers: { stopsSuspended: number; departuresLost: number; routesAffected: number } | null;
  prevHash: string | null;
  hash: string;
};

export type Journal = {
  closureId: string;
  entries: JournalEntry[];
  head: string | null;
  provenance: Provenance[];
};

export const journalBundlePath = (closureId: string) =>
  `/api/closures/${encodeURIComponent(closureId)}/bundle.json`;

export const journal = (closureId: string) =>
  apiGet<Journal>(`/api/closures/${encodeURIComponent(closureId)}/journal`);
