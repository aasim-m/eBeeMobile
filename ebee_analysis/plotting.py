import re

from .pipeline import load_runs
from .stats import safe_float_value
from .validation import best_validation_row, best_validation_rows


def svg_escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def axis_bounds(values, pad_fraction=0.08):
    if not values:
        return 0.0, 1.0
    min_value = min(values)
    max_value = max(values)
    if min_value == max_value:
        padding = max(abs(min_value) * 0.1, 1.0)
        return min_value - padding, max_value + padding
    padding = (max_value - min_value) * pad_fraction
    return min_value - padding, max_value + padding


def svg_scatter(path, rows, x_field, y_field, title, x_label, y_label, slope=None, intercept=None):
    points = []
    for row in rows:
        x = safe_float_value(row.get(x_field))
        y = safe_float_value(row.get(y_field))
        if x is None or y is None:
            continue
        points.append((x, y, row.get("episode", "")))
    if not points:
        return False

    width = 760
    height = 480
    left = 86
    right = 34
    top = 54
    bottom = 76
    plot_width = width - left - right
    plot_height = height - top - bottom
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min, x_max = axis_bounds(xs)
    y_min, y_max = axis_bounds(ys)

    def sx(value):
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def sy(value):
        return top + plot_height - (value - y_min) / (y_max - y_min) * plot_height

    base_colors = {
        "settings_launch": "#2563eb",
        "browser_launch": "#dc2626",
        "gallery_launch": "#16a34a",
    }
    palette = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#4f46e5", "#ca8a04"]
    colors = dict(base_colors)
    legend_names = []
    for _, _, episode in points:
        if episode not in legend_names:
            legend_names.append(episode)
        if episode not in colors:
            colors[episode] = palette[len(colors) % len(palette)]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18" font-weight="700">{svg_escape(title)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827" stroke-width="1"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827" stroke-width="1"/>',
    ]
    for idx in range(6):
        x_value = x_min + (x_max - x_min) * idx / 5
        x_pos = sx(x_value)
        lines.append(f'<line x1="{x_pos:.2f}" y1="{top}" x2="{x_pos:.2f}" y2="{top + plot_height}" stroke="#e5e7eb" stroke-width="1"/>')
        lines.append(f'<text x="{x_pos:.2f}" y="{top + plot_height + 22}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#374151">{x_value:.2f}</text>')
        y_value = y_min + (y_max - y_min) * idx / 5
        y_pos = sy(y_value)
        lines.append(f'<line x1="{left}" y1="{y_pos:.2f}" x2="{left + plot_width}" y2="{y_pos:.2f}" stroke="#e5e7eb" stroke-width="1"/>')
        lines.append(f'<text x="{left - 10}" y="{y_pos + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="#374151">{y_value:.1f}</text>')

    if slope is not None and intercept is not None:
        y1 = slope * x_min + intercept
        y2 = slope * x_max + intercept
        lines.append(f'<line x1="{sx(x_min):.2f}" y1="{sy(y1):.2f}" x2="{sx(x_max):.2f}" y2="{sy(y2):.2f}" stroke="#111827" stroke-width="2.5"/>')

    for x_value, y_value, episode in points:
        color = colors.get(episode, "#4b5563")
        lines.append(f'<circle cx="{sx(x_value):.2f}" cy="{sy(y_value):.2f}" r="4.5" fill="{color}" fill-opacity="0.82"/>')

    lines.append(f'<text x="{left + plot_width / 2}" y="{height - 24}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#111827">{svg_escape(x_label)}</text>')
    lines.append(f'<text transform="translate(22 {top + plot_height / 2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#111827">{svg_escape(y_label)}</text>')
    legend_x = left + plot_width - 175
    legend_y = top + 18
    for idx, name in enumerate(legend_names):
        color = colors.get(name, "#4b5563")
        y = legend_y + idx * 20
        lines.append(f'<circle cx="{legend_x}" cy="{y}" r="4" fill="{color}"/>')
        lines.append(f'<text x="{legend_x + 10}" y="{y + 4}" font-family="sans-serif" font-size="11" fill="#374151">{svg_escape(name)}</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines))
    return True


def svg_gap_line(path, rows, target_metric, proxy_metrics, title):
    series = {proxy: [] for proxy in proxy_metrics}
    for row in rows:
        if row.get("target_metric") != target_metric:
            continue
        proxy = row.get("proxy_metric")
        if proxy not in series or not row.get("pearson_r"):
            continue
        series[proxy].append((float(row["gap_ms"]), float(row["pearson_r"])))
    series = {proxy: sorted(values) for proxy, values in series.items() if values}
    if not series:
        return False

    width = 760
    height = 440
    left = 76
    right = 168
    top = 52
    bottom = 70
    plot_width = width - left - right
    plot_height = height - top - bottom
    x_values = [x for values in series.values() for x, _ in values]
    x_min, x_max = axis_bounds(x_values, 0.02)
    y_min, y_max = -1.0, 1.0

    def sx(value):
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def sy(value):
        return top + plot_height - (value - y_min) / (y_max - y_min) * plot_height

    colors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2"]
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18" font-weight="700">{svg_escape(title)}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827" stroke-width="1"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#111827" stroke-width="1"/>',
        f'<line x1="{left}" y1="{sy(0):.2f}" x2="{left + plot_width}" y2="{sy(0):.2f}" stroke="#9ca3af" stroke-width="1.2" stroke-dasharray="4 4"/>',
    ]
    for idx in range(6):
        x_value = x_min + (x_max - x_min) * idx / 5
        x_pos = sx(x_value)
        lines.append(f'<line x1="{x_pos:.2f}" y1="{top}" x2="{x_pos:.2f}" y2="{top + plot_height}" stroke="#e5e7eb" stroke-width="1"/>')
        lines.append(f'<text x="{x_pos:.2f}" y="{top + plot_height + 22}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#374151">{x_value:.0f}</text>')
    for y_value in [-1, -0.5, 0, 0.5, 1]:
        y_pos = sy(y_value)
        lines.append(f'<line x1="{left}" y1="{y_pos:.2f}" x2="{left + plot_width}" y2="{y_pos:.2f}" stroke="#e5e7eb" stroke-width="1"/>')
        lines.append(f'<text x="{left - 10}" y="{y_pos + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="#374151">{y_value:.1f}</text>')

    for idx, (proxy, values) in enumerate(series.items()):
        color = colors[idx % len(colors)]
        points = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in values)
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.4"/>')
        for x, y in values:
            lines.append(f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="3.5" fill="{color}"/>')
        legend_y = top + 18 + idx * 20
        legend_x = left + plot_width + 22
        lines.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 18}" y2="{legend_y}" stroke="{color}" stroke-width="2.4"/>')
        lines.append(f'<text x="{legend_x + 24}" y="{legend_y + 4}" font-family="sans-serif" font-size="11" fill="#374151">{svg_escape(proxy)}</text>')

    lines.append(f'<text x="{left + plot_width / 2}" y="{height - 24}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#111827">Burst gap (ms)</text>')
    lines.append(f'<text transform="translate(22 {top + plot_height / 2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#111827">Pearson r</text>')
    lines.append("</svg>")
    path.write_text("\n".join(lines))
    return True


