"""Synthetic, non-clinical, deterministic laboratory reports."""
from datetime import datetime, timedelta, timezone

CATALOG = (
    ("CBC", "WBC", "White blood cells", "10^9/L", 4.0, 10.0, 7.0),
    ("CBC", "RBC", "Red blood cells", "10^12/L", 4.0, 5.5, 4.7),
    ("CBC", "HGB", "Hemoglobin", "g/L", 120.0, 165.0, 142.0),
    ("CBC", "PLT", "Platelets", "10^9/L", 150.0, 400.0, 270.0),
    ("MET", "GLU", "Glucose", "mmol/L", 3.9, 6.1, 5.0),
    ("MET", "CRE", "Creatinine", "umol/L", 53.0, 106.0, 77.0),
    ("MET", "ALT", "ALT", "U/L", 7.0, 45.0, 24.0),
    ("MET", "AST", "AST", "U/L", 8.0, 40.0, 22.0),
)
PANELS = ("CBC", "MET")
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def build_report(index: int, patients: int) -> dict:
    if index < 1 or patients < 1:
        raise ValueError("index and patients must be positive")
    panels = []
    for panel_code in PANELS:
        measurements = []
        for seq, (panel, code, label, unit, low, high, base) in enumerate(CATALOG):
            if panel != panel_code:
                continue
            # Deliberately include normal and abnormal observations for meaningful filters.
            change = ((index * 73 + seq * 31) % 101 - 50) / 31.25
            value = round(base + change * ((high - low) / 3), 2)
            measurements.append({
                "code": code, "label": label, "unit": unit,
                "value": value, "reference_low": low, "reference_high": high,
            })
        panels.append({"code": panel_code, "measurements": measurements})
    return {
        "_id": f"R{index:08d}",
        "patient_id": f"DEMO-P{((index - 1) % patients) + 1:05d}",
        "source_encounter_id": None,  # This test dataset is not linked to Lab 1 records.
        "collected_at": BASE_TIME + timedelta(minutes=index * 7),
        "status": "final",
        "panels": panels,
    }


def normalize_report(doc: dict) -> dict:
    """Canonical representation for cross-database equality checks."""
    return {
        "id": doc["_id"], "patient_id": doc["patient_id"],
        "source_encounter_id": doc.get("source_encounter_id"),
        "collected_at": doc["collected_at"].astimezone(timezone.utc).isoformat(),
        "status": doc["status"],
        "panels": [
            {
                "code": panel["code"],
                "measurements": [
                    {"code": m["code"], "label": m["label"], "unit": m["unit"],
                     "value": round(float(m["value"]), 2),
                     "reference_low": round(float(m["reference_low"]), 2),
                     "reference_high": round(float(m["reference_high"]), 2)}
                    for m in sorted(panel["measurements"], key=lambda x: x["code"])
                ],
            } for panel in sorted(doc["panels"], key=lambda x: x["code"])
        ],
    }


def count_abnormal(doc: dict) -> int:
    return sum(
        not (m["reference_low"] <= m["value"] <= m["reference_high"])
        for p in doc["panels"] for m in p["measurements"]
    )
