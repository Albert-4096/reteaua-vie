// One human question per group of unsure rows. Uses analysis.decisionGroups (ticket T2) when the
// backend sends it; otherwise groups the unsure rows by line and reasons on the client.
import type { AffectedStop, Analysis, Decision } from "../api/client";

type Text = { ro: string; en?: string | null };

export type Group = {
  id: string;
  routeId: string;
  /** Server question (T2); null = the client builds the default question. */
  question: Text | null;
  reason: Text | null;
  suggestedLost: boolean;
  rows: AffectedStop[];
};

export type GroupState = "open" | "lost" | "served" | "mixed";

const rowKey = (r: { stopId: string; routeId: string; directionId: number }) => `${r.stopId}|${r.routeId}|${r.directionId}`;

function matchKey(key: string | { stopId: string; routeId: string; directionId: number }, rows: AffectedStop[]) {
  if (typeof key !== "string") return rows.find((r) => rowKey(r) === rowKey(key));
  const parts = key.split(/[|:/,]/);
  return rows.find(
    (r) => parts.includes(r.stopId) && parts.includes(r.routeId) && parts.includes(String(r.directionId)),
  );
}

export function decisionGroups(a: Analysis): Group[] {
  if (a.decisionGroups && a.decisionGroups.length > 0) {
    return a.decisionGroups.map((g) => ({
      id: g.id,
      routeId: g.routeId,
      question: g.question,
      reason: g.reason ?? null,
      suggestedLost: g.suggested === "affected",
      rows: (g.rows ?? g.rowKeys ?? []).map((k) => matchKey(k, a.stops)).filter((r): r is AffectedStop => !!r),
    }));
  }
  const byKey = new Map<string, Group>();
  for (const r of a.stops) {
    if (r.state !== "unsure") continue;
    const id = `${r.routeId}|${[...r.reasons].sort().join(",")}`;
    const g = byKey.get(id) ?? { id, routeId: r.routeId, question: null, reason: null, suggestedLost: false, rows: [] };
    g.rows.push(r);
    byKey.set(id, g);
  }
  return [...byKey.values()];
}

export type GroupCounts = { lost: number; served: number; open: number; total: number };

export function groupCounts(g: Group): GroupCounts {
  const c = { lost: 0, served: 0, open: 0, total: g.rows.length };
  for (const r of g.rows) {
    if (r.confirmed === true) c.lost++;
    else if (r.confirmed === false) c.served++;
    else c.open++;
  }
  return c;
}

export function rowDecision(r: AffectedStop, lost: boolean): Decision {
  return { stopId: r.stopId, routeId: r.routeId, directionId: r.directionId, confirmed: lost };
}

export function groupState(g: Group): GroupState {
  const c = g.rows.map((r) => r.confirmed);
  if (c.every((x) => x === null || x === undefined)) return "open";
  if (c.every((x) => x === true)) return "lost";
  if (c.every((x) => x === false)) return "served";
  return "mixed";
}

/** `lost = true` ticks every row of the group as lost (confirmed: true). */
export function groupDecisions(g: Group, lost: boolean): Decision[] {
  return g.rows.map((r) => ({ stopId: r.stopId, routeId: r.routeId, directionId: r.directionId, confirmed: lost }));
}

export function undecidedCount(a: Analysis): number {
  return a.stops.filter((r) => r.state === "unsure" && (r.confirmed === null || r.confirmed === undefined)).length;
}
