"""
Partner routing and leakage control.

Routes a qualified lead to the nearest capable EPC/dealer by pincode and
capacity band, respecting each partner's daily capacity so the top partner
does not get flooded and quietly sit on leads.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app import store

PARTNERS_PATH = Path(__file__).resolve().parents[1] / "data" / "partners.json"


@dataclass
class Partner:
    partner_id: str
    name: str
    pincodes: list[str] = field(default_factory=list)
    pincode_prefixes: list[str] = field(default_factory=list)
    min_capacity_kw: float = 0.0
    max_capacity_kw: float = 1e9
    segments: list[str] = field(default_factory=lambda: ["residential"])
    latitude: float | None = None
    longitude: float | None = None
    daily_lead_cap: int = 25
    contact_sla_hours: float = 24.0
    active: bool = True
    rating: float = 3.0

    @classmethod
    def from_dict(cls, raw: dict) -> "Partner":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in raw.items() if k in known})


class PartnerRegistry:
    def __init__(self, path: Path = PARTNERS_PATH):
        self.path = Path(path)
        self.partners = self._load()

    def _load(self) -> list[Partner]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Partner.from_dict(p) for p in raw.get("partners", [])]

    def reload(self) -> None:
        self.partners = self._load()

    # ---- matching ----

    def _covers_pincode(self, partner: Partner, pincode: Any) -> tuple[bool, int]:
        """
        Returns (covered, specificity). Exact pincode beats prefix.

        Coerces to string: a pincode read from a CSV arrives as int64 and
        has no .startswith, which would otherwise crash routing mid-batch.
        """
        if pincode is None or pincode == "":
            return True, 0
        pincode = str(pincode).strip()
        if pincode.endswith(".0"):          # int -> float -> str round trip
            pincode = pincode[:-2]
        if pincode in partner.pincodes:
            return True, 3
        for prefix in partner.pincode_prefixes:
            if pincode.startswith(prefix):
                return True, 2 if len(prefix) >= 3 else 1
        return False, 0

    def _assigned_today(self, partner_id: str) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        events = store.list_events(event_type="assigned", limit=2000)
        return sum(
            1 for e in events
            if e["partner_id"] == partner_id and e["created_at"] >= cutoff
        )

    def candidates(
        self,
        segment: str,
        capacity_kw: float,
        pincode: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> list[dict]:
        results = []
        for p in self.partners:
            if not p.active:
                continue
            if segment not in p.segments:
                continue
            if not (p.min_capacity_kw <= capacity_kw <= p.max_capacity_kw):
                continue

            covered, specificity = self._covers_pincode(p, pincode)
            if not covered:
                continue

            load = self._assigned_today(p.partner_id)
            if load >= p.daily_lead_cap:
                continue

            distance_km = None
            if None not in (latitude, longitude, p.latitude, p.longitude):
                distance_km = _haversine_km(
                    latitude, longitude, p.latitude, p.longitude
                )

            # Specificity first, then rating, then proximity, then spare capacity.
            headroom = 1 - (load / max(p.daily_lead_cap, 1))
            score = (
                specificity * 25
                + p.rating * 6
                + headroom * 20
                - (min(distance_km, 100) * 0.3 if distance_km is not None else 0)
            )

            results.append({
                "partner_id": p.partner_id,
                "name": p.name,
                "match_score": round(score, 2),
                "specificity": specificity,
                "distance_km": round(distance_km, 2) if distance_km else None,
                "assigned_last_24h": load,
                "daily_lead_cap": p.daily_lead_cap,
                "contact_sla_hours": p.contact_sla_hours,
                "rating": p.rating,
            })

        results.sort(key=lambda r: r["match_score"], reverse=True)
        return results


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_registry: PartnerRegistry | None = None


def get_registry() -> PartnerRegistry:
    global _registry
    if _registry is None:
        _registry = PartnerRegistry()
    return _registry


def route_lead(
    lead_id: str,
    segment: str,
    capacity_kw: float,
    pincode: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    exclude_partner_ids: list[str] | None = None,
) -> dict:
    """
    Assign a lead and start the contact SLA clock. Recording the assignment
    event is what makes leakage detectable later.
    """
    exclude = set(exclude_partner_ids or [])
    options = [
        c for c in get_registry().candidates(
            segment, capacity_kw, pincode, latitude, longitude
        )
        if c["partner_id"] not in exclude
    ]

    if not options:
        store.record_event(
            "routing_failed", lead_id=lead_id,
            payload={"pincode": pincode, "segment": segment,
                     "capacity_kw": capacity_kw,
                     "reason": "no partner with coverage and spare capacity"},
        )
        return {
            "routed": False,
            "lead_id": lead_id,
            "reason": "no_partner_available",
            "pincode": pincode,
            "alternatives": [],
        }

    chosen = options[0]
    store.record_event(
        "assigned", lead_id=lead_id, partner_id=chosen["partner_id"],
        payload={"pincode": pincode, "capacity_kw": capacity_kw,
                 "contact_sla_hours": chosen["contact_sla_hours"],
                 "match_score": chosen["match_score"]},
    )

    return {
        "routed": True,
        "lead_id": lead_id,
        "partner_id": chosen["partner_id"],
        "partner_name": chosen["name"],
        "contact_sla_hours": chosen["contact_sla_hours"],
        "match_score": chosen["match_score"],
        "distance_km": chosen["distance_km"],
        "alternatives": options[1:4],
    }
