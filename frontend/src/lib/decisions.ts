// One human question per group of unsure rows. Uses analysis.decisionGroups (ticket T2) when the
// backend sends it; otherwise groups the unsure rows by line and reasons on the client.
import type { AffectedStop, Analysis, Decision } from "../api/client";

export type Group = {
  id: string;
  routeId: string;
  /** Server question (T2); null = the client builds the default question. */
  question: { ro: string; en?: string | null } | null;
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
      rows: g.rowKeys.map((k) => matchKey(k, a.stops)).filter((r): r is AffectedStop => !!r),
    }));
  }
  const byKey = new Map<string, Group>();
  for (const r of a.stops) {
    if (r.state !== "unsure") continue;
    const id = `${r.routeId}|${[...r.reasons].sort().join(",")}`;
    const g = byKey.get(id) ?? { id, routeId: r.routeId, question: null, rows: [] };
    g.rows.push(r);
    byKey.set(id, g);
  }
  return [...byKey.values()];
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
