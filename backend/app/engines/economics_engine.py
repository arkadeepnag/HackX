from __future__ import annotations

import math


def calculate_emi(
    principal_rs: float,
    annual_interest_rate: float,
    years: int
):

    if principal_rs <= 0:
        return 0.0

    months = years * 12

    monthly_rate = (
        annual_interest_rate
        / 12
    )

    if monthly_rate == 0:
        return (
            principal_rs
            / months
        )

    factor = (
        (1 + monthly_rate)
        ** months
    )

    return (
        principal_rs
        * monthly_rate
        * factor
        / (factor - 1)
    )


def calculate_irr(
    cashflows: list[float]
):

    if len(cashflows) < 2:
        return 0.0

    low = -0.99
    high = 2.0

    def npv(rate):

        return sum(
            value
            / (
                (1 + rate) ** period
            )
            for period, value
            in enumerate(
                cashflows
            )
        )

    low_npv = npv(low)
    high_npv = npv(high)

    if (
        low_npv * high_npv > 0
    ):
        return 0.0

    for _ in range(150):

        mid = (
            low + high
        ) / 2

        value = npv(mid)

        if abs(value) < 1e-7:
            return mid * 100

        if value > 0:
            low = mid
        else:
            high = mid

    return (
        (low + high) / 2
    ) * 100


def calculate_project_economics(
    capacity_kw: float,
    annual_generation_kwh: float,
    annual_consumption_kwh: float,
    tariff_rs_kwh: float,
    segment: str,
    capex_per_kw: float = 55000,
    subsidy_rs: float = 0,
    annual_degradation: float = 0.005,
    annual_opex_fraction: float = 0.01,
    lifetime_years: int = 25
):

    gross_capex = (
        capacity_kw
        * capex_per_kw
    )

    net_capex = max(
        0,
        gross_capex
        - subsidy_rs
    )

    cashflows = [
        -net_capex
    ]

    annual_savings = []

    for year in range(
        1,
        lifetime_years + 1
    ):

        generation = (
            annual_generation_kwh
            * (
                1
                - annual_degradation
            )
            ** (year - 1)
        )

        offset_energy = min(
            generation,
            annual_consumption_kwh
        )

        savings = (
            offset_energy
            * tariff_rs_kwh
        )

        opex = (
            net_capex
            * annual_opex_fraction
        )

        net_cashflow = (
            savings - opex
        )

        annual_savings.append(
            net_cashflow
        )

        cashflows.append(
            net_cashflow
        )

    first_year_savings = max(
        annual_savings[0],
        0
    )

    if first_year_savings > 0:
        payback_years = (
            net_capex
            / first_year_savings
        )
    else:
        payback_years = 99.0

    irr_pct = calculate_irr(
        cashflows
    )

    total_savings = sum(
        annual_savings
    )

    return {
        "gross_capex_rs":
            float(gross_capex),

        "net_capex_rs":
            float(net_capex),

        "annual_solar_savings_rs":
            float(first_year_savings),

        "lifetime_net_cashflow_rs":
            float(total_savings),

        "payback_years":
            float(payback_years),

        "irr_pct":
            float(irr_pct),

        "cashflows":
            cashflows
    }


def calculate_outage_resilience_value(
    outage_hours: float,
    critical_load_kw: float,
    interruption_cost_rs_kwh: float = 40
):

    outage_energy = (
        outage_hours
        * critical_load_kw
    )

    resilience_value = (
        outage_energy
        * interruption_cost_rs_kwh
    )

    return {
        "outage_energy_kwh":
            float(outage_energy),

        "resilience_value_rs":
            float(resilience_value)
    }