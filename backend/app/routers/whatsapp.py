"""
WhatsApp, partner routing and analytics endpoints.

Kept in a router so main.py stays a thin composition root.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app import store
from app.engines import partner_engine, tracking_engine, whatsapp_flow
from app.engines.policy_learner import PolicyLearner
from app.models.schemas import (
    PartnerRouteRequest,
    SimulateMessageRequest,
)
from app.providers.whatsapp_client import (
    get_client,
    parse_webhook,
    verify_signature,
)

router = APIRouter(prefix="/api/v1", tags=["whatsapp"])

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "raah-verify")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")


# --------------------------- webhook ---------------------------------

@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
):
    """
    Meta's subscription handshake. These arrive as QUERY parameters, and
    Meta expects the raw challenge string echoed back as plain text -- not
    JSON, or the subscription silently fails to verify.
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge or "")
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhooks/whatsapp")
async def receive_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()

    if not verify_signature(
        APP_SECRET, raw, request.headers.get("X-Hub-Signature-256")
    ):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    events = parse_webhook(payload)

    # Meta expects a 200 within seconds and retries otherwise, so the
    # actual work happens after the response is returned.
    background.add_task(_process_events, events)

    return {"status": "received", "event_count": len(events)}


def _process_events(events: list[dict]) -> None:
    client = get_client()

    for event in events:
        if event.get("kind") == "status":
            store.record_event(
                f"whatsapp_{event.get('status')}",
                phone=event.get("phone"),
                payload={"message_id": event.get("message_id")},
            )
            continue

        phone = event.get("phone")
        if not phone:
            continue

        message_id = event.get("message_id")
        if message_id and store.already_processed(message_id):
            continue

        store.log_message(phone, "inbound", event.get("text"), message_id)

        media_url = None
        if event.get("media_id"):
            media_url = client.download_media(event["media_id"])

        reply = whatsapp_flow.handle_message(
            phone=phone,
            text=event.get("text"),
            media_url=media_url,
            media_type=event.get("media_type"),
        )

        for body in reply.messages:
            client.send_text(phone, body)


@router.post("/whatsapp/simulate")
async def simulate(request: SimulateMessageRequest):
    """
    Drive the flow without a WhatsApp account. Same code path the webhook
    uses, so a demo proves the real funnel rather than a mock of it.
    """
    reply = whatsapp_flow.handle_message(
        phone=request.phone,
        text=request.text,
        media_url=request.media_url,
        media_type=request.media_type,
    )
    return {
        "phone": request.phone,
        "state": reply.state,
        "lead_id": reply.lead_id,
        "terminal": reply.terminal,
        "messages": reply.messages,
    }


@router.get("/whatsapp/session/{phone}")
async def get_session(phone: str):
    session = store.get_session(phone)
    if not session:
        raise HTTPException(status_code=404, detail="no active session")
    return session


@router.delete("/whatsapp/session/{phone}")
async def reset_session(phone: str):
    store.delete_session(phone)
    return {"status": "reset", "phone": phone}


@router.get("/whatsapp/transcript/{phone}")
async def transcript(phone: str, limit: int = 100):
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT direction, body, created_at FROM messages"
            " WHERE phone=? ORDER BY id ASC LIMIT ?",
            (phone, limit),
        ).fetchall()
        return {
            "phone": phone,
            "messages": [dict(r) for r in rows],
        }
    finally:
        conn.close()


# --------------------------- partners --------------------------------

@router.get("/partners")
async def list_partners():
    registry = partner_engine.get_registry()
    return {
        "count": len(registry.partners),
        "partners": [p.__dict__ for p in registry.partners],
    }


@router.post("/partners/reload")
async def reload_partners():
    partner_engine.get_registry().reload()
    return {"status": "reloaded"}


@router.post("/partners/route")
async def route(request: PartnerRouteRequest):
    lead = store.get_lead(request.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    result = partner_engine.route_lead(
        lead_id=request.lead_id,
        segment=request.segment,
        capacity_kw=request.capacity_kw,
        pincode=request.pincode or lead.get("pincode"),
        latitude=lead.get("latitude"),
        longitude=lead.get("longitude"),
        exclude_partner_ids=request.exclude_partner_ids,
    )

    lead["status"] = "assigned" if result["routed"] else "awaiting_partner"
    lead["partner_id"] = result.get("partner_id")
    store.upsert_lead(lead)
    return result


@router.get("/partners/scorecard")
async def scorecard(window_days: int = 30):
    return {"window_days": window_days,
            "partners": tracking_engine.partner_scorecard(window_days)}


# --------------------------- analytics -------------------------------

@router.get("/analytics/leakage")
async def leakage(stale_hours: float = 48.0):
    return tracking_engine.detect_leakage(stale_hours=stale_hours)


@router.get("/analytics/funnel")
async def funnel(window_days: int = 90):
    return tracking_engine.funnel_metrics(window_days)


@router.post("/analytics/retrain")
async def retrain(min_samples: int = 30):
    """
    Closed loop: pull terminal outcomes out of the event log and refit the
    policy. Returns the prior when there is not enough history, which is
    the honest answer on day one.
    """
    rows = tracking_engine.training_rows()
    return PolicyLearner().learn(
        rows=rows, target="funded", min_samples=min_samples
    )


@router.get("/analytics/events")
async def events(lead_id: str | None = None, event_type: str | None = None,
                 limit: int = 200):
    return {"events": store.list_events(lead_id, event_type, limit)}