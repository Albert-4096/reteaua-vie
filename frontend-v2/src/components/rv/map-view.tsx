import { useEffect, useRef } from "react";
import maplibregl, { type LngLatBoundsLike, type Map as MlMap } from "maplibre-gl";
import type { Issue } from "@/lib/acum";
import type { Network } from "@/lib/api";
import { STATUS_HEX } from "./status";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const TIMISOARA: [number, number] = [21.2257, 45.7537];

type Props = {
  network: Network;
  issues: Issue[];
  selectedId: string | null;
  onSelect?: (id: string) => void;
  padding?: { top: number; right: number; bottom: number; left: number };
  className?: string;
};

function featureCollection(network: Network, issues: Issue[], selectedId: string | null) {
  const byRoute = new Map<string, Issue>();
  for (const i of [...issues].reverse()) for (const r of i.routeIds) byRoute.set(r, i);
  const base: GeoJSON.Feature[] = [];
  const hot: GeoJSON.Feature[] = [];
  for (const p of network.paths) {
    const issue = byRoute.get(p.routeId);
    if (!issue) {
      base.push({ type: "Feature", geometry: p.geometry, properties: {} });
      continue;
    }
    hot.push({
      type: "Feature",
      geometry: p.geometry,
      properties: { id: issue.id, color: STATUS_HEX[issue.level], selected: issue.id === selectedId ? 1 : 0, level: issue.level },
    });
  }
  const sel = issues.find((i) => i.id === selectedId);
  const stops: GeoJSON.Feature[] = [];
  if (sel) {
    const ids = new Set(sel.routeIds);
    for (const s of network.stops) {
      if (!s.routeIds.some((r) => ids.has(r))) continue;
      stops.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: { name: s.name, focus: s.id === sel.focusStopId ? 1 : 0, color: STATUS_HEX[sel.level] },
      });
    }
  }
  return {
    base: { type: "FeatureCollection", features: base } as GeoJSON.FeatureCollection,
    hot: { type: "FeatureCollection", features: hot } as GeoJSON.FeatureCollection,
    stops: { type: "FeatureCollection", features: stops } as GeoJSON.FeatureCollection,
  };
}

function boundsOf(fc: GeoJSON.FeatureCollection, filter?: (f: GeoJSON.Feature) => boolean): LngLatBoundsLike | null {
  let minX = 180, minY = 90, maxX = -180, maxY = -90, n = 0;
  for (const f of fc.features) {
    if (filter && !filter(f)) continue;
    const g = f.geometry;
    const coords = g.type === "LineString" ? g.coordinates : g.type === "Point" ? [g.coordinates] : [];
    for (const [x, y] of coords) {
      minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y); n++;
    }
  }
  return n ? [[minX, minY], [maxX, maxY]] : null;
}

export function MapView({ network, issues, selectedId, onSelect, padding, className }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const ready = useRef(false);
  const pad = padding ?? { top: 48, right: 48, bottom: 48, left: 48 };

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: STYLE,
      center: TIMISOARA,
      zoom: 12.3,
      attributionControl: { compact: true },
      fadeDuration: 0,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.current = m;
    m.on("load", () => {
      // calmer base: fade labels and roads so the network reads first
      for (const layer of m.getStyle().layers ?? []) {
        if (layer.type === "symbol" && layer.id.includes("poi")) m.setLayoutProperty(layer.id, "visibility", "none");
      }
      const fc = featureCollection(network, issues, selectedId);
      m.addSource("base", { type: "geojson", data: fc.base });
      m.addSource("hot", { type: "geojson", data: fc.hot });
      m.addSource("stops", { type: "geojson", data: fc.stops });
      m.addLayer({ id: "base", type: "line", source: "base", paint: { "line-color": "#7c8696", "line-width": 1.2, "line-opacity": 0.45 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({ id: "hot-halo", type: "line", source: "hot", paint: { "line-color": "#ffffff", "line-width": ["case", ["==", ["get", "selected"], 1], 9, 6], "line-opacity": 0.9 }, layout: { "line-cap": "round", "line-join": "round" } });
      m.addLayer({
        id: "hot",
        type: "line",
        source: "hot",
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", ["==", ["get", "selected"], 1], 5, 3],
          "line-opacity": ["case", ["==", ["get", "selected"], 1], 1, 0.75],
          "line-dasharray": ["case", ["==", ["get", "level"], 3], ["literal", [1.6, 1.1]], ["literal", [1, 0]]],
        },
        layout: { "line-cap": "butt", "line-join": "round" },
      });
      m.addLayer({ id: "stops", type: "circle", source: "stops", paint: { "circle-radius": ["case", ["==", ["get", "focus"], 1], 6, 3.5], "circle-color": "#ffffff", "circle-stroke-color": ["get", "color"], "circle-stroke-width": ["case", ["==", ["get", "focus"], 1], 3, 2] } });
      m.addLayer({
        id: "stop-focus-label",
        type: "symbol",
        source: "stops",
        filter: ["==", ["get", "focus"], 1],
        layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 12, "text-offset": [0, 1.3], "text-anchor": "top" },
        paint: { "text-color": "#1f2633", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      });
      m.on("click", "hot", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id && onSelect) onSelect(String(id));
      });
      m.on("mouseenter", "hot", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "hot", () => (m.getCanvas().style.cursor = ""));
      ready.current = true;
      fit(m, fc, selectedId, pad, false);
    });
    return () => {
      ready.current = false;
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [network]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    const fc = featureCollection(network, issues, selectedId);
    (m.getSource("hot") as maplibregl.GeoJSONSource).setData(fc.hot);
    (m.getSource("stops") as maplibregl.GeoJSONSource).setData(fc.stops);
    fit(m, fc, selectedId, pad, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issues, selectedId]);

  return <div ref={el} className={className} />;
}

function fit(
  m: MlMap,
  fc: ReturnType<typeof featureCollection>,
  selectedId: string | null,
  padding: { top: number; right: number; bottom: number; left: number },
  animate: boolean,
) {
  const b = (selectedId && boundsOf(fc.hot, (f) => f.properties?.id === selectedId)) || boundsOf(fc.hot);
  if (b) m.fitBounds(b, { padding, duration: animate ? 500 : 0, maxZoom: 14.5 });
}
