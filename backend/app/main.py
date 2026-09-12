from __future__ import annotations

from typing import Any

from fastapi import (
    FastAPI,
    HTTPException
)

from contextlib import asynccontextmanager

from fastapi.middleware.cors import (
    CORSMiddleware
)

from app.models.schemas import (
    AnalysisRequest,
    SolarAnalysisRequest,
    FinancingRequest,
    LeadScoreRequest,
    PolicyLearnRequest,
    LeadEvent,
    QualificationUpdate,
    WhatsAppWebhookEvent,
    WhatsAppQualificationMessage,
    PartnerRouteRequest,
    LeadListRequest
)

from app.engines.lead_engine import (
    LeadEngine
)

from app.engines.solar_engine import (
    analyze as analyze_solar
)

from app.engines.building_engine import (
    load_candidates
)

from app.engines.financing_engine import (
    calculate_financing_score
)

from app.engines.scoring_engine import (
    calculate_solar_score,
    calculate_propensity_score,
    determine_routing_class,
    evaluate_sla
)

from app.engines.policy_learner import (
    PolicyLearner
)

from app.engines.tracking_engine import (
    evaluate_event
)

from app.routers.whatsapp import (
    router as whatsapp_router
)

from app.routers.insights import (
    router as insights_router
)

from app import store


@asynccontextmanager
async def lifespan(_app: FastAPI):

    store.init_db()

    # Give the WhatsApp flow real per-pincode irradiance, the correct
    # DISCOM tariff, and coordinates -- without this it uses a national
    # fallback and conversational leads never appear on the map.
    from app.engines import whatsapp_flow
    from app.engines.ingest_engine import build_estimator

    whatsapp_flow.set_estimator(build_estimator())

    yield


