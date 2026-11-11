"""Cross-engine correctness contract. Must pass BEFORE benchmarking."""
import argparse
from datetime import timezone
import json
import random

import psycopg
from pymongo import MongoClient

from src.config import pg_dsn, mongo_uri, mongo_db
from src.dataset import CATALOG, normalize_report, count_abnormal
from src.stores import SqlStore, MongoStore


def validate(pg, col, samples=50, exhaustive=False):
    sql, mongo = SqlStore(pg), MongoStore(col)
    n = int(pg.execute("SELECT COUNT(*) FROM lab2.report").fetchone()[0])
    m = col.count_documents({})
    if n < 1 or n != m:
        raise AssertionError(f"Report counts differ: SQL={n}, Mongo={m}. Run src.load first.")
    markers = int(pg.execute("SELECT COUNT(*) FROM lab2.measurement").fetchone()[0])
    assert markers == n * len(CATALOG), f"Unexpected SQL marker count {markers}"
    ids = list(range(1, n + 1)) if exhaustive else sorted(set([1, n] + random.Random(4).sample(
        range(1, n + 1), min(samples, n))))
    for i in ids:
        report_id = f"R{i:08d}"
        a, b = sql.full_report(report_id), mongo.full_report(report_id)
        if a is None or b is None:
            raise AssertionError(f"Missing report: {report_id}")
        if normalize_report(a) != normalize_report(b):
            raise AssertionError(f"Different report contents for {report_id}")
        # Check the predicate independently of DB query implementation.
        if count_abnormal(a) != count_abnormal(b):
            raise AssertionError(f"Different abnormal interpretation for {report_id}")
    assert sql.full_report("R-NO-SUCH-REPORT") is None
    assert mongo.full_report("R-NO-SUCH-REPORT") is None
    assert sql.latest("DEMO-P-NONEXISTENT") == mongo.latest("DEMO-P-NONEXISTENT") == []
    assert sql.abnormal_count("DEMO-P-NONEXISTENT") == mongo.abnormal_count("DEMO-P-NONEXISTENT") == 0
    assert sql.history("DEMO-P-NONEXISTENT") == mongo.history("DEMO-P-NONEXISTENT") == []
    patient_ids = [r[0] for r in pg.execute(
        "SELECT DISTINCT patient_id FROM lab2.report ORDER BY patient_id LIMIT 12").fetchall()]
    for patient in patient_ids:
        assert sql.latest(patient) == mongo.latest(patient), f"Different latest reports: {patient}"
        assert sql.abnormal_count(patient) == mongo.abnormal_count(patient), f"Different abnormal count: {patient}"
        assert sql.history(patient) == mongo.history(patient), f"Different marker history: {patient}"
    result = {"ok": True, "reports": n, "measurements": markers,
              "reports_checked": len(ids), "patients_checked": len(patient_ids),
              "exhaustive": exhaustive}
    print("CORRECTNESS PASSED: " + json.dumps(result, ensure_ascii=False))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=int, default=50)
    ap.add_argument("--all", action="store_true", help="Compare EVERY report; slower for big datasets")
    args = ap.parse_args()
    if args.samples < 1:
        ap.error("--samples must be >= 1")
    with psycopg.connect(pg_dsn(), autocommit=True) as pg, MongoClient(
        mongo_uri(), serverSelectionTimeoutMS=10000, tz_aware=True, tzinfo=timezone.utc) as client:
        validate(pg, client[mongo_db()].reports, args.samples, args.all)


if __name__ == "__main__":
    main()
