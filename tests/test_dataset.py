import unittest
from datetime import timezone

from src.dataset import CATALOG, build_report, normalize_report, count_abnormal
from src.metrics import percentile


class DeterministicDataTests(unittest.TestCase):
    def test_repeatable(self):
        self.assertEqual(build_report(100, 20), build_report(100, 20))

    def test_eight_distinct_measurements_in_two_panels(self):
        report = build_report(1, 20)
        self.assertEqual(len(report["panels"]), 2)
        all_codes = [m["code"] for p in report["panels"] for m in p["measurements"]]
        self.assertEqual(len(all_codes), len(CATALOG))
        self.assertEqual(len(set(all_codes)), len(CATALOG))

    def test_reference_limits_are_usable(self):
        report = build_report(5, 20)
        for p in report["panels"]:
            for m in p["measurements"]:
                self.assertLess(m["reference_low"], m["reference_high"])
        self.assertIsInstance(count_abnormal(report), int)

    def test_utc_and_no_pii(self):
        doc = build_report(200, 100)
        self.assertEqual(doc["collected_at"].tzinfo, timezone.utc)
        self.assertTrue(doc["patient_id"].startswith("DEMO-P"))
        self.assertIsNone(doc["source_encounter_id"])

    def test_normalization_independent_of_panel_order(self):
        a = build_report(7, 3)
        b = build_report(7, 3)
        b["panels"].reverse()
        for p in b["panels"]:
            p["measurements"].reverse()
        self.assertEqual(normalize_report(a), normalize_report(b))

    def test_values_vary_across_reports(self):
        seen = {next(m["value"] for p in build_report(i, 20)["panels"]
                     for m in p["measurements"] if m["code"] == "GLU")
                for i in range(1, 40)}
        self.assertGreater(len(seen), 20)

    def test_outlier_occurs(self):
        self.assertGreater(sum(count_abnormal(build_report(i, 12)) for i in range(1, 35)), 0)

    def test_percentile(self):
        self.assertEqual(percentile([1, 2, 3], 50), 2)
        self.assertEqual(percentile([5], 95), 5)

    def test_invalid_ids(self):
        with self.assertRaises(ValueError):
            build_report(0, 5)
        with self.assertRaises(ValueError):
            build_report(1, 0)


if __name__ == "__main__":
    unittest.main()
