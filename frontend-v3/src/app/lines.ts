import type { Position } from "geojson";
import type { Network } from "@/lib/network";

/**
 * A line as a sequence of stations, in the order the vehicle meets them.
 * The network gives each line a path and a set of stops, but no order, so we lay every stop on the
 * path (direction 0) and sort by the distance travelled. Two platforms of one station share a name
 * and sit a few metres apart along the path; they become one station.
 */
export type Station = { name: string; ids: string[]; along: number; lon: number; lat: number };
export type LineShape = { routeId: string; stations: Station[]; path: Position[]; cum: number[]; length: number };

// metres per degree at Timișoara's latitude: flat-earth is exact enough at city scale
const KX = Math.cos((45.75 * Math.PI) / 180) * 111_320;
const KY = 110_540;
const xy = ([lon, lat]: Position): [number, number] => [lon * KX, lat * KY];

const OFF_PATH_M = 90; // a stop further than this from the path belongs to the other direction's streets
const SAME_STATION_M = 300;

const cache = new Map<string, LineShape | null>();

export function lineShape(net: Network, routeId: string): LineShape | null {
  if (cache.has(routeId)) return cache.get(routeId)!;
  const path = net.paths.find((p) => p.routeId === routeId && p.directionId === 0)?.geometry.coordinates
    ?? net.paths.find((p) => p.routeId === routeId)?.geometry.coordinates;
  if (!path || path.length < 2) { cache.set(routeId, null); return null; }
  const P = path.map(xy);
  const cum = [0];
  for (let i = 1; i < P.length; i++) cum.push(cum[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));

  const placed: { along: number; name: string; id: string }[] = [];
  for (const s of net.stops) {
    if (!s.routeIds.includes(routeId)) continue;
    const q = xy([s.lon, s.lat]);
    let best = Infinity, along = 0;
    for (let i = 1; i < P.length; i++) {
      const [ax, ay] = P[i - 1], dx = P[i][0] - ax, dy = P[i][1] - ay, L = dx * dx + dy * dy;
      const t = L === 0 ? 0 : Math.max(0, Math.min(1, ((q[0] - ax) * dx + (q[1] - ay) * dy) / L));
      const d = Math.hypot(q[0] - (ax + t * dx), q[1] - (ay + t * dy));
      if (d < best) { best = d; along = cum[i - 1] + t * Math.sqrt(L); }
    }
    if (best <= OFF_PATH_M) placed.push({ along, name: s.name, id: s.id });
  }
  placed.sort((a, b) => a.along - b.along);

  const stations: Station[] = [];
  for (const s of placed) {
    const last = stations[stations.length - 1];
    if (last && last.name === s.name && s.along - last.along < SAME_STATION_M) last.ids.push(s.id);
    else { const [lon, lat] = pointAt(path, cum, s.along); stations.push({ name: s.name, ids: [s.id], along: s.along, lon, lat }); }
  }
  const shape = { routeId, stations, path, cum, length: cum[cum.length - 1] };
  cache.set(routeId, shape);
  return shape;
}

export function pointAt(path: Position[], cum: number[], along: number): Position {
  if (along <= 0) return path[0];
  for (let i = 1; i < cum.length; i++) {
    if (cum[i] >= along) {
      const t = cum[i] === cum[i - 1] ? 0 : (along - cum[i - 1]) / (cum[i] - cum[i - 1]);
      return [path[i - 1][0] + t * (path[i][0] - path[i - 1][0]), path[i - 1][1] + t * (path[i][1] - path[i - 1][1])];
    }
  }
  return path[path.length - 1];
}

/** The stretch of the path between two distances, as coordinates. */
export function slice(shape: LineShape, from: number, to: number): Position[] {
  const [a, b] = from <= to ? [from, to] : [to, from];
  const out: Position[] = [pointAt(shape.path, shape.cum, a)];
  for (let i = 0; i < shape.cum.length; i++) if (shape.cum[i] > a && shape.cum[i] < b) out.push(shape.path[i]);
  out.push(pointAt(shape.path, shape.cum, b));
  return out;
}

/** First and last station that hold one of the given stop ids, and everything between them. */
export function stretch(shape: LineShape, stopIds: Set<string>) {
  const hit = shape.stations.map((s) => s.ids.some((id) => stopIds.has(id)));
  const first = hit.indexOf(true), last = hit.lastIndexOf(true);
  if (first < 0) return null;
  return { first, last, from: shape.stations[first], to: shape.stations[last], coords: slice(shape, shape.stations[first].along, shape.stations[last].along) };
}

/** A station name without the platform's street: "Piața Sfânta Maria (Gheorghe Doja)" → "Piața Sfânta Maria". */
export const plainName = (name: string) => name.replace(/\s*\([^)]*\)\s*$/, "");
