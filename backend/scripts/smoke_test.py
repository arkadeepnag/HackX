#!/usr/bin/env python3
"""
Pre-integration smoke test.

Exercises every subsystem against a running server and prints a PASS/FAIL
line per check. Run this before wiring the frontend or merging modules 1-2 --
it catches the integration-level breakages that unit tests cannot see
(routing not mounted, DB not writable, geo data unreadable).

    uvicorn app.main:app &            # terminal 1
    python scripts/smoke_test.py      # terminal 2

    python scripts/smoke_test.py --base-url http://localhost:8000 \
        --buildings demo_data/buildings.geojson \
        --parcels demo_data/parcels.geojson
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import requests

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    results.append((PASS if condition else FAIL, name, detail))
    marker = "\033[92m✓\033[0m" if condition else "\033[91m✗\033[0m"
    print(f"  {marker} {name}" + (f"  — {detail}" if detail else ""))
    return condition


def skip(name: str, reason: str) -> None:
    results.append((SKIP, name, reason))
    print(f"  \033[93m–\033[0m {name}  — skipped: {reason}")


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--buildings", default="demo_data/buildings.geojson")
    parser.add_argument("--parcels", default="demo_data/parcels.geojson")
    parser.add_argument("--lat", type=float, default=26.9124)
    parser.add_argument("--lon", type=float, default=75.7873)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    api = f"{base}/api/v1"
    phone = f"9199{uuid.uuid4().int % 10**8:08d}"

    # ---------------------------------------------------------------
    section("1. Service reachable")
    try:
        health = requests.get(f"{base}/health", timeout=5)
    except requests.RequestException as exc:
        print(f"  \033[91m✗\033[0m cannot reach {base} — {exc}")
        print("\n  Is the server running?  uvicorn app.main:app")
        return 1

    check("health endpoint", health.status_code == 200)
    spec = requests.get(f"{base}/openapi.json", timeout=10).json()
    paths = spec.get("paths", {})
    check("routers mounted", len(paths) >= 35, f"{len(paths)} paths")
    for required in ("/api/v1/heatmap/cluster", "/api/v1/learning/mistakes",
                     "/api/v1/partner-portal/{partner_id}/leads",
                     "/api/v1/webhooks/whatsapp"):
        check(f"route present {required}", required in paths)

    # ---------------------------------------------------------------
    section("2. WhatsApp webhook contract")
    verify = requests.get(f"{api}/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "raah-verify",
        "hub.challenge": "SMOKE123"}, timeout=5)
    check("verify returns raw challenge as text",
          verify.status_code == 200 and verify.text.strip('"') == "SMOKE123",
          f"got {verify.status_code} {verify.text[:40]!r}")
    bad = requests.get(f"{api}/webhooks/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong",
        "hub.challenge": "X"}, timeout=5)
    check("verify rejects a wrong token", bad.status_code == 403)

    payload = {"entry": [{"changes": [{"value": {"messages": [{
        "id": f"wamid.{uuid.uuid4().hex[:12]}", "from": phone,
        "type": "text", "text": {"body": "hi"}}]}}]}]}
    hook = requests.post(f"{api}/webhooks/whatsapp", json=payload, timeout=10)
    check("nested Meta payload accepted",
          hook.status_code == 200 and hook.json().get("event_count") == 1)

    # ---------------------------------------------------------------
    section("3. Conversational funnel (residential, viable)")
    convo = ["hi", "1", "1", "1", "302015", "700", "5",
             "2400 2250 2500", "skip", "1"]
    reply = {}
    for message in convo:
        response = requests.post(f"{api}/whatsapp/simulate",
                                 json={"phone": phone, "text": message},
                                 timeout=20)
        if response.status_code != 200:
            check("funnel turn accepted", False,
                  f"{response.status_code} at {message!r}")
            break
        reply = response.json()

    lead_id = reply.get("lead_id")
    check("funnel reaches done", reply.get("state") == "done",
          f"state={reply.get('state')}")
    check("lead created", bool(lead_id), str(lead_id))

    if lead_id:
        lead = requests.get(f"{api}/leads/{lead_id}", timeout=10).json()
        offer = (lead.get("offer") or {}).get("capex_option", {})
        check("subsidy applied", offer.get("subsidy_rs", 0) > 0,
              f"Rs {offer.get('subsidy_rs')}")
        check("net-of-EMI computed",
              lead.get("net_monthly_benefit_rs") is not None,
              f"Rs {lead.get('net_monthly_benefit_rs')}")
        check("routed to a partner", bool(lead.get("partner_id")),
              str(lead.get("partner_id")))
        transcript = requests.get(
            f"{api}/whatsapp/transcript/{phone}", timeout=10).json()
        check("transcript persisted",
              len(transcript.get("messages", [])) > 5,
              f"{len(transcript.get('messages', []))} messages")

    # ---------------------------------------------------------------
    section("4. Disqualification (rented roof)")
    rented = f"9198{uuid.uuid4().int % 10**8:08d}"
    drop = {}
    for message in ["hi", "1", "1", "2"]:
        drop = requests.post(f"{api}/whatsapp/simulate",
                             json={"phone": rented, "text": message},
                             timeout=10).json()
    check("rented roof dropped", drop.get("state") == "dropped")
    check("no lead created for dropped roof", drop.get("lead_id") is None)

    # ---------------------------------------------------------------
    section("5. Leads API")
    listing = requests.get(f"{api}/leads?limit=5&offset=0", timeout=10).json()
    check("pagination fields present",
          {"total", "limit", "offset", "has_more"} <= set(listing))
    check("leads returned", listing.get("total", 0) > 0,
          f"total={listing.get('total')}")

    # ---------------------------------------------------------------
    section("6. Geospatial + heatmap")
    missing = [p for p in (args.buildings, args.parcels)
               if "://" not in p and not Path(p).exists()]
    if missing:
        print(f"  \033[93m!\033[0m demo data not found: {', '.join(missing)}")
        print("    run:  python scripts/make_demo_data.py")
    heat = requests.post(f"{api}/heatmap/cluster", json={
        "latitude": args.lat, "longitude": args.lon, "radius_m": 1500,
        "building_source": args.buildings,
        "cadastral_source": args.parcels, "mode": "both"}, timeout=120)

    if heat.status_code == 400:
        detail = heat.json().get("detail", "")
        skip("heatmap", detail[:150])
        skip("cadastral join", "no geo data")
    elif heat.status_code != 200:
        check("heatmap", False, f"HTTP {heat.status_code}")
    else:
        data = heat.json()
        grid = data.get("grid", {}).get("summary", {})
        cad = data.get("cadastral", {}).get("summary", {})
        check("grid cells produced", grid.get("cell_count", 0) > 0,
              f"{grid.get('cell_count')} cells, "
              f"{grid.get('total_addressable_mw')} MW")
        check("grid GeoJSON valid",
              data["grid"].get("type") == "FeatureCollection")
        check("cadastral parcels produced", cad.get("parcel_count", 0) > 0,
              f"{cad.get('parcel_count')} parcels")
        check("cadastral columns resolved",
              bool((cad.get("resolved_columns") or {}).get("parcel_id")),
              str(cad.get("resolved_columns")))
        check("unmatched buildings reported",
              "unmatched_buildings" in cad,
              f"{cad.get('unmatched_buildings')} unmatched")

    geo = requests.get(f"{api}/heatmap/leads", params={
        "min_lon": 60, "min_lat": 5, "max_lon": 100, "max_lat": 40},
        timeout=20).json()
    check("lead GeoJSON layer responds",
          geo.get("type") == "FeatureCollection",
          f"{geo.get('summary', {}).get('returned')} points, "
          f"{geo.get('summary', {}).get('leads_without_coordinates')} "
          f"without coords")

    # ---------------------------------------------------------------
    section("7. Tracking, leakage, partners")
    if lead_id:
        track = requests.post(f"{api}/tracking/evaluate", json={
            "lead_id": lead_id, "status": "contacted",
            "timestamp": "2026-09-11T10:00:00Z",
            "partner_id": "EPC-JAI-001", "contract_sla_hours": 24},
            timeout=10).json()
        check("lifecycle event recorded", track.get("status") == "contacted")

    leakage = requests.get(f"{api}/analytics/leakage", timeout=20).json()
    check("leakage buckets present",
          {"untouched", "stalled", "unrouted"} <= set(leakage),
          f"untouched={leakage.get('untouched_count')} "
          f"stalled={leakage.get('stalled_count')} "
          f"unrouted={leakage.get('unrouted_count')}")

    partners = requests.get(f"{api}/partners", timeout=10).json()
    check("partner registry loaded", partners.get("count", 0) > 0,
          f"{partners.get('count')} partners")

    portal = requests.get(
        f"{api}/partner-portal/EPC-JAI-001/leads?limit=3", timeout=10)
    check("partner portal responds", portal.status_code == 200)
    if portal.status_code == 200 and portal.json().get("leads"):
        first = portal.json()["leads"][0]
        check("partner portal hides internal scores",
              not any(k in first for k in
                      ("propensity_score", "financing_score", "solar_score")))
    check("unknown partner rejected",
          requests.get(f"{api}/partner-portal/NOPE/leads",
                       timeout=10).status_code == 404)

    # ---------------------------------------------------------------
    section("8. Closed-loop learning")
    funnel = requests.get(f"{api}/analytics/funnel", timeout=20).json()
    check("funnel metrics present", "funnel" in funnel,
          f"cost/funded={funnel.get('cost_per_funded_customer_rs')}")

    mistakes = requests.get(f"{api}/learning/mistakes", timeout=20).json()
    check("mistake analysis responds",
          {"false_positives", "false_negatives", "bias"} <= set(mistakes),
          f"FP={mistakes.get('false_positives')} "
          f"FN={mistakes.get('false_negatives')} "
          f"bias={mistakes.get('bias')}")

    learned = requests.post(f"{api}/learning/run", timeout=60).json()
    check("learning cycle completes", "mode" in learned,
          f"mode={learned.get('mode')} n={learned.get('sample_count')}")

    applied = requests.post(f"{api}/learning/apply",
                            json={"propensity_score": 75}, timeout=10).json()
    check("adjustment returns a reason", bool(applied.get("reason")),
          applied.get("reason", "")[:60])

    # ---------------------------------------------------------------
    passed = sum(1 for r, _, _ in results if r == PASS)
    failed = sum(1 for r, _, _ in results if r == FAIL)
    skipped = sum(1 for r, _, _ in results if r == SKIP)

    print(f"\n{'=' * 58}")
    print(f"  {passed} passed   {failed} failed   {skipped} skipped")
    print(f"{'=' * 58}")

    if failed:
        print("\nFailures:")
        for status, name, detail in results:
            if status == FAIL:
                print(f"  - {name}  {detail}")
        return 1

    print("\nBackend is ready for integration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
