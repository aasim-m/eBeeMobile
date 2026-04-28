import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ebee_analysis.validation import (
    format_validation_recommendations_section,
    format_validation_section,
    summarize_validation,
    validation_diagnostic,
)


class ValidationTests(unittest.TestCase):
    def test_validation_diagnostic_covers_edge_cases(self):
        self.assertEqual(validation_diagnostic([], []), "insufficient_samples")
        self.assertEqual(validation_diagnostic([1.0, 2.0], [5.0, 5.0]), "constant_target")
        self.assertEqual(validation_diagnostic([3.0, 3.0], [5.0, 7.0]), "constant_proxy")
        self.assertEqual(validation_diagnostic([1.0, 2.0], [5.0, 7.0]), "ok")

    def test_summarize_validation_marks_non_informative_rows(self):
        rows = [
            {"proxy_a": "1", "proxy_b": "3", "target": "5"},
            {"proxy_a": "2", "proxy_b": "3", "target": "5"},
        ]

        summary_rows = summarize_validation(rows, "scroll", "target", ["proxy_a", "proxy_b"], 5.0)

        self.assertEqual(summary_rows[0]["diagnostic_status"], "constant_target")
        self.assertEqual(summary_rows[0]["pearson_r"], "")
        self.assertEqual(summary_rows[1]["diagnostic_status"], "constant_target")

    def test_format_validation_section_omits_constant_target_tables_and_explains_why(self):
        rows = [
            {
                "gap_ms": "5.00",
                "target_metric": "ground_truth_total_swap_pss_kb",
                "proxy_metric": "allocation_volume",
                "sample_count": 10,
                "diagnostic_status": "constant_target",
                "pearson_r": "",
                "spearman_r": "",
                "slope": "",
                "intercept": "",
                "mae_ms": "",
                "rmse_ms": "",
            }
        ]

        rendered = format_validation_section("Memory Validation", rows, "memory pressure")

        self.assertIn("No statistically informative validation fits were available for this section.", rendered)
        self.assertIn("Omitted `ground_truth_total_swap_pss_kb`", rendered)

    def test_format_validation_recommendations_flags_gap_invariant_proxies(self):
        rows = [
            {
                "gap_ms": "20.00",
                "target_metric": "ground_truth_total_time_ms",
                "proxy_metric": "trace_event_count",
                "sample_count": 30,
                "diagnostic_status": "ok",
                "pearson_r": "0.700000",
                "spearman_r": "0.700000",
                "slope": "1.0",
                "intercept": "0.0",
                "mae_ms": "1.0",
                "rmse_ms": "1.0",
            }
        ]

        rendered = format_validation_recommendations_section("Launch Validation Recommendations", rows)

        self.assertIn("proxy is mostly gap-invariant", rendered)


if __name__ == "__main__":
    unittest.main()
