from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from app.providers.discom import (
    DiscomProvider
)


class TariffProvider:

    def __init__(
        self,
        path=None
    ):

        # Resolve relative to this file, not the process working directory.
        # Previously a launch from anywhere but app/ silently fell back to
        # the hardcoded defaults below.
        self.path = Path(path) if path else DATA_DIR / "tariffs.json"

        self.discom_provider = (
            DiscomProvider()
        )

        self.data = self._load()

    def _load(self):

        if not self.path.exists():

            return {
                "default": {
                    "residential": {
                        "slabs": [
                            {
                                "upto": 50,
                                "rate": 4.75
                            },
                            {
                                "upto": 150,
                                "rate": 6.00
                            },
                            {
                                "upto": 300,
                                "rate": 7.00
                            },
                            {
                                "upto": 500,
                                "rate": 7.00
                            },
                            {
                                "upto": None,
                                "rate": 7.50
                            }
                        ],
                        "fixed_charge_rs": 0
                    },

                    "commercial": {
                        "slabs": [
                            {
                                "upto": 100,
                                "rate": 8.00
                            },
                            {
                                "upto": 500,
                                "rate": 9.00
                            },
                            {
                                "upto": None,
                                "rate": 10.00
                            }
                        ],
                        "fixed_charge_rs": 0
                    }
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
        longitude,
        segment
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
            self.data
            .get(
                discom_name,
                self.data["default"]
            )
            .get(
                segment,
                self.data["default"][
                    "residential"
                ]
            )
        )

        representative_rate = (
            self._representative_rate(
                profile
            )
        )

        return {
            "discom":
                discom_name,

            "state":
                discom["state"],

            "segment":
                segment,

            "slabs":
                profile["slabs"],

            "fixed_charge_rs":
                profile.get(
                    "fixed_charge_rs",
                    0
                ),

            "representative_rate_rs_per_kwh":
                representative_rate,

            "source":
                profile.get(
                    "source",
                    "configured_tariff"
                ),

            "effective_date":
                profile.get(
                    "effective_date"
                ),

            "confidence":
                profile.get(
                    "confidence",
                    0.50
                )
        }

    def effective_rate(
        self,
        monthly_consumption_kwh,
        tariff
    ):
        """
        Blended Rs/kWh actually paid at this consumption level.

        Solar displaces units from the TOP of the slab stack, so the
        marginal rate is what savings should be valued at. A flat average
        of slab rates understates savings for anyone in an upper slab.
        """
        consumption = max(0.0, float(monthly_consumption_kwh))
        if consumption <= 0:
            return float(tariff.get("representative_rate_rs_per_kwh", 0))

        bill = self.bill(consumption, tariff)
        fixed = float(tariff.get("fixed_charge_rs", 0))
        return (bill - fixed) / consumption

    def marginal_rate(
        self,
        monthly_consumption_kwh,
        tariff
    ):
        """Rate of the slab the customer's last unit falls in."""
        consumption = max(0.0, float(monthly_consumption_kwh))
        previous = 0.0
        for slab in tariff["slabs"]:
            upper = slab.get("upto")
            if upper is None or consumption <= float(upper):
                return float(slab["rate"])
            previous = float(upper)
        return float(tariff["slabs"][-1]["rate"])

    def _representative_rate(
        self,
        profile
    ):

        slabs = profile[
            "slabs"
        ]

        finite_rates = [
            float(
                slab["rate"]
            )
            for slab in slabs
            if slab.get("rate") is not None
        ]

        if not finite_rates:
            return 0.0

        return (
            sum(finite_rates)
            / len(finite_rates)
        )

    def bill(
        self,
        monthly_consumption_kwh,
        tariff
    ):

        remaining = max(
            0,
            monthly_consumption_kwh
        )

        previous_limit = 0
        energy_charge = 0

        for slab in tariff[
            "slabs"
        ]:

            upper = slab.get(
                "upto"
            )

            rate = float(
                slab["rate"]
            )

            if upper is None:

                quantity = remaining

            else:

                quantity = min(
                    remaining,
                    max(
                        0,
                        upper
                        - previous_limit
                    )
                )

            energy_charge += (
                quantity * rate
            )

            remaining -= quantity

            if remaining <= 0:
                break

            if upper is not None:
                previous_limit = (
                    upper
                )

        return (
            energy_charge
            + float(
                tariff.get(
                    "fixed_charge_rs",
                    0
                )
            )
        )