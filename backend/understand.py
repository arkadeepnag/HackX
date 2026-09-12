

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import pvlib
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.affinity import translate
from shapely.strtree import STRtree






IST = "Asia/Kolkata"


DEFAULT_FLOOR_HEIGHT_M = 3.0
DEFAULT_HEIGHT_M = 6.0
DEFAULT_MIN_HEIGHT_M = 2.5



AREA_HEIGHT_RULES = [
    (50, 3.0),
    (150, 6.0),
    (400, 9.0),
    (1000, 12.0),
    (2500, 15.0),
    (5000, 18.0),
    (10000, 24.0),
]


USABLE_ROOF_FRACTION = 0.70
PV_MODULE_AREA_M2_PER_KW = 5.0
PV_EFFICIENCY = 0.20
SYSTEM_LOSS = 0.14


WEIGHT_IRRADIATION = 0.35
WEIGHT_SUN_HOURS = 0.20
WEIGHT_SHADING = 0.25
WEIGHT_USABLE_AREA = 0.10
WEIGHT_ORIENTATION = 0.10


@dataclass
class SolarConfig:
    step_minutes: int = 60
    candidate_radius_m: float = 500.0
    roof_sample_spacing_m: float = 5.0
    min_sun_elevation_deg: float = 3.0
    max_buildings: int | None = None
    fast_mode: bool = False






def parse_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("m", "").replace("M", "")
            if "-" in value:
                value = value.split("-")[0]
        x = float(value)
        return x if np.isfinite(x) else None
    except Exception:
        return None


def first_property(row, names):
    for name in names:
        if name in row.index:
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


def utm_crs(lat: float, lon: float):
    zone = int((lon + 180) / 6) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def building_class(row):
    value = first_property(
        row,
        [
            "building",
            "building_type",
            "type",
            "usage",
            "landuse",
            "class",
            "amenity",
        ],
    )
    if value is None:
        return "unknown"

    s = str(value).lower()

    if any(x in s for x in ["house", "residential", "apartments", "detached"]):
        return "residential"
    if any(x in s for x in ["commercial", "retail", "office", "shop"]):
        return "commercial"
    if any(x in s for x in ["industrial", "warehouse", "factory"]):
        return "industrial"
    if any(x in s for x in ["school", "university", "college"]):
        return "institutional"

    return s






def estimate_height(row, footprint_area_m2: float):
    """
    Priority:
        1. explicit height
        2. floor/storey count
        3. area heuristic
        4. default

    Returns (height_m, source).
    """

    explicit = first_property(
        row,
        [
            "height",
            "height_m",
            "building_height",
            "Height",
            "HEIGHT",
        ],
    )
    h = parse_float(explicit)

    if h is not None and h >= DEFAULT_MIN_HEIGHT_M:
        return h, "geojson_height"

    levels = first_property(
        row,
        [
            "building:levels",
            "levels",
            "floors",
            "floor_count",
            "stories",
            "storeys",
        ],
    )
    floors = parse_float(levels)

    if floors is not None and floors > 0:
        return floors * DEFAULT_FLOOR_HEIGHT_M, "levels_estimate"

    
    selected = DEFAULT_HEIGHT_M
    for threshold, height in AREA_HEIGHT_RULES:
        if footprint_area_m2 >= threshold:
            selected = height

    return selected, "area_heuristic"






def solar_time_series(lat, lon, step_minutes=60):
    """
    Full-year solar position + clear-sky irradiance for India.
    """

    freq = f"{step_minutes}min"

    times = pd.date_range(
        "2026-01-01 00:00",
        "2026-12-31 23:59",
        freq=freq,
        tz=IST,
    )

    loc = pvlib.location.Location(
        latitude=lat,
        longitude=lon,
        tz=IST,
    )

    solpos = loc.get_solarposition(times)
    clearsky = loc.get_clearsky(times, model="ineichen")

    
    mask = solpos["apparent_elevation"].values >= 0

    times = times[mask]
    solpos = solpos.loc[mask]
    clearsky = clearsky.loc[mask]

    return times, solpos, clearsky


