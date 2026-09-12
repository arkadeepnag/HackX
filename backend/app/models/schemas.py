from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


Segment = Literal[
    "residential",
    "commercial",
    "industrial",
    "institutional"
]

LeadStatus = Literal[
    "new",
    "contacted",
    "qualified",
    "submitted",
    "funded",
    "dropped",
    "rejected"
]

RoutingClass = Literal[
    "high_priority",
    "high_propensity_finance_risk",
    "low_propensity_financeable",
    "discard_or_nurture"
]


class CustomerProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    segment: Segment = "residential"
    monthly_consumption_kwh: float = Field(default=350, ge=0)
    sanctioned_load_kw: float = Field(default=5, ge=0)
    monthly_bill_rs: Optional[float] = Field(default=None, ge=0)

    gst_registered: Optional[bool] = None
    business_vintage_years: Optional[float] = Field(default=None, ge=0)
    credit_score: Optional[float] = Field(default=None, ge=0, le=100)

    owned_roof: Optional[bool] = None
    bill_count: int = Field(default=0, ge=0)
    roof_photo_uploaded: bool = False

    critical_load_kw: Optional[float] = Field(default=None, ge=0)

    customer_id: Optional[str] = None
    phone_number: Optional[str] = None
    whatsapp_number: Optional[str] = None


class SLAProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_first_response_minutes: int = Field(default=30, ge=1)
    max_stale_hours: float = Field(default=24, gt=0)

    target_conversion_rate: float = Field(
        default=0.12,
        gt=0,
        lt=1
    )

    minimum_propensity_score: float = Field(
        default=55,
        ge=0,
        le=100
    )

    minimum_financing_score: float = Field(
        default=50,
        ge=0,
        le=100
    )

    minimum_solar_score: float = Field(
        default=55,
        ge=0,
        le=100
    )

    max_payback_years: float = Field(
        default=7,
        gt=0
    )

    minimum_irr_pct: float = Field(
        default=12,
        ge=0
    )

    outage_hours_opportunity: float = Field(
        default=12,
        ge=0
    )

    max_assignment_hours: float = Field(
        default=2,
        gt=0
    )

    max_qualification_hours: float = Field(
        default=24,
        gt=0
    )

    max_submission_hours: float = Field(
        default=48,
        gt=0
    )


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    radius_m: float = Field(
        default=500,
        gt=0,
        le=5000
    )

    building_source: str

    customer: CustomerProfile = Field(
        default_factory=CustomerProfile
    )

    sla: SLAProfile = Field(
        default_factory=SLAProfile
    )

    data_mode: Literal[
        "real",
        "offline"
    ] = "real"

    max_buildings: Optional[int] = Field(
        default=300,
        ge=1,
        le=10000
    )

    detail_top_n: int = Field(
        default=25,
        ge=0,
        le=500
    )


class SolarAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    radius_m: float = Field(
        default=500,
        gt=0,
        le=5000
    )

    building_source: str

    data_mode: Literal[
        "real",
        "offline"
    ] = "real"

    max_buildings: Optional[int] = Field(
        default=300,
        ge=1,
        le=10000
    )

    detail_top_n: int = Field(
        default=25,
        ge=0,
        le=500
    )


class FinancingRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    solar_score: float = Field(..., ge=0, le=100)
    payback_years: float = Field(..., ge=0)
    irr_pct: float = Field(...)

    annual_solar_savings_rs: float = Field(
        ...,
        ge=0
    )

    annual_emi_rs: float = Field(
        ...,
        ge=0
    )

    gst_registered: Optional[bool] = None
    business_vintage_years: Optional[float] = Field(
        default=None,
        ge=0
    )

    credit_score: Optional[float] = Field(
        default=None,
        ge=0,
        le=100
    )

    sla: SLAProfile = Field(
        default_factory=SLAProfile
    )


class LeadScoreRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    solar_score: float = Field(..., ge=0, le=100)
    payback_years: float = Field(..., ge=0)
    irr_pct: float
    tariff_rs_kwh: float = Field(..., ge=0)
    outage_hours: float = Field(default=0, ge=0)

    annual_solar_savings_rs: float = Field(
        default=0,
        ge=0
    )

    annual_emi_rs: float = Field(
        default=0,
        ge=0
    )

    financing_score: float = Field(
        default=50,
        ge=0,
        le=100
    )

    owned_roof: Optional[bool] = None
    bill_count: int = Field(default=0, ge=0)
    roof_photo_uploaded: bool = False

    sla: SLAProfile = Field(
        default_factory=SLAProfile
    )


