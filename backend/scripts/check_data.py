#!/usr/bin/env python3
"""
Data readiness audit.

Reports which data the backend is actually running on. Every engine works
today, but several run on placeholder files — this tells you which, so the
gap is a known state rather than a discovery on demo day.

    python scripts/check_data.py
    python scripts/check_data.py --module12 ../hackx4.0-main/outputs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REAL, SEED, MISSING = "REAL", "SEED", "MISSING"

MARK = {REAL: "\033[92m●\033[0m", SEED: "\033[93m○\033[0m",
        MISSING: "\033[91m×\033[0m"}

rows: list[tuple[str, str, str, str]] = []


def report(status: str, name: str, detail: str, action: str = "") -> None:
    rows.append((status, name, detail, action))
    print(f"  {MARK[status]} {name:<26} {detail}")
    if action and status != REAL:
        print(f"      → {action}")


def audit_tariffs(app: Path) -> None:
    path = app / "data" / "tariffs.json"
    if not path.exists():
        return report(MISSING, "DISCOM tariffs", "file absent",
                      "restore app/data/tariffs.json")

    data = json.loads(path.read_text(encoding="utf-8"))
    profiles = [
        p for discom in data.values() if isinstance(discom, dict)
        for p in discom.values() if isinstance(p, dict) and "slabs" in p
    ]
    seeded = [p for p in profiles if p.get("source") == "MVP_CONFIG"]
    confidences = [p.get("confidence", 0) for p in profiles]
    discoms = [k for k in data if not k.startswith("_")]

    if seeded:
        report(
            SEED, "DISCOM tariffs",
            f"{len(seeded)}/{len(profiles)} profiles are MVP_CONFIG, "
            f"confidence {min(confidences):.2f}, discoms: {', '.join(discoms)}",
            "Replace with the real RERC/state tariff order. Every rupee "
            "figure in the UI derives from these slabs.",
        )
    else:
        report(REAL, "DISCOM tariffs",
               f"{len(profiles)} profiles, no MVP_CONFIG markers")


def audit_pincodes(app: Path) -> None:
    path = app / "data" / "pincodes.json"
    if not path.exists():
        return report(MISSING, "Pincode geocoding", "file absent",
                      "restore app/data/pincodes.json")

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("pincodes", raw)
    count = len([k for k in entries if not k.startswith("_")])

    if count < 1000:
        report(SEED, "Pincode geocoding", f"{count} pincodes",
               "Load the India Post directory and set RAAH_PINCODE_PATH. "
               "Unlisted pincodes fall back to a prefix match or nothing, "
               "so WhatsApp leads outside these will not appear on the map.")
    else:
        report(REAL, "Pincode geocoding", f"{count} pincodes")


def audit_partners(app: Path) -> None:
    path = app / "data" / "partners.json"
    if not path.exists():
        return report(MISSING, "Partner registry", "file absent",
                      "restore app/data/partners.json")

    partners = json.loads(path.read_text(encoding="utf-8")).get("partners", [])
    names = [p.get("name", "?") for p in partners]

    if len(partners) <= 5:
        report(SEED, "Partner registry",
               f"{len(partners)} partners: {', '.join(names)}",
               "These EPC names are invented. Replace before any demo that "
               "claims real partner coverage.")
    else:
        report(REAL, "Partner registry", f"{len(partners)} partners")


def audit_reliability(app: Path) -> None:
    path = app / "data" / "reliability.json"
    if not path.exists():
        return report(MISSING, "Grid reliability", "file absent")

    data = json.loads(path.read_text(encoding="utf-8"))
    seeded = any(
        v.get("source") == "MVP_CONFIG"
        for v in data.values() if isinstance(v, dict)
    )
    report(SEED if seeded else REAL, "Grid reliability",
           f"{len(data)} region(s), "
           f"{'MVP_CONFIG default' if seeded else 'sourced'}",
           "Feeds the outage-opportunity score. Low impact on headline "
           "numbers; safe to leave for the MVP." if seeded else "")


def audit_module12(outputs: Path | None) -> None:
    if outputs is None:
        return report(
            MISSING, "Module 1-2 candidates", "path not provided",
            "Run with --module12 ../hackx4.0-main/outputs once the pipeline "
            "has produced target_universe.csv",
        )

    target = outputs / "target_universe.csv"
    if not target.exists():
        return report(
            MISSING, "Module 1-2 candidates", f"not found at {target}",
            "Ask your teammate to run src/create_target_universe.py",
        )

    try:
        import pandas as pd
        frame = pd.read_csv(target, low_memory=False, nrows=5000)
    except Exception as exc:
        return report(MISSING, "Module 1-2 candidates",
                      f"unreadable: {type(exc).__name__}: {exc}")

    required = {"building_id", "latitude", "longitude", "building_area_m2",
                "segment"}
    present = required & set(frame.columns)
    absent = required - set(frame.columns)

    if absent:
        report(SEED, "Module 1-2 candidates",
               f"{len(frame)} rows, missing columns: {sorted(absent)}",
               "Ingestion maps aliases, but these five carry the core "
               "signal. Check GET /api/v1/ingest/schema.")
    else:
        segments = frame["segment"].value_counts().to_dict()
        report(REAL, "Module 1-2 candidates",
               f"{len(frame)} rows (first 5000), all key columns present, "
               f"segments: {segments}")


def audit_geo(root: Path, outputs: Path | None) -> None:
    demo = root / "demo_data" / "buildings.geojson"
    real = (outputs / "jaipur_buildings_places.geojson") if outputs else None

    if real and real.exists():
        size_mb = real.stat().st_size / 1e6
        report(REAL, "Building footprints",
               f"module 1-2 GeoJSON, {size_mb:.1f} MB")
    elif demo.exists():
        report(SEED, "Building footprints", "synthetic demo_data",
               "Point heatmap building_source at module 1-2's "
               "jaipur_buildings_places.geojson for real geometry.")
    else:
        report(MISSING, "Building footprints", "no geo data",
               "Run python scripts/make_demo_data.py")


def audit_env() -> None:
    import os
    token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    if token:
        report(REAL, "WhatsApp Cloud API", "access token configured")
    else:
        report(SEED, "WhatsApp Cloud API", "console mode (messages logged)",
               "Fine for the demo — /whatsapp/simulate exercises the same "
               "code path. Set WHATSAPP_ACCESS_TOKEN only for live sending.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=Path("app"))
    parser.add_argument("--module12", type=Path, default=None,
                        help="path to the teammate's outputs/ directory")
    args = parser.parse_args()

    if not args.app.exists():
        print(f"app directory not found at {args.app.resolve()}")
        print("Run this from the project root (the folder containing app/).")
        return 1

    print("\n\033[1mData readiness\033[0m")
    print("  ● real   ○ placeholder   × missing\n")

    audit_tariffs(args.app)
    audit_pincodes(args.app)
    audit_partners(args.app)
    audit_reliability(args.app)
    audit_geo(args.app.parent, args.module12)
    audit_module12(args.module12)
    audit_env()

    real = sum(1 for r, *_ in rows if r == REAL)
    seed = sum(1 for r, *_ in rows if r == SEED)
    missing = sum(1 for r, *_ in rows if r == MISSING)

    print(f"\n{'=' * 58}")
    print(f"  {real} real   {seed} placeholder   {missing} missing")
    print(f"{'=' * 58}")

    if seed or missing:
        print("\nEvery engine works on placeholder data — nothing is broken.")
        print("The items above change the numbers, not the code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
