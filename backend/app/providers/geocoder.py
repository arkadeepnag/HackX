"""
Pincode -> coordinates.

WhatsApp leads capture a pincode but never a lat/lon, so they were
invisible on the map layer. This resolves a centroid for each pincode and
also gives the flow a real location to pull irradiance and tariff from,
instead of the national fallback.

Ships with a small seed file. Point RAAH_PINCODE_PATH at a fuller dataset
(India Post publishes one) and nothing else changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "pincodes.json"


class PincodeGeocoder:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(
            path or os.getenv("RAAH_PINCODE_PATH") or DEFAULT_PATH
        )
        self.data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw.get("pincodes", raw)

    def resolve(self, pincode: str | None) -> dict | None:
        """
        Exact match first, then progressively shorter prefixes. A prefix
        hit is a district-level approximation -- good enough for
        irradiance and tariff, and flagged as such so nobody mistakes it
        for a rooftop coordinate.
        """
        if not pincode:
            return None
        pincode = str(pincode).strip()

        exact = self.data.get(pincode)
        if exact:
            return {**exact, "match": "exact", "confidence": 0.9}

        for length in (4, 3, 2):
            prefix = pincode[:length]
            for key, value in self.data.items():
                if key.startswith(prefix):
                    return {
                        **value,
                        "match": f"prefix_{length}",
                        "confidence": 0.9 - (6 - length) * 0.15,
                        "note": (
                            "district-level approximation, not a rooftop "
                            "coordinate"
                        ),
                    }
        return None


_geocoder: PincodeGeocoder | None = None


def get_geocoder() -> PincodeGeocoder:
    global _geocoder
    if _geocoder is None:
        _geocoder = PincodeGeocoder()
    return _geocoder