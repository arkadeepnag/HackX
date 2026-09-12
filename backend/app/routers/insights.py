"""
Heatmap, closed-loop learning, and the partner-facing view.

Partner endpoints are deliberately scoped: a partner sees only their own
assigned leads, and only the fields they need to make the call. Scores and
internal reasoning stay on the platform side.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app import store
from app.engines import heatmap_engine, learning_engine, partner_engine
from app.engines import tracking_engine
from app.engines.building_engine import load_candidates
from app.engines.solar_engine import analyze as analyze_solar
from app.engines.ingest_engine import (
    ALIASES,
    INDUSTRIAL_POI,
    SEGMENT_MAP,
    get_ingestor,
    load_target_universe,
)
from app.models.schemas import (
    CandidateFileIngestRequest,
    CandidateIngestRequest,
    HeatmapRequest,
    ScoreAdjustmentRequest,
)
from app.providers.solar_resource import SolarResourceProvider

router = APIRouter(prefix="/api/v1", tags=["insights"])

_solar_resource = SolarResourceProvider()

GEO_SUFFIXES = {".geojson", ".json", ".shp", ".gpkg", ".parquet", ".fgb"}


def _require_readable(source: str, field: str) -> None:
    """
    Fail fast with an actionable message. A missing file should never
    surface as a 500 -- the caller can fix a path, not a stack trace.
    """
    if "://" in source:
        return                      # remote URI, let the driver try

    path = Path(source).expanduser()
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} not found: '{source}' (resolved to "
                f"'{path.resolve()}'). Generate demo data with "
                f"'python scripts/make_demo_data.py', or pass an absolute "
                f"path -- relative paths resolve against the server's "
                f"working directory, not yours."
            ),
        )
    if path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"{field} is a directory, not a file: '{source}'",
        )
    if path.suffix.lower() not in GEO_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field} has an unexpected extension '{path.suffix}'. "
                f"Expected one of {sorted(GEO_SUFFIXES)}."
            ),
        )


# ----------------------------- heatmap -------------------------------

@router.post("/heatmap/cluster")
async def cluster_heatmap(request: HeatmapRequest):
    """
    Total addressable kW across a cluster, as GeoJSON.

    mode=grid       equal-area cells, always available
    mode=cadastral  aggregated to real plot boundaries with their
                    attributes (requires cadastral_source)
    mode=both       returns both layers in one response

    run_solar=true applies shading-adjusted capacity instead of the raw
    geometric roof estimate. Slower, and worth it for a final territory
    plan rather than an exploratory sweep.
    """
    _require_readable(request.building_source, "building_source")
    if request.cadastral_source:
        _require_readable(request.cadastral_source, "cadastral_source")

    try:
        buildings, metric_crs = load_candidates(
            request.building_source,
            request.latitude,
            request.longitude,
            request.radius_m,
            request.max_buildings,
        )
    except Exception as exc:
        # pyogrio raises DataSourceError, which subclasses RuntimeError --
        # not OSError -- so a narrow except turns a bad path into an
        # opaque 500. Catch broadly and return the real reason.
        raise HTTPException(
            status_code=400,
            detail=(
                f"could not read building_source "
                f"'{request.building_source}': {type(exc).__name__}: {exc}"
            ),
        )

    if buildings.empty:
        raise HTTPException(status_code=404,
                            detail="no buildings within the requested radius")

    solar_results = None
    if request.run_solar:
        resource = _solar_resource.get(
            request.latitude, request.longitude, request.data_mode
        )
        solar_results, _ = analyze_solar(
            buildings, request.latitude, request.longitude,
            resource, request.detail_top_n,
        )

    response: dict = {
        "query": {
            "latitude": request.latitude,
            "longitude": request.longitude,
            "radius_m": request.radius_m,
            "metric_crs": metric_crs,
            "building_count": int(len(buildings)),
            "capacity_basis": (
                "shading_adjusted" if request.run_solar
                else "geometric_roof_estimate"
            ),
        }
    }

    if request.mode in {"grid", "both"}:
        response["grid"] = heatmap_engine.grid_heatmap(
            buildings, request.latitude, request.longitude,
            solar_results=solar_results,
            cell_size_m=request.cell_size_m,
            min_buildings_per_cell=request.min_buildings_per_cell,
        )

    if request.mode in {"cadastral", "both"}:
        if not request.cadastral_source:
            raise HTTPException(
                status_code=400,
                detail="cadastral_source is required for cadastral mode",
            )
        try:
            response["cadastral"] = heatmap_engine.cadastral_heatmap(
                buildings, request.latitude, request.longitude,
                cadastral_source=request.cadastral_source,
                solar_results=solar_results,
                min_kw=request.min_kw,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"could not build cadastral layer from "
                    f"'{request.cadastral_source}': "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

    return response


@router.get("/heatmap/leads")
async def lead_heatmap(
    min_lon: float = Query(...), min_lat: float = Query(...),
    max_lon: float = Query(...), max_lat: float = Query(...),
    min_propensity: float = 0, limit: int = 2000,
):
    """
    Scored leads inside a map viewport, as GeoJSON points. This is the
    layer the dashboard map draws on top of the capacity surface.
    """
    leads = store.list_leads(
        min_propensity=min_propensity,
        bbox=(min_lon, min_lat, max_lon, max_lat),
        limit=limit,
    )

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lead["longitude"], lead["latitude"]],
            },
            "properties": {
                "lead_id": lead.get("lead_id"),
                "propensity_score": lead.get("propensity_score"),
                "financing_score": lead.get("financing_score"),
                "solar_score": lead.get("solar_score"),
                "routing_class": lead.get("routing_class"),
                "capacity_kw": lead.get("capacity_kw")
                or lead.get("pv_capacity_kw"),
                "segment": lead.get("segment"),
                "status": lead.get("status"),
            },
        }
        for lead in leads
        if lead.get("latitude") is not None
        and lead.get("longitude") is not None
    ]

    return {
        "type": "FeatureCollection",
        "features": features,
        "summary": {
            "returned": len(features),
            "leads_without_coordinates": len(leads) - len(features),
        },
    }


# ----------------------------- learning ------------------------------

@router.post("/learning/run")
async def run_learning(min_samples: int = 30):
    """
    Full closed-loop cycle: collect terminal outcomes, name the mistakes,
    check calibration, refit, and persist a new model version.
    """
    return learning_engine.learn(min_samples=min_samples)


@router.get("/learning/mistakes")
async def mistakes(
    propensity_bar: float = 55.0, financing_bar: float = 50.0
):
    """
    Where the score was wrong, split by error class.

    False positives cost field visits. False negatives cost revenue and
    are invisible unless sub-threshold leads are tracked, which they are.
    """
    outcomes = learning_engine.collect_outcomes()
    return learning_engine.analyse_mistakes(
        outcomes, propensity_bar, financing_bar
    )


@router.get("/learning/calibration")
async def calibration(bins: int = 5):
    outcomes = learning_engine.collect_outcomes()
    return {
        "sample_count": len(outcomes),
        "bands": learning_engine.calibrate(outcomes, bins),
    }


@router.get("/learning/model")
async def current_model():
    model = learning_engine.current_model()
    if not model:
        raise HTTPException(status_code=404,
                            detail="no model trained yet")
    return model


@router.post("/learning/apply")
async def apply_adjustment(request: ScoreAdjustmentRequest):
    return learning_engine.apply_learned_adjustment(
        request.propensity_score, request.financing_score
    )


# ------------------------- partner-facing view -----------------------

@router.get("/partner-portal/{partner_id}/leads")
async def partner_leads(
    partner_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    A partner's own queue. Internal scores are withheld deliberately --
    a partner who can see the propensity score will work the top of the
    list and let the rest rot, which is the leakage the PS asks us to
    prevent. They get the SLA clock instead.
    """
    registry = partner_engine.get_registry()
    known = {p.partner_id for p in registry.partners}
    if partner_id not in known:
        raise HTTPException(status_code=404, detail="unknown partner")

    leads = store.list_leads(
        partner_id=partner_id, status=status,
        limit=limit, offset=offset,
    )
    total = store.count_leads(partner_id=partner_id, status=status)

    events = store.list_events(limit=5000)
    assigned_at = {}
    for event in sorted(events, key=lambda e: e["created_at"]):
        if event["event_type"] == "assigned" and event["lead_id"]:
            assigned_at[event["lead_id"]] = event["created_at"]

    items = []
    for lead in leads:
        offer = (lead.get("offer") or {}).get("capex_option", {})
        items.append({
            "lead_id": lead.get("lead_id"),
            "status": lead.get("status"),
            "segment": lead.get("segment"),
            "pincode": lead.get("pincode"),
            "latitude": lead.get("latitude"),
            "longitude": lead.get("longitude"),
            "recommended_capacity_kw": (
                lead.get("capacity_kw") or lead.get("pv_capacity_kw")
            ),
            "estimated_monthly_savings_rs": offer.get("monthly_savings_rs"),
            "indicative_emi_rs": offer.get("monthly_emi_rs"),
            "roof_photo_url": (
                lead.get("qualification", {}).get("roof_photo_url")
            ),
            "owned_roof": lead.get("qualification", {}).get("owned_roof"),
            "sanctioned_load_kw": (
                lead.get("qualification", {}).get("sanctioned_load_kw")
            ),
            "assigned_at": assigned_at.get(lead.get("lead_id")),
            "language": lead.get("language"),
        })

    return {
        "partner_id": partner_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "leads": items,
    }


