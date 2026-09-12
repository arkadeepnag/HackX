"""Module 1-2 ingestion seam, geocoding, and quadrant coverage."""
import os, tempfile
os.environ.setdefault("RAAH_DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))

import pytest
from app import store
from app.engines import whatsapp_flow as wf
from app.engines.ingest_engine import get_ingestor
from app.engines.scoring_engine import determine_routing_class
from app.models.schemas import SLAProfile
from app.providers.geocoder import get_geocoder


@pytest.fixture(autouse=True)
def _clean():
    store.reset_db()
    yield


def test_geocoder_resolves_exact_and_prefix():
    g = get_geocoder()
    exact = g.resolve("302015")
    assert exact["match"] == "exact" and exact["state"] == "RAJASTHAN"
    near = g.resolve("302099")
    assert near["match"].startswith("prefix") and near["confidence"] < 0.9
    assert g.resolve("999999") is None


def test_quadrant_has_no_gaps():
    """Every (propensity, financing) pair must land in exactly one class."""
    seen = set()
    for p in range(0, 101, 5):
        for f in range(0, 101, 5):
            cls = determine_routing_class(p, f)
            assert cls in {"high_priority", "high_propensity_finance_risk",
                           "low_propensity_financeable", "discard_or_nurture"}
            seen.add(cls)
    assert len(seen) == 4
    # the regression: above-bar propensity with strong financing is not a discard
    assert determine_routing_class(62, 100) == "high_priority"


def test_ingest_maps_foreign_column_names():
    records = [{
        "osm_id": "way/1", "lat": 26.9124, "lng": 75.7873,
        "footprint_area_m2": 1800, "pin_code": "302015",
        "building_class": "factory", "connected_load_kw": 150,
        "years_in_business": 7, "has_gst": True,
    }]
    out = get_ingestor().ingest(records, SLAProfile(), data_mode="offline")
    assert out["ingested"] == 1
    lead = out["leads"][0]
    assert lead["segment"] == "industrial"
    assert lead["latitude"] == 26.9124
    assert lead["capacity_kw"] > 0
    assert lead["qualification"]["gst_registered"] is True


def test_ingest_geocodes_records_without_coordinates():
    records = [{"id": "U-1", "pincode": "411001", "area_m2": 900,
                "type": "warehouse"}]
    out = get_ingestor().ingest(records, SLAProfile(), data_mode="offline")
    lead = out["leads"][0]
    assert lead["location_source"].startswith("pincode_")
    assert lead["latitude"] is not None


def test_ingest_reports_unlocatable_rows_with_a_reason():
    records = [{"id": "BAD", "area_m2": 500, "type": "shop"}]
    out = get_ingestor().ingest(records, SLAProfile(), data_mode="offline")
    assert out["ingested"] == 0 and out["skipped"] == 1
    assert "location" in out["skipped_detail"][0]["reason"]


def test_ingest_survives_one_bad_row():
    records = [
        {"id": "OK", "pincode": "302015", "area_m2": 500, "type": "house"},
        {"id": "UGLY", "pincode": "302015", "area_m2": "not-a-number",
         "type": "house"},
    ]
    out = get_ingestor().ingest(records, SLAProfile(), data_mode="offline")
    assert out["ingested"] + out["skipped"] == 2
    assert out["ingested"] >= 1


def test_whatsapp_lead_gets_coordinates_without_lifespan():
    """Regression: the estimator must resolve lazily, not only at startup."""
    phone = "919000111222"
    wf.handle_message(phone)
    reply = None
    for t in ["1", "1", "1", "302015", "700", "5",
              "2400 2250 2500", "skip", "1"]:
        reply = wf.handle_message(phone, t)
    lead = store.get_lead(reply.lead_id)
    assert lead["latitude"] is not None and lead["longitude"] is not None
    assert lead["location_source"] != "national_fallback"


# ---- module 1-2 contract (verified against target_universe.csv schema) ----

MODULE_12_ROW = {
    "building_id": "08b2f4a10001fff",
    "place_name": "Sitapura Textiles",
    "place_category": "manufacturer",
    "place_address": "Plot 14, Sitapura, Jaipur, 302022",
    "segment": "C&I",
    "building_area_m2": 3548.62,
    "latitude": 26.8498, "longitude": 75.8221,
    "industrial_cluster": "RIICO Sitapura",
    "industrial_cluster_match": True,
    "candidate_pincode": 302022,          # pandas reads this as int64
    "udyam_available": True, "mca_available": True, "gst_available": True,
    "candidate_rank": 1, "candidate_priority": 7,
    "discom": "JVVNL", "state": "Rajasthan",
}


def test_module_12_columns_all_resolve():
    from app.engines.ingest_engine import _pick, _as_bool
    r = MODULE_12_ROW
    assert _pick(r, "candidate_id") == "08b2f4a10001fff"
    assert _pick(r, "roof_area_m2") == 3548.62      # building_area_m2
    assert _pick(r, "entity_name") == "Sitapura Textiles"
    assert _pick(r, "address").startswith("Plot 14")
    assert _as_bool(_pick(r, "gst_registered")) is True


def test_ci_with_industrial_poi_becomes_industrial():
    """AD shield and C&I sizing only apply to a real factory."""
    from app.engines.ingest_engine import _normalise_segment
    assert _normalise_segment("C&I", MODULE_12_ROW) == "industrial"
    retail = {**MODULE_12_ROW, "place_category": "retail",
              "industrial_cluster_match": False}
    assert _normalise_segment("C&I", retail) == "commercial"
    assert _normalise_segment("Residential", {}) == "residential"


def test_unknown_segment_is_flagged_not_guessed():
    out = get_ingestor().ingest(
        [{**MODULE_12_ROW, "segment": "Unknown", "place_category": None,
          "industrial_cluster_match": False}],
        SLAProfile(), data_mode="offline")
    lead = out["leads"][0]
    assert lead["segment_unknown"] is True
    assert lead["next_action"] == "qualify_segment_via_whatsapp"


def test_integer_pincode_does_not_break_routing():
    """Regression: CSV pincodes arrive as int64 and have no .startswith."""
    out = get_ingestor().ingest([MODULE_12_ROW], SLAProfile(),
                                data_mode="offline", auto_route=True)
    assert out["ingested"] == 1
    assert out["leads"][0]["pincode"] == "302022"


def test_nan_does_not_leak_as_a_string():
    """Regression: pandas NaN is neither None nor '' and reached the UI."""
    from app.engines.ingest_engine import _pick
    row = {**MODULE_12_ROW, "place_name": float("nan"),
           "udyam_enterprise_name": "nan"}
    assert _pick(row, "entity_name") is None


def test_load_target_universe_csv(tmp_path):
    import pandas as pd
    from app.engines.ingest_engine import load_target_universe
    path = tmp_path / "target_universe.csv"
    pd.DataFrame([MODULE_12_ROW, {**MODULE_12_ROW,
                                  "building_id": "b2",
                                  "place_name": None}]).to_csv(path, index=False)
    rows = load_target_universe(str(path))
    assert len(rows) == 2
    out = get_ingestor().ingest(rows, SLAProfile(), data_mode="offline")
    assert out["ingested"] == 2
    assert all(l["latitude"] is not None for l in out["leads"])
