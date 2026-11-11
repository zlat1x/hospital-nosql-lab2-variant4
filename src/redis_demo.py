"""Independent NoSQL family: Redis key-value (cache/ephemeral derived state)."""
from datetime import timezone
import json
import redis
import psycopg
from pymongo import MongoClient

from src.config import pg_dsn, mongo_uri, mongo_db, redis_url
from src.stores import SqlStore, MongoStore

KEY_BASE = "hospital-lab2:demo:"


def main():
    r = redis.Redis.from_url(redis_url(), decode_responses=True,
                             socket_timeout=5, socket_connect_timeout=5)
    with psycopg.connect(pg_dsn(), autocommit=True) as pg, MongoClient(mongo_uri(), tz_aware=True, tzinfo=timezone.utc) as mc:
        sql, mongo = SqlStore(pg), MongoStore(mc[mongo_db()].reports)
        latest = sql.latest("DEMO-P00001")
        if not latest:
            raise RuntimeError("Run 'python -m src.load' before Redis demo")
        report_id = latest[0]
        report = mongo.full_report(report_id)
        if not report:
            raise RuntimeError("Missing report in MongoDB")
        # Redis caches a summary reconstructible from the primary stores.
        summary = {"report_id": report_id,
                   "collected_at": report["collected_at"].astimezone(timezone.utc).isoformat(),
                   "patient_id": report["patient_id"]}
        kv = KEY_BASE + "latest:DEMO-P00001"
        hkey = KEY_BASE + "report-meta:" + report_id
        skey = KEY_BASE + "observed-tests:" + report_id
        try:
            r.set(kv, json.dumps(summary, ensure_ascii=False), ex=120)  # SET + GET + TTL
            print("GET:", r.get(kv))
            print("TTL:", r.ttl(kv))
            r.hset(hkey, mapping={"report_id": report_id, "status": report["status"],
                                  "patient_id": report["patient_id"]})
            print("HGETALL:", r.hgetall(hkey))
            codes = [m["code"] for p in report["panels"] for m in p["measurements"]]
            r.sadd(skey, *codes)
            print("SISMEMBER GLU:", bool(r.sismember(skey, "GLU")))
            print("SMEMBERS:", sorted(r.smembers(skey)))
            print("SCARD:", r.scard(skey))
            r.expire(hkey, 120)
            r.expire(skey, 120)
            assert json.loads(r.get(kv))["report_id"] == report_id
            assert r.hget(hkey, "status") == "final"
            assert bool(r.sismember(skey, "GLU"))
            assert 0 < r.ttl(kv) <= 120
            print("Redis basic operations PASSED (recreatable cache, keys with TTL).")
        finally:
            # Remove only keys owned by this experiment.
            r.delete(kv, hkey, skey)
            r.close()


if __name__ == "__main__":
    main()