@router.get("/partner-portal/{partner_id}/summary")
async def partner_summary(partner_id: str, window_days: int = 30):
    cards = tracking_engine.partner_scorecard(window_days)
    mine = next(
        (c for c in cards if c["partner_id"] == partner_id), None
    )

    leakage = tracking_engine.detect_leakage()
    overdue = [
        record for record in leakage["untouched"]
        if record["partner_id"] == partner_id
    ]

    return {
        "partner_id": partner_id,
        "window_days": window_days,
        "scorecard": mine or {
            "partner_id": partner_id, "assigned": 0,
            "note": "no activity in window",
        },
        "overdue_contacts": overdue,
        "open_leads": store.count_leads(
            partner_id=partner_id, status="assigned"
        ),
    }


@router.post("/partner-portal/{partner_id}/leads/{lead_id}/status")
async def partner_update_status(
    partner_id: str, lead_id: str, status: str,
    note: str | None = None,
):
    """
    Partner-side status transition. Routed through the tracking engine so
    the SLA clock and leakage detection stay consistent with platform-side
    updates.
    """
    lead = store.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    if lead.get("partner_id") != partner_id:
        raise HTTPException(status_code=403,
                            detail="lead is not assigned to this partner")

    allowed = {"contacted", "qualified", "submitted",
               "funded", "dropped", "rejected"}
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(allowed)}",
        )

    result = tracking_engine.evaluate_event({
        "lead_id": lead_id,
        "status": status,
        "timestamp": store.now_iso(),
        "partner_id": partner_id,
        "contract_sla_hours": 24,
    })

    if note:
        store.record_event("partner_note", lead_id=lead_id,
                           partner_id=partner_id, payload={"note": note})
    return result


