"""Coordinates, heatmap, learning-from-mistakes and partner portal."""
import json, os, random, tempfile
os.environ.setdefault("RAAH_DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))

import pytest
from app import store
from app.engines import learning_engine
from app.engines.building_engine import load_candidates
from app.engines.heatmap_engine import grid_heatmap, cadastral_heatmap


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    random.seed(7)
    d = tmp_path_factory.mktemp("geo")
    feats = []
    for i in range(40):
        lon = 75.78 + random.uniform(-0.004, 0.004)
        lat = 26.91 + random.uniform(-0.004, 0.004)
        s = random.choice([0.0004, 0.0008, 0.0015])
        feats.append({"type": "Feature",
                      "properties": {"id": f"B{i}", "building": "industrial"},
                      "geometry": {"type": "Polygon", "coordinates": [[
                          [lon, lat], [lon+s, lat], [lon+s, lat+s*0.7],
                          [lon, lat+s*0.7], [lon, lat]]]}})
    bpath = d / "b.geojson"
    bpath.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    parcels, uses = [], ["industrial", "commercial", "warehouse"]
    for r in range(3):
        for c in range(3):
            lon0, lat0 = 75.7745 + c*0.0045, 26.9065 + r*0.0045
            parcels.append({"type": "Feature", "properties": {
                "khasra_no": f"KH-{r}{c}", "land_use": uses[(r+c) % 3],
                "zone": f"Ward-{r}", "ownership": "private"},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [lon0, lat0], [lon0+.0045, lat0], [lon0+.0045, lat0+.0045],
                    [lon0, lat0+.0045], [lon0, lat0]]]}})
    ppath = d / "p.geojson"
    ppath.write_text(json.dumps({"type": "FeatureCollection", "features": parcels}))
    return str(bpath), str(ppath)


def test_buildings_carry_distinct_coordinates(cluster):
    gdf, _ = load_candidates(cluster[0], 26.91, 75.78, 900, 100)
    assert {"latitude", "longitude"} <= set(gdf.columns)
    assert gdf.latitude.nunique() > 1        # not all the query point
    assert 26.9 < gdf.latitude.mean() < 26.92


def test_grid_heatmap_emits_geojson_with_bands(cluster):
    gdf, _ = load_candidates(cluster[0], 26.91, 75.78, 900, 100)
    hm = grid_heatmap(gdf, 26.91, 75.78, cell_size_m=200)
    assert hm["type"] == "FeatureCollection"
    assert hm["summary"]["total_addressable_kw"] > 0
    assert len(hm["summary"]["bands"]) == 5
    props = hm["features"][0]["properties"]
    assert "total_addressable_kw" in props and "intensity_band" in props


def test_cadastral_heatmap_resolves_khasra_and_landuse(cluster):
    gdf, _ = load_candidates(cluster[0], 26.91, 75.78, 900, 100)
    cd = cadastral_heatmap(gdf, 26.91, 75.78, cluster[1])
    resolved = cd["summary"]["resolved_columns"]
    assert resolved["parcel_id"] == "khasra_no"
    assert resolved["owner_type"] == "ownership"
    assert cd["summary"]["addressable_kw_by_land_use"]
    props = cd["features"][0]["properties"]
    assert props["parcel_id"].startswith("KH-")
    assert props["acquisition_profile"] in {"single_anchor", "multi_roof_campaign"}


def test_cadastral_reports_unmatched_rather_than_dropping_silently(cluster):
    gdf, _ = load_candidates(cluster[0], 26.91, 75.78, 900, 100)
    cd = cadastral_heatmap(gdf, 26.91, 75.78, cluster[1])
    s = cd["summary"]
    assert s["matched_buildings"] + s["unmatched_buildings"] == len(gdf)


def _seed_outcomes(n=60, seed=11):
    store.reset_db()
    random.seed(seed)
    for i in range(n):
        prop, fin = random.uniform(20, 95), random.uniform(20, 95)
        funded = fin > 65 and random.random() < 0.7
        lid = f"L{i}"
        store.upsert_lead({"lead_id": lid, "propensity_score": prop,
                           "financing_score": fin, "solar_score": prop*0.9,
                           "payback_years": 6, "irr_pct": 14,
                           "partner_id": "EPC-JAI-001", "status": "assigned",
                           "latitude": 26.9+i*1e-4, "longitude": 75.78+i*1e-4,
                           "capacity_kw": 5, "segment": "residential"})
        store.record_event("assigned", lead_id=lid, partner_id="EPC-JAI-001")
        store.record_event("funded" if funded else "rejected", lead_id=lid)


def test_mistakes_separate_false_positives_from_false_negatives():
    _seed_outcomes()
    m = learning_engine.analyse_mistakes(learning_engine.collect_outcomes())
    assert m["sample_count"] == 60
    assert m["false_positives"] > 0 and m["false_negatives"] > 0
    assert m["false_positives"] + m["true_positives"] > 0
    # a false positive must be a lead that scored above the bar and died
    fp = m["worst_false_positives"][0]
    assert fp["propensity_score"] >= 55
    assert fp["terminal_status"] != "funded"


def test_learning_finds_the_driving_feature():
    _seed_outcomes()
    model = learning_engine.learn(min_samples=30)
    assert model["mode"] == "outcome_trained"
    top = max(model["feature_importance"].items(), key=lambda kv: kv[1])
    assert top[0] == "financing_score"     # how the data was generated


def test_adjustment_is_bounded_and_explained():
    _seed_outcomes()
    learning_engine.learn(min_samples=30)
    out = learning_engine.apply_learned_adjustment(85)
    assert abs(out["adjustment"]) <= learning_engine.MAX_ADJUSTMENT
    assert 0 <= out["adjusted_propensity_score"] <= 100
    assert out["reason"]


def test_adjustment_is_noop_without_a_model():
    store.reset_db()
    out = learning_engine.apply_learned_adjustment(72)
    assert out["adjusted_propensity_score"] == 72
    assert out["adjustment"] == 0.0


def test_pagination_returns_distinct_pages():
    _seed_outcomes()
    p1 = store.list_leads(limit=10, offset=0)
    p2 = store.list_leads(limit=10, offset=10)
    assert len(p1) == len(p2) == 10
    assert {l["lead_id"] for l in p1}.isdisjoint({l["lead_id"] for l in p2})
    assert store.count_leads() == 60


def test_bbox_filter_excludes_outside_viewport():
    _seed_outcomes()
    assert len(store.list_leads(bbox=(75.0, 26.0, 76.0, 27.0), limit=500)) == 60
    assert len(store.list_leads(bbox=(80.0, 20.0, 81.0, 21.0), limit=500)) == 0


def test_partner_filter_scopes_leads():
    _seed_outcomes()
    assert store.count_leads(partner_id="EPC-JAI-001") == 60
    assert store.count_leads(partner_id="EPC-NAT-009") == 0