def build_launch_figures(output_dir, results_dir, launch_gap_rows, episode_rows_by_gap=None):
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    figure_paths = []

    total_latency = best_validation_row(
        launch_gap_rows,
        "ground_truth_total_time_ms",
        ["episode_elapsed_s", "avg_burst_latency_ms", "p95_burst_latency_ms", "max_burst_latency_ms"],
    )
    total_throughput = best_validation_row(
        launch_gap_rows,
        "ground_truth_total_time_ms",
        ["throughput_bursts_per_s"],
    )
    for row, filename, label in [
        (total_latency, "launch_total_time_vs_latency_proxy.svg", "Launch TotalTime vs best latency-shaped proxy"),
        (total_throughput, "launch_total_time_vs_throughput.svg", "Launch TotalTime vs throughput proxy"),
    ]:
        if row is None:
            continue
        gap_ms = float(row["gap_ms"])
        if episode_rows_by_gap is not None and gap_ms in episode_rows_by_gap:
            gap_episode_rows = episode_rows_by_gap[gap_ms]
        else:
            _, _, gap_episode_rows = load_runs(results_dir, gap_ms)
        launch_rows = [episode for episode in gap_episode_rows if episode.get("episode_family") == "launch"]
        path = figure_dir / filename
        slope = safe_float_value(row.get("slope"))
        intercept = safe_float_value(row.get("intercept"))
        if svg_scatter(
            path,
            launch_rows,
            row["proxy_metric"],
            "ground_truth_total_time_ms",
            label,
            row["proxy_metric"],
            "Ground truth TotalTime (ms)",
            slope,
            intercept,
        ):
            figure_paths.append((label, f"figures/{filename}"))

    gap_path = figure_dir / "launch_gap_pearson_total_time.svg"
    if svg_gap_line(
        gap_path,
        launch_gap_rows,
        "ground_truth_total_time_ms",
        ["episode_elapsed_s", "avg_burst_latency_ms", "p95_burst_latency_ms", "max_burst_latency_ms", "throughput_bursts_per_s"],
        "Launch TotalTime correlation by burst gap",
    ):
        figure_paths.append(("Launch TotalTime correlation by burst gap", "figures/launch_gap_pearson_total_time.svg"))
    return figure_paths


