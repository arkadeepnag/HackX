"""
Closed-loop learning from scoring mistakes.

The PS is specific: feed disbursed, dropped and rejected outcomes back into
scoring so cost per funded customer falls every cycle. That means the
system has to name its own errors, not just report an accuracy number.

Two error classes, with opposite costs:

  false_positive -- scored above the routing bar, then died. Every one of
                    these burned a field visit. Expensive.
  false_negative -- scored below the bar but funded anyway. Every one of
                    these is revenue the filter would have thrown away.
                    Invisible unless you deliberately look for it, which is
                    why sub-threshold leads must still be tracked.

Output is a calibration adjustment applied on top of the rule-based score,
never a replacement for it. The rules stay explainable; the learned layer
is a bounded correction with a stated reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app import store
from app.engines.policy_learner import FEATURES, PolicyLearner
from app.engines.tracking_engine import TERMINAL

MODEL_NAME = "lead_scoring_policy"

# The learned correction is deliberately capped. An early model trained on
# a few dozen outcomes should nudge the rules, not overrule them.
MAX_ADJUSTMENT = 15.0


@dataclass
class Outcome:
    lead_id: str
    funded: bool
    terminal_status: str
    propensity_score: float | None
    financing_score: float | None
    solar_score: float | None
    routed: bool
    features: dict


def collect_outcomes() -> list[Outcome]:
    """Every lead that reached a terminal state, with its scores at routing."""
    terminal_by_lead: dict[str, str] = {}
    routed_leads: set[str] = set()

    for event in sorted(
        store.list_events(limit=50000), key=lambda e: e["created_at"]
    ):
        if not event["lead_id"]:
            continue
        if event["event_type"] == "assigned":
            routed_leads.add(event["lead_id"])
        if event["event_type"] in TERMINAL:
            terminal_by_lead[event["lead_id"]] = event["event_type"]

    outcomes = []
    for lead_id, status in terminal_by_lead.items():
        lead = store.get_lead(lead_id)
        if not lead:
            continue
        outcomes.append(Outcome(
            lead_id=lead_id,
            funded=(status == "funded"),
            terminal_status=status,
            propensity_score=lead.get("propensity_score"),
            financing_score=lead.get("financing_score"),
            solar_score=lead.get("solar_score"),
            routed=lead_id in routed_leads,
            features={f: lead.get(f) for f in FEATURES},
        ))
    return outcomes


def analyse_mistakes(
    outcomes: list[Outcome],
    propensity_bar: float = 55.0,
    financing_bar: float = 50.0,
) -> dict:
    """
    Split terminal outcomes into correct calls and mistakes, and quantify
    what each mistake class cost.
    """
    false_positives, false_negatives = [], []
    true_positives, true_negatives = [], []

    for outcome in outcomes:
        propensity = outcome.propensity_score or 0
        financing = outcome.financing_score or 0
        predicted_good = (
            propensity >= propensity_bar and financing >= financing_bar
        )

        record = {
            "lead_id": outcome.lead_id,
            "propensity_score": propensity,
            "financing_score": financing,
            "terminal_status": outcome.terminal_status,
            "routed": outcome.routed,
        }

        if predicted_good and not outcome.funded:
            record["cost"] = (
                "field visit spent on a lead that did not fund"
                if outcome.routed else "qualified but never converted"
            )
            false_positives.append(record)
        elif not predicted_good and outcome.funded:
            record["cost"] = "revenue that the current bar would discard"
            false_negatives.append(record)
        elif predicted_good:
            true_positives.append(record)
        else:
            true_negatives.append(record)

    total = len(outcomes)
    flagged = len(true_positives) + len(false_positives)

    # Which failure mode dominates tells you which way to move the bar.
    if len(false_positives) > len(false_negatives) * 1.5:
        bias = "over_optimistic"
        guidance = (
            "The score is routing leads that do not fund. Raise the "
            "financing bar before raising the propensity bar -- most "
            "false positives die at underwriting, not at interest."
        )
    elif len(false_negatives) > len(false_positives) * 1.5:
        bias = "over_conservative"
        guidance = (
            "Leads below the bar are funding. The filter is discarding "
            "revenue; loosen the bar or re-weight the features that the "
            "missed leads share."
        )
    else:
        bias = "balanced"
        guidance = "Error classes are roughly balanced at the current bar."

    return {
        "sample_count": total,
        "funded_count": sum(1 for o in outcomes if o.funded),
        "true_positives": len(true_positives),
        "false_positives": len(false_positives),
        "true_negatives": len(true_negatives),
        "false_negatives": len(false_negatives),
        "precision": round(
            len(true_positives) / flagged, 3
        ) if flagged else None,
        "recall": round(
            len(true_positives)
            / (len(true_positives) + len(false_negatives)), 3
        ) if (len(true_positives) + len(false_negatives)) else None,
        "bias": bias,
        "guidance": guidance,
        "worst_false_positives": sorted(
            false_positives,
            key=lambda r: r["propensity_score"], reverse=True
        )[:10],
        "worst_false_negatives": sorted(
            false_negatives,
            key=lambda r: r["propensity_score"]
        )[:10],
    }


def calibrate(outcomes: list[Outcome], bins: int = 5) -> list[dict]:
    """
    Observed funding rate per propensity band.

    A well-calibrated score funds monotonically more often as it rises. A
    band where the funded rate drops as the score climbs is the clearest
    signal that a feature weight is wrong.
    """
    scored = [o for o in outcomes if o.propensity_score is not None]
    if not scored:
        return []

    width = 100.0 / bins
    table = []

    for index in range(bins):
        low, high = index * width, (index + 1) * width
        bucket = [
            o for o in scored
            if low <= o.propensity_score < high
            or (index == bins - 1 and o.propensity_score == 100)
        ]
        if not bucket:
            table.append({
                "band": f"{int(low)}-{int(high)}", "count": 0,
                "funded_rate": None, "expected_rate": round(
                    (low + high) / 200, 3
                ),
            })
            continue

        funded_rate = sum(1 for o in bucket if o.funded) / len(bucket)
        expected = (low + high) / 200
        table.append({
            "band": f"{int(low)}-{int(high)}",
            "count": len(bucket),
            "funded_rate": round(funded_rate, 3),
            "expected_rate": round(expected, 3),
            "drift": round(funded_rate - expected, 3),
        })

    for previous, current in zip(table, table[1:]):
        if (
            previous["funded_rate"] is not None
            and current["funded_rate"] is not None
            and current["funded_rate"] < previous["funded_rate"]
        ):
            current["warning"] = (
                "funding rate falls as score rises -- feature weights "
                "likely mis-specified in this band"
            )
    return table


def learn(min_samples: int = 30) -> dict:
    """
    Run a full learning cycle and persist the result as a new model
    version. Safe to call with no data: it returns the prior and says so.
    """
    outcomes = collect_outcomes()
    mistakes = analyse_mistakes(outcomes)
    calibration = calibrate(outcomes)

    rows = []
    for outcome in outcomes:
        row = dict(outcome.features)
        row["funded"] = 1 if outcome.funded else 0
        rows.append(row)

    tree = PolicyLearner().learn(
        rows=rows, target="funded", min_samples=min_samples
    )

    adjustments = _derive_adjustments(calibration, mistakes)

    model = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "mode": tree["mode"],
        "sample_count": tree.get("sample_count", len(rows)),
        "feature_importance": tree.get("feature_importance", {}),
        "thresholds": tree.get("thresholds", []),
        "mistakes": mistakes,
        "calibration": calibration,
        "adjustments": adjustments,
        "reason": tree.get("reason"),
    }

    model["version"] = store.save_model(MODEL_NAME, model)
    return model


def _derive_adjustments(calibration: list[dict], mistakes: dict) -> dict:
    """
    Turn observed drift into a bounded per-band score correction.

    Deliberately conservative: a band must have at least five outcomes
    before it earns any correction, and the correction is capped.
    """
    per_band = {}
    for band in calibration:
        if not band.get("count") or band["count"] < 5:
            continue
        drift = band.get("drift")
        if drift is None:
            continue
        delta = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, drift * 100))
        per_band[band["band"]] = round(delta, 2)

    return {
        "propensity_band_delta": per_band,
        "bias_correction": mistakes["bias"],
        "max_adjustment": MAX_ADJUSTMENT,
        "note": (
            "Applied additively to the rule-based propensity score, then "
            "clamped to 0-100. Bands with fewer than 5 outcomes are left "
            "untouched."
        ),
    }


def apply_learned_adjustment(
    propensity_score: float,
    financing_score: float | None = None,
) -> dict:
    """
    Apply the persisted model to a fresh score.

    Returns the original alongside the adjusted value and a plain-language
    reason, so a caller reading the dashboard can always see why a lead
    moved. Falls through untouched when no model exists.
    """
    model = store.get_model(MODEL_NAME)

    if not model or model.get("mode") != "outcome_trained":
        return {
            "propensity_score": propensity_score,
            "adjusted_propensity_score": propensity_score,
            "adjustment": 0.0,
            "model_version": model.get("version") if model else None,
            "reason": "no outcome-trained model yet; rule-based score used",
        }

    deltas = model["adjustments"]["propensity_band_delta"]
    band_index = min(int(propensity_score // 20), 4)
    band_key = f"{band_index * 20}-{(band_index + 1) * 20}"
    delta = deltas.get(band_key, 0.0)

    adjusted = max(0.0, min(100.0, propensity_score + delta))

    if delta > 0:
        reason = (
            f"leads scoring {band_key} funded more often than the rules "
            f"predicted; score raised by {delta:.1f}"
        )
    elif delta < 0:
        reason = (
            f"leads scoring {band_key} funded less often than the rules "
            f"predicted; score cut by {abs(delta):.1f}"
        )
    else:
        reason = f"band {band_key} has too few outcomes to adjust"

    return {
        "propensity_score": propensity_score,
        "adjusted_propensity_score": round(adjusted, 2),
        "adjustment": delta,
        "band": band_key,
        "model_version": model["version"],
        "trained_at": model["trained_at"],
        "reason": reason,
    }


def current_model() -> dict | None:
    return store.get_model(MODEL_NAME)