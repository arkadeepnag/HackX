from __future__ import annotations

import pandas as pd
import geopandas as gpd

from shapely.geometry import Point


def utm_crs(latitude: float, longitude: float) -> str:
    zone = int((longitude + 180) / 6) + 1

    if latitude >= 0:
        return f"EPSG:{32600 + zone}"

    return f"EPSG:{32700 + zone}"


def first_property(
    row: pd.Series,
    names: list[str]
):
    for name in names:

        if name not in row.index:
            continue

        value = row[name]

        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except Exception:
            pass

        if str(value).strip():
            return value

    return None


def parse_number(value):

    if value is None:
        return None

    try:
        value = str(value)
        value = value.replace("m", "")
        value = value.replace("M", "")
        value = value.strip()

        if "-" in value:
            value = value.split("-")[0]

        result = float(value)

        if pd.isna(result):
            return None

        return result

    except Exception:
        return None


def classify_building(row):

    value = first_property(
        row,
        [
            "building",
            "building_type",
            "type",
            "usage",
            "landuse",
            "class",
            "amenity"
        ]
    )

    if value is None:
        return "unknown"

    value = str(value).lower()

    if any(
        x in value
        for x in [
            "house",
            "residential",
            "apartments",
            "detached"
        ]
    ):
        return "residential"

    if any(
        x in value
        for x in [
            "commercial",
            "retail",
            "office",
            "shop"
        ]
    ):
        return "commercial"

    if any(
        x in value
        for x in [
            "industrial",
            "warehouse",
            "factory"
        ]
    ):
        return "industrial"

    if any(
        x in value
        for x in [
            "school",
            "university",
            "college"
        ]
    ):
        return "institutional"

    return value


def estimate_height(
    row: pd.Series,
    footprint_area_m2: float
):

    explicit_height = first_property(
        row,
        [
            "height",
            "height_m",
            "building_height",
            "Height",
            "HEIGHT"
        ]
    )

    height = parse_number(explicit_height)

    if height is not None and height >= 2.5:
        return height, "geojson_height"

    levels = first_property(
        row,
        [
            "building:levels",
            "levels",
            "floors",
            "floor_count",
            "stories",
            "storeys"
        ]
    )

    levels = parse_number(levels)

    if levels is not None and levels > 0:
        return levels * 3.0, "levels_estimate"

    if footprint_area_m2 >= 5000:
        return 18.0, "area_heuristic"

    if footprint_area_m2 >= 2500:
        return 15.0, "area_heuristic"

    if footprint_area_m2 >= 1000:
        return 12.0, "area_heuristic"

    if footprint_area_m2 >= 400:
        return 9.0, "area_heuristic"

    if footprint_area_m2 >= 150:
        return 6.0, "area_heuristic"

    return 3.0, "area_heuristic"


def load_candidates(
    path: str,
    latitude: float,
    longitude: float,
    radius_m: float,
    max_buildings: int | None
):

    gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError(
            "Building dataset contains no features."
        )

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    gdf = gdf[
        gdf.geometry.notna()
    ].copy()

    gdf = gdf[
        gdf.geometry.geom_type.isin(
            [
                "Polygon",
                "MultiPolygon"
            ]
        )
    ].copy()

    gdf = gdf[
        gdf.is_valid
    ].copy()

    metric_crs = utm_crs(
        latitude,
        longitude
    )

    gdf = gdf.to_crs(metric_crs)

    center = (
        gpd.GeoSeries(
            [
                Point(
                    longitude,
                    latitude
                )
            ],
            crs="EPSG:4326"
        )
        .to_crs(metric_crs)
        .iloc[0]
    )

    gdf["distance_m"] = (
        gdf.geometry
        .centroid
        .distance(center)
    )

    gdf = gdf[
        gdf.distance_m <= radius_m
    ].copy()

    if max_buildings is not None:
        gdf = (
            gdf
            .sort_values("distance_m")
            .head(max_buildings)
            .copy()
        )

    gdf = gdf.reset_index(drop=True)

    if "id" in gdf.columns:
        gdf["building_uid"] = [
            str(value)
            for value in gdf["id"]
        ]
    else:
        gdf["building_uid"] = [
            str(value)
            for value in gdf.index
        ]

    gdf["footprint_area_m2"] = (
        gdf.geometry.area
    )

    gdf["perimeter_m"] = (
        gdf.geometry.length
    )

    heights = []
    height_sources = []
    building_classes = []

    for _, row in gdf.iterrows():

        height, source = estimate_height(
            row,
            float(
                row["footprint_area_m2"]
            )
        )

        heights.append(height)
        height_sources.append(source)

        building_classes.append(
            classify_building(row)
        )

    gdf["height_m"] = heights

    gdf["height_source"] = (
        height_sources
    )

    gdf["building_class"] = (
        building_classes
    )

    gdf["roof_area_m2"] = (
        gdf["footprint_area_m2"]
    )

    gdf["usable_roof_area_m2"] = (
        gdf["roof_area_m2"] * 0.70
    )

    gdf["pv_capacity_kw"] = (
        gdf["usable_roof_area_m2"] / 5.0
    )

    # Carry a WGS84 centroid per building. Without this every downstream
    # lead is coordinate-less and cannot be plotted, clustered or
    # heat-mapped -- the centroid is computed in the metric CRS (correct)
    # and then reprojected back to lat/lon for transport.
    centroids = (
        gdf.geometry
        .centroid
        .to_crs("EPSG:4326")
    )

    gdf["longitude"] = centroids.x
    gdf["latitude"] = centroids.y

    return gdf, metric_crs