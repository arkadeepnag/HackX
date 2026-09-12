from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pvlib

from shapely.affinity import translate
from shapely.strtree import STRtree


def representative_times(
    latitude: float,
    longitude: float
):

    rows = []

    for month in range(1, 13):

        times = pd.date_range(
            f"2026-{month:02d}-15 06:00",
            f"2026-{month:02d}-15 18:00",
            freq="60min",
            tz="Asia/Kolkata"
        )

        rows.extend(
            times.tolist()
        )

    times = pd.DatetimeIndex(rows)

    location = pvlib.location.Location(
        latitude,
        longitude,
        tz="Asia/Kolkata"
    )

    solar_position = (
        location
        .get_solarposition(times)
    )

    clearsky = (
        location
        .get_clearsky(
            times,
            model="ineichen"
        )
    )

    return (
        times,
        solar_position,
        clearsky
    )


def plane_of_array(
    tilt,
    azimuth,
    solar_position,
    clearsky
):

    irradiance = (
        pvlib.irradiance
        .get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            dni=clearsky["dni"],
            ghi=clearsky["ghi"],
            dhi=clearsky["dhi"],
            solar_zenith=(
                solar_position[
                    "apparent_zenith"
                ]
            ),
            solar_azimuth=(
                solar_position["azimuth"]
            )
        )
    )

    return (
        irradiance["poa_global"].clip(
            lower=0
        ),
        irradiance["poa_direct"].clip(
            lower=0
        ),
        irradiance["poa_diffuse"].clip(
            lower=0
        )
    )


def optimize_panel_angle(
    solar_position,
    clearsky
):

    best = None

    for tilt in range(10, 41, 5):

        for azimuth in range(
            135,
            226,
            15
        ):

            poa, _, _ = (
                plane_of_array(
                    tilt,
                    azimuth,
                    solar_position,
                    clearsky
                )
            )

            energy = float(
                poa.sum()
            )

            if (
                best is None
                or energy > best["energy"]
            ):
                best = {
                    "energy": energy,
                    "tilt_deg": float(tilt),
                    "azimuth_deg": float(
                        azimuth
                    )
                }

    return best


def shadow_vector(
    sun_azimuth,
    sun_elevation,
    blocker_height,
    target_height
):

    height_difference = (
        blocker_height
        - target_height
    )

    if height_difference <= 0:
        return None

    if sun_elevation <= 2:
        return None

    length = (
        height_difference
        / math.tan(
            math.radians(
                sun_elevation
            )
        )
    )

    azimuth = math.radians(
        sun_azimuth
    )

    return (
        -math.sin(azimuth) * length,
        -math.cos(azimuth) * length
    )


def calculate_shadow_loss(
    target_index,
    buildings,
    tree,
    geometries,
    heights,
    solar_position,
    direct_poa,
    diffuse_poa
):

    target = buildings.iloc[
        target_index
    ]

    target_geometry = (
        target.geometry
    )

    target_height = float(
        target.height_m
    )

    target_area = max(
        float(
            target_geometry.area
        ),
        0.01
    )

    candidate_indices = [
        int(index)
        for index in tree.query(
            target_geometry.buffer(250)
        )
        if int(index) != target_index
        and heights[int(index)]
        > target_height
    ]

    monthly_days = np.array(
        [
            31, 28, 31, 30,
            31, 30, 31, 31,
            30, 31, 30, 31
        ],
        dtype=float
    )

    effective_values = []
    baseline_values = []
    direct_hours = 0

    for index in range(
        len(solar_position)
    ):

        elevation = float(
            solar_position.iloc[
                index
            ]["apparent_elevation"]
        )

        azimuth = float(
            solar_position.iloc[
                index
            ]["azimuth"]
        )

        if elevation < 2:
            continue

        shadow_union = None

        for blocker_index in (
            candidate_indices[:80]
        ):

            vector = shadow_vector(
                azimuth,
                elevation,
                heights[
                    blocker_index
                ],
                target_height
            )

            if vector is None:
                continue

            shadow = translate(
                geometries[
                    blocker_index
                ],
                xoff=vector[0],
                yoff=vector[1]
            )

            intersection = (
                shadow
                .intersection(
                    target_geometry
                )
            )

            if intersection.is_empty:
                continue

            if shadow_union is None:
                shadow_union = (
                    intersection
                )
            else:
                shadow_union = (
                    shadow_union.union(
                        intersection
                    )
                )

        if shadow_union is None:
            shadow_fraction = 0.0
        else:
            shadow_fraction = min(
                1.0,
                max(
                    0.0,
                    shadow_union.area
                    / target_area
                )
            )

        direct = float(
            direct_poa.iloc[index]
        )

        diffuse = float(
            diffuse_poa.iloc[index]
        )

        baseline = (
            direct + diffuse
        )

        effective = (
            direct
            * (1 - shadow_fraction)
            + diffuse
        )

        if shadow_fraction < 0.01:
            direct_hours += 1

        effective_values.append(
            effective
        )

        baseline_values.append(
            baseline
        )

    if not effective_values:
        return {
            "annual_irradiation_kwh_m2": 0.0,
            "annual_shading_loss_pct": 0.0,
            "direct_sun_hours_year": 0.0
        }

    months = []

    for timestamp in solar_position.index:
        if timestamp.hour >= 6:
            months.append(
                timestamp.month
            )

    effective_array = np.array(
        effective_values
    )

    baseline_array = np.array(
        baseline_values
    )

    if len(months) != len(
        effective_array
    ):
        months = [
            6
        ] * len(effective_array)

    weights = np.array(
        [
            monthly_days[
                month - 1
            ]
            for month in months
        ]
    )

    effective_annual = (
        np.sum(
            effective_array
            * weights
        )
        / 1000.0
    )

    baseline_annual = (
        np.sum(
            baseline_array
            * weights
        )
        / 1000.0
    )

    shading_loss = max(
        0.0,
        (
            1
            - effective_annual
            / max(
                baseline_annual,
                1e-9
            )
        )
        * 100
    )

    direct_hours_year = (
        direct_hours
        * 365
        / 12
    )

    return {
        "annual_irradiation_kwh_m2":
            float(effective_annual),
        "annual_shading_loss_pct":
            float(shading_loss),
        "direct_sun_hours_year":
            float(direct_hours_year)
    }


