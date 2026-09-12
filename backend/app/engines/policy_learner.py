from __future__ import annotations

from sklearn.tree import (
    DecisionTreeClassifier
)


FEATURES = [
    "solar_score",
    "annual_shading_loss_pct",
    "annual_solar_irradiation_kwh_m2",
    "usable_roof_area_m2",
    "tariff_rs_kwh",
    "payback_years",
    "irr_pct",
    "outage_hours",
    "financing_score",
    "propensity_score"
]


class PolicyLearner:

    def learn(
        self,
        rows,
        target="funded",
        min_samples=30
    ):

        if len(rows) < min_samples:

            return {
                "mode":
                    "sla_prior",

                "sample_count":
                    len(rows),

                "feature_importance":
                    {},

                "thresholds":
                    [],

                "reason":
                    "insufficient historical outcomes"
            }

        X = []
        y = []

        for row in rows:

            if target not in row:
                continue

            X.append([
                float(
                    row.get(
                        feature,
                        0
                    ) or 0
                )
                for feature in FEATURES
            ])

            y.append(
                int(
                    bool(
                        row[target]
                    )
                )
            )

        if len(y) < min_samples:

            return {
                "mode":
                    "sla_prior",

                "sample_count":
                    len(y),

                "feature_importance":
                    {},

                "thresholds":
                    [],

                "reason":
                    "insufficient labelled records"
            }

        if len(set(y)) < 2:

            return {
                "mode":
                    "sla_prior",

                "sample_count":
                    len(y),

                "feature_importance":
                    {},

                "thresholds":
                    [],

                "reason":
                    "historical data contains one outcome class"
            }

        model = DecisionTreeClassifier(
            max_depth=3,
            min_samples_leaf=max(
                5,
                len(y) // 20
            ),
            random_state=42
        )

        model.fit(
            X,
            y
        )

        importance = {}

        for feature, value in zip(
            FEATURES,
            model.feature_importances_
        ):

            if value > 0:

                importance[
                    feature
                ] = float(value)

        thresholds = []

        for node in range(
            model.tree_.node_count
        ):

            threshold = (
                model.tree_
                .threshold[node]
            )

            if threshold < 0:
                continue

            feature_index = (
                model.tree_
                .feature[node]
            )

            if feature_index < 0:
                continue

            feature = FEATURES[
                feature_index
            ]

            thresholds.append({
                "feature":
                    feature,

                "threshold":
                    float(threshold)
            })

        return {
            "mode":
                "outcome_trained",

            "sample_count":
                len(y),

            "feature_importance":
                importance,

            "thresholds":
                thresholds
        }

    def calibrate_sla(
        self,
        sla
    ):

        return {
            "minimum_solar_score":
                sla.minimum_solar_score,

            "minimum_propensity_score":
                sla.minimum_propensity_score,

            "minimum_financing_score":
                sla.minimum_financing_score,

            "max_payback_years":
                sla.max_payback_years,

            "minimum_irr_pct":
                sla.minimum_irr_pct,

            "max_stale_hours":
                sla.max_stale_hours,

            "max_assignment_hours":
                sla.max_assignment_hours,

            "max_qualification_hours":
                sla.max_qualification_hours,

            "max_submission_hours":
                sla.max_submission_hours,

            "outage_hours_opportunity":
                sla.outage_hours_opportunity
        }