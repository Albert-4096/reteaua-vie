import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import type { Feature, FeatureCollection } from "geojson";
import { loadNetwork } from "@/lib/network";

export type MapStop = { id: string; name: string; lon: number; lat: number; tone: "closed" | "unsure" | "ok" };
export type MapProps = {
  closures?: { id: string; geometry?: Feature["geometry"]; selected?: boolean }[];
  highlight?: string[]; // routeIds drawn in colour; the rest stay grey
  stops?: MapStop[];
  vehicles?: { id: string; lon: number; lat: number }[];
  fitTo?: string; // closure id to frame
  onClosure?: (id: string) => void;
};

maplibregl.setWorkerUrl(workerUrl);

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const TM: LngLatBoundsLike = [[21.15, 45.71], [21.3, 45.8]];
const fc = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });

/** One map for every step: the city's lines (grey, affected ones in their own colour), works in barrier red, stops, vehicles. */
export function MapView({ closures = [], highlight = [], stops = [], vehicles = [], fitTo, onClosure }: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const latest = useRef({ closures, highlight, stops, vehicles, fitTo });
  latest.current = { closures, highlight, stops, vehicles, fitTo };
  const onClosureRef = useRef(onClosure);
  onClosureRef.current = onClosure;

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current!, style: STYLE, bounds: TM, attributionControl: { compact: true } });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", async () => {
      const net = await loadNetwork().catch(() => null);
      const lines = fc((net?.paths ?? []).filter((p) => p.directionId === 0).map((p) => {
        const r = net!.byId.get(p.routeId);
        return { type: "Feature", geometry: p.geometry, properties: { routeId: p.routeId, color: `#${r?.color ?? "888888"}`, tram: r?.type === 0 } };
      }));
      m.addSource("lines", { type: "geojson", data: lines });
      m.addSource("closures", { type: "geojson", data: fc([]) });
      m.addSource("stops", { type: "geojson", data: fc([]) });
      m.addSource("vehicles", { type: "geojson", data: fc([]) });
      m.addLayer({ id: "lines-base", type: "line", source: "lines", paint: { "line-color": "#9aa5a1", "line-width": 1.4, "line-opacity": 0.45 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "lines-hi", type: "line", source: "lines", filter: ["in", ["get", "routeId"], ["literal", []]],
        paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "tram"], 5, 4] }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "closures-casing", type: "line", source: "closures", paint: { "line-color": "#ffffff", "line-width": ["case", ["get", "selected"], 13, 9] }, layout: { "line-cap": "round" } });
      m.addLayer({ id: "closures", type: "line", source: "closures", paint: { "line-color": "#d63b2f", "line-width": ["case", ["get", "selected"], 8, 5], "line-dasharray": [1.2, 0.8] }, layout: { "line-cap": "butt" } });
      m.addLayer({ id: "stops", type: "circle", source: "stops", paint: {
        "circle-radius": 5.5, "circle-stroke-width": 2, "circle-stroke-color": "#ffffff",
        "circle-color": ["match", ["get", "tone"], "closed", "#d63b2f", "unsure", "#16201c", "#9aa5a1"] } });
      m.addLayer({ id: "vehicles", type: "circle", source: "vehicles", paint: { "circle-radius": 4.5, "circle-color": "#16201c", "circle-stroke-width": 1.8, "circle-stroke-color": "#ffffff" } });
      m.on("click", "closures", (e: MapLayerMouseEvent) => { const id = e.features?.[0]?.properties?.id; if (id) onClosureRef.current?.(id); });
      m.on("mouseenter", "closures", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "closures", () => (m.getCanvas().style.cursor = ""));
      const popup = new maplibregl.Popup({ closeButton: false, offset: 10 });
      m.on("mouseenter", "stops", (e: MapLayerMouseEvent) => { const f = e.features?.[0]; if (f) popup.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number]).setText(f.properties.name).addTo(m); });
      m.on("mouseleave", "stops", () => popup.remove());
      ready.current = true;
      sync(m, latest.current, true);
    });
    return () => { ready.current = false; m.remove(); };
  }, []);

  useEffect(() => {
    if (map.current && ready.current) sync(map.current, { closures, highlight, stops, vehicles, fitTo }, false);
  }, [closures, highlight, stops, vehicles, fitTo]);

  return <div ref={el} className="h-full w-full" />;
}

let lastFit: string | undefined;
function sync(m: maplibregl.Map, p: Required<Omit<MapProps, "onClosure" | "fitTo">> & { fitTo?: string }, first: boolean) {
  (m.getSource("closures") as GeoJSONSource).setData(fc(p.closures.filter((c) => c.geometry).map((c) => ({ type: "Feature", geometry: c.geometry!, properties: { id: c.id, selected: !!c.selected } }))));
  (m.getSource("stops") as GeoJSONSource).setData(fc(p.stops.map((s) => ({ type: "Feature", geometry: { type: "Point", coordinates: [s.lon, s.lat] }, properties: { name: s.name, tone: s.tone } }))));
  (m.getSource("vehicles") as GeoJSONSource).setData(fc(p.vehicles.map((v) => ({ type: "Feature", geometry: { type: "Point", coordinates: [v.lon, v.lat] }, properties: { id: v.id } }))));
  m.setFilter("lines-hi", ["in", ["get", "routeId"], ["literal", p.highlight]]);
  if (p.fitTo && (first || p.fitTo !== lastFit)) {
    const c = p.closures.find((x) => x.id === p.fitTo)?.geometry;
    const pts: number[][] = !c ? [] : c.type === "LineString" ? c.coordinates : c.type === "MultiLineString" ? c.coordinates.flat() : [];
    const near = p.stops.length ? p.stops.map((s) => [s.lon, s.lat]) : pts;
    const all = [...pts, ...near];
    if (all.length) {
      const b = all.reduce((acc, [x, y]) => acc.extend([x, y]), new maplibregl.LngLatBounds(all[0] as [number, number], all[0] as [number, number]));
      m.fitBounds(b, { padding: { top: 60, left: 60, right: 60, bottom: 110 }, maxZoom: 15.5, duration: first ? 0 : 900 });
      lastFit = p.fitTo;
    }
  }
}
