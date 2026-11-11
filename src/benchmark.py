"""Comparable warm-cache client round trips (not server-only execution time)."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import random
import time

import psycopg
from pymongo import MongoClient

from src.config import pg_dsn, mongo_db, mongo_uri
from src.dataset import build_report
from src.metrics import summarize
from src.stores import SQL_ABNORMAL, SQL_FULL_REPORT, SQL_HISTORY, SQL_LATEST, SqlStore, MongoStore
from src.validate import validate


def timed_call(fn):
    t = time.perf_counter_ns()
    fn()
    return (time.perf_counter_ns() - t) / 1_000_000


def run_paired(label, arguments, sql_fn, mongo_fn, warmups, measurements):
    """Same argument sequence on both backends; alternate engine order by trial."""
    if not arguments:
        raise ValueError("Non-empty arguments required")
    sql_times, mongo_times = [], []
    for i in range(warmups + measurements):
        arg = arguments[i % len(arguments)]
        funcs = [("SQL", lambda a=arg: sql_fn(a)),
                 ("MongoDB", lambda a=arg: mongo_fn(a))]
        if i % 2:
            funcs.reverse()
        for engine, fn in funcs:
            elapsed = timed_call(fn)
            if i >= warmups:
                (sql_times if engine == "SQL" else mongo_times).append(elapsed)
    return [{"workload": label, "engine": "SQL", **summarize(sql_times)},
            {"workload": label, "engine": "MongoDB", **summarize(mongo_times)}]


def plans(pg, col, patient, report_id):
    """Capture real read plans OUTSIDE timed trials (server execution statistics)."""
    pg_plans = {}
    for label, query, params in [
        ("full_report", SQL_FULL_REPORT, (report_id,)),
        ("latest_ids", SQL_LATEST, (patient,)),
        ("abnormal_count", SQL_ABNORMAL, (patient,)),
        ("marker_history", SQL_HISTORY, (patient, "GLU")),
    ]:
        pg_plans[label] = pg.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, params).fetchone()[0]

    mongo_commands = [
        ("full_report", {"find": col.name, "filter": {"_id": report_id}, "limit": 1}),
        ("latest_ids", {"find": col.name, "filter": {"patient_id": patient},
                        "projection": {"_id": 1}, "sort": {"collected_at": -1, "_id": -1}, "limit": 10}),
        ("abnormal_count", {"aggregate": col.name, "pipeline": [
            {"$match": {"patient_id": patient}},
            {"$unwind": "$panels"},
            {"$unwind": "$panels.measurements"},
            {"$match": {"$expr": {"$or": [
                {"$lt": ["$panels.measurements.value", "$panels.measurements.reference_low"]},
                {"$gt": ["$panels.measurements.value", "$panels.measurements.reference_high"]},
            ]}}},
            {"$count": "total"},
        ], "cursor": {}}),
        ("marker_history", {"aggregate": col.name, "pipeline": [
            {"$match": {"patient_id": patient, "panels.measurements.code": "GLU"}},
            {"$unwind": "$panels"},
            {"$unwind": "$panels.measurements"},
            {"$match": {"panels.measurements.code": "GLU"}},
            {"$sort": {"collected_at": -1, "_id": -1}},
            {"$limit": 20},
            {"$project": {"_id": 1, "collected_at": 1,
                          "value": "$panels.measurements.value"}},
        ], "cursor": {}}),
    ]
    mongo_plans = {}
    for label, command in mongo_commands:
        try:
            # Aggregation explain may report plans under stages.$cursor.
            data = col.database.command({"explain": command, "verbosity": "executionStats"})
            mongo_plans[label] = data
        except Exception as exc:
            mongo_plans[label] = {"error": str(exc)}
    return {"postgres": pg_plans, "mongodb": mongo_plans}


def benchmark(samples, warmups, write_samples, outdir):
    outdir.mkdir(exist_ok=True, parents=True)
    with psycopg.connect(pg_dsn(), autocommit=True) as pg, MongoClient(
            mongo_uri(), serverSelectionTimeoutMS=10000, tz_aware=True, tzinfo=timezone.utc) as mc:
        col = mc[mongo_db()].reports
        verified = validate(pg, col, samples=50)
        count = verified["reports"]
        ids = [r[0] for r in pg.execute("SELECT id FROM lab2.report ORDER BY id").fetchall()]
        patient_ids = [r[0] for r in pg.execute(
            "SELECT DISTINCT patient_id FROM lab2.report ORDER BY patient_id").fetchall()]
        rng = random.Random(20261110)
        chosen_ids = [rng.choice(ids) for _ in range(max(samples, 30))]
        chosen_patients = [rng.choice(patient_ids) for _ in range(max(samples, 30))]
        sql, mongo = SqlStore(pg), MongoStore(col)
        results = []
        for label, args, sf, mf in [
            ("full_report", chosen_ids, sql.full_report, mongo.full_report),
            ("latest_10_ids", chosen_patients, sql.latest, mongo.latest),
            ("abnormal_count", chosen_patients, sql.abnormal_count, mongo.abnormal_count),
            ("marker_history_20", chosen_patients, sql.history, mongo.history),
        ]:
            results += run_paired(label, args, sf, mf, warmups, samples)
            print(f"Measured {label}: {samples} round trips per database")

        # Writes change actual stored values, alternating SQL and MongoDB request order.
        # Use a fixed existing report and restore it even when a benchmark raises.
        target_id = chosen_ids[0]
        original = next(m for p in mongo.full_report(target_id)["panels"] for m in p["measurements"]
                        if m["code"] == "WBC")["value"]
        try:
            values = [8.27 if i % 2 else 8.49 for i in range(max(write_samples + 5, 10))]
            results += run_paired("update_one_marker", values,
                                  lambda v: sql.update_wbc(target_id, v),
                                  lambda v: mongo.update_wbc(target_id, v),
                                  5, write_samples)
        finally:
            sql.update_wbc(target_id, original)
            mongo.update_wbc(target_id, original)

        # New report insert: SQL is one logical transaction spanning 3 tables;
        # MongoDB is one document. Cleanup OUTSIDE the timed region.
        insert_args = []
        for i in range(write_samples + 5):
            d = build_report((i % count) + 1, len(patient_ids))
            d["_id"] = f"TMP-BENCH-{i:08d}"
            insert_args.append(d)
        try:
            # Insert experiments are unique, so warmup and measured calls use distinct docs.
            counter = {"SQL": 0, "MongoDB": 0}
            def insert_sql(_unused):
                d = insert_args[counter["SQL"]]
                counter["SQL"] += 1
                sql.insert(d)
            def insert_mongo(_unused):
                d = insert_args[counter["MongoDB"]]
                counter["MongoDB"] += 1
                mongo.insert(d)
            results += run_paired("insert_full_report", [None], insert_sql, insert_mongo,
                                  5, write_samples)
        finally:
            pg.execute("DELETE FROM lab2.report WHERE id LIKE 'TMP-BENCH-%'")
            col.delete_many({"_id": {"$regex": "^TMP-BENCH-"}})

        # Ensure comparisons are still equivalent after controlled mutable workloads.
        verified_after = validate(pg, col, samples=25)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"benchmark_{count}_{stamp}"
        pg_total_bytes = pg.execute("""
          SELECT COALESCE(sum(pg_total_relation_size(c.oid)), 0)::bigint
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
          WHERE n.nspname = 'lab2' AND c.relkind = 'r'
        """).fetchone()[0]
        mongo_sizes = {}
        try:
            stats = col.database.command("collStats", col.name)
            mongo_sizes = {"logical_bytes": stats.get("size"),
                           "storage_bytes": stats.get("storageSize"),
                           "index_bytes": stats.get("totalIndexSize")}
        except Exception as exc:
            mongo_sizes = {"error": f"Collection storage stats unavailable: {exc}"}
        metadata = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "postgres": pg.execute("SHOW server_version").fetchone()[0],
                            "mongodb": mc.server_info().get("version"),
                            "topology": "three separate Docker containers on one host; localhost TCP"},
            "dataset": {"reports": count, "patients": len(patient_ids),
                        "measurements": verified["measurements"]},
            "storage": {"postgres_tables_plus_indexes_bytes": pg_total_bytes,
                        "mongodb": mongo_sizes},
            "procedure": {"warmups": warmups, "read_trials_per_database": samples,
                          "write_trials_per_database": write_samples,
                          "ordering": "SQL/MongoDB order alternated by trial",
                          "metric": "client round-trip latency in milliseconds; sequential, single-thread, warm cache",
                          "timing_excludes": "loading, validation, query plans, cleanup, report generation"},
            "validated_before": verified, "validated_after": verified_after, "results": results,
        }
        json_path = outdir / f"{base}.json"
        json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        csv_path = outdir / f"{base}.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)
        try:
            query_plans = plans(pg, col, patient_ids[0], ids[0])
            (outdir / f"{base}_plans.json").write_text(
                json.dumps(query_plans, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            print(f"Plan capture failed (timings still valid): {exc}")
        print(f"RESULTS: {csv_path} and {json_path}")
        for s, m in zip(results[::2], results[1::2]):
            ratio = s["p50_ms"] / m["p50_ms"] if m["p50_ms"] > 0 else None
            ratio_str = f"{ratio:.2f}x" if ratio is not None else "n/a"
            print(f"{s['workload']}: SQL median={s['p50_ms']} ms; "
                  f"MongoDB median={m['p50_ms']} ms; SQL/Mongo={ratio_str}")
        return metadata


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", type=int, default=120)
    ap.add_argument("--warmups", type=int, default=15)
    ap.add_argument("--write-samples", type=int, default=25)
    ap.add_argument("--out", type=Path, default=Path("results"))
    args = ap.parse_args()
    if args.samples < 1 or args.warmups < 0 or args.write_samples < 1:
        ap.error("Invalid sample counts")
    benchmark(args.samples, args.warmups, args.write_samples, args.out)


if __name__ == "__main__":
    main()
