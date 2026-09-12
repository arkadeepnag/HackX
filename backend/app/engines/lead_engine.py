from __future__ import annotations

from app.engines.building_engine import (
    load_candidates
)

from app.engines.solar_engine import (
    analyze as analyze_solar
)

from app.engines.economics_engine import (
    calculate_project_economics,
    calculate_emi,
    calculate_outage_resilience_value
)

from app.engines.financing_engine import (
    calculate_financing_score
)

from app.engines.scoring_engine import (
    calculate_solar_score,
    calculate_propensity_score,
    determine_routing_class,
    evaluate_sla
)

from app.engines.policy_learner import (
    PolicyLearner
)

from app.providers.solar_resource import (
    SolarResourceProvider
)

from app.providers.tariff import (
    TariffProvider
)

from app.providers.reliability import (
    ReliabilityProvider
)

from app.engines.subsidy_engine import (
    resolve_incentives
)


class LeadEngine:

    def __init__(self):

        self.solar_resource = (
            SolarResourceProvider()
        )

        self.tariff_provider = (
            TariffProvider()
        )

        self.reliability_provider = (
            ReliabilityProvider()
        )

        self.policy_learner = (
            PolicyLearner()
        )

    def analyze(
        self,
        request
    ):

        buildings, metric_crs = (
            load_candidates(
                request.building_source,
                request.latitude,
                request.longitude,
                request.radius_m,
                request.max_buildings
            )
        )

        resource = (
            self.solar_resource.get(
                request.latitude,
                request.longitude,
                request.data_mode
            )
        )

        tariff = (
            self.tariff_provider.resolve(
                request.latitude,
                request.longitude,
                request.customer.segment
            )
        )

        reliability = (
            self.reliability_provider.resolve(
                request.latitude,
                request.longitude
            )
        )

        solar_results, optimum = (
            analyze_solar(
                buildings,
                request.latitude,
                request.longitude,
                resource,
                request.detail_top_n
            )
        )

        reliability_score = self._reliability_score(
            reliability
        )

        results = []

        annual_consumption = (
            request.customer
            .monthly_consumption_kwh
            * 12
        )

        monthly_bill = (
            self.tariff_provider.bill(
                request.customer
                .monthly_consumption_kwh,
                tariff
            )
        )

        annual_bill = (
            monthly_bill * 12
        )

        for _, solar in (
            solar_results.iterrows()
        ):

            # Value displaced units at the marginal slab rate, not the
            # flat average of all slabs -- solar eats the top slab first.
            tariff_rate = float(
                self.tariff_provider.marginal_rate(
                    request.customer
                    .monthly_consumption_kwh,
                    tariff
                )
            )

            incentives = resolve_incentives(
                segment=request.customer.segment,
                capacity_kw=float(
                    solar["pv_capacity_kw"]
                ),
                gross_capex_rs=float(
                    solar["pv_capacity_kw"]
                ) * 55000.0,
                state=tariff.get("state"),
                is_manufacturing=(
                    request.customer.segment
                    == "industrial"
                )
            )

            economics = (
                calculate_project_economics(
                    capacity_kw=float(
                        solar[
                            "pv_capacity_kw"
                        ]
                    ),

                    annual_generation_kwh=float(
                        solar[
                            "annual_pv_generation_kwh"
                        ]
                    ),

                    annual_consumption_kwh=(
                        annual_consumption
                    ),

                    tariff_rs_kwh=(
                        tariff_rate
                    ),

                    segment=(
                        request.customer.segment
                    ),

                    # Previously read tariff["subsidy_rs"], a key that
                    # exists in no tariff record -- so every residential
                    # lead was modelled at full, unsubsidised capex.
                    subsidy_rs=float(
                        incentives[
                            "capex_reduction_rs"
                        ]
                    )
                )
            )

            emi_monthly = (
                calculate_emi(
                    economics[
                        "net_capex_rs"
                    ],
                    0.105,
                    7
                )
            )

            annual_emi = (
                emi_monthly * 12
            )

            critical_load = (
                request.customer
                .critical_load_kw
            )

            if critical_load is None:

                critical_load = min(
                    request.customer
                    .sanctioned_load_kw,

                    max(
                        1,
                        float(
                            solar[
                                "pv_capacity_kw"
                            ]
                        ) * 0.5
                    )
                )

            outage_hours = float(
                reliability.get(
                    "saidi_hours_per_customer_year",
                    0
                )
            )

            resilience = (
                calculate_outage_resilience_value(
                    outage_hours,
                    critical_load
                )
            )

            solar_score = (
                calculate_solar_score(
                    annual_irradiation_kwh_m2=float(
                        solar[
                            "annual_solar_irradiation_kwh_m2"
                        ]
                    ),

                    direct_sun_hours_year=float(
                        solar[
                            "direct_sun_hours_year"
                        ]
                    ),

                    shading_loss_pct=float(
                        solar[
                            "annual_shading_loss_pct"
                        ]
                    ),

                    usable_roof_area_m2=float(
                        solar[
                            "usable_roof_area_m2"
                        ]
                    ),

                    tariff_rs_kwh=tariff_rate,

                    grid_reliability_score=(
                        reliability_score
                    )
                )
            )

            propensity_score = (
                calculate_propensity_score(
                    solar_score=solar_score,

                    payback_years=economics[
                        "payback_years"
                    ],

                    irr_pct=economics[
                        "irr_pct"
                    ],

                    tariff_rs_kwh=tariff_rate,

                    outage_hours=outage_hours,

                    owned_roof=(
                        request.customer
                        .owned_roof
                    ),

                    bill_count=(
                        request.customer
                        .bill_count
                    ),

                    roof_photo_uploaded=(
                        request.customer
                        .roof_photo_uploaded
                    ),

                    sla=request.sla
                )
            )

            financing_score, financing_reasons = (
                calculate_financing_score(
                    solar_score=solar_score,

                    payback_years=economics[
                        "payback_years"
                    ],

                    irr_pct=economics[
                        "irr_pct"
                    ],

                    annual_solar_savings_rs=(
                        economics[
                            "annual_solar_savings_rs"
                        ]
                    ),

                    annual_emi_rs=(
                        annual_emi
                    ),

                    gst_registered=(
                        request.customer
                        .gst_registered
                    ),

                    business_vintage_years=(
                        request.customer
                        .business_vintage_years
                    ),

                    credit_score=(
                        request.customer
                        .credit_score
                    ),

                    sla=request.sla
                )
            )

            routing_class = (
                determine_routing_class(
                    propensity_score,
                    financing_score
                )
            )

            sla_result = (
                evaluate_sla(
                    propensity_score,
                    financing_score,
                    solar_score,
                    economics[
                        "payback_years"
                    ],
                    request.sla
                )
            )

            reasons = []

            if solar_score >= (
                request.sla
                .minimum_solar_score
            ):
                reasons.append(
                    "solar viability clears SLA"
                )
            else:
                reasons.append(
                    "solar viability below SLA"
                )

            if economics[
                "payback_years"
            ] <= request.sla.max_payback_years:
                reasons.append(
                    "payback clears SLA"
                )
            else:
                reasons.append(
                    "payback exceeds SLA"
                )

            if float(
                solar[
                    "annual_shading_loss_pct"
                ]
            ) <= 20:
                reasons.append(
                    "shading within screening tolerance"
                )
            else:
                reasons.append(
                    "high shading"
                )

            if outage_hours >= (
                request.sla
                .outage_hours_opportunity
            ):
                reasons.append(
                    "grid disruption creates resilience opportunity"
                )

            reasons.extend(
                financing_reasons[:3]
            )

            result = {
                "building_uid":
                    solar["building_uid"],

                "latitude":
                    float(
                        solar["latitude"]
                    )
                    if solar.get("latitude")
                    is not None
                    else None,

                "longitude":
                    float(
                        solar["longitude"]
                    )
                    if solar.get("longitude")
                    is not None
                    else None,

                "building_class":
                    solar["building_class"],

                "footprint_area_m2":
                    float(
                        solar[
                            "footprint_area_m2"
                        ]
                    ),

                "height_m":
                    float(
                        solar["height_m"]
                    ),

                "height_source":
                    solar[
                        "height_source"
                    ],

                "usable_roof_area_m2":
                    float(
                        solar[
                            "usable_roof_area_m2"
                        ]
                    ),

                "pv_capacity_kw":
                    float(
                        solar[
                            "pv_capacity_kw"
                        ]
                    ),

                "optimal_panel_tilt_deg":
                    float(
                        solar[
                            "optimal_panel_tilt_deg"
                        ]
                    ),

                "optimal_panel_azimuth_deg":
                    float(
                        solar[
                            "optimal_panel_azimuth_deg"
                        ]
                    ),

                "annual_solar_irradiation_kwh_m2":
                    float(
                        solar[
                            "annual_solar_irradiation_kwh_m2"
                        ]
                    ),

                "direct_sun_hours_year":
                    float(
                        solar[
                            "direct_sun_hours_year"
                        ]
                    ),

                "annual_shading_loss_pct":
                    float(
                        solar[
                            "annual_shading_loss_pct"
                        ]
                    ),

                "annual_pv_generation_kwh":
                    float(
                        solar[
                            "annual_pv_generation_kwh"
                        ]
                    ),

                "shadow_method":
                    solar[
                        "shadow_method"
                    ],

                "discom":
                    tariff["discom"],

                "tariff_source":
                    tariff["source"],

                "tariff_rs_kwh":
                    tariff_rate,

                "monthly_bill_rs":
                    float(
                        monthly_bill
                    ),

                "annual_bill_rs":
                    float(
                        annual_bill
                    ),

                "annual_solar_savings_rs":
                    float(
                        economics[
                            "annual_solar_savings_rs"
                        ]
                    ),

                "gross_capex_rs":
                    float(
                        economics[
                            "gross_capex_rs"
                        ]
                    ),

                "net_capex_rs":
                    float(
                        economics[
                            "net_capex_rs"
                        ]
                    ),

                "annual_emi_rs":
                    float(
                        annual_emi
                    ),

                "monthly_emi_rs":
                    float(
                        emi_monthly
                    ),

                "subsidy_rs":
                    float(
                        incentives[
                            "capex_reduction_rs"
                        ]
                    ),

                "year1_tax_shield_rs":
                    float(
                        incentives[
                            "year1_tax_shield_rs"
                        ]
                    ),

                "incentives":
                    incentives,

                # The number that closes the sale.
                "net_monthly_benefit_rs":
                    float(
                        economics[
                            "annual_solar_savings_rs"
                        ] / 12.0
                        - emi_monthly
                    ),

                "payback_years":
                    float(
                        economics[
                            "payback_years"
                        ]
                    ),

                "irr_pct":
                    float(
                        economics[
                            "irr_pct"
                        ]
                    ),

                "saifi":
                    reliability.get(
                        "saifi"
                    ),

                "saidi_hours_per_customer_year":
                    outage_hours,

                "outage_hours":
                    outage_hours,

                "reliability_source":
                    reliability.get(
                        "source"
                    ),

                "reliability_spatial_level":
                    reliability.get(
                        "spatial_level"
                    ),

                "outage_energy_kwh":
                    resilience[
                        "outage_energy_kwh"
                    ],

                "resilience_value_rs":
                    resilience[
                        "resilience_value_rs"
                    ],

                "solar_score":
                    solar_score,

                "propensity_score":
                    propensity_score,

                "financing_score":
                    financing_score,

                "routing_class":
                    routing_class,

                "sla_eligible":
                    sla_result[
                        "eligible"
                    ],

                "sla_failed_conditions":
                    sla_result[
                        "failed_conditions"
                    ],

                "reasons":
                    reasons,

                "qualification": {
                    "owned_roof":
                        request.customer
                        .owned_roof,

                    "sanctioned_load_kw":
                        request.customer
                        .sanctioned_load_kw,

                    "monthly_consumption_kwh":
                        request.customer
                        .monthly_consumption_kwh,

                    "bill_count":
                        request.customer
                        .bill_count,

                    "roof_photo_uploaded":
                        request.customer
                        .roof_photo_uploaded
                }
            }

            results.append(
                result
            )

        results.sort(
            key=lambda item: (
                item["sla_eligible"],
                item["propensity_score"],
                item["financing_score"],
                item["solar_score"]
            ),
            reverse=True
        )

        return {
            "analysis": {
                "latitude":
                    request.latitude,

                "longitude":
                    request.longitude,

                "radius_m":
                    request.radius_m,

                "candidate_count":
                    len(results),

                "metric_crs":
                    metric_crs,

                "solar_resource":
                    resource,

                "optimum":
                    optimum,

                "tariff":
                    tariff,

                "reliability":
                    reliability,

                "policy":
                    self.policy_learner
                    .calibrate_sla(
                        request.sla
                    )
            },

            "leads":
                results
        }

    def _reliability_score(
        self,
        reliability
    ):
        """
        Named "reliability" but deliberately increasing in SAIDI: a worse
        grid raises willingness to pay for rooftop solar. Treat it as an
        outage-opportunity score, not grid quality.
        """

        saidi = reliability.get(
            "saidi_hours_per_customer_year"
        )

        if saidi is None:
            return 50.0

        score = min(
            100,
            float(saidi) * 5
        )

        return score