"""
Lead lifecycle tracking, SLA enforcement and leakage control.

This module was imported by main.py but did not exist, so the service
could not start. It implements the PS requirements the architecture
diagram labels "Analytics & Feedback": contact SLA enforcement, untouched
and stalled lead detection, and cost per funded customer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app import store

# Order matters: a lead may only move forward through the funnel.
FUNNEL = [
    "new", "assigned", "contacted", "qualified",
    "submitted", "funded",
]
TERMINAL = {"dropped", "rejected", "funded"}

# Stage -> the SLA field that governs how long it may sit there.
STAGE_SLA_FIELD = {
    "new": "max_assignment_hours",
    "assigned": "max_first_response_minutes",
    "contacted": "max_qualification_hours",
    "qualified": "max_submission_hours",
}


def _parse(ts: str | None) -> datetime:
    if not ts:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def evaluate_event(event: Any) -> dict:
    """
    Record a lifecycle event and judge it against the contract SLA.

    Accepts the LeadEvent pydantic model or a plain dict, so the same
    function serves the API and the internal WhatsApp flow.
    """
    data = event if isinstance(event, dict) else event.model_dump()

    lead_id = data["lead_id"]
    status = data["status"]
    timestamp = data.get("timestamp")
    sla_hours = float(data.get("contract_sla_hours") or 24)

    history = sorted(
        store.list_events(lead_id=lead_id),
        key=lambda e: e["created_at"],
    )
    previous = history[-1] if history else None

    event_time = _parse(timestamp)
    previous_time = _parse(previous["created_at"]) if previous else event_time
    elapsed_hours = max(0.0, (event_time - previous_time).total_seconds() / 3600)

    breached = elapsed_hours > sla_hours and status not in {"new"}

    # A lead going backwards usually means a partner is reopening a dead
    # lead to reset their SLA clock. Worth surfacing, not silently allowing.
    regression = False
    if previous and previous["event_type"] in FUNNEL and status in FUNNEL:
        regression = FUNNEL.index(status) < FUNNEL.index(previous["event_type"])

    store.record_event(
        status,
        lead_id=lead_id,
        partner_id=data.get("partner_id"),
        payload={
            "funded_amount_rs": data.get("funded_amount_rs"),
            "acquisition_cost_rs": data.get("acquisition_cost_rs"),
            "elapsed_hours": round(elapsed_hours, 2),
            "sla_breached": breached,
        },
        timestamp=event_time.isoformat(),
    )

    lead = store.get_lead(lead_id)
    if lead:
        lead["status"] = status
        if data.get("partner_id"):
            lead["partner_id"] = data["partner_id"]
        if data.get("funded_amount_rs") is not None:
            lead["funded_amount_rs"] = data["funded_amount_rs"]
        if data.get("acquisition_cost_rs") is not None:
            lead["acquisition_cost_rs"] = data["acquisition_cost_rs"]
        store.upsert_lead(lead)

    return {
        "lead_id": lead_id,
        "status": status,
        "previous_status": previous["event_type"] if previous else None,
        "elapsed_hours": round(elapsed_hours, 2),
        "contract_sla_hours": sla_hours,
        "sla_breached": breached,
        "status_regression": regression,
        "terminal": status in TERMINAL,
        "recorded_at": event_time.isoformat(),
    }


def detect_leakage(sla: Any | None = None, stale_hours: float = 48.0) -> dict:
    """
    Find leads that were routed and then went quiet.

    Three distinct failure modes, because they need different fixes:
      untouched  -- assigned but never contacted (partner ignoring the queue)
      stalled    -- contacted but frozen mid-funnel (partner sitting on it)
      unrouted   -- qualified but never assigned (our own routing gap)
    """
    now = datetime.now(timezone.utc)

    assignment_hours = getattr(sla, "max_assignment_hours", 2.0) if sla else 2.0
    first_response_minutes = (
        getattr(sla, "max_first_response_minutes", 30) if sla else 30
    )

    latest: dict[str, dict] = {}
    for e in sorted(store.list_events(limit=5000), key=lambda x: x["created_at"]):
        if e["lead_id"]:
            latest[e["lead_id"]] = e

    untouched, stalled, unrouted = [], [], []

    for lead_id, last in latest.items():
        if last["event_type"] in TERMINAL:
            continue

        idle_hours = (now - _parse(last["created_at"])).total_seconds() / 3600
        lead = store.get_lead(lead_id) or {}

        record = {
            "lead_id": lead_id,
            "partner_id": last["partner_id"],
            "current_status": last["event_type"],
            "idle_hours": round(idle_hours, 2),
            "pincode": lead.get("pincode"),
            "propensity_score": lead.get("propensity_score"),
            "financing_score": lead.get("financing_score"),
        }

        if last["event_type"] == "assigned":
            limit = first_response_minutes / 60.0
            if idle_hours > limit:
                record["sla_limit_hours"] = round(limit, 2)
                record["severity"] = (
                    "critical" if idle_hours > limit * 4 else "warning"
                )
                untouched.append(record)

        elif last["event_type"] == "new":
            if idle_hours > assignment_hours:
                record["sla_limit_hours"] = assignment_hours
                unrouted.append(record)

        elif idle_hours > stale_hours:
            record["sla_limit_hours"] = stale_hours
            stalled.append(record)

    for bucket in (untouched, stalled, unrouted):
        bucket.sort(key=lambda r: r["idle_hours"], reverse=True)

    return {
        "generated_at": now.isoformat(),
        "untouched_count": len(untouched),
        "stalled_count": len(stalled),
        "unrouted_count": len(unrouted),
        "untouched": untouched,
        "stalled": stalled,
        "unrouted": unrouted,
    }


def partner_scorecard(window_days: int = 30) -> list[dict]:
    """Per-partner conversion and responsiveness. Feeds routing weights."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    events = [
        e for e in store.list_events(limit=10000)
        if e["created_at"] >= cutoff and e["partner_id"]
    ]

    by_partner: dict[str, dict] = {}
    for e in events:
        p = by_partner.setdefault(e["partner_id"], {
            "partner_id": e["partner_id"], "assigned": 0, "contacted": 0,
            "funded": 0, "dropped": 0, "rejected": 0,
            "response_hours": [], "sla_breaches": 0,
        })
        kind = e["event_type"]
        if kind in p:
            p[kind] += 1
        if kind == "contacted":
            elapsed = (e["payload"] or {}).get("elapsed_hours")
            if elapsed is not None:
                p["response_hours"].append(elapsed)
        if (e["payload"] or {}).get("sla_breached"):
            p["sla_breaches"] += 1

    scorecards = []
    for p in by_partner.values():
        assigned = max(p["assigned"], 1)
        responses = p["response_hours"]
        scorecards.append({
            "partner_id": p["partner_id"],
            "assigned": p["assigned"],
            "contacted": p["contacted"],
            "funded": p["funded"],
            "dropped": p["dropped"],
            "rejected": p["rejected"],
            "contact_rate_pct": round(p["contacted"] / assigned * 100, 1),
            "conversion_rate_pct": round(p["funded"] / assigned * 100, 1),
            "median_response_hours": (
                round(sorted(responses)[len(responses) // 2], 2)
                if responses else None
            ),
            "sla_breaches": p["sla_breaches"],
        })

    scorecards.sort(key=lambda s: s["conversion_rate_pct"], reverse=True)
    return scorecards


def funnel_metrics(window_days: int = 90) -> dict:
    """
    Cost per funded customer -- the PS calls this the only metric that
    matters. Everything else here exists to explain its movement.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    events = [e for e in store.list_events(limit=20000) if e["created_at"] >= cutoff]

    counts = {stage: 0 for stage in FUNNEL + ["dropped", "rejected"]}
    seen: dict[str, set] = {}
    total_acquisition_cost = 0.0
    total_funded_amount = 0.0

    for e in events:
        stage = e["event_type"]
        if stage not in counts:
            continue
        bucket = seen.setdefault(stage, set())
        if e["lead_id"] in bucket:
            continue
        bucket.add(e["lead_id"])
        counts[stage] += 1

        payload = e["payload"] or {}
        if payload.get("acquisition_cost_rs"):
            total_acquisition_cost += float(payload["acquisition_cost_rs"])
        if payload.get("funded_amount_rs"):
            total_funded_amount += float(payload["funded_amount_rs"])

    funded = counts.get("funded", 0)
    assigned = counts.get("assigned", 0)

    return {
        "window_days": window_days,
        "funnel": counts,
        "assigned_to_funded_pct": (
            round(funded / assigned * 100, 2) if assigned else 0.0
        ),
        "total_acquisition_cost_rs": round(total_acquisition_cost, 2),
        "total_funded_amount_rs": round(total_funded_amount, 2),
        "cost_per_funded_customer_rs": (
            round(total_acquisition_cost / funded, 2) if funded else None
        ),
        "note": (
            "cost_per_funded_customer_rs is null until at least one lead "
            "reaches funded status."
        ),
    }


def training_rows() -> list[dict]:
    """
    Assemble labelled rows for PolicyLearner: every lead that reached a
    terminal outcome, with its scores at the time of routing.
    """
    outcomes: dict[str, str] = {}
    for e in sorted(store.list_events(limit=20000), key=lambda x: x["created_at"]):
        if e["event_type"] in TERMINAL and e["lead_id"]:
            outcomes[e["lead_id"]] = e["event_type"]

    rows = []
    for lead_id, outcome in outcomes.items():
        lead = store.get_lead(lead_id)
        if not lead:
            continue
        row = {
            k: lead.get(k) for k in (
                "solar_score", "annual_shading_loss_pct",
                "annual_solar_irradiation_kwh_m2", "usable_roof_area_m2",
                "tariff_rs_kwh", "payback_years", "irr_pct", "outage_hours",
                "financing_score", "propensity_score",
            )
        }
        row["funded"] = 1 if outcome == "funded" else 0
        rows.append(row)
    return rows