def panel_poa(
    tilt_deg,
    azimuth_deg,
    solpos,
    clearsky,
):
    """
    Plane-of-array irradiance.

    azimuth:
        0   = north
        90  = east
        180 = south
        270 = west
    """

    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=float(tilt_deg),
        surface_azimuth=float(azimuth_deg),
        dni=clearsky["dni"],
        ghi=clearsky["ghi"],
        dhi=clearsky["dhi"],
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
    )

    return poa["poa_global"].clip(lower=0)


def optimize_panel_angle(solpos, clearsky, fast=False):
    """
    Search tilt/azimuth for the highest annual plane-of-array energy.

    The optimization is independent of urban shading initially. A second
    shading-aware optimization is possible, but is considerably more
    expensive. This gives the physically useful baseline optimum.
    """

    if fast:
        tilts = range(0, 46, 5)
        azimuths = range(90, 271, 15)
    else:
        tilts = range(0, 61, 5)
        azimuths = range(0, 360, 15)

    best = None

    for tilt in tilts:
        for az in azimuths:
            poa = panel_poa(tilt, az, solpos, clearsky)
            energy = float(poa.sum())

            if best is None or energy > best["energy"]:
                best = {
                    "tilt_deg": float(tilt),
                    "azimuth_deg": float(az),
                    "energy": energy,
                }

    return best






def shadow_translation(
    sun_azimuth_deg: float,
    sun_elevation_deg: float,
    blocker_height_m: float,
    target_height_m: float,
):
    """
    Return dx, dy for the blocker shadow projected onto a horizontal plane
    at target_height_m.

    Coordinates:
        x = east
        y = north

    pvlib azimuth is clockwise from north.

    Shadow direction is opposite the sun direction.
    """

    dh = blocker_height_m - target_height_m

    if dh <= 0:
        return 0.0, 0.0

    if sun_elevation_deg <= 0.1:
        return None

    elevation_rad = math.radians(sun_elevation_deg)

    length = dh / math.tan(elevation_rad)

    az_rad = math.radians(sun_azimuth_deg)

    sun_dx = math.sin(az_rad)
    sun_dy = math.cos(az_rad)

    return (
        -sun_dx * length,
        -sun_dy * length,
    )


def projected_shadow(blocker_geom, dx, dy):
    return translate(blocker_geom, xoff=dx, yoff=dy)






def make_tree(geometries):
    return STRtree(list(geometries))


def candidate_blockers(
    target_geom,
    target_height,
    blocker_geoms,
    blocker_heights,
    tree,
    max_distance,
):
    """
    Find nearby geometries. Exact filtering is done later for the current
    sun position because the shadow length changes with solar elevation.
    """

    query_geom = target_geom.buffer(max_distance)

    indexes = tree.query(query_geom)

    candidates = []

    for idx in indexes:
        idx = int(idx)

        if blocker_geoms[idx].equals(target_geom):
            continue

        if blocker_heights[idx] <= target_height:
            continue

        if blocker_geoms[idx].distance(target_geom) > max_distance:
            continue

        candidates.append(idx)

    return candidates