app = FastAPI(
    lifespan=lifespan,
    title="Solar Lead Discovery and Qualification API",
    version="1.0.0",
    description="Backend-only GeoAI solar lead intelligence platform"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


lead_engine = LeadEngine()
policy_learner = PolicyLearner()


app.include_router(
    whatsapp_router
)

app.include_router(
    insights_router
)


@app.get(
    "/health"
)
async def health():

    return {
        "status": "ok",
        "service":
            "solar-lead-backend",
        "frontend":
            False,
        "api_version":
            "v1"
    }


@app.get(
    "/api/v1/system/status"
)
async def system_status():

    return {
        "status": "operational",
        "engines": {
            "building":
                "ready",

            "solar":
                "ready",

            "economics":
                "ready",

            "financing":
                "ready",

            "scoring":
                "ready",

            "policy_learning":
                "ready",

            "tracking":
                "ready"
        },

        "integrations": {
            "frontend":
                "api_ready",

            "whatsapp":
                "webhook_ready",

            "partner_routing":
                "api_ready"
        }
    }


@app.post(
    "/api/v1/analyze"
)
async def analyze(
    request: AnalysisRequest
):

    result = lead_engine.analyze(
        request
    )

    for lead in result["leads"]:

        record = dict(lead)

        record["lead_id"] = (
            lead["building_uid"]
        )

        record["status"] = "new"

        record["source"] = (
            "outbound_discovery"
        )

        record["pincode"] = (
            request.customer.model_dump()
            .get("pincode")
        )

        record["segment"] = (
            request.customer.segment
        )

        store.upsert_lead(record)

        store.record_event(
            "new",
            lead_id=record["lead_id"],
            payload={
                "propensity_score":
                    record["propensity_score"],

                "financing_score":
                    record["financing_score"]
            }
        )

    return result


@app.post(
    "/api/v1/solar/analyze"
)
async def solar_analyze(
    request: SolarAnalysisRequest
):

    buildings, _ = load_candidates(
        request.building_source,
        request.latitude,
        request.longitude,
        request.radius_m,
        request.max_buildings
    )

    resource = (
        lead_engine
        .solar_resource
        .get(
            request.latitude,
            request.longitude,
            request.data_mode
        )
    )

    results, optimum = analyze_solar(
        buildings,
        request.latitude,
        request.longitude,
        resource,
        request.detail_top_n
    )

    return {
        "solar_resource":
            resource,

        "optimum":
            optimum,

        "candidate_count":
            len(results),

        "buildings":
            results.to_dict(
                orient="records"
            )
    }


@app.post(
    "/api/v1/financing/evaluate"
)
async def financing_evaluate(
    request: FinancingRequest
):

    score, reasons = (
        calculate_financing_score(
            solar_score=request.solar_score,
            payback_years=request.payback_years,
            irr_pct=request.irr_pct,
            annual_solar_savings_rs=(
                request.annual_solar_savings_rs
            ),
            annual_emi_rs=(
                request.annual_emi_rs
            ),
            gst_registered=(
                request.gst_registered
            ),
            business_vintage_years=(
                request.business_vintage_years
            ),
            credit_score=(
                request.credit_score
            ),
            sla=request.sla
        )
    )

    return {
        "financing_score":
            score,

        "eligible":
            score
            >= request.sla
            .minimum_financing_score,

        "reasons":
            reasons
    }


@app.post(
    "/api/v1/scoring/evaluate"
)
async def scoring_evaluate(
    request: LeadScoreRequest
):

    solar_score = request.solar_score

    propensity = (
        calculate_propensity_score(
            solar_score=solar_score,
            payback_years=request.payback_years,
            irr_pct=request.irr_pct,
            tariff_rs_kwh=request.tariff_rs_kwh,
            outage_hours=request.outage_hours,
            owned_roof=request.owned_roof,
            bill_count=request.bill_count,
            roof_photo_uploaded=(
                request.roof_photo_uploaded
            ),
            sla=request.sla
        )
    )

    routing = (
        determine_routing_class(
            propensity,
            request.financing_score
        )
    )

    sla_result = (
        evaluate_sla(
            propensity,
            request.financing_score,
            solar_score,
            request.payback_years,
            request.sla
        )
    )

    return {
        "solar_score":
            solar_score,

        "propensity_score":
            propensity,

        "financing_score":
            request.financing_score,

        "routing_class":
            routing,

        "sla":
            sla_result
    }


@app.post(
    "/api/v1/policy/learn"
)
async def learn_policy(
    request: PolicyLearnRequest
):

    return policy_learner.learn(
        rows=request.rows,
        target=request.target,
        min_samples=request.min_samples
    )


@app.get(
    "/api/v1/leads"
)
async def get_leads(
    minimum_propensity_score: float = 0,
    minimum_financing_score: float = 0,
    routing_class: str | None = None,
    status: str | None = None,
    partner_id: str | None = None,
    limit: int = 100,
    offset: int = 0
):

    leads = store.list_leads(
        min_propensity=(
            minimum_propensity_score
        ),
        min_financing=(
            minimum_financing_score
        ),
        routing_class=routing_class,
        status=status,
        partner_id=partner_id,
        limit=limit,
        offset=offset
    )

    total = store.count_leads(
        min_propensity=(
            minimum_propensity_score
        ),
        min_financing=(
            minimum_financing_score
        ),
        routing_class=routing_class,
        status=status,
        partner_id=partner_id
    )

    return {
        "count":
            len(leads),

        "total":
            total,

        "limit":
            limit,

        "offset":
            offset,

        "has_more":
            offset + len(leads) < total,

        "leads":
            leads
    }


@app.get(
    "/api/v1/leads/{lead_id}"
)
async def get_lead(
    lead_id: str
):

    lead = store.get_lead(
        lead_id
    )

    if lead is None:

        raise HTTPException(
            status_code=404,
            detail="Lead not found"
        )

    return lead


@app.patch(
    "/api/v1/leads/{lead_id}/qualification"
)
async def update_qualification(
    lead_id: str,
    request: QualificationUpdate
):

    lead = store.get_lead(
        lead_id
    )

    if lead is None:

        raise HTTPException(
            status_code=404,
            detail="Lead not found"
        )

    update = request.model_dump(
        exclude_none=True
    )

    qualification = lead.setdefault(
        "qualification",
        {}
    )

    qualification.update(
        update
    )

    if update.get("customer_phone"):

        lead["phone"] = update[
            "customer_phone"
        ]

    store.upsert_lead(lead)

    return {
        "lead_id":
            lead_id,

        "qualification":
            qualification,

        "status":
            "updated"
    }


@app.post(
    "/api/v1/tracking/evaluate"
)
async def tracking_evaluate(
    event: LeadEvent
):

    return evaluate_event(
        event
    )


@app.post(
    "/api/v1/frontend/analyze"
)
async def frontend_analyze(
    request: AnalysisRequest
):

    return await analyze(
        request
    )


@app.get(
    "/api/v1/frontend/leads"
)
async def frontend_leads(
    minimum_propensity_score: float = 0,
    minimum_financing_score: float = 0,
    routing_class: str | None = None,
    limit: int = 100
):

    return await get_leads(
        minimum_propensity_score,
        minimum_financing_score,
        routing_class,
        limit
    )


@app.get(
    "/api/v1/frontend/leads/{lead_id}"
)
async def frontend_lead(
    lead_id: str
):

    return await get_lead(
        lead_id
    )