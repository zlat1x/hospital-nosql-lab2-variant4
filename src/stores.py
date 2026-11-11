"""Equivalent SQL and MongoDB operations, including full report reassembly."""
from datetime import timezone
from decimal import Decimal

SQL_FULL_REPORT = """
SELECT r.id, r.patient_id, r.source_encounter_id, r.collected_at, r.status,
       p.code, m.test_code, c.display_name, c.unit,
       m.value_num, m.reference_low, m.reference_high
FROM lab2.report AS r
LEFT JOIN lab2.panel AS p ON p.report_id = r.id
LEFT JOIN lab2.measurement AS m
  ON m.report_id = p.report_id AND m.panel_code = p.code
LEFT JOIN lab2.test_catalog AS c
  ON c.panel_code = m.panel_code AND c.test_code = m.test_code
WHERE r.id = %s
ORDER BY p.code, m.test_code
"""
SQL_LATEST = """
SELECT id FROM lab2.report
WHERE patient_id = %s
ORDER BY collected_at DESC, id DESC LIMIT 10
"""
SQL_ABNORMAL = """
SELECT COUNT(*) FROM lab2.report AS r
JOIN lab2.measurement AS m ON m.report_id = r.id
WHERE r.patient_id = %s
  AND (m.value_num < m.reference_low OR m.value_num > m.reference_high)
"""
SQL_HISTORY = """
SELECT r.id, r.collected_at, m.value_num
FROM lab2.report AS r
JOIN lab2.measurement AS m ON m.report_id = r.id
WHERE r.patient_id = %s AND m.test_code = %s
ORDER BY r.collected_at DESC, r.id DESC LIMIT 20
"""


def _as_python(value):
    return float(value) if isinstance(value, Decimal) else value


class SqlStore:
    def __init__(self, connection):
        self.conn = connection

    def full_report(self, report_id):
        rows = self.conn.execute(SQL_FULL_REPORT, (report_id,)).fetchall()
        if not rows:
            return None
        first = rows[0]
        doc = {"_id": first[0], "patient_id": first[1], "source_encounter_id": first[2],
               "collected_at": first[3], "status": first[4], "panels": []}
        panels = {}
        for row in rows:
            code = row[5]
            if code is None:
                continue
            if code not in panels:
                panels[code] = {"code": code, "measurements": []}
                doc["panels"].append(panels[code])
            if row[6] is not None:
                panels[code]["measurements"].append({
                    "code": row[6], "label": row[7], "unit": row[8],
                    "value": _as_python(row[9]),
                    "reference_low": _as_python(row[10]),
                    "reference_high": _as_python(row[11]),
                })
        return doc

    def latest(self, patient_id):
        return [r[0] for r in self.conn.execute(SQL_LATEST, (patient_id,)).fetchall()]

    def abnormal_count(self, patient_id):
        return int(self.conn.execute(SQL_ABNORMAL, (patient_id,)).fetchone()[0])

    def history(self, patient_id, test_code="GLU"):
        return [(r[0], r[1].astimezone(timezone.utc).isoformat(), float(r[2]))
                for r in self.conn.execute(SQL_HISTORY, (patient_id, test_code)).fetchall()]

    def update_wbc(self, report_id, value):
        with self.conn.transaction():
            result = self.conn.execute(
                "UPDATE lab2.measurement SET value_num=%s "
                "WHERE report_id=%s AND panel_code='CBC' AND test_code='WBC'",
                (value, report_id),
            )
            if result.rowcount != 1:
                raise RuntimeError(f"Missing SQL report {report_id}")

    def insert(self, doc):
        # One logical report transaction; foreign keys make 3 physical tables necessary.
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO lab2.report(id,patient_id,source_encounter_id,collected_at,status) "
                "VALUES(%s,%s,%s,%s,%s)",
                (doc["_id"], doc["patient_id"], doc["source_encounter_id"],
                 doc["collected_at"], doc["status"]),
            )
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO lab2.panel(report_id,code) VALUES(%s,%s)",
                    [(doc["_id"], p["code"]) for p in doc["panels"]],
                )
                cur.executemany(
                    "INSERT INTO lab2.measurement "
                    "(report_id,panel_code,test_code,value_num,reference_low,reference_high) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    [(doc["_id"], p["code"], m["code"], m["value"],
                      m["reference_low"], m["reference_high"])
                     for p in doc["panels"] for m in p["measurements"]],
                )


class MongoStore:
    def __init__(self, collection):
        self.col = collection

    def full_report(self, report_id):
        return self.col.find_one({"_id": report_id})

    def latest(self, patient_id):
        cursor = self.col.find({"patient_id": patient_id}, {"_id": 1}).sort(
            [("collected_at", -1), ("_id", -1)]).limit(10)
        return [r["_id"] for r in cursor]

    def abnormal_count(self, patient_id):
        pipeline = [
            {"$match": {"patient_id": patient_id}},
            {"$unwind": "$panels"},
            {"$unwind": "$panels.measurements"},
            {"$match": {"$expr": {"$or": [
                {"$lt": ["$panels.measurements.value", "$panels.measurements.reference_low"]},
                {"$gt": ["$panels.measurements.value", "$panels.measurements.reference_high"]},
            ]}}},
            {"$count": "total"},
        ]
        rows = list(self.col.aggregate(pipeline))
        return int(rows[0]["total"]) if rows else 0

    def history(self, patient_id, test_code="GLU"):
        pipeline = [
            {"$match": {"patient_id": patient_id, "panels.measurements.code": test_code}},
            {"$unwind": "$panels"},
            {"$unwind": "$panels.measurements"},
            {"$match": {"panels.measurements.code": test_code}},
            {"$sort": {"collected_at": -1, "_id": -1}},
            {"$limit": 20},
            {"$project": {"_id": 1, "collected_at": 1,
                          "value": "$panels.measurements.value"}},
        ]
        return [(r["_id"], r["collected_at"].astimezone(timezone.utc).isoformat(),
                 float(r["value"])) for r in self.col.aggregate(pipeline)]

    def update_wbc(self, report_id, value):
        result = self.col.update_one(
            {"_id": report_id},
            {"$set": {"panels.$[p].measurements.$[m].value": value}},
            array_filters=[{"p.code": "CBC"}, {"m.code": "WBC"}],
        )
        if result.matched_count != 1:
            raise RuntimeError(f"Missing MongoDB report {report_id}")

    def insert(self, doc):
        self.col.insert_one(doc)