def hourly_shadow_for_target(
    target_idx,
    buildings,
    tree,
    candidate_cache,
    solpos,
    clearsky,
    optimum_tilt,
    optimum_azimuth,
    config,
):
    """
    Calculate hourly direct-beam shading for one building.

    For every sun position:
        - project each taller nearby building's shadow
        - intersect with target footprint
        - calculate shaded fraction
        - reduce only the direct beam component

    Returns:
        dataframe with hourly target solar metrics
        contributor dictionary
    """

    target = buildings.iloc[target_idx]
    target_geom = target.geometry
    target_height = float(target.height_m)

    candidates = candidate_cache[target_idx]

    records = []
    contributor_energy = {}

    
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=optimum_tilt,
        surface_azimuth=optimum_azimuth,
        dni=clearsky["dni"],
        ghi=clearsky["ghi"],
        dhi=clearsky["dhi"],
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
    )

    poa_global = poa["poa_global"].clip(lower=0)
    poa_direct = poa["poa_direct"].clip(lower=0)
    poa_diffuse = poa["poa_diffuse"].clip(lower=0)

    area = max(float(target_geom.area), 0.01)

    for i, timestamp in enumerate(solpos.index):

        elevation = float(solpos.iloc[i]["apparent_elevation"])
        azimuth = float(solpos.iloc[i]["azimuth"])

        if elevation < config.min_sun_elevation_deg:
            continue

        shaded_union = None
        shaded_by = []

        for blocker_idx in candidates:

            blocker = buildings.iloc[blocker_idx]
            blocker_height = float(blocker.height_m)

            vec = shadow_translation(
                azimuth,
                elevation,
                blocker_height,
                target_height,
            )

            if vec is None:
                continue

            dx, dy = vec

            
            
            shadow = projected_shadow(
                blocker.geometry,
                dx,
                dy,
            )

            intersection = shadow.intersection(target_geom)

            if intersection.is_empty:
                continue

            fraction = min(
                1.0,
                max(
                    0.0,
                    intersection.area / area,
                ),
            )

            if fraction <= 0:
                continue

            shaded_by.append((blocker_idx, fraction))

            if shaded_union is None:
                shaded_union = intersection
            else:
                shaded_union = shaded_union.union(intersection)

        if shaded_union is None:
            shaded_fraction = 0.0
        else:
            shaded_fraction = min(
                1.0,
                max(
                    0.0,
                    shaded_union.area / area,
                ),
            )

        direct = float(poa_direct.iloc[i])
        diffuse = float(poa_diffuse.iloc[i])

        
        effective_poa = direct * (1 - shaded_fraction) + diffuse

        dt_hours = config.step_minutes / 60.0

        energy = effective_poa * dt_hours / 1000.0

        records.append(
            {
                "building_index": target_idx,
                "timestamp": timestamp,
                "solar_elevation_deg": elevation,
                "solar_azimuth_deg": azimuth,
                "baseline_poa_w_m2": float(poa_global.iloc[i]),
                "direct_poa_w_m2": direct,
                "diffuse_poa_w_m2": diffuse,
                "shadow_fraction": shaded_fraction,
                "effective_poa_w_m2": effective_poa,
                "effective_energy_kwh_m2": energy,
                "direct_sun": int(shaded_fraction < 0.01),
            }
        )

        
        if shaded_by and direct > 0:
            total_shadow_energy = (
                direct * shaded_fraction * dt_hours / 1000.0
            )

            total_fraction = sum(x[1] for x in shaded_by)

            if total_fraction > 0:
                for blocker_idx, fraction in shaded_by:
                    share = fraction / total_fraction
                    contributor_energy[blocker_idx] = (
                        contributor_energy.get(blocker_idx, 0.0)
                        + total_shadow_energy * share
                    )

    hourly = pd.DataFrame(records)

    return hourly, contributor_energy






def minmax_score(value, low, high):
    if high <= low:
        return 50.0
    return float(np.clip((value - low) / (high - low) * 100, 0, 100))


def calculate_score(
    annual_irradiation,
    direct_sun_hours,
    shading_loss_pct,
    usable_area,
    orientation_deg,
):
    """
    Explainable 0-100 score.

    Components:
        35% annual irradiation
        20% direct sunlight duration
        25% shading resistance
        10% usable roof area
        10% orientation/tilt suitability

    The absolute normalization ranges are screening ranges, not bankable
    engineering thresholds.
    """

    irradiation_score = minmax_score(
        annual_irradiation,
        800,
        2200,
    )

    sun_score = minmax_score(
        direct_sun_hours,
        2,
        9,
    )

    shading_score = float(
        np.clip(100 - shading_loss_pct, 0, 100)
    )

    area_score = minmax_score(
        usable_area,
        20,
        1000,
    )

    
    
    diff = abs((orientation_deg - 180 + 180) % 360 - 180)
    orientation_score = float(
        np.clip(100 - diff / 90 * 100, 0, 100)
    )

    score = (
        WEIGHT_IRRADIATION * irradiation_score
        + WEIGHT_SUN_HOURS * sun_score
        + WEIGHT_SHADING * shading_score
        + WEIGHT_USABLE_AREA * area_score
        + WEIGHT_ORIENTATION * orientation_score
    )

    return float(np.clip(score, 0, 100))






def load_buildings(path):
    gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError("GeoJSON contains no building features.")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    gdf = gdf[gdf.geometry.notnull()].copy()

    
    gdf = gdf[
        gdf.geometry.geom_type.isin(
            ["Polygon", "MultiPolygon"]
        )
    ].copy()

    gdf = gdf[gdf.is_valid].copy()

    return gdf


