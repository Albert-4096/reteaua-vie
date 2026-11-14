// The persistent map: OpenFreeMap vector style, plain background if the tiles fail.
// City layers (zones, network) and the step's overlay (closure, stops, routes) are drawn on top.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { Network } from "../api/client";
import { bounds } from "../lib/geo";

// Vite pre-bundles maplibre, so its own relative worker lookup fails: give it the worker file.
maplibregl.setWorkerUrl(workerUrl);

export type MapStop = {
  id: string;
  name: string;
  location: [number, number];
  status: "lost" | "unsure" | "served";
  /** Plain words shown on click: the status is never colour alone. */
  label: string;
};

export type MapOverlay = {
  closure?: GeoJSON.Geometry | null;
  tempRoutes?: GeoJSON.Geometry[];
  highlightRouteIds?: string[];
  stops?: MapStop[];
  /** A short honesty label about what is drawn (e.g. „locație aproximativă”). */
  note?: string;
  /** Change it to refit the view to the overlay. */
  fitKey?: string;
  /** Extra thematic layers (steps 0 and 4). One source and layer per id; colours from tokens. */
  layers?: { id: ExtraLayerId; data: GeoJSON.FeatureCollection }[];
  hideNetwork?: boolean;
  /** Replaces the stop counts in the map's text equivalent when the colours mean something else (step 4). */
  stopsText?: string;
};

export type ExtraLayerId = "bike" | "parking" | "population" | "vehicles" | "detour";
const EXTRA_IDS: ExtraLayerId[] = ["bike", "parking", "population", "vehicles", "detour"];

function extraData(o: MapOverlay, id: ExtraLayerId): GeoJSON.FeatureCollection {
  return o.layers?.find((l) => l.id === id)?.data ?? empty;
}

const BASE_STYLE = "https://tiles.openfreemap.org/styles/positron";
const CENTER: [number, number] = [21.2272, 45.7537];

const OverlayCtx = createContext<(o: MapOverlay) => void>(() => {});

export const MapOverlayProvider = OverlayCtx.Provider;

/** A step sets what the map shows while it is on screen. */
export function useMapOverlay(overlay: MapOverlay, deps: unknown[]) {
  const set = useContext(OverlayCtx);
  useEffect(() => {
    set(overlay);
    return () => set({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function fallbackStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": cssVar("--map-bg") } }],
  };
}

/** Diagonal hatch for the closed street: drawn at runtime from the tokens. */
function hatchImage(): ImageData {
  const size = 16;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, size, size);
  g.strokeStyle = cssVar("--map-closure");
  g.lineWidth = 4;
  g.beginPath();
  for (let k = -size; k <= size * 2; k += 8) {
    g.moveTo(k, size);
    g.lineTo(k + size, 0);
  }
  g.stroke();
  return g.getImageData(0, 0, size, size);
}

const empty: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function networkFc(net: Network | undefined): GeoJSON.FeatureCollection {
  if (!net) return empty;
  return {
    type: "FeatureCollection",
    features: net.paths
      .filter((p) => p.geometry)
      .map((p) => ({
        type: "Feature",
        properties: { routeId: p.routeId },
        geometry: p.geometry as unknown as GeoJSON.Geometry,
      })),
  };
}

/** Short bars across both ends of each closed section, so it reads as a blocked road. */
function endBars(g: GeoJSON.Geometry): GeoJSON.Feature[] {
  const parts =
    g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : ([] as number[][][]);
  const bars: GeoJSON.Feature[] = [];
  for (const line of parts) {
    if (line.length < 2) continue;
    for (const [end, next] of [
      [line[0], line[1]],
      [line[line.length - 1], line[line.length - 2]],
    ]) {
      const k = Math.cos((end[1] * Math.PI) / 180);
      const dx = (next[0] - end[0]) * k;
      const dy = next[1] - end[1];
      const len = Math.hypot(dx, dy) || 1;
      const half = 22 / 111_320; // about 22 m each side
      const px = (-dy / len) * half;
      const py = (dx / len) * half;
      bars.push({
        type: "Feature",
        properties: { kind: "bar" },
        geometry: {
          type: "LineString",
          coordinates: [
            [end[0] + px / k, end[1] + py],
            [end[0] - px / k, end[1] - py],
          ],
        },
      });
    }
  }
  return bars;
}

function overlayData(o: MapOverlay) {
  const closure: GeoJSON.FeatureCollection = o.closure
    ? {
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: { kind: "road" }, geometry: o.closure }, ...endBars(o.closure)],
      }
    : empty;
  const temp: GeoJSON.FeatureCollection = {
    type: "FeatureCollection",
    features: (o.tempRoutes ?? []).map((g) => ({ type: "Feature", properties: {}, geometry: g })),
  };
  const stops: GeoJSON.FeatureCollection = {
    type: "FeatureCollection",
    features: (o.stops ?? []).map((s) => ({
      type: "Feature",
      properties: { id: s.id, name: s.name, status: s.status, label: s.label },
      geometry: { type: "Point", coordinates: s.location },
    })),
  };
  return { closure, temp, stops };
}

