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


def calculate_financing_score(
    solar_score,
    payback_years,
    irr_pct,
    annual_solar_savings_rs,
    annual_emi_rs,
    gst_registered,
    business_vintage_years,
    credit_score,
    sla
):

    score = 50.0

    reasons = []

    if solar_score >= (
        sla.minimum_solar_score
    ):
        score += 8
        reasons.append(
            "solar project clears SLA"
        )
    else:
        score -= 8
        reasons.append(
            "solar project below SLA"
        )

    if payback_years <= (
        sla.max_payback_years
    ):
        score += 12
        reasons.append(
            "payback within SLA"
        )
    else:
        score -= 15
        reasons.append(
            "payback exceeds SLA"
        )

    if irr_pct >= (
        sla.minimum_irr_pct
    ):
        score += 10
        reasons.append(
            "IRR clears SLA"
        )
    else:
        score -= 10
        reasons.append(
            "IRR below SLA"
        )

    if (
        annual_solar_savings_rs
        >= annual_emi_rs
    ):
        score += 18
        reasons.append(
            "solar savings cover modeled EMI"
        )
    else:
        score -= 20
        reasons.append(
            "EMI exceeds modeled savings"
        )

    if gst_registered is True:
        score += 8
        reasons.append(
            "GST registration available"
        )

    if (
        business_vintage_years
        is not None
    ):

        if business_vintage_years >= 3:
            score += 10
            reasons.append(
                "business vintage >= 3 years"
            )

        elif business_vintage_years < 1:
            score -= 10
            reasons.append(
                "business vintage < 1 year"
            )

    if credit_score is not None:

        score += (
            credit_score - 50
        ) * 0.35

        if credit_score >= 70:
            reasons.append(
                "strong credit signal"
            )

        elif credit_score < 40:
            reasons.append(
                "weak credit signal"
            )

    return (
        clamp(score),
        reasons
    )