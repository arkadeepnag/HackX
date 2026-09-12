"""
Rooftop addressable-capacity heatmap with cadastral enrichment.

Two aggregation modes:

  grid      -- equal-area cells over the cluster. Fast, always available,
               good for a continuous heat surface.
  cadastral -- aggregates to real plot boundaries (khasra / survey / plot
               polygons) and carries the parcel attributes through. This is
               what turns a pretty raster into something a territory
               planner can act on, because a sales team visits a *plot*,
               not a 200 m grid square.

Both emit GeoJSON so any map library renders them directly.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from app.engines.building_engine import utm_crs

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Cadastral attribute names vary wildly between state portals, so we probe
# a list of aliases rather than demanding one schema.
CADASTRAL_ALIASES = {
    "parcel_id": ["parcel_id", "plot_id", "khasra", "khasra_no", "survey_no",
                  "survey_number", "gis_id", "plot_no", "id"],
    "land_use": ["land_use", "landuse", "use", "zone_use", "category",
                 "land_use_type"],
    "zone": ["zone", "ward", "zone_name", "planning_zone", "sector"],
    "owner_type": ["owner_type", "ownership", "owner", "tenure"],
    "plot_area_m2": ["plot_area_m2", "area_sqm", "plot_area", "area"],
}


def _first_alias(gdf: gpd.GeoDataFrame, field: str):
    for alias in CADASTRAL_ALIASES[field]:
        for column in gdf.columns:
            if column.lower() == alias:
                return column
    return None


def _percentile_bands(values: list[float]) -> list[dict]:
    """
    Quintile bands for map colouring. Percentile-based rather than fixed
    thresholds, because absolute kW ranges differ by an order of magnitude
    between a residential colony and an industrial estate.
    """
    clean = [v for v in values if v and v > 0]
    if not clean:
        return []
    cuts = np.percentile(clean, [20, 40, 60, 80, 100])
    labels = ["very_low", "low", "medium", "high", "very_high"]
    bands, lower = [], 0.0
    for label, cut in zip(labels, cuts):
        bands.append({
            "band": label,
            "min_kw": round(float(lower), 2),
            "max_kw": round(float(cut), 2),
        })
        lower = cut
    return bands


def _band_for(value: float, bands: list[dict]) -> str:
    for band in bands:
        if value <= band["max_kw"]:
            return band["band"]
    return bands[-1]["band"] if bands else "very_low"


def _capacity_frame(
    buildings: gpd.GeoDataFrame,
    solar_results: pd.DataFrame | None,
) -> gpd.GeoDataFrame:
    """
    Attach per-building addressable kW. Uses solar-engine output when it is
    available (shading-adjusted, the honest number) and falls back to the
    geometric roof estimate otherwise.
    """
    gdf = buildings.copy()

    if solar_results is not None and not solar_results.empty:
        columns = ["building_uid", "pv_capacity_kw", "annual_pv_generation_kwh"]
        if "annual_shading_loss_pct" in solar_results.columns:
            columns.append("annual_shading_loss_pct")
        merged = gdf.merge(
            solar_results[columns], on="building_uid",
            how="left", suffixes=("", "_solar"),
        )
        if "pv_capacity_kw_solar" in merged.columns:
            merged["addressable_kw"] = merged["pv_capacity_kw_solar"].fillna(
                merged["pv_capacity_kw"]
            )
        else:
            merged["addressable_kw"] = merged["pv_capacity_kw"]
        gdf = merged
    else:
        gdf["addressable_kw"] = gdf["pv_capacity_kw"]
        gdf["annual_pv_generation_kwh"] = np.nan
        gdf["annual_shading_loss_pct"] = np.nan

    if "annual_shading_loss_pct" not in gdf.columns:
        gdf["annual_shading_loss_pct"] = np.nan
    if "annual_pv_generation_kwh" not in gdf.columns:
        gdf["annual_pv_generation_kwh"] = np.nan

    return gdf


def grid_heatmap(
    buildings: gpd.GeoDataFrame,
    latitude: float,
    longitude: float,
    solar_results: pd.DataFrame | None = None,
    cell_size_m: float = 200.0,
    min_buildings_per_cell: int = 1,
) -> dict:
    """Equal-area grid aggregation. Returns a GeoJSON FeatureCollection."""
    metric = utm_crs(latitude, longitude)
    gdf = _capacity_frame(buildings, solar_results).to_crs(metric)

    minx, miny, maxx, maxy = gdf.total_bounds
    if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)):
        return {"type": "FeatureCollection", "features": [], "summary": {}}

    centroids = gdf.geometry.centroid
    col = ((centroids.x - minx) // cell_size_m).astype(int)
    row = ((centroids.y - miny) // cell_size_m).astype(int)
    gdf["_col"], gdf["_row"] = col, row

    aggregated = gdf.groupby(["_col", "_row"]).agg(
        building_count=("building_uid", "count"),
        total_addressable_kw=("addressable_kw", "sum"),
        mean_addressable_kw=("addressable_kw", "mean"),
        total_roof_area_m2=("usable_roof_area_m2", "sum"),
        mean_shading_loss_pct=("annual_shading_loss_pct", "mean"),
        total_annual_generation_kwh=("annual_pv_generation_kwh", "sum"),
    ).reset_index()

    aggregated = aggregated[
        aggregated.building_count >= min_buildings_per_cell
    ]

    bands = _percentile_bands(aggregated.total_addressable_kw.tolist())
    cell_area_km2 = (cell_size_m ** 2) / 1e6

    geometries, records = [], []
    for _, cell in aggregated.iterrows():
        x0 = minx + cell._col * cell_size_m
        y0 = miny + cell._row * cell_size_m
        geometries.append(box(x0, y0, x0 + cell_size_m, y0 + cell_size_m))

        total_kw = float(cell.total_addressable_kw)
        records.append({
            "cell_id": f"C{int(cell._col)}_{int(cell._row)}",
            "building_count": int(cell.building_count),
            "total_addressable_kw": round(total_kw, 2),
            "mean_addressable_kw": round(float(cell.mean_addressable_kw), 2),
            "kw_per_km2": round(total_kw / cell_area_km2, 1),
            "total_roof_area_m2": round(float(cell.total_roof_area_m2), 1),
            "mean_shading_loss_pct": (
                round(float(cell.mean_shading_loss_pct), 2)
                if pd.notna(cell.mean_shading_loss_pct) else None
            ),
            "total_annual_generation_kwh": (
                round(float(cell.total_annual_generation_kwh), 1)
                if pd.notna(cell.total_annual_generation_kwh) else None
            ),
            "intensity_band": _band_for(total_kw, bands),
        })

    cells = gpd.GeoDataFrame(records, geometry=geometries, crs=metric)
    cells = cells.to_crs("EPSG:4326")

    return _to_geojson(cells, {
        "mode": "grid",
        "cell_size_m": cell_size_m,
        "cell_count": len(cells),
        "building_count": int(gdf.shape[0]),
        "total_addressable_kw": round(
            float(gdf["addressable_kw"].sum()), 2
        ),
        "total_addressable_mw": round(
            float(gdf["addressable_kw"].sum()) / 1000.0, 3
        ),
        "bands": bands,
    })


def cadastral_heatmap(
    buildings: gpd.GeoDataFrame,
    latitude: float,
    longitude: float,
    cadastral_source: str,
    solar_results: pd.DataFrame | None = None,
    min_kw: float = 0.0,
) -> dict:
    """
    Aggregate addressable capacity to cadastral parcels.

    Each output feature is a real plot with its identifier, land use and
    zone carried through, so the result is a call list with boundaries
    rather than an anonymous heat surface. Buildings are matched to the
    parcel containing their centroid, which avoids double-counting a shed
    that straddles a boundary line.
    """
    metric = utm_crs(latitude, longitude)

    parcels = gpd.read_file(cadastral_source)
    if parcels.crs is None:
        parcels = parcels.set_crs("EPSG:4326")
    parcels = parcels[parcels.geometry.notna()].copy()
    parcels = parcels[
        parcels.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    ].copy()
    if parcels.empty:
        raise ValueError("Cadastral dataset contains no usable polygons.")

    parcels = parcels.to_crs(metric)

    # Normalise whatever the source calls its columns.
    resolved = {
        field: _first_alias(parcels, field)
        for field in CADASTRAL_ALIASES
    }
    parcels["_parcel_id"] = (
        parcels[resolved["parcel_id"]].astype(str)
        if resolved["parcel_id"] else
        [f"P{i}" for i in range(len(parcels))]
    )
    for field in ("land_use", "zone", "owner_type"):
        column = resolved[field]
        parcels[f"_{field}"] = (
            parcels[column].astype(str) if column else None
        )
    parcels["_plot_area_m2"] = (
        pd.to_numeric(parcels[resolved["plot_area_m2"]], errors="coerce")
        if resolved["plot_area_m2"] else parcels.geometry.area
    )

    gdf = _capacity_frame(buildings, solar_results).to_crs(metric)
    points = gdf.copy()
    points["geometry"] = points.geometry.centroid

    joined = gpd.sjoin(
        points,
        parcels[[
            "_parcel_id", "_land_use", "_zone", "_owner_type",
            "_plot_area_m2", "geometry",
        ]],
        how="inner",
        predicate="within",
    )

    if joined.empty:
        return {
            "type": "FeatureCollection", "features": [],
            "summary": {
                "mode": "cadastral", "parcel_count": 0,
                "unmatched_buildings": int(len(gdf)),
                "warning": (
                    "No building centroid fell inside a cadastral parcel. "
                    "Check that both layers cover the same area."
                ),
            },
        }

    aggregated = joined.groupby("_parcel_id").agg(
        building_count=("building_uid", "count"),
        total_addressable_kw=("addressable_kw", "sum"),
        max_building_kw=("addressable_kw", "max"),
        total_roof_area_m2=("usable_roof_area_m2", "sum"),
        mean_shading_loss_pct=("annual_shading_loss_pct", "mean"),
        total_annual_generation_kwh=("annual_pv_generation_kwh", "sum"),
        land_use=("_land_use", "first"),
        zone=("_zone", "first"),
        owner_type=("_owner_type", "first"),
        plot_area_m2=("_plot_area_m2", "first"),
    ).reset_index()

    aggregated = aggregated[aggregated.total_addressable_kw >= min_kw]
    bands = _percentile_bands(aggregated.total_addressable_kw.tolist())

    geometry_by_id = parcels.set_index("_parcel_id").geometry
    records, geometries = [], []

    for _, parcel in aggregated.iterrows():
        parcel_id = parcel._parcel_id
        if parcel_id not in geometry_by_id.index:
            continue
        geometry = geometry_by_id.loc[parcel_id]
        if hasattr(geometry, "iloc"):       # duplicate parcel ids
            geometry = geometry.iloc[0]

        total_kw = float(parcel.total_addressable_kw)
        plot_area = float(parcel.plot_area_m2 or 0)

        records.append({
            "parcel_id": parcel_id,
            "land_use": parcel.land_use,
            "zone": parcel.zone,
            "owner_type": parcel.owner_type,
            "plot_area_m2": round(plot_area, 1),
            "building_count": int(parcel.building_count),
            "total_addressable_kw": round(total_kw, 2),
            "largest_roof_kw": round(float(parcel.max_building_kw), 2),
            "total_roof_area_m2": round(float(parcel.total_roof_area_m2), 1),
            "roof_coverage_pct": (
                round(float(parcel.total_roof_area_m2) / plot_area * 100, 1)
                if plot_area > 0 else None
            ),
            "kw_per_1000_sqm_plot": (
                round(total_kw / (plot_area / 1000.0), 2)
                if plot_area > 0 else None
            ),
            "mean_shading_loss_pct": (
                round(float(parcel.mean_shading_loss_pct), 2)
                if pd.notna(parcel.mean_shading_loss_pct) else None
            ),
            "total_annual_generation_kwh": (
                round(float(parcel.total_annual_generation_kwh), 1)
                if pd.notna(parcel.total_annual_generation_kwh) else None
            ),
            "intensity_band": _band_for(total_kw, bands),
            # A single large parcel is one negotiation; many small ones on
            # the same kW is a campaign. Sales needs to tell them apart.
            "acquisition_profile": (
                "single_anchor" if parcel.building_count <= 2
                else "multi_roof_campaign"
            ),
        })
        geometries.append(geometry)

    cells = gpd.GeoDataFrame(records, geometry=geometries, crs=metric)
    cells = cells.to_crs("EPSG:4326")

    matched = int(joined.shape[0])
    by_use = (
        aggregated.groupby("land_use").total_addressable_kw.sum()
        .sort_values(ascending=False).round(2).to_dict()
        if aggregated.land_use.notna().any() else {}
    )

    return _to_geojson(cells, {
        "mode": "cadastral",
        "parcel_count": len(cells),
        "matched_buildings": matched,
        "unmatched_buildings": int(len(gdf) - matched),
        "total_addressable_kw": round(
            float(aggregated.total_addressable_kw.sum()), 2
        ),
        "total_addressable_mw": round(
            float(aggregated.total_addressable_kw.sum()) / 1000.0, 3
        ),
        "addressable_kw_by_land_use": by_use,
        "resolved_columns": resolved,
        "bands": bands,
    })


def _to_geojson(gdf: gpd.GeoDataFrame, summary: dict) -> dict:
    payload = json.loads(gdf.to_json())
    payload["summary"] = summary

    ranked = sorted(
        payload["features"],
        key=lambda f: f["properties"].get("total_addressable_kw", 0),
        reverse=True,
    )
    payload["top_targets"] = [f["properties"] for f in ranked[:20]]
    return payload