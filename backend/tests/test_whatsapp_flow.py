"""Funnel tests. No WhatsApp account or network required."""
import os, tempfile
os.environ.setdefault("RAAH_DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))

import pytest
from app import store
from app.engines import whatsapp_flow as wf
from app.engines.subsidy_engine import residential_subsidy, accelerated_depreciation_benefit
from app.engines.offer_engine import build_offer, recommend_capacity_kw
from app.providers.whatsapp_client import parse_webhook, verify_signature


@pytest.fixture(autouse=True)
def _clean():
    store.reset_db()
    yield


def drive(phone, turns):
    r = wf.handle_message(phone)
    for t in turns:
        media = None
        if isinstance(t, tuple):
            t, media = t
        r = wf.handle_message(phone, t, media_url=media)
        if r.terminal:
            break
    return r


def test_subsidy_caps_at_three_kw():
    assert residential_subsidy(3)["total_subsidy_rs"] == 78000
    assert residential_subsidy(10)["total_subsidy_rs"] == 78000
    assert residential_subsidy(2)["total_subsidy_rs"] == 60000
    assert residential_subsidy(1)["total_subsidy_rs"] == 30000


def test_ad_half_rate_when_under_180_days():
    full = accelerated_depreciation_benefit(1_000_000, True)
    half = accelerated_depreciation_benefit(1_000_000, False)
    assert half["year1_tax_shield_rs"] == pytest.approx(
        full["year1_tax_shield_rs"] / 2
    )


def test_sizing_respects_sanctioned_load():
    out = recommend_capacity_kw("residential", 20000, 50.0, 5.0, 1450)
    assert out["recommended_capacity_kw"] == 5.0
    assert out["binding_constraint"] == "sanctioned_load_limited_kw"


def test_rented_roof_dropped_before_any_solar_math():
    r = drive("911", ["1", "1", "2"])
    assert r.state == wf.DROPPED
    assert r.lead_id is None          # no lead created
    events = store.list_events()
    assert any(e["event_type"] == "dropped_in_conversation" for e in events)


def test_low_consumption_dropped_without_field_visit():
    r = drive("912", ["1", "1", "1", "110001", "400", "2", "300 310 290", "skip"])
    assert r.state == wf.DROPPED


def test_viable_residential_lead_routes_to_partner():
    r = drive("913", ["1", "1", "1", "302015", "700", "5",
                      "2400 2250 2500", "skip", "1"])
    assert r.state == wf.DONE
    lead = store.get_lead(r.lead_id)
    assert lead["status"] == "assigned"
    assert lead["partner_id"] == "EPC-JAI-001"
    assert lead["offer"]["capex_option"]["subsidy_rs"] > 0
    assert lead["net_monthly_benefit_rs"] > 0


def test_sme_offer_includes_capex_and_opex():
    r = drive("914", ["1", "2", "1", "302015", "9000", "150",
                      "180000 175000 190000", "1", "8", (None, "u://p.jpg")])
    lead = store.get_lead(r.lead_id)
    assert "opex_option" in lead["offer"]
    assert lead["offer"]["comparison"]["recommendation"] in {"capex", "opex_resco"}


def test_language_persists_across_turns():
    wf.handle_message("915")
    wf.handle_message("915", "2")          # Hindi
    r = wf.handle_message("915", "1")
    assert store.get_session("915")["language"] == "hi"
    assert "छत" in r.messages[0]


def test_three_bad_replies_hands_off_to_human():
    wf.handle_message("916")
    for _ in range(3):
        r = wf.handle_message("916", "@@@")
    assert any(e["event_type"] == "human_handoff_auto"
               for e in store.list_events())


def test_restart_command_resets_but_keeps_language():
    wf.handle_message("917")
    wf.handle_message("917", "2")
    r = wf.handle_message("917", "restart")
    assert r.state == wf.ASK_LANGUAGE
    assert store.get_session("917")["language"] == "hi"


def test_webhook_parses_real_meta_payload():
    events = parse_webhook({"entry": [{"changes": [{"value": {"messages": [
        {"id": "w1", "from": "91", "type": "text", "text": {"body": "hi"}},
        {"id": "w2", "from": "91", "type": "image",
         "image": {"id": "M", "mime_type": "image/jpeg"}},
    ]}}]}]})
    assert events[0]["text"] == "hi"
    assert events[1]["media_id"] == "M"


def test_signature_rejects_tampering():
    import hmac, hashlib
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert verify_signature("s", body, good)
    assert not verify_signature("s", body, "sha256=bad")


def test_duplicate_webhook_is_ignored():
    assert store.already_processed("wamid.X") is False
    assert store.already_processed("wamid.X") is True
