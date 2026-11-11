"""Reassembly contract tested without running PostgreSQL or MongoDB."""
import unittest

from src.dataset import build_report, normalize_report
from src.stores import SQL_FULL_REPORT, SQL_LATEST, SqlStore


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, query, params):
        self.executed.append((query, params))
        return FakeResult(self.rows)


class SqlReassemblyTests(unittest.TestCase):
    def test_full_report_reconstructs_nested_panels(self):
        original = build_report(9, 4)
        rows = []
        for p in original["panels"]:
            for m in p["measurements"]:
                rows.append((original["_id"], original["patient_id"],
                             original["source_encounter_id"], original["collected_at"],
                             original["status"], p["code"], m["code"],
                             m["label"], m["unit"], m["value"],
                             m["reference_low"], m["reference_high"]))
        conn = FakeConnection(rows)
        actual = SqlStore(conn).full_report(original["_id"])
        self.assertEqual(normalize_report(original), normalize_report(actual))
        self.assertEqual(conn.executed, [(SQL_FULL_REPORT, (original["_id"],))])

    def test_no_report_means_none(self):
        conn = FakeConnection([])
        self.assertIsNone(SqlStore(conn).full_report("NONE"))

    def test_latest_ids_returns_only_id_strings(self):
        conn = FakeConnection([("R00000003",), ("R00000002",)])
        self.assertEqual(SqlStore(conn).latest("DEMO-P00001"), ["R00000003", "R00000002"])
        self.assertEqual(conn.executed, [(SQL_LATEST, ("DEMO-P00001",))])


if __name__ == "__main__":
    unittest.main()
