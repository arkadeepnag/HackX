#!/usr/bin/env python3
"""
Generate synthetic building + cadastral GeoJSON so the backend can be tested
before modules 1-2 deliver real data.

Produces a plausible mixed industrial/residential cluster near Jaipur with
parcel boundaries using the same column names a state cadastral portal
would export (khasra_no, land_use, ownership).

    python scripts/make_demo_data.py
    python scripts/make_demo_data.py --lat 28.61 --lon 77.20 --out demo/

Swap in your friend's real GeoJSON later by pointing building_source at it;
nothing else changes.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def rect(lon: float, lat: float, w: float, h: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon, lat], [lon + w, lat], [lon + w, lat + h],
            [lon, lat + h], [lon, lat],
        ]],
    }


def make_buildings(lat0: float, lon0: float, count: int, seed: int) -> dict:
    random.seed(seed)
    features = []

    for i in range(count):
        # Two populations: a dense residential belt to the south and larger
        # industrial sheds to the north. A single uniform cloud would make
        # the heatmap bands meaningless.
        industrial = i % 3 == 0
        lat = lat0 + (random.uniform(0.001, 0.006) if industrial
                      else random.uniform(-0.006, -0.001))
        lon = lon0 + random.uniform(-0.006, 0.006)

        if industrial:
            w = random.uniform(0.0009, 0.0022)
            h = w * random.uniform(0.5, 0.9)
            props = {
                "id": f"IND-{i:03d}",
                "building": random.choice(["industrial", "warehouse", "factory"]),
                "building:levels": random.choice([1, 1, 2]),
                "name": f"Unit {i}",
            }
        else:
            w = random.uniform(0.00012, 0.00035)
            h = w * random.uniform(0.7, 1.2)
            props = {
                "id": f"RES-{i:03d}",
                "building": random.choice(["residential", "house", "apartments"]),
                "building:levels": random.choice([1, 2, 2, 3, 4]),
            }

        features.append({
            "type": "Feature", "properties": props,
            "geometry": rect(lon, lat, w, h),
        })

    return {"type": "FeatureCollection", "features": features}


def make_parcels(lat0: float, lon0: float, seed: int) -> dict:
    random.seed(seed + 1)
    uses = ["industrial", "warehouse", "commercial",
            "residential", "institutional", "vacant"]
    features = []
    size = 0.0040
    index = 0

    for row in range(-2, 3):
        for col in range(-2, 3):
            lat = lat0 + row * size
            lon = lon0 + col * size
            use = uses[index % len(uses)] if row >= 0 else "residential"
            features.append({
                "type": "Feature",
                "properties": {
                    "khasra_no": f"KH-{1000 + index}",
                    "land_use": use,
                    "zone": f"Ward-{abs(row) + 1}",
                    "ownership": random.choice(["private", "private", "lease"]),
                    "area_sqm": round(size * size * 1.23e10, 1),
                },
                "geometry": rect(lon, lat, size, size),
            })
            index += 1

    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, default=26.9124)
    parser.add_argument("--lon", type=float, default=75.7873)
    parser.add_argument("--buildings", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("demo_data"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    buildings = make_buildings(args.lat, args.lon, args.buildings, args.seed)
    parcels = make_parcels(args.lat, args.lon, args.seed)

    b_path = args.out / "buildings.geojson"
    p_path = args.out / "parcels.geojson"
    b_path.write_text(json.dumps(buildings))
    p_path.write_text(json.dumps(parcels))

    print(f"buildings : {b_path}  ({len(buildings['features'])} features)")
    print(f"parcels   : {p_path}  ({len(parcels['features'])} features)")
    print(f"centre    : {args.lat}, {args.lon}")
    print()
    print("Try it:")
    print(f"""  curl -s -X POST localhost:8000/api/v1/heatmap/cluster \\
    -H 'Content-Type: application/json' -d '{{
      "latitude": {args.lat}, "longitude": {args.lon}, "radius_m": 1500,
      "building_source": "{b_path}",
      "cadastral_source": "{p_path}",
      "mode": "both"}}' | python -m json.tool | head -40""")


if __name__ == "__main__":
    main()
