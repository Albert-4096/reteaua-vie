import type { Feature, MultiPolygon, Position } from "geojson";

export type Projector = { x: (lon: number) => number; y: (lat: number) => number; width: number; height: number };

/** Equirectangular projection fitted to a bbox, good enough at city scale. */
export function fitProjection(features: Feature<MultiPolygon>[], width: number, pad = 12): Projector {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const f of features)
    for (const poly of f.geometry.coordinates)
      for (const [lon, lat] of poly[0]) {
        minX = Math.min(minX, lon); maxX = Math.max(maxX, lon);
        minY = Math.min(minY, lat); maxY = Math.max(maxY, lat);
      }
  const kx = Math.cos(((minY + maxY) / 2) * (Math.PI / 180));
  const scale = (width - pad * 2) / ((maxX - minX) * kx);
  const height = (maxY - minY) * scale + pad * 2;
  return {
    x: (lon) => pad + (lon - minX) * kx * scale,
    y: (lat) => pad + (maxY - lat) * scale,
    width,
    height,
  };
}

type Ring = number[]; // flat x0,y0,x1,y1… in screen space

function inRing(x: number, y: number, r: Ring) {
  let inside = false;
  for (let i = 0, j = r.length - 2; i < r.length; j = i, i += 2) {
    const xi = r[i], yi = r[i + 1], xj = r[j], yj = r[j + 1];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const project = (ring: Position[], p: Projector): Ring => ring.flatMap(([lon, lat]) => [p.x(lon), p.y(lat)]);

export type Dot = { x: number; y: number; zone: number };

/** A regular dot grid clipped to the neighbourhood polygons; each dot knows its zone. */
export function dotGrid(
  features: Feature<MultiPolygon>[],
  p: Projector,
  step: number,
  bounds = { x0: 0, y0: 0, x1: p.width, y1: p.height },
): Dot[] {
  const zones = features.map((f) => {
    const polys = f.geometry.coordinates.map((poly) => poly.map((ring) => project(ring, p)));
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const poly of polys)
      for (let i = 0; i < poly[0].length; i += 2) {
        x0 = Math.min(x0, poly[0][i]); x1 = Math.max(x1, poly[0][i]);
        y0 = Math.min(y0, poly[0][i + 1]); y1 = Math.max(y1, poly[0][i + 1]);
      }
    return { polys, x0, y0, x1, y1 };
  });
  const dots: Dot[] = [];
  const sx = Math.ceil(bounds.x0 / step) * step, sy = Math.ceil(bounds.y0 / step) * step;
  for (let y = sy + step / 2; y < bounds.y1; y += step)
    for (let x = sx + step / 2; x < bounds.x1; x += step) {
      const zone = zones.findIndex(
        (z) =>
          x >= z.x0 && x <= z.x1 && y >= z.y0 && y <= z.y1 &&
          z.polys.some((poly) => inRing(x, y, poly[0]) && !poly.slice(1).some((h) => inRing(x, y, h))),
      );
      if (zone >= 0) dots.push({ x, y, zone });
    }
  return dots;
}