@router.post("/partner-portal/{partner_id}/leads/{lead_id}/reject")
async def partner_reject(partner_id: str, lead_id: str, reason: str):
    """
    Hand a lead back. It is immediately re-routed to the next best partner
    excluding this one, so a rejection does not silently park a qualified
    lead forever.
    """
    lead = store.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    store.record_event("partner_rejected", lead_id=lead_id,
                       partner_id=partner_id, payload={"reason": reason})

    rerouted = partner_engine.route_lead(
        lead_id=lead_id,
        segment=lead.get("segment", "residential"),
        capacity_kw=lead.get("capacity_kw") or 0,
        pincode=lead.get("pincode"),
        latitude=lead.get("latitude"),
        longitude=lead.get("longitude"),
        exclude_partner_ids=[partner_id],
    )

    lead["partner_id"] = rerouted.get("partner_id")
    lead["status"] = "assigned" if rerouted["routed"] else "awaiting_partner"
    store.upsert_lead(lead)

    return {"released_from": partner_id, "rerouted": rerouted}


# --------------------- module 1-2 ingestion --------------------------

@router.post("/ingest/candidates")
async def ingest_candidates(request: CandidateIngestRequest):
    """
    Accept module 1-2's candidate rooftop/SME list and run every record
    through viability, financing, scoring and (optionally) routing.

    Records that cannot be located are reported in `skipped_detail` with a
    reason rather than dropped silently, so a broken column mapping is
    visible on the first run instead of showing up as a short lead count.
    """
    records = request.records[:request.max_records]

    result = get_ingestor().ingest(
        records=records,
        sla=request.sla,
        data_mode=request.data_mode,
        auto_route=request.auto_route,
    )

    if not request.include_leads:
        result.pop("leads", None)
    return result


