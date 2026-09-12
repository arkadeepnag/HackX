"""
Vernacular WhatsApp qualification flow.

Design rules, taken straight from the problem statement:

1. Disqualifiers first. Ownership is asked before anything expensive is
   computed, because a rented roof kills the deal regardless of how good
   the irradiance is. Cheap questions that can end the conversation go
   before costly ones that cannot.
2. Drop out unviable leads without a field visit, and tell the customer
   the real reason. A clean "no" now is cheaper than a truck roll later.
3. Every reply is pure: handle_message() returns the outbound messages and
   the new state. It never touches the network, so the whole funnel is
   unit-testable without a WhatsApp account.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app import store
from app.engines.offer_engine import (
    OfferAssumptions,
    build_offer,
    recommend_capacity_kw,
)
from app.engines import partner_engine
from app.i18n.messages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    drop_reason,
    format_inr,
    t,
)

SESSION_TTL_HOURS = 72

# ------------------------------ states -------------------------------

ASK_LANGUAGE = "ask_language"
ASK_SEGMENT = "ask_segment"
ASK_OWNERSHIP = "ask_ownership"
ASK_PINCODE = "ask_pincode"
ASK_ROOF_AREA = "ask_roof_area"
ASK_SANCTIONED_LOAD = "ask_sanctioned_load"
ASK_BILLS = "ask_bills"
ASK_GST = "ask_gst"
ASK_VINTAGE = "ask_vintage"
ASK_PHOTO = "ask_photo"
ASK_CONSENT = "ask_consent"
DONE = "done"
DROPPED = "dropped"
PARKED = "parked"

LANGUAGE_BY_INDEX = ["en", "hi", "mr", "gu", "ta"]

# ---------------------------- parsing --------------------------------

AFFIRMATIVE = {
    "1", "yes", "y", "ok", "okay", "yeah", "yep", "own", "owned", "sure",
    "haan", "ha", "han", "हाँ", "हा", "होय", "હા", "ஆம்", "ஆமாம்",
}
NEGATIVE = {
    "2", "no", "n", "nope", "rent", "rented", "not", "nahi", "nahin",
    "नहीं", "नाही", "ના", "இல்லை",
}
DONT_KNOW = {
    "dont know", "don't know", "dontknow", "idk", "not sure", "no idea",
    "pata nahi", "पता नहीं", "माहीत नाही", "ખબર નથી", "தெரியாது", "skip",
}

CMD_RESTART = {"restart", "reset", "start over", "फिर से", "पुन्हा", "ફરીથી"}
CMD_HELP = {"help", "support", "agent", "मदद", "मदत", "મદદ", "உதவி"}
CMD_RESUME = {"resume", "continue", "आगे", "पुढे", "આગળ", "தொடர்"}
CMD_NO_CONTACT = {"no contact", "nocontact", "no call", "koi call nahi"}
CMD_CHECK_AGAIN = {"check again", "checkagain", "recheck"}
CMD_OWNER_OK = {"owner ok", "ownerok", "owner consent", "malik ok"}


def _normalise(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _choice(text: str) -> int | None:
    """Extract a 1-based menu choice."""
    stripped = _normalise(text)
    match = re.match(r"^([1-9])\b", stripped)
    return int(match.group(1)) if match else None


def _is_yes(text: str) -> bool | None:
    stripped = _normalise(text)
    if stripped in AFFIRMATIVE:
        return True
    if stripped in NEGATIVE:
        return False
    return None


def _is_dont_know(text: str) -> bool:
    return _normalise(text) in DONT_KNOW


def _number(text: str) -> float | None:
    """First number in the message, tolerating commas and units."""
    cleaned = (text or "").replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(match.group(1)) if match else None


def _numbers(text: str) -> list[float]:
    cleaned = (text or "").replace(",", "")
    return [float(n) for n in re.findall(r"\d+(?:\.\d+)?", cleaned)]


def _pincode(text: str) -> str | None:
    match = re.search(r"\b(\d{6})\b", (text or "").replace(" ", ""))
    return match.group(1) if match else None


# ------------------------- flow configuration ------------------------

@dataclass
class FlowConfig:
    # Screening thresholds. A lead failing any of these is dropped
    # in-conversation rather than sent to a field team.
    min_capacity_kw: float = 1.0
    min_monthly_consumption_kwh_residential: float = 100.0
    min_monthly_consumption_kwh_ci: float = 500.0
    max_payback_years: float = 8.0
    require_positive_net_monthly: bool = True

    # Roof area -> capacity
    sqft_per_kw: float = 90.0
    usable_fraction_residential: float = 0.70
    usable_fraction_ci: float = 0.80

    # Fallback roof area when the customer does not know (sq ft)
    assumed_roof_sqft_residential: float = 600.0
    assumed_roof_sqft_ci: float = 5000.0

    default_specific_yield_kwh_per_kw: float = 1450.0
    default_tariff_residential: float = 7.0
    default_tariff_ci: float = 9.0

    assumptions: OfferAssumptions = field(default_factory=OfferAssumptions)


DEFAULT_CONFIG = FlowConfig()

# An estimator resolves site-specific solar and tariff inputs for a
# pincode. The default is a coarse national fallback; wire the real one
# (module 1-2 building footprints + solar_engine) via set_estimator().
Estimator = Callable[[dict], dict]


def _default_estimator(context: dict) -> dict:
    return {
        "specific_yield_kwh_per_kw": DEFAULT_CONFIG.default_specific_yield_kwh_per_kw,
        "tariff_rs_kwh": (
            DEFAULT_CONFIG.default_tariff_residential
            if context.get("segment") == "residential"
            else DEFAULT_CONFIG.default_tariff_ci
        ),
        "state": None,
        "latitude": None,
        "longitude": None,
        "shading_loss_pct": 12.0,
        "source": "national_fallback",
    }


_estimator: Estimator | None = None
_estimator_explicit = False


def set_estimator(fn: Estimator) -> None:
    """Inject a custom geo/solar estimator."""
    global _estimator, _estimator_explicit
    _estimator = fn
    _estimator_explicit = True


def _resolve_estimator() -> Estimator:
    """
    Lazily build the real pincode-backed estimator on first use.

    Deliberately not left to application startup: a lifespan hook is
    skipped by TestClient and by any script that imports the flow
    directly, which silently downgrades every lead to the national
    fallback. Resolving here means the flow behaves the same however it
    is entered.
    """
    global _estimator
    if _estimator is not None:
        return _estimator
    try:
        from app.engines.ingest_engine import build_estimator
        _estimator = build_estimator()
    except Exception:
        _estimator = _default_estimator
    return _estimator


# ----------------------------- messages ------------------------------

@dataclass
class Reply:
    messages: list[str]
    state: str
    lead_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    terminal: bool = False


def _msg(*parts: str) -> list[str]:
    return [p for p in parts if p]


# ------------------------------ session ------------------------------

def _new_session(phone: str) -> dict:
    return {
        "phone": phone,
        "state": ASK_LANGUAGE,
        "language": DEFAULT_LANGUAGE,
        "lead_id": None,
        "context": {"retries": 0},
    }


def _expired(session: dict) -> bool:
    updated = session.get("updated_at")
    if not updated:
        return False
    try:
        last = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last > timedelta(hours=SESSION_TTL_HOURS)


# ------------------------- main entry point --------------------------

def handle_message(
    phone: str,
    text: str | None = None,
    media_url: str | None = None,
    media_type: str | None = None,
    config: FlowConfig = DEFAULT_CONFIG,
) -> Reply:
    """
    Advance the conversation by one turn. Pure with respect to the network;
    reads and writes only the store.
    """
    session = store.get_session(phone)

    if session and _expired(session) and session["state"] not in {DONE, DROPPED}:
        language = session.get("language") or DEFAULT_LANGUAGE
        session = _new_session(phone)
        session["language"] = language
        store.save_session(session)
        return _emit(session, _msg(
            t(language, "session_expired"), t(language, "ask_language")
        ), ASK_LANGUAGE)

    if session is None:
        session = _new_session(phone)
        store.save_session(session)
        return _emit(session, _msg(t(DEFAULT_LANGUAGE, "ask_language")), ASK_LANGUAGE)

    language = session.get("language") or DEFAULT_LANGUAGE
    context = session.get("context") or {}
    stripped = _normalise(text)

    # ---- global commands, valid in any state ----
    if stripped in CMD_RESTART:
        language = session.get("language") or DEFAULT_LANGUAGE
        session = _new_session(phone)
        session["language"] = language
        store.save_session(session)
        return _emit(session, _msg(
            t(language, "restart"), t(language, "ask_language")
        ), ASK_LANGUAGE)

    if stripped in CMD_HELP:
        store.record_event("human_handoff_requested", phone=phone,
                           lead_id=session.get("lead_id"))
        return _emit(session, _msg(t(language, "help")), session["state"])

    if stripped in CMD_NO_CONTACT and session.get("lead_id"):
        lead_id = session["lead_id"]
        store.record_event("contact_sla_complaint", lead_id=lead_id, phone=phone)
        return _emit(session, _msg(
            t(language, "escalated", lead_id=lead_id, sla_hours=4)
        ), session["state"])

    if stripped in CMD_RESUME and session["state"] == PARKED:
        session["state"] = ASK_CONSENT
        store.save_session(session)
        return _emit(session, _msg(
            t(language, "resume"), t(language, "ask_consent")
        ), ASK_CONSENT)

    if stripped in CMD_CHECK_AGAIN and session["state"] == DROPPED:
        language = session.get("language") or DEFAULT_LANGUAGE
        session = _new_session(phone)
        session["language"] = language
        session["state"] = ASK_SEGMENT
        store.save_session(session)
        return _emit(session, _msg(t(language, "ask_segment")), ASK_SEGMENT)

    if stripped in CMD_OWNER_OK and session["state"] == DROPPED:
        context["owned_roof"] = True
        context["owner_consent_declared"] = True
        session["context"] = context
        session["state"] = ASK_PINCODE
        store.save_session(session)
        store.record_event("owner_consent_declared", phone=phone)
        return _emit(session, _msg(t(language, "ask_pincode")), ASK_PINCODE)

    state = session["state"]

    if state in {DONE, DROPPED, PARKED}:
        # Conversation has concluded; stay quiet rather than restarting
        # an unwanted funnel, but leave the documented escape hatches.
        return _emit(session, [], state, terminal=True)

    handler = _HANDLERS.get(state)
    if handler is None:
        return _emit(session, _msg(t(language, "fallback", retry="")), state)

    return handler(session, text, stripped, media_url, media_type, config)


def _emit(session, messages, state, terminal=False, lead_id=None) -> Reply:
    for body in messages:
        store.log_message(session["phone"], "outbound", body)
    return Reply(
        messages=messages,
        state=state,
        lead_id=lead_id or session.get("lead_id"),
        context=session.get("context", {}),
        terminal=terminal,
    )


def _advance(session, state, messages, config=None) -> Reply:
    session["state"] = state
    session["context"]["retries"] = 0
    store.save_session(session)
    return _emit(session, messages, state)


def _retry(session, prompt_key, language, **kwargs) -> Reply:
    """
    Re-ask after an unparseable reply. After three failures the lead is
    handed to a human instead of looping the customer forever.
    """
    context = session["context"]
    context["retries"] = context.get("retries", 0) + 1

    if context["retries"] >= 3:
        store.save_session(session)
        store.record_event("human_handoff_auto", phone=session["phone"],
                           payload={"stuck_at": session["state"]})
        return _emit(session, _msg(t(language, "help")), session["state"])

    store.save_session(session)
    retry_text = t(language, prompt_key, **kwargs)
    return _emit(session, _msg(t(language, "fallback", retry=retry_text)),
                 session["state"])


# ---------------------------- handlers -------------------------------

def _h_language(session, text, stripped, media_url, media_type, config):
    choice = _choice(stripped)
    language = None

    if choice and 1 <= choice <= len(LANGUAGE_BY_INDEX):
        language = LANGUAGE_BY_INDEX[choice - 1]
    else:
        for code, name in LANGUAGES.items():
            if stripped in {code, name.lower()}:
                language = code
                break

    if not language:
        return _retry(session, "ask_language", session.get("language", DEFAULT_LANGUAGE))

    session["language"] = language
    return _advance(session, ASK_SEGMENT, _msg(t(language, "ask_segment")))


def _h_segment(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    choice = _choice(stripped)

    if choice == 1 or "home" in stripped or "घर" in stripped or "வீடு" in stripped:
        segment = "residential"
    elif choice == 2 or any(
        w in stripped for w in ("business", "factory", "shop", "office",
                                "व्यापार", "फैक्ट्री", "दुकान", "કારખાન")
    ):
        segment = "commercial"
    else:
        return _retry(session, "ask_segment", language)

    session["context"]["segment"] = segment
    return _advance(session, ASK_OWNERSHIP, _msg(t(language, "ask_ownership")))


def _h_ownership(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    answer = _is_yes(stripped)

    if answer is None:
        return _retry(session, "ask_ownership", language)

    if answer is False:
        # The cheapest possible disqualification: no engineer dispatched,
        # no solar calculation run, and the customer is told exactly why.
        session["context"]["owned_roof"] = False
        session["state"] = DROPPED
        store.save_session(session)
        store.record_event("dropped_in_conversation", phone=session["phone"],
                           payload={"reason": "rented_roof", "stage": "ownership"})
        return _emit(session, _msg(t(language, "disqualify_rented")),
                     DROPPED, terminal=True)

    session["context"]["owned_roof"] = True
    return _advance(session, ASK_PINCODE, _msg(t(language, "ask_pincode")))


def _h_pincode(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    pincode = _pincode(text or "")

    if not pincode:
        return _retry(session, "invalid_pincode", language)

    session["context"]["pincode"] = pincode
    return _advance(session, ASK_ROOF_AREA, _msg(t(language, "ask_roof_area")))


def _h_roof_area(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    segment = session["context"].get("segment", "residential")

    if _is_dont_know(stripped):
        assumed = (
            config.assumed_roof_sqft_residential
            if segment == "residential"
            else config.assumed_roof_sqft_ci
        )
        session["context"]["roof_area_sqft"] = assumed
        session["context"]["roof_area_assumed"] = True
        return _advance(session, ASK_SANCTIONED_LOAD, _msg(
            t(language, "dont_know_ack"), t(language, "ask_sanctioned_load")
        ))

    area = _number(text or "")
    if area is None or area <= 0:
        return _retry(session, "ask_roof_area", language)

    session["context"]["roof_area_sqft"] = area
    session["context"]["roof_area_assumed"] = False
    return _advance(session, ASK_SANCTIONED_LOAD,
                    _msg(t(language, "ask_sanctioned_load")))


def _h_sanctioned_load(session, text, stripped, media_url, media_type, config):
    language = session["language"]

    if _is_dont_know(stripped):
        session["context"]["sanctioned_load_kw"] = None
        return _advance(session, ASK_BILLS, _msg(
            t(language, "dont_know_ack"), t(language, "ask_bills")
        ))

    load = _number(text or "")
    if load is None or load <= 0:
        return _retry(session, "ask_sanctioned_load", language)

    session["context"]["sanctioned_load_kw"] = load
    return _advance(session, ASK_BILLS, _msg(t(language, "ask_bills")))


def _h_bills(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    bills = [b for b in _numbers(text or "") if b > 0]

    if not bills:
        return _retry(session, "invalid_bills", language)

    session["context"]["bills"] = bills[:3]
    session["context"]["bill_count"] = len(bills[:3])

    if session["context"].get("segment") == "residential":
        return _advance(session, ASK_PHOTO, _msg(t(language, "ask_photo")))
    return _advance(session, ASK_GST, _msg(t(language, "ask_gst")))


def _h_gst(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    answer = _is_yes(stripped)

    if answer is None:
        return _retry(session, "ask_gst", language)

    session["context"]["gst_registered"] = answer
    return _advance(session, ASK_VINTAGE, _msg(t(language, "ask_vintage")))


def _h_vintage(session, text, stripped, media_url, media_type, config):
    language = session["language"]

    if _is_dont_know(stripped):
        session["context"]["business_vintage_years"] = None
    else:
        years = _number(text or "")
        if years is None:
            return _retry(session, "ask_vintage", language)
        session["context"]["business_vintage_years"] = years

    return _advance(session, ASK_PHOTO, _msg(t(language, "ask_photo")))


def _h_photo(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    context = session["context"]

    if media_url:
        context["roof_photo_url"] = media_url
        context["roof_photo_uploaded"] = True
        ack = t(language, "photo_received")
    elif _is_dont_know(stripped) or _is_yes(stripped) is False:
        context["roof_photo_uploaded"] = False
        ack = t(language, "photo_skipped")
    else:
        return _retry(session, "ask_photo", language)

    store.save_session(session)
    return _build_and_send_offer(session, ack, config)


def _h_consent(session, text, stripped, media_url, media_type, config):
    language = session["language"]
    answer = _is_yes(stripped)

    if answer is None:
        return _retry(session, "ask_consent", language)

    lead_id = session.get("lead_id")
    lead = store.get_lead(lead_id) if lead_id else None
    context = session["context"]

    if answer is False:
        session["state"] = PARKED
        store.save_session(session)
        store.record_event("consent_declined", lead_id=lead_id,
                           phone=session["phone"])
        if lead:
            lead["status"] = "nurture"
            store.upsert_lead(lead)
        return _emit(session, _msg(t(language, "declined", lead_id=lead_id)),
                     PARKED, terminal=True)

    routing = partner_engine.route_lead(
        lead_id=lead_id,
        segment=context.get("segment", "residential"),
        capacity_kw=context.get("capacity_kw", 0),
        pincode=context.get("pincode"),
        latitude=context.get("latitude"),
        longitude=context.get("longitude"),
    )

    if lead:
        lead["status"] = "assigned" if routing["routed"] else "awaiting_partner"
        lead["partner_id"] = routing.get("partner_id")
        store.upsert_lead(lead)

    session["state"] = DONE
    store.save_session(session)

    if not routing["routed"]:
        return _emit(session, _msg(t(
            language, "no_partner",
            pincode=context.get("pincode"), lead_id=lead_id
        )), DONE, terminal=True)

    return _emit(session, _msg(t(
        language, "routed",
        partner=routing["partner_name"],
        sla_hours=int(routing["contact_sla_hours"]),
        lead_id=lead_id,
    )), DONE, terminal=True)


# ------------------------- offer construction ------------------------

def _build_and_send_offer(session, ack: str, config: FlowConfig) -> Reply:
    """
    Run the viability + financing screen, then either drop the lead with a
    reason or return the instant offer.
    """
    language = session["language"]
    context = session["context"]
    segment = context.get("segment", "residential")

    site = _resolve_estimator()(context)
    context.update({
        "specific_yield_kwh_per_kw": site["specific_yield_kwh_per_kw"],
        "tariff_rs_kwh": site["tariff_rs_kwh"],
        "latitude": site.get("latitude"),
        "longitude": site.get("longitude"),
        "estimator_source": site.get("source"),
        "discom": site.get("discom"),
    })

    tariff = float(site["tariff_rs_kwh"])
    specific_yield = float(site["specific_yield_kwh_per_kw"])
    shading_loss = float(site.get("shading_loss_pct") or 0)

    # Roof area -> installable capacity
    usable_fraction = (
        config.usable_fraction_residential if segment == "residential"
        else config.usable_fraction_ci
    )
    roof_sqft = float(context.get("roof_area_sqft") or 0)
    roof_capacity_kw = (roof_sqft * usable_fraction) / config.sqft_per_kw

    # Bills -> consumption
    bills = context.get("bills") or []
    avg_bill = sum(bills) / len(bills) if bills else 0.0
    monthly_kwh = (avg_bill / tariff) if tariff > 0 else 0.0
    annual_kwh = monthly_kwh * 12
    context["monthly_consumption_kwh"] = round(monthly_kwh, 1)

    sizing = recommend_capacity_kw(
        segment=segment,
        annual_consumption_kwh=annual_kwh,
        roof_capacity_kw=roof_capacity_kw,
        sanctioned_load_kw=context.get("sanctioned_load_kw"),
        specific_yield_kwh_per_kw=specific_yield,
        assumptions=config.assumptions,
    )
    capacity_kw = sizing["recommended_capacity_kw"]
    context["capacity_kw"] = capacity_kw
    context["sizing"] = sizing

    # ---- screening, cheapest checks first ----
    min_consumption = (
        config.min_monthly_consumption_kwh_residential if segment == "residential"
        else config.min_monthly_consumption_kwh_ci
    )

    if monthly_kwh < min_consumption:
        return _drop(session, "low_consumption", ack, context)
    if roof_capacity_kw < config.min_capacity_kw:
        return _drop(session, "tiny_roof", ack, context)
    if shading_loss > 35:
        return _drop(session, "heavy_shading", ack, context)
    if capacity_kw < config.min_capacity_kw:
        return _drop(session, "tiny_roof", ack, context)

    annual_generation = capacity_kw * specific_yield * (1 - shading_loss / 100.0)

    offer = build_offer(
        segment=segment,
        capacity_kw=capacity_kw,
        annual_generation_kwh=annual_generation,
        annual_consumption_kwh=annual_kwh,
        tariff_rs_kwh=tariff,
        state=site.get("state"),
        sanctioned_load_kw=context.get("sanctioned_load_kw"),
        is_manufacturing=(segment == "industrial"),
        assumptions=config.assumptions,
    )
    capex = offer["capex_option"]

    if capex["payback_years"] > config.max_payback_years:
        return _drop(session, "poor_economics", ack, context)

    best_net_monthly = capex["net_monthly_benefit_rs"]
    if "opex_option" in offer:
        best_net_monthly = max(
            best_net_monthly, offer["opex_option"]["net_monthly_benefit_rs"]
        )
    if config.require_positive_net_monthly and best_net_monthly <= 0:
        return _drop(session, "emi_exceeds_savings", ack, context)

    # ---- survivor: persist the lead and present the offer ----
    lead_id = session.get("lead_id") or f"WA-{uuid.uuid4().hex[:10].upper()}"
    session["lead_id"] = lead_id
    context["offer"] = offer

    store.upsert_lead({
        "lead_id": lead_id,
        "phone": session["phone"],
        "pincode": context.get("pincode"),
        "latitude": context.get("latitude"),
        "longitude": context.get("longitude"),
        "location_source": context.get("estimator_source"),
        "discom": context.get("discom"),
        "segment": segment,
        "status": "qualified",
        "source": "whatsapp_conversational",
        "language": language,
        "capacity_kw": capacity_kw,
        "monthly_consumption_kwh": context["monthly_consumption_kwh"],
        "tariff_rs_kwh": tariff,
        "payback_years": capex["payback_years"],
        "irr_pct": capex["irr_pct"],
        "net_monthly_benefit_rs": capex["net_monthly_benefit_rs"],
        "annual_shading_loss_pct": shading_loss,
        "usable_roof_area_m2": round(roof_sqft * usable_fraction * 0.0929, 1),
        "qualification": {
            "owned_roof": context.get("owned_roof"),
            "sanctioned_load_kw": context.get("sanctioned_load_kw"),
            "bill_count": context.get("bill_count", 0),
            "roof_photo_uploaded": context.get("roof_photo_uploaded", False),
            "roof_photo_url": context.get("roof_photo_url"),
            "gst_registered": context.get("gst_registered"),
            "business_vintage_years": context.get("business_vintage_years"),
        },
        "offer": offer,
    })
    store.record_event("qualified", lead_id=lead_id, phone=session["phone"],
                       payload={"capacity_kw": capacity_kw,
                                "net_monthly_benefit_rs":
                                    capex["net_monthly_benefit_rs"]})

    offer_text = _render_offer(language, segment, offer, tariff,
                               annual_generation, config)

    session["state"] = ASK_CONSENT
    session["context"] = context
    store.save_session(session)

    return _emit(session, _msg(ack, offer_text, t(language, "ask_consent")),
                 ASK_CONSENT, lead_id=lead_id)


def _drop(session, reason_code: str, ack: str, context: dict) -> Reply:
    language = session["language"]
    session["state"] = DROPPED
    session["context"] = context
    store.save_session(session)
    store.record_event("dropped_in_conversation", phone=session["phone"],
                       payload={"reason": reason_code,
                                "capacity_kw": context.get("capacity_kw"),
                                "pincode": context.get("pincode")})
    return _emit(session, _msg(ack, t(
        language, "dropped_unviable", reason=drop_reason(language, reason_code)
    )), DROPPED, terminal=True)


def _render_offer(language, segment, offer, tariff, generation, config) -> str:
    capex = offer["capex_option"]

    if segment == "residential":
        return t(
            language, "offer_residential",
            capacity=capex["capacity_kw"],
            gross_capex=format_inr(capex["gross_capex_rs"]),
            subsidy=format_inr(capex["subsidy_rs"]),
            net_capex=format_inr(capex["net_capex_rs"]),
            emi=format_inr(capex["monthly_emi_rs"]),
            savings=format_inr(capex["monthly_savings_rs"]),
            net_benefit=format_inr(capex["net_monthly_benefit_rs"]),
            payback=capex["payback_years"],
        )

    opex = offer.get("opex_option", {})
    comparison = offer.get("comparison", {})
    ad = (capex.get("incentives") or {}).get("accelerated_depreciation") or {}

    return t(
        language, "offer_sme",
        capacity=capex["capacity_kw"],
        generation=format_inr(generation),
        gross_capex=format_inr(capex["gross_capex_rs"]),
        emi=format_inr(capex["monthly_emi_rs"]),
        savings=format_inr(capex["monthly_savings_rs"]),
        net_benefit=format_inr(capex["net_monthly_benefit_rs"]),
        tax_shield=format_inr(ad.get("year1_tax_shield_rs", 0)),
        irr=capex["irr_pct"],
        payback=capex["payback_years"],
        ppa_tariff=opex.get("ppa_tariff_rs_kwh", "-"),
        grid_tariff=round(tariff, 2),
        opex_benefit=format_inr(opex.get("net_monthly_benefit_rs", 0)),
        recommendation=(
            "CAPEX" if comparison.get("recommendation") == "capex" else "OPEX / PPA"
        ),
        rationale=comparison.get("rationale", ""),
    )


_HANDLERS = {
    ASK_LANGUAGE: _h_language,
    ASK_SEGMENT: _h_segment,
    ASK_OWNERSHIP: _h_ownership,
    ASK_PINCODE: _h_pincode,
    ASK_ROOF_AREA: _h_roof_area,
    ASK_SANCTIONED_LOAD: _h_sanctioned_load,
    ASK_BILLS: _h_bills,
    ASK_GST: _h_gst,
    ASK_VINTAGE: _h_vintage,
    ASK_PHOTO: _h_photo,
    ASK_CONSENT: _h_consent,
}