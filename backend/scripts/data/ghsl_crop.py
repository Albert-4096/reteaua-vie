"""Crop a GHSL GHS-POP tile to the Timișoara bbox and print sanity numbers.

Usage: ghsl_crop.py TILE.tif OUT.tif MINLON,MINLAT,MAXLON,MAXLAT [ZONES.geojson]

Prints the bounds, resolution and CRS of the crop, the population summed over
the bbox, and the population inside the city's zones (pixel centre inside the
zone). The figures are a model (GHSL 2020), not a census.
"""

import json
import sys

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds

# A point well inside Timișoara; the tile must cover it.
CHECK_POINT = (21.2, 45.75)


def population_sum(data: np.ndarray, nodata) -> float:
    valid = np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    valid &= data >= 0
    return float(data[valid].sum())


def main() -> None:
    tile_path, out_path, bbox_arg = sys.argv[1:4]
    zones_path = sys.argv[4] if len(sys.argv) > 4 else None
    minlon, minlat, maxlon, maxlat = (float(v) for v in bbox_arg.split(","))

    with rasterio.open(tile_path) as src:
        print(f"tile crs={src.crs} bounds={tuple(round(b, 6) for b in src.bounds)}")
        left, bottom, right, top = src.bounds
        lon, lat = CHECK_POINT
        if not (left <= lon <= right and bottom <= lat <= top):
            sys.exit(f"tile does not cover {CHECK_POINT}")
        if src.crs is None or src.crs.to_epsg() != 4326:
            sys.exit(f"expected EPSG:4326, got {src.crs}")

        # Snap the window outwards to whole pixels so no cell is resampled.
        window = from_bounds(minlon, minlat, maxlon, maxlat, transform=src.transform)
        window = window.round_offsets(op="floor").round_lengths(op="ceil")
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            transform=transform,
            compress="deflate",
            tiled=False,
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
        nodata = src.nodata

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)

    with rasterio.open(out_path) as crop:
        b = crop.bounds
        print(f"crop file={out_path}")
        print(f"crop crs={crop.crs} size={crop.width}x{crop.height} dtype={crop.dtypes[0]} nodata={crop.nodata}")
        print(f"crop bounds=({b.left:.6f}, {b.bottom:.6f}, {b.right:.6f}, {b.top:.6f})")
        print(f"crop resolution_deg=({crop.res[0]:.10f}, {crop.res[1]:.10f}) (3 arcsec = {3 / 3600:.10f})")

    print(f"population in bbox: {population_sum(data, nodata):,.0f} (model GHSL 2020, nu recensământ)")

    if zones_path:
        with open(zones_path, encoding="utf-8") as f:
            zones = json.load(f)["features"]
        # One mask over all zones, so a cell on a shared border counts once.
        inside = geometry_mask(
            [z["geometry"] for z in zones], out_shape=data.shape, transform=transform, invert=True
        )
        total = population_sum(np.where(inside, data, 0), nodata)
        print(
            f"population in the {len(zones)} zones of {zones_path.rsplit('/', 2)[-2]}/zones.geojson: "
            f"{total:,.0f} (model GHSL 2020, nu recensământ)"
        )


if __name__ == "__main__":
    main()
