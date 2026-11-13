// Geometry helpers on [lon, lat]: order a line's stops along its GTFS path and build the line schema.
import type { AffectedStop, Network } from "../api/client";

type LonLat = [number, number];
const M_PER_DEG_LAT = 111_320;

function project(p: LonLat, lat0: number): [number, number] {
  return [p[0] * M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180), p[1] * M_PER_DEG_LAT];
}

/** Distance along the path of the closest point to `p`, and how far `p` is from the path (metres). */
function locate(path: LonLat[], p: LonLat): { along: number; off: number } {
  const lat0 = p[1];
  const q = project(p, lat0);
  let best = { along: 0, off: Infinity };
  let acc = 0;
  for (let i = 0; i < path.length - 1; i++) {
    const a = project(path[i], lat0);
    const b = project(path[i + 1], lat0);
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / len2));
    const x = a[0] + t * dx - q[0];
    const y = a[1] + t * dy - q[1];
    const off = Math.hypot(x, y);
    if (off < best.off) best = { along: acc + t * Math.sqrt(len2), off };
    acc += Math.sqrt(len2);
  }
  return best;
}

const MAX_OFF_PATH_M = 45;

/** Stop names of one route and direction, in path order (opposite platforms share a name and are merged). */
function orderedNames(net: Network, routeId: string, directionId: number): string[] {
  const path = net.paths.find((p) => p.routeId === routeId && p.directionId === directionId);
  const coords = (path?.geometry?.coordinates ?? []) as LonLat[];
  if (coords.length < 2) return [];
  const located = net.stops
    .filter((s) => s.routeIds?.includes(routeId))
    .map((s) => ({ name: s.name, ...locate(coords, [s.lon, s.lat]) }))
    .filter((s) => s.off <= MAX_OFF_PATH_M)
    .sort((a, b) => a.along - b.along);
  const names: string[] = [];
  for (const s of located) if (names[names.length - 1] !== s.name && !names.includes(s.name)) names.push(s.name);
  return names;
}

/** Merge two ordered name lists (longest common subsequence), keeping every name once. */
function merge(a: string[], b: string[]): string[] {
  const n = a.length;
  const m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: string[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) {
      out.push(a[i]);
      i++;
      j++;
    } else if (j >= m || (i < n && L[i + 1][j] >= L[i][j + 1])) out.push(a[i++]);
    else out.push(b[j++]);
  }
  return out.filter((x, k) => out.indexOf(x) === k);
}

export type RowStatus = "lost" | "unsure" | "served";

/** Lost = affected and not unticked, or unsure and ticked (same rule as the generated notice). */
export function rowStatus(r: AffectedStop): RowStatus {
  if (r.state === "affected") return r.confirmed === false ? "served" : "lost";
  if (r.confirmed === true) return "lost";
  if (r.confirmed === false) return "served";
  return "unsure";
}

export type SchemaStop = {
  name: string;
  status: RowStatus | "partial";
  /** For "partial": the headsigns of the directions where the line no longer stops. */
  lostTowards: string[];
};

/** The affected section of one line, in order, with one served stop on each side. */
export function lineSchema(net: Network, routeId: string, rows: AffectedStop[]): SchemaStop[] {
  const d0 = orderedNames(net, routeId, 0);
  const d1 = orderedNames(net, routeId, 1).reverse();
  const names = merge(d0, d1);
  for (const r of rows) if (!names.includes(r.name)) names.push(r.name);

  const stops: SchemaStop[] = names.map((name) => {
    const mine = rows.filter((r) => r.name === name);
    if (mine.length === 0) return { name, status: "served", lostTowards: [] };
    const st = mine.map(rowStatus);
    if (st.includes("unsure")) return { name, status: "unsure", lostTowards: [] };
    const lost = mine.filter((r) => rowStatus(r) === "lost");
    if (lost.length === 0) return { name, status: "served", lostTowards: [] };
    // Lost in every direction the line serves here?
    const dirsServedHere = new Set<number>();
    if (d0.includes(name)) dirsServedHere.add(0);
    if (d1.includes(name)) dirsServedHere.add(1);
    const lostDirs = new Set(lost.map((r) => r.directionId));
    const all = [...dirsServedHere].every((d) => lostDirs.has(d as 0 | 1));
    if (all) return { name, status: "lost", lostTowards: [] };
    return { name, status: "partial", lostTowards: lost.map((r) => r.headsign ?? "").filter(Boolean) };
  });

  const hit = stops.map((s, i) => (s.status === "served" ? -1 : i)).filter((i) => i >= 0);
  if (hit.length === 0) return [];
  const from = Math.max(0, Math.min(...hit) - 1);
  const to = Math.min(stops.length - 1, Math.max(...hit) + 1);
  return stops.slice(from, to + 1);
}

export function bounds(points: LonLat[]): [LonLat, LonLat] | null {
  if (points.length === 0) return null;
  let [minX, minY] = points[0];
  let [maxX, maxY] = points[0];
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
