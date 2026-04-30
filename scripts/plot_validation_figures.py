#!/usr/bin/env python3

"""Generate report-ready validation figures from eBeeMobile outputs."""

import argparse
import csv
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ebee_analysis.pipeline import load_runs
from ebee_analysis.stats import safe_float_value


TEXT_COLOR = colors.HexColor("#1F2937")
GRID_COLOR = colors.HexColor("#D9DEE7")
POINT_COLOR = colors.HexColor("#4C78A8")
LINE_COLOR = colors.HexColor("#111827")
ZERO_COLOR = colors.HexColor("#9CA3AF")


FIGURES = [
    {
        "family": "launch",
        "gap_ms": 20.0,
        "target": "ground_truth_total_time_ms",
        "proxy": "throughput_bursts_per_s",
        "sweep_csv": "launch_gap_sweep.csv",
        "output": "launch_totaltime_vs_throughput.pdf",
        "title": "Launch TotalTime vs burst throughput",
        "x_label": "Throughput (bursts/s)",
        "y_label": "Ground truth TotalTime (ms)",
        "annotation": "gap = 20 ms, N = 30, r = -0.922793",
    },
    {
        "family": "scroll",
        "gap_ms": 10.0,
        "target": "ground_truth_frame_p90_ms",
        "proxy": "max_burst_latency_ms",
        "sweep_csv": "scroll_gap_sweep.csv",
        "output": "scroll_frame_p90_vs_max_burst_latency.pdf",
        "title": "Frame P90 vs maximum burst latency",
        "x_label": "Max burst latency (ms)",
        "y_label": "Ground truth frame P90 (ms)",
        "annotation": "gap = 10 ms, N = 40, r = 0.930868",
    },
    {
        "family": "memory",
        "gap_ms": 1.0,
        "target": "ground_truth_dalvik_heap_pss_kb",
        "proxy": "file_syscall_intensity",
        "sweep_csv": "memory_gap_sweep.csv",
        "output": "memory_dalvik_pss_vs_file_syscall_intensity.pdf",
        "title": "Dalvik heap PSS vs file syscall intensity",
        "x_label": "File syscall intensity (openat + read + write)",
        "y_label": "Ground truth Dalvik heap PSS (KB)",
        "annotation": "gap = 1 ms, N = 10, r = 0.866039",
    },
]


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def find_fit_row(results_dir, spec):
    rows = read_csv(results_dir / spec["sweep_csv"])
    for row in rows:
        if (
            row.get("target_metric") == spec["target"]
            and row.get("proxy_metric") == spec["proxy"]
            and abs(float(row.get("gap_ms", "-1")) - spec["gap_ms"]) < 1e-9
            and row.get("diagnostic_status") == "ok"
        ):
            return row
    raise SystemExit(f"Missing validation row for {spec['output']}")


def collect_points(results_dir, spec):
    _, _, episode_rows = load_runs(results_dir, spec["gap_ms"])
    points = []
    for row in episode_rows:
        if row.get("episode_family") != spec["family"]:
            continue
        x = safe_float_value(row.get(spec["proxy"]))
        y = safe_float_value(row.get(spec["target"]))
        if x is None or y is None:
            continue
        points.append((x, y))
    return points


def bounds(values, pad_fraction=0.08):
    lo = min(values)
    hi = max(values)
    if lo == hi:
        pad = max(abs(lo) * 0.1, 1.0)
        lower = lo - pad
        if lo >= 0:
            lower = max(0, lower)
        return lower, hi + pad
    pad = (hi - lo) * pad_fraction
    lower = lo - pad
    if lo >= 0:
        lower = max(0, lower)
    return lower, hi + pad


def fmt(value):
    if abs(value) >= 10000:
        return f"{value / 1000:.1f}k"
    if abs(value) >= 1000:
        return f"{value:.0f}"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.0f}"
    return f"{value:.1f}"


def draw_scatter(path, spec, points, fit_row):
    width, height = 5.8 * inch, 4.1 * inch
    c = canvas.Canvas(str(path), pagesize=(width, height))

    left = 0.78 * inch
    right = width - 0.25 * inch
    bottom = 0.68 * inch
    top = height - 0.62 * inch
    plot_w = right - left
    plot_h = top - bottom

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = bounds(xs)
    y_min, y_max = bounds(ys)

    def sx(value):
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value):
        return bottom + (value - y_min) / (y_max - y_min) * plot_h

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 0.34 * inch, spec["title"])

    c.setStrokeColor(GRID_COLOR)
    c.setLineWidth(0.4)
    c.setFont("Helvetica", 7)
    c.setFillColor(TEXT_COLOR)
    for idx in range(6):
        x_value = x_min + (x_max - x_min) * idx / 5
        y_value = y_min + (y_max - y_min) * idx / 5
        tx = sx(x_value)
        ty = sy(y_value)
        c.line(tx, bottom, tx, top)
        c.drawCentredString(tx, bottom - 13, fmt(x_value))
        c.line(left, ty, right, ty)
        c.drawRightString(left - 5, ty - 2.5, fmt(y_value))

    c.setStrokeColor(TEXT_COLOR)
    c.setLineWidth(0.8)
    c.line(left, bottom, right, bottom)
    c.line(left, bottom, left, top)

    slope = float(fit_row["slope"])
    intercept = float(fit_row["intercept"])
    c.setStrokeColor(LINE_COLOR)
    c.setLineWidth(1.4)
    c.line(sx(x_min), sy(slope * x_min + intercept), sx(x_max), sy(slope * x_max + intercept))

    c.setFillColor(POINT_COLOR)
    c.setStrokeColor(colors.white)
    c.setLineWidth(0.4)
    for x, y in points:
        c.circle(sx(x), sy(y), 3.0, fill=1, stroke=1)

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 8)
    c.drawCentredString(left + plot_w / 2, 0.28 * inch, spec["x_label"])
    c.saveState()
    c.translate(0.24 * inch, bottom + plot_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, spec["y_label"])
    c.restoreState()

    c.setFont("Helvetica", 8)
    c.drawRightString(right, top - 0.12 * inch, spec["annotation"])
    c.showPage()
    c.save()