def select_radius(gdf, lat, lon, radius_m):
    local = utm_crs(lat, lon)

    metric = gdf.to_crs(local)

    center = (
        gpd.GeoSeries(
            [Point(lon, lat)],
            crs="EPSG:4326",
        )
        .to_crs(local)
        .iloc[0]
    )

    metric["distance_m"] = metric.geometry.centroid.distance(center)

    selected = metric[
        metric["distance_m"] <= radius_m
    ].copy()

    return selected, local


def prepare_buildings(gdf):
    gdf = gdf.copy()

    gdf["building_uid"] = [
        str(x)
        for x in (
            gdf["id"]
            if "id" in gdf.columns
            else gdf.index
        )
    ]

    gdf["footprint_area_m2"] = gdf.geometry.area
    gdf["perimeter_m"] = gdf.geometry.length

    gdf["building_class"] = gdf.apply(
        building_class,
        axis=1,
    )

    heights = []
    sources = []

    for _, row in gdf.iterrows():
        h, source = estimate_height(
            row,
            float(row["footprint_area_m2"]),
        )
        heights.append(h)
        sources.append(source)

    gdf["height_m"] = heights
    gdf["height_source"] = sources

    
    gdf["roof_area_m2"] = gdf["footprint_area_m2"]

    gdf["usable_roof_area_m2"] = (
        gdf["roof_area_m2"] * USABLE_ROOF_FRACTION
    )

    gdf["pv_capacity_kw"] = (
        gdf["usable_roof_area_m2"]
        / PV_MODULE_AREA_M2_PER_KW
    )

    return gdf


