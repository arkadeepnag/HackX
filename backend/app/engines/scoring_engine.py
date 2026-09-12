from __future__ import annotations

import numpy as np


def clamp(
    value,
    minimum=0,
    maximum=100
):

    return float(
        np.clip(
            value,
            minimum,
            maximum
        )
    )


def normalize(
    value,
    low,
    high
):

    if high <= low:
        return 50.0

    return clamp(
        (
            value - low
        )
        / (
            high - low
        )
        * 100
    )


def calculate_solar_score(
    annual_irradiation_kwh_m2,
    direct_sun_hours_year,
    shading_loss_pct,
    usable_roof_area_m2,
    tariff_rs_kwh,
    grid_reliability_score=50
):

    irradiation_score = normalize(
        annual_irradiation_kwh_m2,
        1000,
        2100
    )

    sunlight_score = normalize(
        direct_sun_hours_year / 365,
        2,
        9
    )

    shading_score = clamp(
        100 - shading_loss_pct
    )

    roof_score = normalize(
        usable_roof_area_m2,
        20,
        1000
    )

    tariff_score = normalize(
        tariff_rs_kwh,
        3,
        12
    )

    reliability_score = clamp(
        grid_reliability_score
    )

    score = (
        irradiation_score * 0.30
        + sunlight_score * 0.15
        + shading_score * 0.20
        + roof_score * 0.15
        + tariff_score * 0.10
        + reliability_score * 0.10
    )

    return clamp(score)


def calculate_propensity_score(
    solar_score,
    payback_years,
    irr_pct,
    tariff_rs_kwh,
    outage_hours,
    owned_roof,
    bill_count,
    roof_photo_uploaded,
    sla
):

    solar_component = (
        solar_score
    )

    payback_component = clamp(
        100
        - (
            payback_years
            / max(
                sla.max_payback_years,
                1
            )
            * 50
        )
    )

    irr_component = clamp(
        irr_pct
        / max(
            sla.minimum_irr_pct,
            1
        )
        * 50
    )

    tariff_component = normalize(
        tariff_rs_kwh,
        3,
        12
    )

    outage_component = clamp(
        outage_hours
        / max(
            sla.outage_hours_opportunity,
            1
        )
        * 50
    )

    readiness = 0

    if owned_roof is True:
        readiness += 20

    if bill_count >= 3:
        readiness += 10

    if roof_photo_uploaded:
        readiness += 10

    score = (
        solar_component * 0.40
        + payback_component * 0.20
        + irr_component * 0.10
        + tariff_component * 0.10
        + outage_component * 0.10
        + min(readiness, 40)
    )

    return clamp(score)


def determine_routing_class(
    propensity_score,
    financing_score,
    propensity_bar=55.0,
    financing_bar=50.0
):
    """
    Map a lead onto the dual-axis quadrant.

    Previously the thresholds left a hole: a lead at propensity 62 with a
    financing score of 100 matched no rule and fell through to
    "discard_or_nurture" -- discarding a financeable, above-bar lead. The
    quadrant is now a clean two-way split on each axis, so every point
    lands in exactly one class.
    """

    strong_propensity = (
        propensity_score >= propensity_bar
    )

    strong_financing = (
        financing_score >= financing_bar
    )

    if (
        strong_propensity
        and strong_financing
    ):
        return "high_priority"

    if (
        strong_propensity
        and not strong_financing
    ):
        return (
            "high_propensity_finance_risk"
        )

    if (
        not strong_propensity
        and strong_financing
    ):
        return (
            "low_propensity_financeable"
        )

    return "discard_or_nurture"


def evaluate_sla(
    propensity_score,
    financing_score,
    solar_score,
    payback_years,
    sla
):

    failures = []

    if (
        solar_score
        < sla.minimum_solar_score
    ):
        failures.append(
            "solar_score"
        )

    if (
        propensity_score
        < sla.minimum_propensity_score
    ):
        failures.append(
            "propensity_score"
        )

    if (
        financing_score
        < sla.minimum_financing_score
    ):
        failures.append(
            "financing_score"
        )

    if (
        payback_years
        > sla.max_payback_years
    ):
        failures.append(
            "payback_years"
        )

    return {
        "eligible":
            len(failures) == 0,

        "failed_conditions":
            failures
    }