class PolicyLearnRequest(BaseModel):
    rows: list[dict[str, Any]]
    target: str = "funded"

    min_samples: int = Field(
        default=30,
        ge=10
    )


class LeadEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    lead_id: str

    status: LeadStatus

    timestamp: str

    contract_sla_hours: float = Field(
        default=24,
        gt=0
    )

    funded_amount_rs: Optional[float] = Field(
        default=None,
        ge=0
    )

    acquisition_cost_rs: Optional[float] = Field(
        default=None,
        ge=0
    )

    partner_id: Optional[str] = None


class QualificationUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    lead_id: str

    owned_roof: Optional[bool] = None
    rented_roof: Optional[bool] = None

    sanctioned_load_kw: Optional[float] = Field(
        default=None,
        ge=0
    )

    monthly_consumption_kwh: Optional[float] = Field(
        default=None,
        ge=0
    )

    bill_count: Optional[int] = Field(
        default=None,
        ge=0
    )

    roof_photo_uploaded: Optional[bool] = None

    roof_photo_url: Optional[str] = None

    customer_phone: Optional[str] = None

    whatsapp_number: Optional[str] = None


class WhatsAppWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: Optional[str] = None
    phone_number: Optional[str] = None
    whatsapp_number: Optional[str] = None

    text: Optional[str] = None

    media_type: Optional[str] = None
    media_url: Optional[str] = None

    timestamp: Optional[str] = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class WhatsAppQualificationMessage(BaseModel):
    lead_id: str

    phone_number: str

    message_type: Literal[
        "text",
        "template",
        "document",
        "image"
    ] = "text"

    message: str

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class PartnerRouteRequest(BaseModel):
    lead_id: str

    segment: Segment

    pincode: Optional[str] = None

    capacity_kw: float = Field(
        ...,
        ge=0
    )

    preferred_partner_ids: list[str] = Field(
        default_factory=list
    )

    exclude_partner_ids: list[str] = Field(
        default_factory=list
    )


class LeadListRequest(BaseModel):
    minimum_propensity_score: float = Field(
        default=0,
        ge=0,
        le=100
    )

    minimum_financing_score: float = Field(
        default=0,
        ge=0,
        le=100
    )

    routing_class: Optional[RoutingClass] = None

    limit: int = Field(
        default=100,
        ge=1,
        le=1000
    )


class SimulateMessageRequest(BaseModel):
    """Drive the WhatsApp flow locally, without a Meta account."""

    phone: str

    text: Optional[str] = None

    media_url: Optional[str] = None

    media_type: Optional[str] = None


class HeatmapRequest(BaseModel):
    """Addressable-capacity heatmap over an industrial cluster."""

    model_config = ConfigDict(extra="allow")

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    radius_m: float = Field(default=2000, gt=0, le=20000)

    building_source: str

    cadastral_source: Optional[str] = None

    mode: Literal["grid", "cadastral", "both"] = "grid"

    cell_size_m: float = Field(default=200, ge=25, le=2000)

    min_buildings_per_cell: int = Field(default=1, ge=1)

    min_kw: float = Field(default=0, ge=0)

    max_buildings: Optional[int] = Field(default=2000, ge=1, le=50000)

    run_solar: bool = False

    data_mode: Literal["real", "offline"] = "real"

    detail_top_n: int = Field(default=0, ge=0, le=500)


class ScoreAdjustmentRequest(BaseModel):
    propensity_score: float = Field(..., ge=0, le=100)
    financing_score: Optional[float] = Field(default=None, ge=0, le=100)


class CandidateIngestRequest(BaseModel):
    """
    Module 1-2 handoff: a batch of discovered rooftop/SME candidates.

    Records are intentionally permissive (extra="allow") and field names
    are alias-mapped, so integration does not block on schema agreement.
    """

    model_config = ConfigDict(extra="allow")

    records: list[dict[str, Any]] = Field(..., min_length=1)

    sla: SLAProfile = Field(default_factory=SLAProfile)

    data_mode: Literal["real", "offline"] = "real"

    auto_route: bool = False

    include_leads: bool = True

    max_records: int = Field(default=5000, ge=1, le=50000)


class CandidateFileIngestRequest(BaseModel):
    """Ingest module 1-2's target_universe.csv straight from disk."""

    model_config = ConfigDict(extra="allow")

    path: str

    sla: SLAProfile = Field(default_factory=SLAProfile)

    data_mode: Literal["real", "offline"] = "offline"

    auto_route: bool = False

    include_leads: bool = False

    limit: Optional[int] = Field(default=2000, ge=1, le=100000)
