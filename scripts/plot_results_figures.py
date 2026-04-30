#!/usr/bin/env python3

"""Generate report-ready workload-level result figures.

The script intentionally uses only the CSV artifacts emitted by the
eBeeMobile analysis pipeline.  It avoids matplotlib so the figures can be
regenerated in the same lightweight environment used for the project.
"""

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


WORKLOADS = [
    ("workload_a", "A: Idle"),
    ("workload_b", "B: Launch"),
    ("workload_c", "C: Scroll"),
    ("workload_d", "D: Background"),
]

BAR_COLOR = colors.HexColor("#4C78A8")
ALT_COLOR = colors.HexColor("#72B7B2")
LINE_COLORS = [
    colors.HexColor("#4C78A8"),
    colors.HexColor("#F58518"),
    colors.HexColor("#54A24B"),
    colors.HexColor("#B279A2"),
]
GRID_COLOR = colors.HexColor("#D9DEE7")
TEXT_COLOR = colors.HexColor("#1F2937")


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(row, field):
    return float(row[field])


def workload_rows(rows):
    by_name = {row["workload"]: row for row in rows}
    return [(name, label, by_name[name]) for name, label in WORKLOADS]


def fmt_tick(value):
    if abs(value) >= 1000:
        return f"{value / 1000:.0f}k"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.0f}"
    return f"{value:.1f}"


def nice_max(value):
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    scaled = value / magnitude
    if scaled <= 1:
        nice = 1
    elif scaled <= 2:
        nice = 2
    elif scaled <= 5:
        nice = 5
    else:
        nice = 10
    return nice * magnitude


def draw_title(c, width, height, title):
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 0.38 * inch, title)


def draw_panel_title(c, x, y, w, title):
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w / 2, y, title)


def draw_bar_panel(c, x, y, w, h, labels, values, y_label, color=BAR_COLOR, value_fmt=None):
    max_value = nice_max(max(values) * 1.12)
    tick_count = 5
    plot_left = x + 0.56 * inch
    plot_right = x + w - 0.12 * inch
    plot_bottom = y + 0.42 * inch
    plot_top = y + h - 0.22 * inch
    plot_w = plot_right - plot_left
    plot_h = plot_top - plot_bottom

    c.setStrokeColor(GRID_COLOR)
    c.setLineWidth(0.4)
    c.setFont("Helvetica", 7)
    c.setFillColor(TEXT_COLOR)
    for idx in range(tick_count + 1):
        tick_value = max_value * idx / tick_count
        ty = plot_bottom + plot_h * idx / tick_count
        c.line(plot_left, ty, plot_right, ty)
        c.drawRightString(plot_left - 5, ty - 2.5, fmt_tick(tick_value))

    c.setStrokeColor(TEXT_COLOR)
    c.setLineWidth(0.8)
    c.line(plot_left, plot_bottom, plot_right, plot_bottom)
    c.line(plot_left, plot_bottom, plot_left, plot_top)

    gap = plot_w * 0.08
    bar_w = (plot_w - gap * (len(values) + 1)) / len(values)
    c.setFillColor(color)
    for idx, (label, value) in enumerate(zip(labels, values)):
        bx = plot_left + gap + idx * (bar_w + gap)
        bh = 0 if max_value == 0 else plot_h * value / max_value
        c.rect(bx, plot_bottom, bar_w, bh, fill=1, stroke=0)
        c.setFillColor(TEXT_COLOR)
        c.setFont("Helvetica", 7)
        c.drawCentredString(bx + bar_w / 2, plot_bottom - 13, label)
        if value_fmt is not None:
            c.drawCentredString(bx + bar_w / 2, plot_bottom + bh + 4, value_fmt(value))
        c.setFillColor(color)

    c.saveState()
    c.translate(x + 0.12 * inch, plot_bottom + plot_h / 2)
    c.rotate(90)
    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 8)
    c.drawCentredString(0, 0, y_label)
    c.restoreState()