def analyze(
    buildings,
    latitude,
    longitude,
    resource,
    detail_top_n=25
):

    (
        times,
        solar_position,
        clearsky
    ) = representative_times(
        latitude,
        longitude
    )

    optimum = optimize_panel_angle(
        solar_position,
        clearsky
    )

    baseline_poa, direct_poa, diffuse_poa = (
        plane_of_array(
            optimum["tilt_deg"],
            optimum["azimuth_deg"],
            solar_position,
            clearsky
        )
    )

    monthly_days = np.array(
        [
            31, 28, 31, 30,
            31, 30, 31, 31,
            30, 31, 30, 31
        ],
        dtype=float
    )

    weights = np.array(
        [
            monthly_days[
                timestamp.month - 1
            ]
            for timestamp in times
        ]
    )

    baseline_annual = float(
        np.sum(
            baseline_poa.values
            * weights
        )
        / 1000
    )

    geometries = list(
        buildings.geometry
    )

    heights = (
        buildings["height_m"]
        .astype(float)
        .tolist()
    )

    tree = STRtree(
        geometries
    )

    detailed_indices = set(
        buildings
        .sort_values(
            "usable_roof_area_m2",
            ascending=False
        )
        .head(detail_top_n)
        .index
        .tolist()
    )

    rows = []

    resource_annual = float(
        resource[
            "annual_irradiation_kwh_m2"
        ]
    )

    resource_ratio = (
        resource_annual
        / max(
            baseline_annual,
            1e-9
        )
    )

    for index, building in (
        buildings.iterrows()
    ):

        if index in detailed_indices:

            shadow = calculate_shadow_loss(
                index,
                buildings,
                tree,
                geometries,
                heights,
                solar_position,
                direct_poa,
                diffuse_poa
            )

            effective_annual = (
                shadow[
                    "annual_irradiation_kwh_m2"
                ]
            )

            shading_loss = (
                shadow[
                    "annual_shading_loss_pct"
                ]
            )

            direct_sun_hours = (
                shadow[
                    "direct_sun_hours_year"
                ]
            )

            shadow_method = (
                "representative_geometry"
            )

        else:

            nearby = tree.query(
                building.geometry.buffer(
                    150
                )
            )

            risk = 0.0

            for nearby_index in nearby:

                nearby_index = int(
                    nearby_index
                )

                if nearby_index == index:
                    continue

                distance = (
                    building.geometry
                    .distance(
                        geometries[
                            nearby_index
                        ]
                    )
                )

                if (
                    heights[
                        nearby_index
                    ]
                    > heights[index]
                    and distance < 150
                ):
                    risk += min(
                        0.08,
                        (
                            heights[
                                nearby_index
                            ]
                            - heights[index]
                        )
                        / (
                            max(
                                distance,
                                5
                            ) * 20
                        )
                    )

            shading_loss = min(
                45.0,
                risk * 100
            )

            effective_annual = (
                baseline_annual
                * (
                    1
                    - shading_loss
                    / 100
                )
            )

            direct_sun_hours = (
                4380
                * (
                    1
                    - shading_loss
                    / 100
                )
            )

            shadow_method = (
                "screening_proxy"
            )

        solar_irradiation = (
            effective_annual
            * resource_ratio
        )

        usable_area = float(
            building[
                "usable_roof_area_m2"
            ]
        )

        pv_capacity = float(
            building["pv_capacity_kw"]
        )

        annual_generation = (
            usable_area
            * solar_irradiation
            * 0.20
            * 0.86
            / 1000
        )

        rows.append({
            "building_uid":
                building["building_uid"],

            "latitude":
                float(
                    building["latitude"]
                )
                if "latitude" in building
                else None,

            "longitude":
                float(
                    building["longitude"]
                )
                if "longitude" in building
                else None,

            "building_class":
                building["building_class"],

            "footprint_area_m2":
                float(
                    building[
                        "footprint_area_m2"
                    ]
                ),

            "height_m":
                float(
                    building["height_m"]
                ),

            "height_source":
                building[
                    "height_source"
                ],

            "usable_roof_area_m2":
                usable_area,

            "pv_capacity_kw":
                pv_capacity,

            "optimal_panel_tilt_deg":
                optimum["tilt_deg"],

            "optimal_panel_azimuth_deg":
                optimum[
                    "azimuth_deg"
                ],

            "annual_solar_irradiation_kwh_m2":
                float(
                    solar_irradiation
                ),

            "direct_sun_hours_year":
                float(
                    direct_sun_hours
                ),

            "annual_shading_loss_pct":
                float(
                    shading_loss
                ),

            "annual_pv_generation_kwh":
                float(
                    annual_generation
                ),

            "shadow_method":
                shadow_method
        })

    return (
        pd.DataFrame(rows),
        optimum
    )