@router.get("/ingest/schema")
async def ingest_schema():
    """
    The field aliases ingestion understands. Hand this to whoever owns
    modules 1-2 -- matching any one alias per row is enough.
    """
    return {
        "accepted_aliases": ALIASES,
        "required": [
            "one of latitude+longitude, or a resolvable pincode",
            "one of roof_area_m2 aliases (else capacity falls back to "
            "consumption and sanctioned load only)",
        ],
        "segment_values": sorted(set(SEGMENT_MAP.values())),
        "segment_aliases": SEGMENT_MAP,
        "industrial_poi_categories": sorted(INDUSTRIAL_POI),
        "module_1_2_contract": {
            "file": "outputs/target_universe.csv",
            "verified_columns": [
                "building_id", "latitude", "longitude", "building_area_m2",
                "segment", "place_category", "place_name", "place_address",
                "candidate_pincode", "industrial_cluster",
                "industrial_cluster_match", "udyam_available",
                "mca_available", "gst_available", "candidate_rank",
                "candidate_priority",
            ],
            "not_supplied_by_module_1_2": [
                "sanctioned_load_kw", "monthly_consumption_kwh",
                "business_vintage_years",
            ],
            "note": (
                "Missing fields are assumed conservatively at ingest and "
                "replaced with real values during WhatsApp qualification."
            ),
        },
        "example": {
            "building_uid": "OSM-way-12345",
            "lat": 26.9124, "lon": 75.7873,
            "roof_area_m2": 850,
            "pincode": "302015",
            "building_class": "factory",
            "sanctioned_load_kw": 120,
            "udyam": "UDYAM-RJ-17-0001234",
            "vintage_years": 6,
            "has_gst": True,
        },
    }


@router.post("/ingest/file")
async def ingest_file(request: CandidateFileIngestRequest):
    """
    Ingest module 1-2's target_universe.csv directly.

    Defaults to include_leads=false because a full Jaipur universe is tens
    of thousands of rows -- fetch the results from /api/v1/leads instead of
    returning them all inline.
    """
    try:
        records = load_target_universe(request.path, request.limit)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"could not read '{request.path}': "
                   f"{type(exc).__name__}: {exc}",
        )

    if not records:
        raise HTTPException(status_code=400, detail="file contained no rows")

    result = get_ingestor().ingest(
        records=records,
        sla=request.sla,
        data_mode=request.data_mode,
        auto_route=request.auto_route,
    )
    result["source_file"] = request.path
    result["rows_read"] = len(records)

    if not request.include_leads:
        result.pop("leads", None)
    return result
