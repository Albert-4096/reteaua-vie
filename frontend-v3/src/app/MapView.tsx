import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike, MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import type { Feature, FeatureCollection, Position } from "geojson";
import { inkOn, loadNetwork, type Network } from "@/lib/network";

export type StopTone = "closed" | "ask" | "served";
export type MapStop = { id: string; name: string; lon: number; lat: number; tone: StopTone };
export type MapVehicle = { id: string; lon: number; lat: number; routeId: string };
export type MapLabel = { id: string; lon: number; lat: number; text: string; tone: "work" | "stop" | "ghost" | "end"; place?: "top" | "bottom" | "left" | "right" };
export type MapProps = {
  closures?: { id: string; geometry?: Feature["geometry"]; selected?: boolean }[];
  highlight?: string[]; // lines drawn in full colour; the rest of the network steps back to grey
  ghost?: string[]; // lines the timetable lists but the live data does not show: dashed, in their own colour
  dim?: boolean; // step the rest of the network back to grey even when no line is highlighted
  segment?: Position[] | null; // the stretch a question is about
  detour?: Position[] | null; // a temporary route (the replacement bus)
  stops?: MapStop[];
  vehicles?: MapVehicle[];
  labels?: MapLabel[]; // names written on the map, so nobody has to know where a street is
  fit?: { key: string; points?: Position[]; maxZoom?: number }; // frame these points when the key changes; no points = the city
  onClosure?: (id: string) => void;
  onVehicle?: (routeId: string) => void;
};

maplibregl.setWorkerUrl(workerUrl);

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const TM: LngLatBoundsLike = [[21.15, 45.71], [21.3, 45.8]];
const INK = "#16201c", RED = "#d63b2f", GREY = "#9aa5a1";
const TONE_WORD: Record<StopTone, string> = { closed: "nu oprește", ask: "de hotărât", served: "oprește" };
const fc = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
const line = (coordinates: Position[] | null | undefined): Feature[] =>
  coordinates && coordinates.length > 1 ? [{ type: "Feature", geometry: { type: "LineString", coordinates }, properties: {} }] : [];
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

type State = Required<Omit<MapProps, "onClosure" | "onVehicle" | "fit">> & { fit?: MapProps["fit"] };

