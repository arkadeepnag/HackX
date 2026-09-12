"""
Integration seam for modules 1-2.

Your friend's pipeline ends at "Output: Candidate Rooftop/SME List". This
module is where that list enters modules 3-9. Two entry points:

  ingest_candidates()  -- takes their candidate records, runs each through
                          solar viability, financing, scoring and routing,
                          and persists a ranked lead.
  build_estimator()    -- gives the WhatsApp flow real per-pincode
                          irradiance and tariff instead of the national
                          fallback, and stamps coordinates onto the lead so
                          it appears on the map.

Their schema is not pinned down yet, so ingestion accepts a permissive
record and maps common field aliases. Tighten CandidateRecord once the
contract is agreed -- do not tighten it before, or integration day becomes
a schema argument instead of a test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app import store
from app.engines import partner_engine
from app.engines.economics_engine import calculate_emi
from app.engines.financing_engine import calculate_financing_score
from app.engines.offer_engine import (
    OfferAssumptions,
    build_offer,
    recommend_capacity_kw,
)
from app.engines.scoring_engine import (
    calculate_propensity_score,
    calculate_solar_score,
    determine_routing_class,
    evaluate_sla,
)
from app.providers.geocoder import get_geocoder
from app.providers.reliability import ReliabilityProvider
from app.providers.solar_resource import SolarResourceProvider
from app.providers.tariff import TariffProvider

# Field aliases. Module 1-2 may label these differently; add to the lists
# rather than asking them to rename columns.
# Aliases are ordered: the most specific/trustworthy name first. Verified
# against the module 1-2 target_universe.csv schema (building_id,
# building_area_m2, candidate_pincode, place_name, gst_available, ...).
ALIASES = {
    "candidate_id": ["candidate_id", "building_id", "building_uid", "uid",
                     "osm_id", "id"],
    "latitude": ["latitude", "lat", "y", "centroid_lat"],
    "longitude": ["longitude", "lon", "lng", "x", "centroid_lon"],
    "roof_area_m2": ["roof_area_m2", "usable_roof_area_m2",
                     "building_area_m2", "footprint_area_m2", "roof_area",
                     "area_m2", "area_sqm"],
    "pincode": ["pincode", "candidate_pincode", "udyam_pincode", "pin_code",
                "postal_code", "zip"],
    "segment": ["segment", "category", "building_class", "type"],
    "place_category": ["place_category", "poi_category", "nic_description"],
    "industrial_cluster": ["industrial_cluster", "cluster",
                           "industrial_estate"],
    "industrial_cluster_match": ["industrial_cluster_match",
                                 "in_industrial_cluster", "riico_match"],
    "sanctioned_load_kw": ["sanctioned_load_kw", "sanctioned_load",
                           "connected_load_kw"],
    "monthly_consumption_kwh": ["monthly_consumption_kwh", "consumption_kwh",
                                "monthly_units"],
    "gst_registered": ["gst_registered", "gst_available", "has_gst", "gst",
                       "gst_match"],
    "udyam_available": ["udyam_available", "udyam_match"],
    "mca_available": ["mca_available", "mca_match"],
    "business_vintage_years": ["business_vintage_years", "vintage_years",
                               "years_in_business", "udyam_vintage",
                               "mca_age_years"],
    "entity_name": ["entity_name", "place_name", "udyam_enterprise_name",
                    "business_name", "company_name", "name", "owner_name"],
    "address": ["address", "place_address", "udyam_address", "full_address",
                "formatted_address"],
    "udyam_number": ["udyam_number", "udyam", "udyam_id",
                     "udyam_registration_number"],
    "candidate_rank": ["candidate_rank", "rank"],
    "candidate_priority": ["candidate_priority", "priority"],
    "shading_loss_pct": ["shading_loss_pct", "annual_shading_loss_pct",
                         "shading"],
}

SEGMENT_MAP = {
    "residential": "residential", "house": "residential",
    "apartments": "residential", "home": "residential", "domestic": "residential",
    "commercial": "commercial", "retail": "commercial", "shop": "commercial",
    "office": "commercial", "sme": "commercial",
    "industrial": "industrial", "factory": "industrial",
    "warehouse": "industrial", "manufacturing": "industrial",
    "institutional": "institutional", "school": "institutional",
    "hospital": "institutional", "college": "institutional",
    # Module 1-2 emits a combined C&I bucket; split below on POI category.
    "c&i": "commercial", "c and i": "commercial", "ci": "commercial",
    "commercial / industrial": "commercial",
    "unknown": "unknown", "requires qualification": "unknown",
}

# POI categories that promote a generic C&I row to true industrial. This
# matters: accelerated depreciation and the tariff-arbitrage thesis apply
# to a factory, not to a retail showroom, and module 1-2 cannot tell them
# apart from building geometry alone.
INDUSTRIAL_POI = {
    "manufacturer", "factory", "industrial", "warehouse",
    "automotive_service", "manufacturing", "mill", "plant",
}

# Typical unmetered consumption when module 1-2 cannot supply it. Used only
# to size a first estimate; the WhatsApp flow replaces it with real bills.
ASSUMED_MONTHLY_KWH = {
    "residential": 350.0, "commercial": 2500.0,
    "industrial": 15000.0, "institutional": 4000.0, "unknown": 1500.0,
}


def _is_blank(value: Any) -> bool:
    """
    Treat pandas NaN as missing.

    A CSV read by pandas fills empty cells with float('nan'), which is not
    None and not "" -- so a naive check lets the literal string "nan" reach
    the lead record and the dashboard.
    """
    if value is None or value == "":
        return True
    if isinstance(value, float) and value != value:      # NaN
        return True
    return str(value).strip().lower() in {"nan", "none", "null", "<na>"}


def _pick(record: dict, field: str, default: Any = None) -> Any:
    lowered = {str(k).lower(): k for k in record}
    for alias in ALIASES[field]:
        key = lowered.get(alias)
        if key is not None and not _is_blank(record[key]):
            return record[key]
    return default


def _as_pincode(value: Any) -> str | None:
    """CSV pincodes arrive as int64 or float; normalise to a 6-char string."""
    if _is_blank(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6)[:6] if digits else None


def _as_bool(value: Any) -> bool | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def _normalise_segment(raw: Any, record: dict | None = None) -> str:
    """
    Map module 1-2's segment onto our four-way split.

    Their classifier outputs Residential / C&I / Unknown. C&I is refined to
    industrial when the POI category or an industrial-cluster match says so,
    because the AD tax shield and the C&I sizing rule differ materially.
    Unknown is NOT silently guessed -- it is returned as "unknown" so the
    caller can route it to WhatsApp qualification instead of pricing it on
    an assumption.
    """
    segment = SEGMENT_MAP.get(str(raw or "").strip().lower(), "unknown")

    if record is not None and segment in {"commercial", "unknown"}:
        category = str(_pick(record, "place_category") or "").strip().lower()
        cluster_match = _pick(record, "industrial_cluster_match")
        in_cluster = str(cluster_match).strip().lower() in {"true", "1", "yes"}

        if category in INDUSTRIAL_POI:
            return "industrial"
        if segment == "commercial" and in_cluster:
            return "industrial"

    return segment


class CandidateIngestor:
    """Runs module 1-2 output through the full 3-9 pipeline."""

    def __init__(self) -> None:
        self.solar_resource = SolarResourceProvider()
        self.tariff_provider = TariffProvider()
        self.reliability_provider = ReliabilityProvider()
        self.geocoder = get_geocoder()
        self._resource_cache: dict[tuple, dict] = {}

    def _resource(self, lat: float, lon: float, mode: str) -> dict:
        # One PVGIS/NASA call per ~1 km tile instead of per rooftop. A
        # 2,000-building cluster would otherwise be 2,000 HTTP calls.
        key = (round(lat, 2), round(lon, 2), mode)
        if key not in self._resource_cache:
            self._resource_cache[key] = self.solar_resource.get(lat, lon, mode)
        return self._resource_cache[key]

    def ingest(
        self,
        records: Iterable[dict],
        sla,
        data_mode: str = "real",
        auto_route: bool = False,
        assumptions: OfferAssumptions | None = None,
    ) -> dict:
        assumptions = assumptions or OfferAssumptions()
        leads, skipped = [], []

        for index, raw in enumerate(records):
            try:
                lead = self._process(raw, index, sla, data_mode, assumptions)
            except Exception as exc:
                skipped.append({
                    "index": index,
                    "candidate_id": _pick(raw, "candidate_id", f"row-{index}"),
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                continue

            if lead is None:
                skipped.append({
                    "index": index,
                    "candidate_id": _pick(raw, "candidate_id", f"row-{index}"),
                    "reason": "no usable location (need lat/lon or a "
                              "resolvable pincode)",
                })
                continue

            if auto_route and lead["sla_eligible"]:
                routing = partner_engine.route_lead(
                    lead_id=lead["lead_id"],
                    segment=lead["segment"],
                    capacity_kw=lead["capacity_kw"],
                    pincode=lead.get("pincode"),
                    latitude=lead.get("latitude"),
                    longitude=lead.get("longitude"),
                )
                lead["partner_id"] = routing.get("partner_id")
                lead["status"] = (
                    "assigned" if routing["routed"] else "awaiting_partner"
                )

            store.upsert_lead(lead)
            store.record_event("new", lead_id=lead["lead_id"], payload={
                "source": "module_1_2_discovery",
                "propensity_score": lead["propensity_score"],
                "financing_score": lead["financing_score"],
            })
            leads.append(lead)

        leads.sort(
            key=lambda l: (l["sla_eligible"], l["propensity_score"],
                           l["financing_score"]),
            reverse=True,
        )

        eligible = [l for l in leads if l["sla_eligible"]]
        return {
            "ingested": len(leads),
            "skipped": len(skipped),
            "sla_eligible": len(eligible),
            "total_addressable_kw": round(
                sum(l["capacity_kw"] for l in leads), 2
            ),
            "skipped_detail": skipped[:50],
            "leads": leads,
        }

    def _process(self, raw, index, sla, data_mode, assumptions):
        candidate_id = str(_pick(raw, "candidate_id", f"CAND-{index:06d}"))
        pincode = _as_pincode(_pick(raw, "pincode"))

        latitude = _pick(raw, "latitude")
        longitude = _pick(raw, "longitude")
        location_source = "module_1_2"

        if latitude is None or longitude is None:
            resolved = self.geocoder.resolve(pincode)
            if not resolved:
                return None
            latitude, longitude = resolved["lat"], resolved["lon"]
            location_source = f"pincode_{resolved['match']}"

        latitude, longitude = float(latitude), float(longitude)
        raw_segment = _pick(raw, "segment")
        segment = _normalise_segment(raw_segment, raw)

        # An unclassified building still gets screened, but on conservative
        # commercial assumptions and flagged so nobody quotes off it.
        segment_unknown = segment == "unknown"
        if segment_unknown:
            segment = "commercial"

        resource = self._resource(latitude, longitude, data_mode)
        tariff = self.tariff_provider.resolve(latitude, longitude, segment)
        reliability = self.reliability_provider.resolve(latitude, longitude)

        monthly_kwh = float(
            _pick(raw, "monthly_consumption_kwh")
            or ASSUMED_MONTHLY_KWH[segment]
        )
        consumption_assumed = _pick(raw, "monthly_consumption_kwh") is None
        annual_kwh = monthly_kwh * 12

        tariff_rate = float(
            self.tariff_provider.marginal_rate(monthly_kwh, tariff)
        )

        roof_area = float(_pick(raw, "roof_area_m2") or 0)
        usable_fraction = 0.70 if segment == "residential" else 0.80
        roof_capacity_kw = (roof_area * usable_fraction) / 10.0

        specific_yield = float(
            resource.get("annual_specific_yield")
            or resource.get("specific_yield_kwh_per_kw")
            or 1450.0
        )
        shading_loss = float(_pick(raw, "shading_loss_pct") or 10.0)

        sizing = recommend_capacity_kw(
            segment=segment,
            annual_consumption_kwh=annual_kwh,
            roof_capacity_kw=roof_capacity_kw,
            sanctioned_load_kw=_pick(raw, "sanctioned_load_kw"),
            specific_yield_kwh_per_kw=specific_yield,
            assumptions=assumptions,
        )
        capacity_kw = sizing["recommended_capacity_kw"]
        generation = capacity_kw * specific_yield * (1 - shading_loss / 100)

        offer = build_offer(
            segment=segment,
            capacity_kw=capacity_kw,
            annual_generation_kwh=generation,
            annual_consumption_kwh=annual_kwh,
            tariff_rs_kwh=tariff_rate,
            state=tariff.get("state"),
            sanctioned_load_kw=_pick(raw, "sanctioned_load_kw"),
            is_manufacturing=(segment == "industrial"),
            assumptions=assumptions,
        )
        capex = offer["capex_option"]

        outage_hours = float(
            reliability.get("saidi_hours_per_customer_year") or 0
        )
        solar_score = calculate_solar_score(
            annual_irradiation_kwh_m2=float(
                resource.get("annual_irradiation_kwh_m2") or 1800
            ),
            direct_sun_hours_year=float(
                resource.get("direct_sun_hours_year") or 2200
            ),
            shading_loss_pct=shading_loss,
            usable_roof_area_m2=roof_area * usable_fraction,
            tariff_rs_kwh=tariff_rate,
            grid_reliability_score=min(100.0, outage_hours * 5),
        )

        propensity = calculate_propensity_score(
            solar_score=solar_score,
            payback_years=capex["payback_years"],
            irr_pct=capex["irr_pct"],
            tariff_rs_kwh=tariff_rate,
            outage_hours=outage_hours,
            owned_roof=None,          # unknown until WhatsApp qualification
            bill_count=0,
            roof_photo_uploaded=False,
            sla=sla,
        )

        annual_emi = capex["monthly_emi_rs"] * 12
        financing_score, financing_reasons = calculate_financing_score(
            solar_score=solar_score,
            payback_years=capex["payback_years"],
            irr_pct=capex["irr_pct"],
            annual_solar_savings_rs=capex["annual_savings_rs"],
            annual_emi_rs=annual_emi,
            gst_registered=_as_bool(_pick(raw, "gst_registered")),
            business_vintage_years=_pick(raw, "business_vintage_years"),
            credit_score=None,
            sla=sla,
        )

        sla_result = evaluate_sla(
            propensity, financing_score, solar_score,
            capex["payback_years"], sla,
        )

        return {
            "lead_id": f"DSC-{candidate_id}",
            "source": "module_1_2_discovery",
            "candidate_id": candidate_id,
            "entity_name": _pick(raw, "entity_name"),
            "address": _pick(raw, "address"),
            "udyam_number": _pick(raw, "udyam_number"),
            "latitude": latitude,
            "longitude": longitude,
            "location_source": location_source,
            "pincode": pincode,
            "segment": segment,
            "segment_reported": raw_segment,
            "segment_unknown": segment_unknown,
            "status": "new",
            "industrial_cluster": _pick(raw, "industrial_cluster"),
            "candidate_rank": _pick(raw, "candidate_rank"),
            "candidate_priority": _pick(raw, "candidate_priority"),
            "identity_signals": {
                "udyam": _as_bool(_pick(raw, "udyam_available")),
                "mca": _as_bool(_pick(raw, "mca_available")),
                "gst": _as_bool(_pick(raw, "gst_registered")),
            },
            "roof_area_m2": roof_area,
            "usable_roof_area_m2": round(roof_area * usable_fraction, 1),
            "capacity_kw": capacity_kw,
            "sizing": sizing,
            "annual_generation_kwh": round(generation, 1),
            "annual_shading_loss_pct": shading_loss,
            "monthly_consumption_kwh": monthly_kwh,
            "consumption_assumed": consumption_assumed,
            "tariff_rs_kwh": tariff_rate,
            "discom": tariff.get("discom"),
            "outage_hours": outage_hours,
            "payback_years": capex["payback_years"],
            "irr_pct": capex["irr_pct"],
            "net_monthly_benefit_rs": capex["net_monthly_benefit_rs"],
            "solar_score": solar_score,
            "propensity_score": propensity,
            "financing_score": financing_score,
            "routing_class": determine_routing_class(
                propensity, financing_score
            ),
            "sla_eligible": sla_result["eligible"],
            "sla_failed_conditions": sla_result["failed_conditions"],
            "reasons": financing_reasons[:4],
            "offer": offer,
            "qualification": {
                "owned_roof": None,
                "sanctioned_load_kw": _pick(raw, "sanctioned_load_kw"),
                "bill_count": 0,
                "roof_photo_uploaded": False,
                "gst_registered": _as_bool(_pick(raw, "gst_registered")),
                "business_vintage_years": _pick(
                    raw, "business_vintage_years"
                ),
            },
            "next_action": (
                "qualify_segment_via_whatsapp" if segment_unknown
                else "send_whatsapp_qualification" if sla_result["eligible"]
                else "nurture"
            ),
        }


def load_target_universe(path: str, limit: int | None = None) -> list[dict]:
    """
    Read module 1-2's target_universe.csv (or any CSV/Parquet of candidate
    rows) into plain dicts, with NaN normalised to None so downstream
    alias lookups behave.
    """
    import pandas as pd

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"candidate file not found: {source}")

    if source.suffix.lower() == ".parquet":
        frame = pd.read_parquet(source)
    else:
        frame = pd.read_csv(source, low_memory=False)

    if limit:
        frame = frame.head(limit)

    return frame.where(pd.notna(frame), None).to_dict(orient="records")


_ingestor: CandidateIngestor | None = None


def get_ingestor() -> CandidateIngestor:
    global _ingestor
    if _ingestor is None:
        _ingestor = CandidateIngestor()
    return _ingestor


def build_estimator():
    """
    Real estimator for the WhatsApp flow.

    Replaces the national fallback with per-pincode irradiance, the correct
    DISCOM tariff at the customer's own consumption, and coordinates -- so
    conversational leads finally appear on the map instead of silently
    dropping out of the GeoJSON layer.
    """
    ingestor = get_ingestor()

    def estimator(context: dict) -> dict:
        location = ingestor.geocoder.resolve(context.get("pincode"))

        if not location:
            return {
                "specific_yield_kwh_per_kw": 1450.0,
                "tariff_rs_kwh": (
                    7.0 if context.get("segment") == "residential" else 9.0
                ),
                "state": None, "latitude": None, "longitude": None,
                "shading_loss_pct": 12.0,
                "source": "national_fallback_unknown_pincode",
            }

        lat, lon = location["lat"], location["lon"]
        segment = context.get("segment", "residential")

        try:
            resource = ingestor._resource(lat, lon, "real")
            specific_yield = float(
                resource.get("annual_specific_yield")
                or resource.get("specific_yield_kwh_per_kw") or 1450.0
            )
            source = "pvgis_nasa"
        except Exception:
            # Never fail a live conversation on a flaky upstream API.
            specific_yield, source = 1450.0, "fallback_resource_unavailable"

        tariff = ingestor.tariff_provider.resolve(lat, lon, segment)
        monthly_kwh = context.get("monthly_consumption_kwh") or 300
        rate = float(
            ingestor.tariff_provider.marginal_rate(monthly_kwh, tariff)
        )

        return {
            "specific_yield_kwh_per_kw": specific_yield,
            "tariff_rs_kwh": rate,
            "state": tariff.get("state") or location.get("state"),
            "discom": tariff.get("discom"),
            "latitude": lat,
            "longitude": lon,
            "shading_loss_pct": 12.0,
            "location_match": location["match"],
            "source": f"{source}+{location['match']}",
        }

    return estimator
