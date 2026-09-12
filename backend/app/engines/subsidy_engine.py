"""
Subsidy + tax-benefit engine.

Residential  -> PM Surya Ghar Muft Bijli Yojana (CFA slab).
C&I          -> Accelerated Depreciation (Income Tax Act) tax shield.

All rates are config-driven so a policy revision is a data change, not a
code change. Values below are the MNRE CFA structure in force for the
MVP; confirm against the current MNRE office memorandum before a real
disbursement, and override via SubsidyConfig if it has moved.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubsidyConfig:
    # PM Surya Ghar central financial assistance (residential only)
    psg_rate_first_2kw_rs: float = 30_000.0
    psg_rate_third_kw_rs: float = 18_000.0
    psg_cap_rs: float = 78_000.0
    psg_max_eligible_kw: float = 3.0

    # Group housing society / resident welfare association common facilities
    ghs_rate_rs_per_kw: float = 18_000.0
    ghs_cap_kw: float = 500.0

    # Optional state top-up, keyed by state name (upper case)
    state_topup_rs_per_kw: dict[str, float] = field(default_factory=dict)
    state_topup_cap_rs: dict[str, float] = field(default_factory=dict)

    # Accelerated depreciation (C&I)
    ad_rate_year1: float = 0.40          # Appendix I, renewable devices
    ad_additional_year1: float = 0.20    # sec 32(1)(iia), manufacturing only
    effective_tax_rate: float = 0.2517   # 22% + surcharge + cess
    ad_half_rate_if_under_180_days: bool = True


DEFAULT_SUBSIDY_CONFIG = SubsidyConfig()


def residential_subsidy(
    capacity_kw: float,
    state: str | None = None,
    is_group_housing: bool = False,
    config: SubsidyConfig = DEFAULT_SUBSIDY_CONFIG,
) -> dict:
    """
    PM Surya Ghar CFA for an individual residential rooftop.

    Slab structure: flat rate for the first 2 kW, a lower rate for the
    3rd kW, hard cap thereafter. A 10 kW home system draws exactly the
    same CFA as a 3 kW one -- which is precisely why residential sizing
    should not chase roof area.
    """
    capacity_kw = max(0.0, float(capacity_kw))

    if is_group_housing:
        eligible_kw = min(capacity_kw, config.ghs_cap_kw)
        central = eligible_kw * config.ghs_rate_rs_per_kw
        basis = "group_housing_common_facility"
    else:
        eligible_kw = min(capacity_kw, config.psg_max_eligible_kw)
        first = min(eligible_kw, 2.0) * config.psg_rate_first_2kw_rs
        third = max(0.0, eligible_kw - 2.0) * config.psg_rate_third_kw_rs
        central = min(first + third, config.psg_cap_rs)
        basis = "pm_surya_ghar_individual"

    key = (state or "").strip().upper()
    topup_rate = config.state_topup_rs_per_kw.get(key, 0.0)
    topup_cap = config.state_topup_cap_rs.get(key)
    state_topup = eligible_kw * topup_rate
    if topup_cap is not None:
        state_topup = min(state_topup, topup_cap)

    total = central + state_topup

    return {
        "scheme": basis,
        "eligible_capacity_kw": round(eligible_kw, 3),
        "central_subsidy_rs": round(central, 2),
        "state_subsidy_rs": round(state_topup, 2),
        "total_subsidy_rs": round(total, 2),
        "capacity_above_subsidy_cap_kw": round(
            max(0.0, capacity_kw - eligible_kw), 3
        ),
        "notes": (
            "CFA is capped; capacity beyond the cap carries no subsidy."
            if capacity_kw > eligible_kw
            else "Full system capacity is within the subsidy cap."
        ),
    }


def accelerated_depreciation_benefit(
    gross_capex_rs: float,
    commissioned_within_180_days: bool = True,
    is_manufacturing: bool = False,
    config: SubsidyConfig = DEFAULT_SUBSIDY_CONFIG,
) -> dict:
    """
    Year-1 tax shield from accelerated depreciation on a C&I rooftop asset.

    This is not a cash grant. It is a reduction in year-1 tax outgo, and it
    only has value if the entity is actually profitable and paying tax --
    so we return it as a separate line, never netted into CAPEX silently.
    """
    gross_capex_rs = max(0.0, float(gross_capex_rs))

    rate = config.ad_rate_year1
    if is_manufacturing:
        rate += config.ad_additional_year1

    if not commissioned_within_180_days and config.ad_half_rate_if_under_180_days:
        rate = rate / 2.0
        timing_note = (
            "Asset in use under 180 days in the financial year: "
            "year-1 depreciation restricted to half rate."
        )
    else:
        timing_note = "Full year-1 depreciation rate applied."

    depreciation_base = gross_capex_rs * rate
    tax_shield = depreciation_base * config.effective_tax_rate

    return {
        "applicable": gross_capex_rs > 0,
        "year1_depreciation_rate": round(rate, 4),
        "year1_depreciation_rs": round(depreciation_base, 2),
        "effective_tax_rate": config.effective_tax_rate,
        "year1_tax_shield_rs": round(tax_shield, 2),
        "effective_capex_after_ad_rs": round(gross_capex_rs - tax_shield, 2),
        "timing_note": timing_note,
        "caveat": (
            "Tax shield realisable only against taxable profits. "
            "Confirm with the entity's tax position before quoting."
        ),
    }


def resolve_incentives(
    segment: str,
    capacity_kw: float,
    gross_capex_rs: float,
    state: str | None = None,
    is_group_housing: bool = False,
    is_manufacturing: bool = False,
    commissioned_within_180_days: bool = True,
    config: SubsidyConfig = DEFAULT_SUBSIDY_CONFIG,
) -> dict:
    """
    Single entry point. Residential gets a capex-reducing grant; C&I gets a
    tax shield that does not reduce the financed principal.
    """
    segment = (segment or "residential").lower()

    if segment == "residential":
        subsidy = residential_subsidy(
            capacity_kw, state, is_group_housing, config
        )
        return {
            "segment": segment,
            "incentive_type": "capex_subsidy",
            "capex_reduction_rs": subsidy["total_subsidy_rs"],
            "year1_tax_shield_rs": 0.0,
            "subsidy": subsidy,
            "accelerated_depreciation": None,
        }

    ad = accelerated_depreciation_benefit(
        gross_capex_rs, commissioned_within_180_days, is_manufacturing, config
    )
    return {
        "segment": segment,
        "incentive_type": "accelerated_depreciation",
        "capex_reduction_rs": 0.0,
        "year1_tax_shield_rs": ad["year1_tax_shield_rs"],
        "subsidy": None,
        "accelerated_depreciation": ad,
    }