/** One map for the whole app: the city's lines in STPT's colours, works in barrier red, stops, vehicles, and names. */
export function MapView({ closures = [], highlight = [], ghost = [], dim = false, segment = null, detour = null, stops = [], vehicles = [], labels = [], fit, onClosure, onVehicle }: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const net = useRef<Network | null>(null);
  const ready = useRef(false);
  const lastFit = useRef<string | undefined>(undefined);
  const markers = useRef(new Map<string, maplibregl.Marker>());
  const shown = useRef(new Map<string, [number, number]>()); // where each vehicle is drawn right now
  const glide = useRef(0);
  const state: State = { closures, highlight, ghost, dim, segment, detour, stops, vehicles, labels, fit };
  const latest = useRef(state);
  latest.current = state;
  const cb = useRef({ onClosure, onVehicle });
  cb.current = { onClosure, onVehicle };

  const sync = (first: boolean) => {
    const m = map.current;
    if (!m || !ready.current) return;
    const p = latest.current;
    const src = (id: string) => m.getSource(id) as GeoJSONSource;
    const focused = p.dim || p.highlight.length > 0 || !!p.segment;

    src("closures").setData(fc(p.closures.filter((c) => c.geometry).map((c) => ({ type: "Feature", geometry: c.geometry!, properties: { id: c.id, selected: !!c.selected } }))));
    src("segment").setData(fc(line(p.segment)));
    m.setPaintProperty("segment", "line-color", `#${net.current?.byId.get(p.highlight[0])?.color ?? "ffffff"}`);
    src("detour").setData(fc(line(p.detour)));
    // a stop that already has its name written beside it does not get a second one from the map
    const named = (s: MapStop) => p.labels.some((l) => Math.abs(l.lon - s.lon) < 1e-4 && Math.abs(l.lat - s.lat) < 1e-4);
    src("stops").setData(fc(p.stops.map((s) => ({ type: "Feature", geometry: { type: "Point", coordinates: [s.lon, s.lat] }, properties: { name: s.name, tone: s.tone, text: named(s) ? "" : s.name } }))));
    m.setFilter("lines-hi", ["in", ["get", "routeId"], ["literal", p.highlight]]);
    m.setFilter("lines-hi-casing", ["in", ["get", "routeId"], ["literal", p.highlight]]);
    m.setFilter("lines-ghost", ["in", ["get", "routeId"], ["literal", p.ghost]]);
    // with nothing in focus the whole network shows its colours; with a focus it steps back to grey
    m.setPaintProperty("lines-base", "line-color", focused ? GREY : ["get", "color"]);
    m.setPaintProperty("lines-base", "line-opacity", focused ? 0.4 : 0.55);

    // vehicles glide to their new place instead of jumping
    const target = new Map(p.vehicles.map((v) => [v.id, v] as const));
    for (const id of [...shown.current.keys()]) if (!target.has(id)) shown.current.delete(id);
    const from = new Map(shown.current);
    const draw = (t: number) => {
      const feats: Feature[] = [];
      for (const v of target.values()) {
        const a = from.get(v.id) ?? [v.lon, v.lat];
        const at: [number, number] = [a[0] + (v.lon - a[0]) * t, a[1] + (v.lat - a[1]) * t];
        shown.current.set(v.id, at);
        const r = net.current?.byId.get(v.routeId);
        feats.push({ type: "Feature", geometry: { type: "Point", coordinates: at }, properties: { routeId: v.routeId, label: r?.shortName ?? "", color: `#${r?.color ?? "16201c"}`, ink: r ? inkOn(r.color) : "#ffffff" } });
      }
      src("vehicles").setData(fc(feats));
    };
    cancelAnimationFrame(glide.current);
    if (first || calm() || from.size === 0) draw(1);
    else {
      const t0 = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / 1400);
        draw(1 - (1 - k) ** 3);
        if (k < 1) glide.current = requestAnimationFrame(step);
      };
      glide.current = requestAnimationFrame(step);
    }

    // names on the map
    const want = new Map(p.labels.map((l) => [l.id, l] as const));
    for (const [id, mk] of markers.current) if (!want.has(id)) { mk.remove(); markers.current.delete(id); }
    for (const l of want.values()) {
      const place = l.place ?? "top";
      let mk = markers.current.get(l.id);
      if (mk && mk.getElement().dataset.place !== place) { mk.remove(); markers.current.delete(l.id); mk = undefined; }
      if (!mk) {
        const node = document.createElement("div");
        node.className = "rv-label";
        node.dataset.place = place;
        const anchor = ({ top: "bottom", bottom: "top", left: "right", right: "left" } as const)[place];
        const offset = ({ top: [0, -11], bottom: [0, 11], left: [-11, 0], right: [11, 0] } as const)[place];
        mk = new maplibregl.Marker({ element: node, anchor, offset: [...offset] }).setLngLat([l.lon, l.lat]).addTo(m);
        markers.current.set(l.id, mk);
      }
      const node = mk.getElement();
      node.dataset.tone = l.tone;
      if (node.textContent !== l.text) node.textContent = l.text;
      mk.setLngLat([l.lon, l.lat]);
    }

    if (p.fit && (first || p.fit.key !== lastFit.current)) {
      const pts = p.fit.points ?? [];
      const duration = first || calm() ? 0 : 700;
      if (pts.length) {
        const b = pts.reduce((acc, [x, y]) => acc.extend([x, y]), new maplibregl.LngLatBounds(pts[0] as [number, number], pts[0] as [number, number]));
        m.fitBounds(b, { padding: { top: 90, right: 80, bottom: 80, left: 80 }, maxZoom: p.fit.maxZoom ?? 15.5, duration });
      } else m.fitBounds(TM, { padding: 24, duration });
      lastFit.current = p.fit.key;
    }
  };

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current!, style: STYLE, bounds: TM, attributionControl: { compact: true } });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    const resize = new ResizeObserver(() => m.resize());
    resize.observe(el.current!);
    m.on("load", async () => {
      net.current = await loadNetwork().catch(() => null);
      const n = net.current;
      const lines = fc((n?.paths ?? []).filter((p) => p.directionId === 0).map((p) => {
        const r = n!.byId.get(p.routeId);
        return { type: "Feature", geometry: p.geometry, properties: { routeId: p.routeId, color: `#${r?.color ?? "888888"}`, tram: r?.type === 0 } };
      }));
      for (const id of ["closures", "segment", "detour", "stops", "vehicles"]) m.addSource(id, { type: "geojson", data: fc([]) });
      m.addSource("lines", { type: "geojson", data: lines });
      const round = { "line-cap": "round", "line-join": "round" } as const;
      const none = ["in", ["get", "routeId"], ["literal", []]] as maplibregl.FilterSpecification;
      m.addLayer({ id: "lines-base", type: "line", source: "lines", layout: round, paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "tram"], 2.2, 1.5], "line-opacity": 0.55 } });
      m.addLayer({ id: "lines-ghost", type: "line", source: "lines", filter: none, paint: { "line-color": ["get", "color"], "line-width": 3.5, "line-dasharray": [0.6, 1.6] }, layout: round });
      m.addLayer({ id: "lines-hi-casing", type: "line", source: "lines", filter: none, layout: round, paint: { "line-color": "#ffffff", "line-width": ["case", ["get", "tram"], 8, 7] } });
      m.addLayer({ id: "lines-hi", type: "line", source: "lines", filter: none, layout: round, paint: { "line-color": ["get", "color"], "line-width": ["case", ["get", "tram"], 4.5, 3.5] } });
      m.addLayer({ id: "detour", type: "line", source: "detour", paint: { "line-color": INK, "line-width": 2.5, "line-dasharray": [2, 1.6] } });
      m.addLayer({ id: "segment-casing", type: "line", source: "segment", layout: round, paint: { "line-color": INK, "line-width": 11 } });
      m.addLayer({ id: "segment", type: "line", source: "segment", layout: round, paint: { "line-color": "#ffffff", "line-width": 5.5 } });
      m.addLayer({ id: "closures-casing", type: "line", source: "closures", layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": ["case", ["get", "selected"], 13, 10] } });
      m.addLayer({ id: "closures", type: "line", source: "closures", layout: { "line-cap": "butt" }, paint: { "line-color": RED, "line-width": ["case", ["get", "selected"], 8, 6], "line-dasharray": [1.2, 0.8] } });
      m.addLayer({ id: "stops", type: "circle", source: "stops", paint: {
        "circle-radius": ["match", ["get", "tone"], "served", 4, 5.5],
        "circle-color": ["match", ["get", "tone"], "closed", RED, "#ffffff"],
        "circle-stroke-width": ["match", ["get", "tone"], "closed", 2, "ask", 2.6, 1.8],
        "circle-stroke-color": ["match", ["get", "tone"], "closed", "#ffffff", "ask", INK, "#5b6a64"] } });
      m.addLayer({ id: "stops-name", type: "symbol", source: "stops", minzoom: 13.4, layout: {
        "text-field": ["get", "text"], "text-font": ["Noto Sans Regular"], "text-size": 11.5, "text-anchor": "top", "text-offset": [0, 0.8], "text-max-width": 9, "text-optional": true },
        paint: { "text-color": INK, "text-halo-color": "#ffffff", "text-halo-width": 1.6 } });
      m.addLayer({ id: "vehicles", type: "circle", source: "vehicles", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 4.5, 13.2, 6, 13.6, 9.5],
        "circle-color": ["get", "color"], "circle-stroke-width": 1.8, "circle-stroke-color": "#ffffff" } });
      m.addLayer({ id: "vehicles-name", type: "symbol", source: "vehicles", minzoom: 13.4, layout: {
        "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 9.5, "text-allow-overlap": true, "text-ignore-placement": true },
        paint: { "text-color": ["get", "ink"] } });

      const pointer = (layer: string) => {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      };
      m.on("click", "closures", (e: MapLayerMouseEvent) => { const id = e.features?.[0]?.properties?.id; if (id) cb.current.onClosure?.(id); });
      m.on("click", "vehicles", (e: MapLayerMouseEvent) => { const id = e.features?.[0]?.properties?.routeId; if (id) cb.current.onVehicle?.(id); });
      pointer("closures"); pointer("vehicles");
      const popup = new maplibregl.Popup({ closeButton: false, offset: 10, className: "rv-popup" });
      m.on("mouseenter", "stops", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (f) popup.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number]).setText(`${f.properties.name} · ${TONE_WORD[f.properties.tone as StopTone]}`).addTo(m);
      });
      m.on("mouseleave", "stops", () => popup.remove());
      m.on("mouseenter", "vehicles", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        const r = f && net.current?.byId.get(f.properties.routeId);
        if (f && r) popup.setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number]).setText(`${r.shortName} · ${r.longName}`).addTo(m);
      });
      m.on("mouseleave", "vehicles", () => popup.remove());
      ready.current = true;
      sync(true);
    });
    return () => {
      ready.current = false;
      cancelAnimationFrame(glide.current);
      resize.disconnect();
      markers.current.clear();
      shown.current.clear();
      m.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => sync(false), [closures, highlight, ghost, dim, segment, detour, stops, vehicles, labels, fit]);

  return <div ref={el} className="h-full w-full" role="application" aria-label="Harta rețelei" />;
}
