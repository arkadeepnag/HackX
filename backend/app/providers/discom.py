from __future__ import annotations


class DiscomProvider:

    def __init__(self):

        self.regions = [
            {
                "name": "JVVNL",
                "state": "Rajasthan",
                "lat_min": 24.0,
                "lat_max": 28.5,
                "lon_min": 74.5,
                "lon_max": 78.5
            },
            {
                "name": "AVVNL",
                "state": "Rajasthan",
                "lat_min": 24.0,
                "lat_max": 28.5,
                "lon_min": 72.0,
                "lon_max": 76.0
            },
            {
                "name": "JDVVNL",
                "state": "Rajasthan",
                "lat_min": 26.0,
                "lat_max": 30.5,
                "lon_min": 70.0,
                "lon_max": 75.5
            }
        ]

    def resolve(
        self,
        latitude: float,
        longitude: float
    ):

        for region in self.regions:

            if (
                region["lat_min"]
                <= latitude
                <= region["lat_max"]
                and
                region["lon_min"]
                <= longitude
                <= region["lon_max"]
            ):

                return {
                    "discom":
                        region["name"],

                    "state":
                        region["state"],

                    "source":
                        "configured_boundary",

                    "confidence":
                        0.65
                }

        return {
            "discom":
                "UNKNOWN",

            "state":
                "UNKNOWN",

            "source":
                "unresolved",

            "confidence":
                0.0
        }