#!/usr/bin/env python3
"""
Clip a large building layer to a demo area.

Module 1-2's Overture extract for a whole city can be hundreds of MB — too
large to commit, deploy, or load on every heatmap request. This produces a
small, real subset covering the area you will actually demo, so the heatmap
runs on genuine building geometry instead of synthetic data.

    # clip around Sitapura industrial area, 3 km radius
    python scripts/clip_geodata.py \
        --input ../hackx4.0-main/outputs/jaipur_buildings_places.geojson \
        --lat 26.7963 --lon 75.8397 --radius-km 3

    # or an explicit bounding box
    python scripts/clip_geodata.py --input big.geojson \
        --bbox 75.75 26.78 75.90 26.88

Writes GeoJSON by default. Pass --format gpkg for a smaller, faster file
(GeoPackage is binary and typically a third the size).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box


def human(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def bbox_from_radius(lat: float, lon: float, radius_km: float):
    """Degrees per km varies with latitude; longitude shrinks by cos(lat)."""
    import math
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius-km", type=float, default=3.0)
    parser.add_argument("--bbox", nargs=4, type=float,
                        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    parser.add_argument("--max-features", type=int, default=None,
                        help="keep only the N largest footprints")
    parser.add_argument("--min-area-m2", type=float, default=None,
                        help="drop footprints below this area")
    parser.add_argument("--format", choices=["geojson", "gpkg"],
                        default="geojson")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input.resolve()}")
        return 1

    if args.bbox:
        bounds = tuple(args.bbox)
    elif args.lat is not None and args.lon is not None:
        bounds = bbox_from_radius(args.lat, args.lon, args.radius_km)
    else:
        print("give either --bbox or --lat/--lon")
        return 1

    source_size = args.input.stat().st_size
    print(f"reading {args.input.name} ({human(source_size)})")

    # Push the filter into the driver: for a large file this avoids loading
    # the whole layer into memory just to throw most of it away.
    try:
        gdf = gpd.read_file(args.input, bbox=bounds)
        filtered_by_driver = True
    except Exception:
        gdf = gpd.read_file(args.input)
        filtered_by_driver = False

    if gdf.empty:
        print("no features inside the requested area — check lat/lon order "
              "(GeoJSON is lon, lat)")
        return 1

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf.to_crs("EPSG:4326")

    if not filtered_by_driver:
        gdf = gdf[gdf.intersects(box(*bounds))].copy()

    before = len(gdf)

    if args.min_area_m2 or args.max_features:
        metric = gdf.to_crs(gdf.estimate_utm_crs())
        gdf["_area_m2"] = metric.geometry.area

        if args.min_area_m2:
            gdf = gdf[gdf["_area_m2"] >= args.min_area_m2]
        if args.max_features:
            gdf = gdf.nlargest(args.max_features, "_area_m2")

        gdf = gdf.drop(columns="_area_m2")

    if gdf.empty:
        print("all features removed by the area filters — relax them")
        return 1

    suffix = ".geojson" if args.format == "geojson" else ".gpkg"
    output = args.output or args.input.parent / f"{args.input.stem}_clip{suffix}"
    driver = "GeoJSON" if args.format == "geojson" else "GPKG"
    gdf.to_file(output, driver=driver)

    out_size = output.stat().st_size
    print(f"\n  area      : {bounds[0]:.4f},{bounds[1]:.4f} -> "
          f"{bounds[2]:.4f},{bounds[3]:.4f}")
    print(f"  features  : {before} in area -> {len(gdf)} kept")
    print(f"  written   : {output}  ({human(out_size)})")
    print(f"  reduction : {(1 - out_size / source_size) * 100:.1f}% smaller")
    print(f"\nUse it:\n  \"building_source\": \"{output}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
