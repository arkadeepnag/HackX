from __future__ import annotations

import math
from typing import Any

import requests


class SolarResourceProvider:

    def __init__(self):

        self.timeout = 20

    def get(
        self,
        latitude: float,
        longitude: float,
        data_mode: str = "real"
    ) -> dict[str, Any]:

        if data_mode == "offline":
            return self._offline(
                latitude,
                longitude
            )

        try:

            result = self._pvgis(
                latitude,
                longitude
            )

            if result is not None:
                return result

        except Exception:
            pass

        try:

            result = self._nasa_power(
                latitude,
                longitude
            )

            if result is not None:
                return result

        except Exception:
            pass

        return self._offline(
            latitude,
            longitude
        )

    def _pvgis(
        self,
        latitude,
        longitude
    ):

        url = (
            "https://re.jrc.ec.europa.eu/"
            "api/v5_2/PVcalc"
        )

        params = {
            "lat": latitude,
            "lon": longitude,
            "peakpower": 1,
            "loss": 14,
            "angle": max(
                10,
                min(
                    40,
                    abs(latitude) * 0.85
                )
            ),
            "aspect": 0,
            "outputformat": "json"
        }

        response = requests.get(
            url,
            params=params,
            timeout=self.timeout
        )

        response.raise_for_status()

        data = response.json()

        outputs = (
            data
            .get("outputs", {})
        )

        totals = (
            outputs
            .get("totals", {})
        )

        fixed = (
            totals
            .get("fixed", {})
        )

        annual_energy = (
            fixed
            .get("E_y")
        )

        if annual_energy is None:
            return None

        irradiation = (
            fixed.get(
                "E_d"
            )
        )

        if irradiation is None:
            irradiation = (
                annual_energy
                / 0.20
                / 0.86
            )

        return {
            "annual_irradiation_kwh_m2":
                float(irradiation),

            "annual_pv_yield_kwh_per_kw":
                float(annual_energy),

            "source":
                "PVGIS",

            "confidence":
                0.90,

            "latitude":
                latitude,

            "longitude":
                longitude
        }

    def _nasa_power(
        self,
        latitude,
        longitude
    ):

        url = (
            "https://power.larc.nasa.gov/"
            "api/temporal/monthly/point"
        )

        params = {
            "parameters":
                "ALLSKY_SFC_SW_DWN",

            "community":
                "RE",

            "longitude":
                longitude,

            "latitude":
                latitude,

            "start":
                "2020",

            "end":
                "2024",

            "format":
                "JSON"
        }

        response = requests.get(
            url,
            params=params,
            timeout=self.timeout
        )

        response.raise_for_status()

        data = response.json()

        parameter = (
            data
            .get("properties", {})
            .get("parameter", {})
            .get("ALLSKY_SFC_SW_DWN", {})
        )

        values = []

        for year in parameter.values():

            if not isinstance(
                year,
                dict
            ):
                continue

            for value in year.values():

                try:
                    value = float(value)

                    if value > 0:
                        values.append(
                            value
                        )

                except Exception:
                    continue

        if not values:
            return None

        monthly_mean = (
            sum(values)
            / len(values)
        )

        annual_irradiation = (
            monthly_mean
            * 365
        )

        return {
            "annual_irradiation_kwh_m2":
                float(
                    annual_irradiation
                ),

            "annual_pv_yield_kwh_per_kw":
                float(
                    annual_irradiation
                    * 0.20
                    * 0.86
                ),

            "source":
                "NASA_POWER",

            "confidence":
                0.78,

            "latitude":
                latitude,

            "longitude":
                longitude
        }

    def _offline(
        self,
        latitude,
        longitude
    ):

        latitude_factor = (
            1
            - abs(latitude - 20)
            * 0.008
        )

        latitude_factor = max(
            0.75,
            min(
                1.05,
                latitude_factor
            )
        )

        longitude_factor = (
            1
            - abs(
                longitude - 78
            )
            * 0.001
        )

        longitude_factor = max(
            0.95,
            min(
                1.02,
                longitude_factor
            )
        )

        annual_irradiation = (
            1750
            * latitude_factor
            * longitude_factor
        )

        return {
            "annual_irradiation_kwh_m2":
                float(
                    annual_irradiation
                ),

            "annual_pv_yield_kwh_per_kw":
                float(
                    annual_irradiation
                    * 0.20
                    * 0.86
                ),

            "source":
                "offline_model",

            "confidence":
                0.35,

            "latitude":
                latitude,

            "longitude":
                longitude
        }