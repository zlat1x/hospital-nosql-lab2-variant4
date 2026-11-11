"""Controlled, repeatable seed of IDENTICAL business facts in both engines."""
import argparse
from datetime import timezone
import sys

import psycopg
from pymongo import ASCENDING, DESCENDING, MongoClient

from src.config import pg_dsn, mongo_uri, mongo_db
from src.dataset import CATALOG, build_report

VALIDATOR = {"$jsonSchema": {
    "bsonType": "object",
    "required": ["_id", "patient_id", "collected_at", "status", "panels"],
    "properties": {
        "_id": {"bsonType": "string"},
        "patient_id": {"bsonType": "string"},
        "collected_at": {"bsonType": "date"},
        "status": {"enum": ["final", "amended"]},
        "panels": {"bsonType": "array", "minItems": 1, "maxItems": 5, "items": {
            "bsonType": "object", "required": ["code", "measurements"],
            "properties": {
                "code": {"bsonType": "string"},
                "measurements": {"bsonType": "array", "minItems": 1,
                                 "maxItems": 32, "items": {
                    "bsonType": "object",
                    "required": ["code", "label", "unit", "value", "reference_low", "reference_high"],
                    "properties": {
                        "code": {"bsonType": "string"},
                        "label": {"bsonType": "string"},
                        "unit": {"bsonType": "string"},
                        "value": {"bsonType": ["double", "int", "long", "decimal"]},
                        "reference_low": {"bsonType": ["double", "int", "long", "decimal"]},
                        "reference_high": {"bsonType": ["double", "int", "long", "decimal"]},
                    },
                }},
            },
        }},
    },
}}


def setup_mongo(db):
    if "reports" not in db.list_collection_names():
        db.create_collection("reports", validator=VALIDATOR)
    else:
        db.command("collMod", "reports", validator=VALIDATOR)
    collection = db.reports
    collection.create_index([("patient_id", ASCENDING), ("collected_at", DESCENDING),
                             ("_id", DESCENDING)], name="ix_patient_time")
    collection.create_index([("patient_id", ASCENDING),
                             ("panels.measurements.code", ASCENDING),
                             ("collected_at", DESCENDING)], name="ix_patient_marker_time")
    return collection


def load(reports: int, patients: int):
    if reports < 1 or patients < 1 or patients > reports:
        raise ValueError("Expected reports >= patients >= 1")
    with psycopg.connect(pg_dsn(), autocommit=True) as pg, MongoClient(
            mongo_uri(), serverSelectionTimeoutMS=10000, tz_aware=True, tzinfo=timezone.utc) as mc:
        mc.admin.command("ping")
        col = setup_mongo(mc[mongo_db()])
        # Reset the isolated experiment dataset before deterministic loading.
        pg.execute("TRUNCATE lab2.measurement,lab2.panel,lab2.report,lab2.test_catalog")
        col.delete_many({})
        with pg.transaction():
            with pg.cursor() as cur:
                cur.executemany(
                    "INSERT INTO lab2.test_catalog(panel_code,test_code,display_name,unit) VALUES(%s,%s,%s,%s)",
                    [(p, c, name, unit) for p, c, name, unit, *_ in CATALOG],
                )
        # PostgreSQL COPY protocol permits ONE COPY stream per connection at a time.
        # Order matters because foreign keys are enforced at insertion.
        with pg.transaction():
            with pg.cursor() as cur:
                with cur.copy("COPY lab2.report(id,patient_id,source_encounter_id,collected_at,status) FROM STDIN") as cp:
                    for i in range(1, reports + 1):
                        d = build_report(i, patients)
                        cp.write_row((d["_id"], d["patient_id"], None, d["collected_at"], d["status"]))
                with cur.copy("COPY lab2.panel(report_id,code) FROM STDIN") as cp:
                    for i in range(1, reports + 1):
                        d = build_report(i, patients)
                        for panel in d["panels"]:
                            cp.write_row((d["_id"], panel["code"]))
                with cur.copy("COPY lab2.measurement(report_id,panel_code,test_code,value_num,reference_low,reference_high) FROM STDIN") as cp:
                    for i in range(1, reports + 1):
                        d = build_report(i, patients)
                        for panel in d["panels"]:
                            for m in panel["measurements"]:
                                cp.write_row((d["_id"], panel["code"], m["code"],
                                              m["value"], m["reference_low"], m["reference_high"]))
        for start in range(1, reports + 1, 1000):
            batch = [build_report(i, patients) for i in range(start, min(start + 1000, reports + 1))]
            col.insert_many(batch, ordered=True)
        sql_count = pg.execute("SELECT COUNT(*) FROM lab2.report").fetchone()[0]
        mongo_count = col.count_documents({})
        marker_count = pg.execute("SELECT COUNT(*) FROM lab2.measurement").fetchone()[0]
        assert sql_count == mongo_count == reports and marker_count == reports * len(CATALOG)
        pg.execute("ANALYZE lab2.report")
        pg.execute("ANALYZE lab2.measurement")
        print(f"Loaded {reports:,} identical synthetic reports into SQL + MongoDB; "
              f"{marker_count:,} marker measurements in PostgreSQL.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=int, default=10000)
    parser.add_argument("--patients", type=int, default=250)
    args = parser.parse_args()
    try:
        load(args.reports, args.patients)
    except Exception as exc:
        print(f"LOAD ERROR: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
