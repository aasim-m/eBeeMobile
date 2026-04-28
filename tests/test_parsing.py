import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ebee_analysis.parsing import load_launch_ground_truth, parse_gfxinfo, parse_meminfo


class ParsingTests(unittest.TestCase):
    def test_parse_gfxinfo_percentiles_use_measured_values_not_percentile_labels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "gfxinfo.txt"
            path.write_text(
                "\n".join(
                    [
                        "Total frames rendered: 26",
                        "Janky frames: 2 (7.69%)",
                        "50th percentile: 7ms",
                        "90th percentile: 29ms",
                        "95th percentile: 93ms",
                        "99th percentile: 101ms",
                        "Number Missed Vsync: 0",
                        "Number High input latency: 10",
                        "Number Slow UI thread: 1",
                        "Number Slow bitmap uploads: 2",
                        "Number Slow issue draw commands: 3",
                        "Number Frame deadline missed: 4",
                        "Total ViewRootImpl   : 1",
                        "Total attached Views : 14",
                        "Total RenderNode: 32.80 kB of render nodes",
                    ]
                )
            )

            metrics = parse_gfxinfo(path)

        self.assertEqual(metrics["total_frames_rendered"], 26)
        self.assertEqual(metrics["janky_frames"], 2)
        self.assertEqual(metrics["janky_frames_pct"], 7.69)
        self.assertEqual(metrics["frame_p50_ms"], 7.0)
        self.assertEqual(metrics["frame_p90_ms"], 29.0)
        self.assertEqual(metrics["frame_p95_ms"], 93.0)
        self.assertEqual(metrics["frame_p99_ms"], 101.0)
        self.assertEqual(metrics["missed_vsync"], 0)
        self.assertEqual(metrics["high_input_latency"], 10)
        self.assertEqual(metrics["slow_ui_thread"], 1)
        self.assertEqual(metrics["slow_bitmap_uploads"], 2)
        self.assertEqual(metrics["slow_issue_draw_commands"], 3)
        self.assertEqual(metrics["frame_deadline_missed"], 4)
        self.assertEqual(metrics["total_viewrootimpl"], 1)
        self.assertEqual(metrics["total_attached_views"], 14)
        self.assertEqual(metrics["total_rendernode_kb"], 32.80)

    def test_parse_meminfo_supports_total_swap_kb_format(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "meminfo.txt"
            path.write_text(
                "\n".join(
                    [
                        "  Native Heap    32434    32324        0        0    36272",
                        "  Dalvik Heap     2423     2184        0        0     9948",
                        "        TOTAL   133416    86264    10268        0   333360",
                        "           Graphics:    31772",
                        "             System:    36884",
                        "           TOTAL PSS:   133416            TOTAL RSS:   333360      TOTAL SWAP (KB):        7",
                        "               Views:       14         ViewRootImpl:        1",
                        "          Activities:        1",
                        "             WebViews:        1",
                    ]
                )
            )

            metrics = parse_meminfo(path)

        self.assertEqual(metrics["native_heap_pss_kb"], 32434)
        self.assertEqual(metrics["dalvik_heap_pss_kb"], 2423)
        self.assertEqual(metrics["graphics_pss_kb"], 31772)
        self.assertEqual(metrics["system_pss_kb"], 36884)
        self.assertEqual(metrics["total_pss_kb"], 133416)
        self.assertEqual(metrics["total_rss_kb"], 333360)
        self.assertEqual(metrics["total_swap_pss_kb"], 7)
        self.assertEqual(metrics["views"], 14)
        self.assertEqual(metrics["activities"], 1)
        self.assertEqual(metrics["webviews"], 1)

    def test_load_launch_ground_truth_indexes_rows_by_episode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "launch_ground_truth.csv"
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["episode", "status", "activity", "this_time_ms", "total_time_ms", "wait_time_ms"],
                )
                writer.writeheader()
                writer.writerow({
                    "episode": "settings_launch",
                    "status": "ok",
                    "activity": "com.android.settings/.Settings",
                    "this_time_ms": "120",
                    "total_time_ms": "180",
                    "wait_time_ms": "200",
                })

            rows = load_launch_ground_truth(path)

        self.assertIn("settings_launch", rows)
        self.assertEqual(rows["settings_launch"]["total_time_ms"], "180")


if __name__ == "__main__":
    unittest.main()