def run_analysis(
    geojson,
    lat,
    lon,
    radius,
    output_dir,
    config,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/8] Loading buildings...")
    gdf = load_buildings(geojson)

    print("[2/8] Selecting requested radius...")
    buildings, local_crs = select_radius(
        gdf,
        lat,
        lon,
        radius,
    )

    if config.max_buildings is not None:
        buildings = buildings.head(config.max_buildings).copy()

    if buildings.empty:
        raise RuntimeError(
            "No buildings found in the requested radius."
        )

    print(
        f"      Buildings selected: {len(buildings):,}"
    )

    buildings = prepare_buildings(buildings)
    buildings = buildings.reset_index(drop=True)

    print("[3/8] Computing solar position and clear-sky irradiance...")
    times, solpos, clearsky = solar_time_series(
        lat,
        lon,
        config.step_minutes,
    )

    print("[4/8] Finding optimum solar angle...")
    optimum = optimize_panel_angle(
        solpos,
        clearsky,
        fast=config.fast_mode,
    )

    print(
        f"      Optimal baseline tilt: "
        f"{optimum['tilt_deg']:.1f}°"
    )
    print(
        f"      Optimal baseline azimuth: "
        f"{optimum['azimuth_deg']:.1f}°"
    )

    
    print("[5/8] Building spatial index...")
    geometries = list(buildings.geometry)
    heights = buildings["height_m"].astype(float).tolist()
    tree = make_tree(geometries)

    candidate_cache = {}

    
    
    
    for idx in range(len(buildings)):
        candidate_cache[idx] = candidate_blockers(
            buildings.geometry.iloc[idx],
            heights[idx],
            geometries,
            heights,
            tree,
            config.candidate_radius_m,
        )

    hourly_parts = []
    contributor_rows = []

    print("[6/8] Running building shadow simulation...")

    for idx in range(len(buildings)):
        if idx % 25 == 0:
            print(
                f"      {idx + 1:,}/{len(buildings):,}"
            )

        hourly, contributors = hourly_shadow_for_target(
            idx,
            buildings,
            tree,
            candidate_cache,
            solpos,
            clearsky,
            optimum["tilt_deg"],
            optimum["azimuth_deg"],
            config,
        )

        hourly_parts.append(hourly)

        target_uid = buildings.iloc[idx]["building_uid"]

        for blocker_idx, loss_kwh_m2 in contributors.items():
            contributor_rows.append(
                {
                    "target_building_uid": target_uid,
                    "blocker_building_uid":
                        buildings.iloc[blocker_idx]["building_uid"],
                    "estimated_shading_loss_kwh_m2":
                        loss_kwh_m2,
                }
            )

    hourly_all = pd.concat(
        hourly_parts,
        ignore_index=True,
    )

    print("[7/8] Aggregating annual results...")

    
    baseline_poa = panel_poa(
        optimum["tilt_deg"],
        optimum["azimuth_deg"],
        solpos,
        clearsky,
    )

    baseline_annual = (
        float(baseline_poa.sum())
        * config.step_minutes
        / 60
        / 1000
    )

    summary_rows = []

    for idx in range(len(buildings)):
        target = buildings.iloc[idx]

        h = hourly_all[
            hourly_all["building_index"] == idx
        ].copy()

        if h.empty:
            continue

        effective_annual = float(
            h["effective_energy_kwh"].sum()
        )

        baseline_annual_here = float(
            h["baseline_poa_w_m2"].sum()
            * config.step_minutes
            / 60
            / 1000
        )

        shading_loss_pct = (
            max(
                0.0,
                1
                - effective_annual
                / max(baseline_annual_here, 1e-9),
            )
            * 100
        )

        direct_sun_hours = float(
            h["direct_sun"].sum()
            * config.step_minutes
            / 60
        )

        
        peak_idx = h["effective_poa_w_m2"].idxmax()
        peak_row = h.loc[peak_idx]

        peak_time = pd.Timestamp(
            peak_row["timestamp"]
        )

        peak_time_str = peak_time.strftime("%H:%M")

        
        annual_irradiation = effective_annual

        usable_area = float(
            target["usable_roof_area_m2"]
        )

        pv_capacity = float(
            target["pv_capacity_kw"]
        )

        annual_pv_energy = (
            usable_area
            * annual_irradiation
            * PV_EFFICIENCY
            * (1 - SYSTEM_LOSS)
            / 1000
        )

        
        score = calculate_score(
            annual_irradiation,
            direct_sun_hours / 365.0,
            shading_loss_pct,
            usable_area,
            optimum["azimuth_deg"],
        )

        if score >= 90:
            grade = "exceptional"
        elif score >= 75:
            grade = "excellent"
        elif score >= 60:
            grade = "good"
        elif score >= 40:
            grade = "moderate"
        elif score >= 20:
            grade = "poor"
        else:
            grade = "very_poor"

        summary_rows.append(
            {
                "building_uid": target["building_uid"],
                "building_class": target["building_class"],
                "footprint_area_m2":
                    float(target["footprint_area_m2"]),
                "height_m":
                    float(target["height_m"]),
                "height_source":
                    target["height_source"],
                "roof_area_m2":
                    float(target["roof_area_m2"]),
                "usable_roof_area_m2":
                    usable_area,
                "pv_capacity_kw":
                    pv_capacity,
                "optimal_panel_tilt_deg":
                    optimum["tilt_deg"],
                "optimal_panel_azimuth_deg":
                    optimum["azimuth_deg"],
                "peak_sun_time":
                    peak_time_str,
                "peak_sun_elevation_deg":
                    float(peak_row["solar_elevation_deg"]),
                "peak_sun_azimuth_deg":
                    float(peak_row["solar_azimuth_deg"]),
                "direct_sun_hours_year":
                    direct_sun_hours,
                "direct_sun_hours_day":
                    direct_sun_hours / 365.0,
                "annual_solar_irradiation_kwh_m2":
                    annual_irradiation,
                "annual_shading_loss_pct":
                    shading_loss_pct,
                "annual_pv_generation_kwh":
                    annual_pv_energy,
                "solar_score":
                    score,
                "solar_grade":
                    grade,
            }
        )

    summary = pd.DataFrame(summary_rows)

    
    
    

    contributor_df = pd.DataFrame(contributor_rows)

    if not contributor_df.empty:
        contributor_df = contributor_df.sort_values(
            [
                "target_building_uid",
                "estimated_shading_loss_kwh_m2",
            ],
            ascending=[True, False],
        )

        top = (
            contributor_df
            .groupby("target_building_uid")
            .head(5)
        )

        top_lists = {}

        for uid, group in top.groupby(
            "target_building_uid"
        ):
            vals = []
            for _, r in group.iterrows():
                vals.append(
                    f"{r['blocker_building_uid']}="
                    f"{r['estimated_shading_loss_kwh_m2']:.2f}"
                )
            top_lists[uid] = ";".join(vals)

        summary["top_shading_buildings"] = (
            summary["building_uid"]
            .map(top_lists)
            .fillna("")
        )

    
    
    

    result = buildings.merge(
        summary,
        on=[
            "building_uid",
            "building_class",
            "footprint_area_m2",
            "height_m",
            "height_source",
            "roof_area_m2",
            "usable_roof_area_m2",
            "pv_capacity_kw",
        ],
        how="left",
        suffixes=("", "_summary"),
    )

    
    if "distance_m" in result.columns:
        result = result.drop(columns=["distance_m"])

    result_wgs84 = result.to_crs("EPSG:4326")

    
    
    

    geojson_out = output_dir / "buildings_solar.geojson"
    csv_out = output_dir / "buildings_solar.csv"
    hourly_out = output_dir / "hourly_solar.csv"
    shadows_out = output_dir / "shadow_events.csv"

    result_wgs84.to_file(
        geojson_out,
        driver="GeoJSON",
    )

    result_wgs84.drop(
        columns="geometry"
    ).to_csv(
        csv_out,
        index=False,
    )

    hourly_export = hourly_all.merge(
        buildings[
            [
                "building_uid",
                "building_class",
                "height_m",
            ]
        ],
        left_on="building_index",
        right_index=True,
        how="left",
    )

    hourly_export.to_csv(
        hourly_out,
        index=False,
    )

    contributor_df.to_csv(
        shadows_out,
        index=False,
    )

    print("\n==============================")
    print("SOLAR ANALYSIS COMPLETE")
    print("==============================")
    print(
        f"Buildings: {len(result_wgs84):,}"
    )
    print(
        f"Optimal tilt: "
        f"{optimum['tilt_deg']:.1f}°"
    )
    print(
        f"Optimal azimuth: "
        f"{optimum['azimuth_deg']:.1f}°"
    )
    print(
        f"Total usable roof: "
        f"{result_wgs84['usable_roof_area_m2'].sum():,.0f} m²"
    )
    print(
        f"Potential PV: "
        f"{result_wgs84['pv_capacity_kw'].sum():,.1f} kWp"
    )
    print(
        f"Estimated annual generation: "
        f"{result_wgs84['annual_pv_generation_kwh'].sum():,.0f} kWh"
    )
    print("\nOutputs:")
    print(f"  {geojson_out}")
    print(f"  {csv_out}")
    print(f"  {hourly_out}")
    print(f"  {shadows_out}")

    return result_wgs84