def draw_gap_sweep(path, rows):
    target = "ground_truth_total_time_ms"
    proxies = [
        ("throughput_bursts_per_s", "Throughput"),
        ("avg_burst_latency_ms", "Avg latency"),
        ("p95_burst_latency_ms", "P95 latency"),
        ("max_burst_latency_ms", "Max latency"),
    ]
    series = {}
    for proxy, label in proxies:
        values = []
        for row in rows:
            if row.get("target_metric") != target or row.get("proxy_metric") != proxy:
                continue
            if not row.get("pearson_r"):
                continue
            values.append((float(row["gap_ms"]), float(row["pearson_r"])))
        series[label] = sorted(values)

    width, height = 6.1 * inch, 3.8 * inch
    c = canvas.Canvas(str(path), pagesize=(width, height))
    left = 0.7 * inch
    right = width - 1.0 * inch
    bottom = 0.6 * inch
    top = height - 0.58 * inch
    plot_w = right - left
    plot_h = top - bottom

    x_min, x_max = 0, 52
    y_min, y_max = -1.0, 1.0

    def sx(value):
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value):
        return bottom + (value - y_min) / (y_max - y_min) * plot_h

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 0.34 * inch, "Launch TotalTime correlation by burst gap")

    c.setStrokeColor(GRID_COLOR)
    c.setLineWidth(0.4)
    c.setFont("Helvetica", 7)
    c.setFillColor(TEXT_COLOR)
    for tick in [1, 2, 5, 10, 20, 50]:
        tx = sx(tick)
        c.line(tx, bottom, tx, top)
        c.drawCentredString(tx, bottom - 13, str(tick))
    for y in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        ty = sy(y)
        c.line(left, ty, right, ty)
        c.drawRightString(left - 5, ty - 2.5, f"{y:.1f}")
    c.setStrokeColor(ZERO_COLOR)
    c.setLineWidth(0.8)
    c.line(left, sy(0), right, sy(0))

    c.setStrokeColor(TEXT_COLOR)
    c.setLineWidth(0.8)
    c.line(left, bottom, right, bottom)
    c.line(left, bottom, left, top)

    palette = [colors.HexColor("#4C78A8"), colors.HexColor("#F58518"), colors.HexColor("#54A24B"), colors.HexColor("#B279A2")]
    for idx, (label, values) in enumerate(series.items()):
        if not values:
            continue
        color = palette[idx]
        c.setStrokeColor(color)
        c.setLineWidth(1.4)
        last = None
        for x, y in values:
            point = (sx(x), sy(y))
            if last is not None:
                c.line(last[0], last[1], point[0], point[1])
            last = point
        c.setFillColor(color)
        for x, y in values:
            c.circle(sx(x), sy(y), 2.6, fill=1, stroke=0)
        ly = top - idx * 0.2 * inch
        lx = right + 0.16 * inch
        c.setStrokeColor(color)
        c.line(lx, ly, lx + 0.18 * inch, ly)
        c.setFillColor(TEXT_COLOR)
        c.setFont("Helvetica", 7)
        c.drawString(lx + 0.23 * inch, ly - 2.5, label)

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 8)
    c.drawCentredString(left + plot_w / 2, 0.25 * inch, "Burst gap (ms)")
    c.saveState()
    c.translate(0.23 * inch, bottom + plot_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, "Pearson r")
    c.restoreState()
    c.showPage()
    c.save()


def main():
    parser = argparse.ArgumentParser(description="Generate validation figures for eBeeMobile Results.")
    parser.add_argument("--input", type=Path, default=Path("runs/main_validation"))
    parser.add_argument("--output", type=Path, default=Path("figures/results/validation"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    for spec in FIGURES:
        points = collect_points(args.input, spec)
        fit_row = find_fit_row(args.input, spec)
        if len(points) != int(fit_row["sample_count"]):
            raise SystemExit(
                f"Point count mismatch for {spec['output']}: "
                f"{len(points)} points vs expected {fit_row['sample_count']}"
            )
        output = args.output / spec["output"]
        draw_scatter(output, spec, points, fit_row)
        print(output)

    launch_rows = read_csv(args.input / "launch_gap_sweep.csv")
    gap_output = args.output / "launch_totaltime_gap_sweep.pdf"
    draw_gap_sweep(gap_output, launch_rows)
    print(gap_output)


if __name__ == "__main__":
    main()
