from __future__ import annotations

import json
from pathlib import Path

from app.providers.discom import (
    DiscomProvider
)


class ReliabilityProvider:

    def __init__(
        self,
        path="data/reliability.json"
    ):

        self.path = Path(path)

        self.discom_provider = (
            DiscomProvider()
        )

        self.data = self._load()

    def _load(self):

        if not self.path.exists():

            return {
                "default": {
                    "saifi": 10,
                    "saidi_hours_per_customer_year": 12,
                    "maifi": None,
                    "source":
                        "configured_default",
                    "spatial_level":
                        "discom",
                    "confidence":
                        0.30
                }
            }

        return json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )

    def resolve(
        self,
        latitude,
        longitude
    ):

        discom = (
            self.discom_provider
            .resolve(
                latitude,
                longitude
            )
        )

        discom_name = (
            discom["discom"]
        )

        profile = (
            self.data.get(
                discom_name,
                self.data["default"]
            )
        )

        return {
            "discom":
                discom_name,

            "saifi":
                profile.get(
                    "saifi"
                ),

            "saidi_hours_per_customer_year":
                profile.get(
                    "saidi_hours_per_customer_year"
                ),

            "maifi":
                profile.get(
                    "maifi"
                ),

            "source":
                profile.get(
                    "source"
                ),

            "spatial_level":
                profile.get(
                    "spatial_level",
                    "discom"
                ),

            "confidence":
                profile.get(
                    "confidence",
                    0.30
                )
        }