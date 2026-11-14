// CONTRACT v2.19: official street register + OSM geometry, keyed by streetId.
import { apiGet, type Provenance } from "./client";

export type StreetHit = {
  streetId: string; name: string; codGis: string | null; type: string;
  neighbourhood: string | null; formerName: string | null; hasGeometry: boolean;
};
export type StreetSearchResult = { query: string; streets: StreetHit[]; provenance: Provenance[] };
export type MapPoint = [number, number];
export type StreetSection = {
  streetId: string; name: string; codGis: string | null;
  geometry: GeoJSON.LineString | GeoJSON.MultiLineString;
  lengthMeters: number; whole: boolean; fromPoint: MapPoint | null; toPoint: MapPoint | null;
  provenance: Provenance[];
};
export const streets = {
  search: (query: string) => apiGet<StreetSearchResult>(`/api/streets?q=${encodeURIComponent(query)}&limit=12`),
  section: (id: string, points?: MapPoint[]) => {
    const query = points?.length === 2 ? `?from=${points[0].join(",")}&to=${points[1].join(",")}` : "";
    return apiGet<StreetSection>(`/api/streets/${encodeURIComponent(id)}/section${query}`);
  },
};

/** datetime-local fields describe the City's timezone, independently of the browser's zone. */
export function cityInput(iso: string) {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Bucharest", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso)).replace(" ", "T");
}

export function cityInstant(value: string): string | null {
  const numbers = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!numbers) return null;
  const [year, month, day, hour, minute] = numbers.slice(1).map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  let instant = wall;
  for (let i = 0; i < 3; i++) {
    const shown = cityInput(new Date(instant).toISOString());
    if (shown === value) return new Date(instant).toISOString();
    const [date, time] = shown.split("T");
    const [y, m, d] = date.split("-").map(Number);
    const [h, min] = time.split(":").map(Number);
    instant += wall - Date.UTC(y, m - 1, d, h, min);
  }
  return null; // A skipped hour at the daylight-saving switch is not silently shifted.
}