def save_burst_structure(output_path, burst_rows):
    width, height = landscape((7.2 * inch, 3.7 * inch))
    c = canvas.Canvas(str(output_path), pagesize=(width, height))
    draw_title(c, width, height, "Burst structure by workload")
    rows = workload_rows(burst_rows)
    labels = [label for _, label, _ in rows]
    burst_counts = [as_float(row, "burst_count") for _, _, row in rows]
    syscalls = [as_float(row, "avg_syscalls_per_burst") for _, _, row in rows]
    panel_y = 0.28 * inch
    panel_h = height - 0.82 * inch
    panel_w = (width - 0.55 * inch) / 2
    draw_panel_title(c, 0.12 * inch, height - 0.62 * inch, panel_w, "Pseudo-request count")
    draw_bar_panel(
        c,
        0.12 * inch,
        panel_y,
        panel_w,
        panel_h,
        labels,
        burst_counts,
        "Bursts per run",
        BAR_COLOR,
        lambda v: f"{v:.0f}",
    )
    draw_panel_title(c, panel_w + 0.34 * inch, height - 0.62 * inch, panel_w, "Syscall density")
    draw_bar_panel(
        c,
        panel_w + 0.34 * inch,
        panel_y,
        panel_w,
        panel_h,
        labels,
        syscalls,
        "Syscalls per burst",
        ALT_COLOR,
        lambda v: f"{v:.0f}",
    )
    c.showPage()
    c.save()


def save_throughput(output_path, burst_rows):
    width, height = 5.4 * inch, 3.5 * inch
    c = canvas.Canvas(str(output_path), pagesize=(width, height))
    draw_title(c, width, height, "Pseudo-request throughput")
    rows = workload_rows(burst_rows)
    draw_bar_panel(
        c,
        0.15 * inch,
        0.28 * inch,
        width - 0.3 * inch,
        height - 0.82 * inch,
        [label for _, label, _ in rows],
        [as_float(row, "throughput_bursts_per_s") for _, _, row in rows],
        "Bursts per second",
        BAR_COLOR,
        lambda v: f"{v:.1f}",
    )
    c.showPage()
    c.save()


def save_intensity(output_path, derived_rows):
    width, height = landscape((7.2 * inch, 3.7 * inch))
    c = canvas.Canvas(str(output_path), pagesize=(width, height))
    draw_title(c, width, height, "Workload-level intensity metrics")
    rows = workload_rows(derived_rows)
    labels = [label for _, label, _ in rows]
    file_intensity = [as_float(row, "file_syscall_intensity") for _, _, row in rows]
    allocation_volume = [as_float(row, "allocation_volume") for _, _, row in rows]
    panel_y = 0.28 * inch
    panel_h = height - 0.82 * inch
    panel_w = (width - 0.55 * inch) / 2
    draw_panel_title(c, 0.12 * inch, height - 0.62 * inch, panel_w, "File syscall intensity")
    draw_bar_panel(
        c,
        0.12 * inch,
        panel_y,
        panel_w,
        panel_h,
        labels,
        file_intensity,
        "openat + read + write",
        BAR_COLOR,
        lambda v: f"{v/1000:.1f}k",
    )
    draw_panel_title(c, panel_w + 0.34 * inch, height - 0.62 * inch, panel_w, "Allocation volume")
    draw_bar_panel(
        c,
        panel_w + 0.34 * inch,
        panel_y,
        panel_w,
        panel_h,
        labels,
        allocation_volume,
        "Page allocations",
        ALT_COLOR,
        lambda v: f"{v/1000:.1f}k",
    )
    c.showPage()
    c.save()