def sanitize_filename(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def metric_label(field_name):
    labels = {
        "ground_truth_total_time_ms": "Ground truth TotalTime (ms)",
        "ground_truth_wait_time_ms": "Ground truth WaitTime (ms)",
        "ground_truth_total_frames_rendered": "Ground truth total frames rendered",
        "ground_truth_janky_frames_pct": "Ground truth janky frames (%)",
        "ground_truth_janky_frames": "Ground truth janky frames",
        "ground_truth_frame_p50_ms": "Ground truth frame P50 (ms)",
        "ground_truth_frame_p90_ms": "Ground truth frame P90 (ms)",
        "ground_truth_frame_p95_ms": "Ground truth frame P95 (ms)",
        "ground_truth_frame_p99_ms": "Ground truth frame P99 (ms)",
        "ground_truth_total_pss_kb": "Ground truth total PSS (KB)",
        "ground_truth_total_swap_pss_kb": "Ground truth total swap (KB)",
        "ground_truth_graphics_pss_kb": "Ground truth graphics PSS (KB)",
        "ground_truth_native_heap_pss_kb": "Ground truth native heap PSS (KB)",
        "ground_truth_dalvik_heap_pss_kb": "Ground truth dalvik heap PSS (KB)",
        "episode_elapsed_s": "Episode elapsed (s)",
        "avg_burst_latency_ms": "Average burst latency (ms)",
        "p95_burst_latency_ms": "P95 burst latency (ms)",
        "max_burst_latency_ms": "Max burst latency (ms)",
        "avg_syscalls_per_burst": "Average syscalls per burst",
        "throughput_bursts_per_s": "Throughput (bursts/s)",
        "trace_event_count": "Trace event count",
        "burst_count": "Burst count",
        "allocation_volume": "Allocation volume",
        "higher_order_allocation_share": "Higher-order allocation share",
        "slow_allocation_share": "Slow allocation share",
        "long_tail_share": "Long-tail share",
        "file_syscall_intensity": "File syscall intensity",
    }
    return labels.get(field_name, field_name.replace("_", " "))


def format_figure_gallery(title, figure_paths):
    if not figure_paths:
        return ""
    lines = [f"{title}:", ""]
    for label, path in figure_paths:
        lines.append(f"![{label}]({path})")
        lines.append("")
    return "\n".join(lines)


def build_family_figures(output_dir, results_dir, family, section_label, gap_rows, episode_rows_by_gap=None):
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    figure_paths = []
    gap_cache = {}

    for row in best_validation_rows(gap_rows):
        gap_ms = float(row["gap_ms"])
        if gap_ms not in gap_cache:
            if episode_rows_by_gap is not None and gap_ms in episode_rows_by_gap:
                gap_episode_rows = episode_rows_by_gap[gap_ms]
            else:
                _, _, gap_episode_rows = load_runs(results_dir, gap_ms)
            gap_cache[gap_ms] = [
                episode
                for episode in gap_episode_rows
                if episode.get("episode_family") == family
            ]
        family_rows = gap_cache[gap_ms]
        target_metric = row["target_metric"]
        proxy_metric = row["proxy_metric"]

        scatter_filename = f"{family}_{sanitize_filename(target_metric)}_vs_{sanitize_filename(proxy_metric)}.svg"
        scatter_label = f"{section_label} {metric_label(target_metric)} vs {metric_label(proxy_metric)}"
        slope = safe_float_value(row.get("slope"))
        intercept = safe_float_value(row.get("intercept"))
        if svg_scatter(
            figure_dir / scatter_filename,
            family_rows,
            proxy_metric,
            target_metric,
            scatter_label,
            metric_label(proxy_metric),
            metric_label(target_metric),
            slope,
            intercept,
        ):
            figure_paths.append((scatter_label, f"figures/{scatter_filename}"))

        proxy_metrics = []
        for candidate in gap_rows:
            if candidate.get("target_metric") != target_metric:
                continue
            if candidate.get("diagnostic_status", "ok") != "ok":
                continue
            proxy = candidate.get("proxy_metric", "")
            if proxy and proxy not in proxy_metrics:
                proxy_metrics.append(proxy)

        gap_filename = f"{family}_{sanitize_filename(target_metric)}_gap_pearson.svg"
        gap_label = f"{section_label} {metric_label(target_metric)} correlation by burst gap"
        if proxy_metrics and svg_gap_line(
            figure_dir / gap_filename,
            gap_rows,
            target_metric,
            proxy_metrics,
            gap_label,
        ):
            figure_paths.append((gap_label, f"figures/{gap_filename}"))

    return figure_paths