def cli():
    parser = argparse.ArgumentParser(
        description="Building-level solar and urban-shadow analysis."
    )

    parser.add_argument(
        "--geojson",
        required=True,
        help="Input building GeoJSON.",
    )

    parser.add_argument(
        "--lat",
        type=float,
        required=True,
        help="Center latitude.",
    )

    parser.add_argument(
        "--lon",
        type=float,
        required=True,
        help="Center longitude.",
    )

    parser.add_argument(
        "--radius",
        type=float,
        required=True,
        help="Analysis radius in meters.",
    )

    parser.add_argument(
        "--output",
        default="solar_output",
        help="Output directory.",
    )

    parser.add_argument(
        "--step-minutes",
        type=int,
        default=60,
        choices=[15, 30, 60],
        help="Solar/shadow timestep.",
    )

    parser.add_argument(
        "--candidate-radius",
        type=float,
        default=500,
        help="Maximum blocker search radius in meters.",
    )

    parser.add_argument(
        "--max-buildings",
        type=int,
        default=None,
        help="Limit buildings for testing.",
    )

    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use coarser optimum-angle search.",
    )

    args = parser.parse_args()

    config = SolarConfig(
        step_minutes=args.step_minutes,
        candidate_radius_m=args.candidate_radius,
        max_buildings=args.max_buildings,
        fast_mode=args.fast,
    )

    run_analysis(
        geojson=args.geojson,
        lat=args.lat,
        lon=args.lon,
        radius=args.radius,
        output_dir=args.output,
        config=config,
    )


if __name__ == "__main__":
    cli()