function coordsOf(g: GeoJSON.Geometry | null | undefined): [number, number][] {
  if (!g) return [];
  if (g.type === "Point") return [g.coordinates as [number, number]];
  if (g.type === "LineString") return g.coordinates as [number, number][];
  if (g.type === "MultiLineString") return g.coordinates.flat() as [number, number][];
  return [];
}

type Props = {
  network?: Network;
  zones?: GeoJSON.FeatureCollection;
  overlay: MapOverlay;
};

export function MapView({ network, zones, overlay }: Props) {
  const { t } = useTranslation();
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(0);
  const [fallback, setFallback] = useState(false);
  const latest = useRef({ network, zones, overlay });
  latest.current = { network, zones, overlay };

  useEffect(() => {
    if (!el.current) return;
    let usedFallback = false;
    let baseLoaded = false;
    const map = new maplibregl.Map({
      container: el.current,
      style: BASE_STYLE,
      center: CENTER,
      zoom: 12.4,
      attributionControl: { compact: true },
      fadeDuration: 0,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

    const toFallback = () => {
      if (usedFallback) return;
      usedFallback = true;
      setFallback(true);
      map.setStyle(fallbackStyle());
    };
    // Fall back only when the base style itself never loads; a slow or failed tile later is not a reason.
    const timer = window.setTimeout(() => {
      if (!baseLoaded) toFallback();
    }, 8000);
    map.on("error", () => {
      if (!baseLoaded) toFallback();
    });
    map.on("style.load", () => {
      baseLoaded = true;
      addCityLayers(map);
      setReady((n) => n + 1);
    });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: true, offset: 8 });
    map.on("click", "rv-stops", (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { name: string; label: string };
      popup
        .setLngLat(e.lngLat)
        .setHTML(`<strong>${escapeHtml(p.name)}</strong><br>${escapeHtml(p.label)}`)
        .addTo(map);
    });
    map.on("mouseenter", "rv-stops", () => (map.getCanvas().style.cursor = "pointer"));
    map.on("mouseleave", "rv-stops", () => (map.getCanvas().style.cursor = ""));

    return () => {
      window.clearTimeout(timer);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // City layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (map.getSource("rv-network") as GeoJSONSource | undefined)?.setData(networkFc(network));
    (map.getSource("rv-zones") as GeoJSONSource | undefined)?.setData(zones ?? empty);
  }, [network, zones, ready]);

  // Step overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const d = overlayData(overlay);
    (map.getSource("rv-closure") as GeoJSONSource | undefined)?.setData(d.closure);
    (map.getSource("rv-temp") as GeoJSONSource | undefined)?.setData(d.temp);
    (map.getSource("rv-stops") as GeoJSONSource | undefined)?.setData(d.stops);
    for (const id of EXTRA_IDS) (map.getSource(`rv-x-${id}`) as GeoJSONSource | undefined)?.setData(extraData(overlay, id));
    if (map.getLayer("rv-network")) map.setLayoutProperty("rv-network", "visibility", overlay.hideNetwork ? "none" : "visible");
    const hi = overlay.highlightRouteIds ?? [];
    if (map.getLayer("rv-network-hi")) map.setFilter("rv-network-hi", ["in", ["get", "routeId"], ["literal", hi]]);
  }, [overlay, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !overlay.fitKey) return;
    const pts = [...coordsOf(overlay.closure), ...(overlay.stops ?? []).map((s) => s.location)];
    const b = bounds(pts);
    if (b) map.fitBounds(b, { padding: 48, maxZoom: 15.5, duration: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay.fitKey, ready]);

  function addCityLayers(map: maplibregl.Map) {
    const { network: net, zones: z, overlay: o } = latest.current;
    const d = overlayData(o);
    if (!map.hasImage("rv-hatch")) map.addImage("rv-hatch", hatchImage(), { pixelRatio: 2 });
    map.addSource("rv-zones", { type: "geojson", data: z ?? empty });
    map.addSource("rv-network", { type: "geojson", data: networkFc(net) });
    map.addSource("rv-temp", { type: "geojson", data: d.temp });
    map.addSource("rv-closure", { type: "geojson", data: d.closure });
    map.addSource("rv-stops", { type: "geojson", data: d.stops });
    for (const id of EXTRA_IDS) map.addSource(`rv-x-${id}`, { type: "geojson", data: extraData(o, id) });
    map.addLayer({
      id: "rv-zones",
      type: "line",
      source: "rv-zones",
      paint: { "line-color": cssVar("--map-zone"), "line-width": 0.8, "line-dasharray": [3, 2] },
    });
    map.addLayer({
      id: "rv-x-population",
      type: "fill",
      source: "rv-x-population",
      paint: {
        "fill-color": cssVar("--c-text"),
        "fill-opacity": ["interpolate", ["linear"], ["coalesce", ["get", "residents"], 0], 0, 0, 300, 0.35],
      },
    });
    map.addLayer({
      id: "rv-network",
      type: "line",
      source: "rv-network",
      layout: { "line-join": "round", "line-cap": "round", visibility: o.hideNetwork ? "none" : "visible" },
      paint: { "line-color": cssVar("--map-network"), "line-width": 1.2, "line-opacity": 0.8 },
    });
    map.addLayer({
      id: "rv-network-hi",
      type: "line",
      source: "rv-network",
      filter: ["in", ["get", "routeId"], ["literal", o.highlightRouteIds ?? []]],
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": cssVar("--map-route-hi"), "line-width": 2.2 },
    });
    for (const id of ["bike", "detour"] as const)
      map.addLayer({
        id: `rv-x-${id}`,
        type: "line",
        source: `rv-x-${id}`,
        layout: { "line-join": "round" },
        paint: { "line-color": cssVar("--map-temp-route"), "line-width": 2 },
      });
    map.addLayer({
      id: "rv-x-parking",
      type: "line",
      source: "rv-x-parking",
      paint: { "line-color": cssVar("--c-text-muted"), "line-width": 1.5 },
    });
    map.addLayer({
      id: "rv-x-vehicles",
      type: "circle",
      source: "rv-x-vehicles",
      paint: { "circle-color": cssVar("--c-text"), "circle-radius": 3.5 },
    });
    map.addLayer({
      id: "rv-temp",
      type: "line",
      source: "rv-temp",
      layout: { "line-join": "round" },
      paint: { "line-color": cssVar("--map-temp-route"), "line-width": 2.5, "line-dasharray": [2, 1.5] },
    });
    // The closed street: a dark casing with a hatched, blocked road inside, and bars at both ends.
    map.addLayer({
      id: "rv-closure-casing",
      type: "line",
      source: "rv-closure",
      filter: ["==", ["get", "kind"], "road"],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: { "line-color": cssVar("--map-closure-casing"), "line-width": 14 },
    });
    map.addLayer({
      id: "rv-closure",
      type: "line",
      source: "rv-closure",
      filter: ["==", ["get", "kind"], "road"],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: { "line-pattern": "rv-hatch", "line-width": 11 },
    });
    map.addLayer({
      id: "rv-closure-bars",
      type: "line",
      source: "rv-closure",
      filter: ["==", ["get", "kind"], "bar"],
      layout: { "line-cap": "butt" },
      paint: { "line-color": cssVar("--map-closure-casing"), "line-width": 5 },
    });
    map.addLayer({
      id: "rv-stops",
      type: "circle",
      source: "rv-stops",
      paint: {
        "circle-radius": ["match", ["get", "status"], "served", 4, 5.5],
        "circle-color": [
          "match",
          ["get", "status"],
          "lost",
          cssVar("--c-lost"),
          "unsure",
          cssVar("--c-unsure"),
          cssVar("--c-bg"),
        ],
        "circle-stroke-color": ["match", ["get", "status"], "served", cssVar("--c-text"), cssVar("--c-bg")],
        "circle-stroke-width": 1.5,
      },
    });
  }

  return (
    <div className="map">
      <div
        ref={el}
        style={{ position: "absolute", inset: 0 }}
        aria-label={t("mapText.label")}
        aria-describedby="map-text"
        role="region"
      />
      <p id="map-text" className="visually-hidden">
        {mapText(overlay, network, t)}
      </p>
      {(fallback || overlay.note) && (
        <p className="map-note">
          {overlay.note}
          {fallback && overlay.note && <br />}
          {fallback && t("mapFallback")}
        </p>
      )}
    </div>
  );
}

/** The map in one sentence, for screen readers (R22): only counts of what is drawn, from data already loaded. */
function mapText(o: MapOverlay, net: Network | undefined, t: TFunction) {
  const parts: string[] = [];
  if (o.closure) parts.push(t("mapText.closure"));
  if (o.tempRoutes?.length) parts.push(t("mapText.temp"));
  const short = new Map((net?.routes ?? []).map((r) => [r.id, r.shortName]));
  const names = [...new Set((o.highlightRouteIds ?? []).map((id) => short.get(id) ?? id))];
  if (names.length) parts.push(t("mapText.lines", { count: names.length, names: names.join(", ") }));
  if (o.stopsText) parts.push(o.stopsText);
  else if (o.stops?.length) {
    const n = { lost: 0, unsure: 0, served: 0 };
    for (const s of o.stops) n[s.status] += 1;
    parts.push(t("mapText.stops", n));
  }
  for (const l of o.layers ?? []) parts.push(t(`mapText.layer.${l.id}`, { count: l.data.features.length }));
  if (!parts.length) parts.push(t("mapText.network", { count: net?.routes.length ?? 0 }));
  return `${t("mapText.prefix")} ${parts.join("; ")}.`;
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