def percentile(sorted_values, p):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * p
    lo = int(math.floor(k))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def save_latency_ecdf(output_path, pseudo_rows):
    durations = defaultdict(list)
    for row in pseudo_rows:
        durations[row["workload"]].append(float(row["duration_ms"]))
    for values in durations.values():
        values.sort()

    width, height = 6.2 * inch, 3.9 * inch
    c = canvas.Canvas(str(output_path), pagesize=(width, height))
    draw_title(c, width, height, "Burst latency distribution")

    left = 0.7 * inch
    right = width - 0.28 * inch
    bottom = 0.62 * inch
    top = height - 0.62 * inch
    plot_w = right - left
    plot_h = top - bottom
    x_max = max(math.log10(1 + max(values)) for values in durations.values())

    def sx(ms):
        return left + math.log10(1 + ms) / x_max * plot_w

    def sy(frac):
        return bottom + frac * plot_h

    c.setStrokeColor(GRID_COLOR)
    c.setLineWidth(0.4)
    x_ticks = [0, 1, 10, 100, 1000, 3000]
    c.setFont("Helvetica", 7)
    c.setFillColor(TEXT_COLOR)
    for tick in x_ticks:
        if math.log10(1 + tick) <= x_max:
            tx = sx(tick)
            c.line(tx, bottom, tx, top)
            c.drawCentredString(tx, bottom - 13, str(tick))
    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        ty = sy(frac)
        c.line(left, ty, right, ty)
        c.drawRightString(left - 5, ty - 2.5, f"{frac:.2f}")

    c.setStrokeColor(TEXT_COLOR)
    c.setLineWidth(0.8)
    c.line(left, bottom, right, bottom)
    c.line(left, bottom, left, top)

    for idx, (workload, label) in enumerate(WORKLOADS):
        values = durations[workload]
        if not values:
            continue
        color = LINE_COLORS[idx]
        c.setStrokeColor(color)
        c.setLineWidth(1.6)
        prev_x = sx(values[0])
        prev_y = sy(0)
        for point_idx, value in enumerate(values, start=1):
            x = sx(value)
            y = sy(point_idx / len(values))
            c.line(prev_x, prev_y, x, prev_y)
            c.line(x, prev_y, x, y)
            prev_x, prev_y = x, y
        c.line(prev_x, prev_y, sx(values[-1]), prev_y)

        legend_x = left + 0.15 * inch
        legend_y = top - 0.18 * inch - idx * 0.18 * inch
        c.setStrokeColor(color)
        c.setLineWidth(2)
        c.line(legend_x, legend_y, legend_x + 0.22 * inch, legend_y)
        c.setFillColor(TEXT_COLOR)
        c.setFont("Helvetica", 7)
        c.drawString(legend_x + 0.28 * inch, legend_y - 2.5, label)

    c.setFillColor(TEXT_COLOR)
    c.setFont("Helvetica", 8)
    c.drawCentredString(left + plot_w / 2, 0.24 * inch, "Burst latency (ms), log-scaled as log10(1 + ms)")
    c.saveState()
    c.translate(0.22 * inch, bottom + plot_h / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, "Empirical CDF")
    c.restoreState()
    c.showPage()
    c.save()


def main():
    parser = argparse.ArgumentParser(description="Generate eBeeMobile Results section figures.")
    parser.add_argument("--input", type=Path, default=Path("runs/main_validation"))
    parser.add_argument("--output", type=Path, default=Path("figures/results"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    burst_rows = read_csv(args.input / "burst_summary.csv")
    derived_rows = read_csv(args.input / "derived_metrics.csv")
    pseudo_rows = read_csv(args.input / "pseudo_requests.csv")

    outputs = [
        args.output / "burst_structure.pdf",
        args.output / "latency_ecdf.pdf",
        args.output / "throughput.pdf",
        args.output / "intensity_metrics.pdf",
    ]
    save_burst_structure(outputs[0], burst_rows)
    save_latency_ecdf(outputs[1], pseudo_rows)
    save_throughput(outputs[2], burst_rows)
    save_intensity(outputs[3], derived_rows)

    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
