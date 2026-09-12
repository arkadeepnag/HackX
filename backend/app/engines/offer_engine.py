"""
Instant offer construction.

Turns a qualified lead into the four numbers a buyer actually decides on:
  system size, subsidy, indicative EMI, and monthly savings NET of EMI.

For SME/C&I it additionally returns a CAPEX-vs-OPEX(RESCO) comparison and
the accelerated-depreciation impact, because a plant manager does not buy
on payback -- they buy on whether it clears the credit committee.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engines.economics_engine import (
    calculate_emi,
    calculate_irr,
)
from app.engines.subsidy_engine import (
    resolve_incentives,
    SubsidyConfig,
    DEFAULT_SUBSIDY_CONFIG,
)


@dataclass
class OfferAssumptions:
    capex_per_kw_rs: float = 55_000.0
    loan_rate: float = 0.105
    loan_years: int = 7
    loan_ltv: float = 0.80              # lender funds 80% of net capex
    annual_degradation: float = 0.005
    annual_opex_fraction: float = 0.01  # of GROSS capex, not net
    lifetime_years: int = 25
    tariff_escalation: float = 0.03     # discom tariffs do not stay still

    # Net metering / net billing
    export_credit_rs_kwh: float | None = None   # None -> retail (true net metering)
    export_allowed_fraction: float = 1.0

    # OPEX / RESCO route (C&I)
    ppa_tariff_rs_kwh: float = 4.75
    ppa_escalation: float = 0.02
    ppa_years: int = 25

    # Sizing
    residential_sizing_headroom: float = 1.10   # slight oversizing vs consumption
    ci_sizing_headroom: float = 0.90            # C&I sized under load to avoid export


def recommend_capacity_kw(
    segment: str,
    annual_consumption_kwh: float,
    roof_capacity_kw: float,
    sanctioned_load_kw: float | None,
    specific_yield_kwh_per_kw: float,
    assumptions: OfferAssumptions = OfferAssumptions(),
) -> dict:
    """
    Recommended size is the binding minimum of three constraints:
    roof, consumption, and sanctioned load. Most quotes in the market
    ignore the third and get rejected at the discom feasibility stage.
    """
    specific_yield = max(1.0, float(specific_yield_kwh_per_kw))

    headroom = (
        assumptions.residential_sizing_headroom
        if segment == "residential"
        else assumptions.ci_sizing_headroom
    )
    consumption_limited_kw = (
        annual_consumption_kwh / specific_yield
    ) * headroom

    constraints = {
        "roof_limited_kw": round(float(roof_capacity_kw), 2),
        "consumption_limited_kw": round(consumption_limited_kw, 2),
    }

    candidates = [float(roof_capacity_kw), consumption_limited_kw]

    if sanctioned_load_kw and sanctioned_load_kw > 0:
        # Most state regulations cap rooftop PV at the sanctioned load.
        constraints["sanctioned_load_limited_kw"] = round(
            float(sanctioned_load_kw), 2
        )
        candidates.append(float(sanctioned_load_kw))

    recommended = max(0.0, min(candidates))
    binding = min(constraints, key=lambda k: constraints[k])

    return {
        "recommended_capacity_kw": round(recommended, 2),
        "binding_constraint": binding,
        "constraints": constraints,
    }


def _annual_savings(
    generation_kwh: float,
    annual_consumption_kwh: float,
    tariff_rs_kwh: float,
    assumptions: OfferAssumptions,
) -> dict:
    """Self-consumption at retail tariff, export at the credit rate."""
    self_consumed = min(generation_kwh, annual_consumption_kwh)
    surplus = max(0.0, generation_kwh - annual_consumption_kwh)
    exported = surplus * assumptions.export_allowed_fraction
    curtailed = surplus - exported

    export_rate = (
        tariff_rs_kwh
        if assumptions.export_credit_rs_kwh is None
        else assumptions.export_credit_rs_kwh
    )

    return {
        "self_consumed_kwh": self_consumed,
        "exported_kwh": exported,
        "curtailed_kwh": curtailed,
        "savings_rs": self_consumed * tariff_rs_kwh + exported * export_rate,
    }


def build_capex_offer(
    segment: str,
    capacity_kw: float,
    annual_generation_kwh: float,
    annual_consumption_kwh: float,
    tariff_rs_kwh: float,
    state: str | None = None,
    is_group_housing: bool = False,
    is_manufacturing: bool = False,
    assumptions: OfferAssumptions = OfferAssumptions(),
    subsidy_config: SubsidyConfig = DEFAULT_SUBSIDY_CONFIG,
) -> dict:
    gross_capex = capacity_kw * assumptions.capex_per_kw_rs

    incentives = resolve_incentives(
        segment=segment,
        capacity_kw=capacity_kw,
        gross_capex_rs=gross_capex,
        state=state,
        is_group_housing=is_group_housing,
        is_manufacturing=is_manufacturing,
        config=subsidy_config,
    )

    net_capex = max(0.0, gross_capex - incentives["capex_reduction_rs"])
    financed = net_capex * assumptions.loan_ltv
    down_payment = net_capex - financed

    monthly_emi = calculate_emi(
        financed, assumptions.loan_rate, assumptions.loan_years
    )

    year1 = _annual_savings(
        annual_generation_kwh, annual_consumption_kwh,
        tariff_rs_kwh, assumptions,
    )
    year1_savings = year1["savings_rs"]
    monthly_savings = year1_savings / 12.0

    # THE closing number.
    net_monthly_benefit = monthly_savings - monthly_emi

    cashflows = [-down_payment]
    cumulative = -down_payment
    payback_years = None

    for year in range(1, assumptions.lifetime_years + 1):
        generation = annual_generation_kwh * (
            (1 - assumptions.annual_degradation) ** (year - 1)
        )
        tariff = tariff_rs_kwh * ((1 + assumptions.tariff_escalation) ** (year - 1))
        savings = _annual_savings(
            generation, annual_consumption_kwh, tariff, assumptions
        )["savings_rs"]

        opex = gross_capex * assumptions.annual_opex_fraction
        debt_service = monthly_emi * 12 if year <= assumptions.loan_years else 0.0

        net = savings - opex - debt_service
        cashflows.append(net)

        if payback_years is None:
            previous = cumulative
            cumulative += net
            if cumulative >= 0 and net > 0:
                payback_years = (year - 1) + (-previous / net)

    if payback_years is None:
        payback_years = 99.0

    irr_pct = calculate_irr(cashflows)

    # Simple payback on the full net capex -- the number used for SLA
    # screening and comparable across leads regardless of gearing.
    year1_opex = gross_capex * assumptions.annual_opex_fraction
    year1_net = year1_savings - year1_opex
    simple_payback = (net_capex / year1_net) if year1_net > 0 else 99.0

    return {
        "mode": "capex",
        "capacity_kw": round(capacity_kw, 2),
        "gross_capex_rs": round(gross_capex, 2),
        "subsidy_rs": round(incentives["capex_reduction_rs"], 2),
        "net_capex_rs": round(net_capex, 2),
        "down_payment_rs": round(down_payment, 2),
        "financed_amount_rs": round(financed, 2),
        "loan_rate_pct": round(assumptions.loan_rate * 100, 2),
        "loan_tenure_years": assumptions.loan_years,
        "monthly_emi_rs": round(monthly_emi, 2),
        "annual_generation_kwh": round(annual_generation_kwh, 1),
        "self_consumed_kwh": round(year1["self_consumed_kwh"], 1),
        "exported_kwh": round(year1["exported_kwh"], 1),
        "monthly_savings_rs": round(monthly_savings, 2),
        "net_monthly_benefit_rs": round(net_monthly_benefit, 2),
        "cash_positive_from_day_one": net_monthly_benefit >= 0,
        "annual_savings_rs": round(year1_savings, 2),
        "payback_years": round(min(float(simple_payback), 99.0), 2),
        "equity_payback_years": round(float(payback_years), 2),
        "payback_basis": "simple payback on net capex after subsidy",
        "irr_pct": round(float(irr_pct), 2),
        "incentives": incentives,
    }


def build_opex_offer(
    capacity_kw: float,
    annual_generation_kwh: float,
    annual_consumption_kwh: float,
    tariff_rs_kwh: float,
    assumptions: OfferAssumptions = OfferAssumptions(),
) -> dict:
    """
    RESCO / OPEX: developer owns the asset, the SME signs a PPA and pays
    only for units consumed. Zero capex, zero balance-sheet impact, no AD
    benefit, and a lower but immediate saving.
    """
    total_savings = 0.0
    year1_savings = 0.0

    for year in range(1, assumptions.ppa_years + 1):
        generation = annual_generation_kwh * (
            (1 - assumptions.annual_degradation) ** (year - 1)
        )
        consumed = min(generation, annual_consumption_kwh)
        grid_tariff = tariff_rs_kwh * (
            (1 + assumptions.tariff_escalation) ** (year - 1)
        )
        ppa_tariff = assumptions.ppa_tariff_rs_kwh * (
            (1 + assumptions.ppa_escalation) ** (year - 1)
        )
        savings = consumed * max(0.0, grid_tariff - ppa_tariff)
        total_savings += savings
        if year == 1:
            year1_savings = savings

    return {
        "mode": "opex_resco",
        "capacity_kw": round(capacity_kw, 2),
        "upfront_investment_rs": 0.0,
        "ppa_tariff_rs_kwh": assumptions.ppa_tariff_rs_kwh,
        "ppa_escalation_pct": round(assumptions.ppa_escalation * 100, 2),
        "ppa_years": assumptions.ppa_years,
        "monthly_savings_rs": round(year1_savings / 12.0, 2),
        "net_monthly_benefit_rs": round(year1_savings / 12.0, 2),
        "annual_savings_rs": round(year1_savings, 2),
        "lifetime_savings_rs": round(total_savings, 2),
        "balance_sheet_impact": "none",
        "accelerated_depreciation_available": False,
    }


def build_offer(
    segment: str,
    capacity_kw: float,
    annual_generation_kwh: float,
    annual_consumption_kwh: float,
    tariff_rs_kwh: float,
    state: str | None = None,
    sanctioned_load_kw: float | None = None,
    is_group_housing: bool = False,
    is_manufacturing: bool = False,
    assumptions: OfferAssumptions = OfferAssumptions(),
    subsidy_config: SubsidyConfig = DEFAULT_SUBSIDY_CONFIG,
) -> dict:
    """
    Full instant offer. Residential gets the CAPEX case only; C&I gets both
    routes side by side plus a recommendation.
    """
    segment = (segment or "residential").lower()

    capex = build_capex_offer(
        segment, capacity_kw, annual_generation_kwh, annual_consumption_kwh,
        tariff_rs_kwh, state, is_group_housing, is_manufacturing,
        assumptions, subsidy_config,
    )

    offer = {
        "segment": segment,
        "capex_option": capex,
        "headline": _headline(segment, capex),
    }

    if segment != "residential":
        opex = build_opex_offer(
            capacity_kw, annual_generation_kwh,
            annual_consumption_kwh, tariff_rs_kwh, assumptions,
        )
        offer["opex_option"] = opex
        offer["comparison"] = _compare(capex, opex)

    return offer


def _headline(segment: str, capex: dict) -> dict:
    if segment == "residential":
        return {
            "system_size_kw": capex["capacity_kw"],
            "subsidy_rs": capex["subsidy_rs"],
            "monthly_emi_rs": capex["monthly_emi_rs"],
            "net_monthly_benefit_rs": capex["net_monthly_benefit_rs"],
            "payback_years": capex["payback_years"],
        }
    ad = capex["incentives"].get("accelerated_depreciation") or {}
    return {
        "system_size_kw": capex["capacity_kw"],
        "monthly_emi_rs": capex["monthly_emi_rs"],
        "net_monthly_benefit_rs": capex["net_monthly_benefit_rs"],
        "irr_pct": capex["irr_pct"],
        "payback_years": capex["payback_years"],
        "year1_tax_shield_rs": ad.get("year1_tax_shield_rs", 0.0),
    }


def _compare(capex: dict, opex: dict) -> dict:
    ad = capex["incentives"].get("accelerated_depreciation") or {}
    if capex["net_monthly_benefit_rs"] >= opex["net_monthly_benefit_rs"]:
        recommendation = "capex"
        rationale = (
            "CAPEX delivers a higher month-one net benefit and retains the "
            "asset plus the depreciation shield."
        )
    else:
        recommendation = "opex_resco"
        rationale = (
            "OPEX delivers a higher month-one net benefit with no upfront "
            "outlay -- preferable if capital is constrained or the credit "
            "committee will not clear the debt."
        )
    return {
        "recommendation": recommendation,
        "rationale": rationale,
        "capex_net_monthly_rs": capex["net_monthly_benefit_rs"],
        "opex_net_monthly_rs": opex["net_monthly_benefit_rs"],
        "capex_upfront_rs": capex["down_payment_rs"],
        "opex_upfront_rs": 0.0,
        "capex_year1_tax_shield_rs": ad.get("year1_tax_shield_rs", 0.0),
    }