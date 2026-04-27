#!/usr/bin/env python3

import argparse
import csv
import math
import re
from pathlib import Path


WORKLOAD_LABELS = {
    "workload_a": "Workload A (Idle Baseline)",
    "workload_b": "Workload B (App Launch Burst)",
    "workload_c": "Workload C (Interaction / Scrolling)",
    "workload_d": "Workload D (Background Activity)",
}

LATENCY_BUCKETS = [
    "< 1 us",
    "1 - 5 us",
    "5 - 10 us",
    "10 - 50 us",
    "50 - 100 us",
    "100 - 500 us",
    "500 us - 1 ms",
    ">= 1 ms",
]

TIMESTAMP_RE = re.compile(r"\b(\d+\.\d+):")
MARKER_RE = re.compile(r"\b(\d+\.\d+):.*tracing_mark_write:\s+(.*)")
WORKLOAD_B_EPISODE_MARKERS = {
    "settings_launch": ("SETTINGS_LAUNCH_START", "SETTINGS_LAUNCH_END"),
    "browser_launch": ("BROWSER_LAUNCH_START", "BROWSER_LAUNCH_END"),
    "gallery_launch": ("GALLERY_LAUNCH_START", "GALLERY_LAUNCH_END"),
}

WORKLOAD_C_EPISODE_MARKERS = {
    "page_load": ("PAGE_LOAD_START", "PAGE_SETTLED"),
    "swipe_1": ("SWIPE_1_START", "SWIPE_1_END"),
    "swipe_2": ("SWIPE_2_START", "SWIPE_2_END"),
    "swipe_3": ("SWIPE_3_START", "SWIPE_3_END"),
}

WORKLOAD_C_GFXINFO_FILES = {
    "page_load": "ground_truth_page_load_gfxinfo.txt",
    "swipe_1": "ground_truth_swipe_1_gfxinfo.txt",
    "swipe_2": "ground_truth_swipe_2_gfxinfo.txt",
    "swipe_3": "ground_truth_swipe_3_gfxinfo.txt",
}

WORKLOAD_C_MEMINFO_FILES = {
    "page_load": "ground_truth_page_load_meminfo.txt",
    "swipe_1": "ground_truth_swipe_1_meminfo.txt",
    "swipe_2": "ground_truth_swipe_2_meminfo.txt",
    "swipe_3": "ground_truth_swipe_3_meminfo.txt",
}

WORKLOAD_D_EPISODE_MARKERS = {
    "background_window": ("BACKGROUND_WINDOW_START", "BACKGROUND_WINDOW_END"),
}

WORKLOAD_D_GFXINFO_FILES = {
    "background_window": "ground_truth_background_gfxinfo.txt",
}

WORKLOAD_D_MEMINFO_FILES = {
    "background_window": "ground_truth_background_meminfo.txt",
}


def parse_count_pairs(text):
    counts = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        left, right = line.split("|", 1)
        left = left.strip()
        right = right.strip()
        if not right.isdigit():
            continue
        counts[left] = int(right)
    return counts


def parse_file_stats(path):
    counts = parse_count_pairs(path.read_text())
    return {
        "openat": counts.get("openat", 0),
        "read": counts.get("read", 0),
        "write": counts.get("write", 0),
    }


def parse_page_order(path):
    counts = parse_count_pairs(path.read_text())
    return {f"order_{order}": counts.get(str(order), 0) for order in range(16)}


def parse_alloc_latency(path):
    counts = parse_count_pairs(path.read_text())
    return {
        f"latency_bucket_{idx}": counts.get(label, 0)
        for idx, label in enumerate(LATENCY_BUCKETS)
    }


def parse_metadata(path):
    metadata = {}
    if not path.exists():
        return metadata

    for line in path.read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def parse_syscall_trace(path, metadata):
    if not path.exists():
        return [], {}

    start_marker = f"WORKLOAD_{metadata.get('workload', '')}_RUN_{metadata.get('run_index', '')}_START"
    end_marker = f"WORKLOAD_{metadata.get('workload', '')}_RUN_{metadata.get('run_index', '')}_END"

    timestamps = []
    markers = {}
    marker_start_ts = None
    marker_end_ts = None

    for line in path.read_text(errors="replace").splitlines():
        marker_match = MARKER_RE.search(line)
        if marker_match:
            ts = float(marker_match.group(1))
            marker_text = marker_match.group(2).strip()
            markers[marker_text] = ts
            if marker_text == start_marker:
                marker_start_ts = ts
            elif marker_text == end_marker:
                marker_end_ts = ts
            continue

        match = TIMESTAMP_RE.search(line)
        if not match:
            continue
        timestamps.append(float(match.group(1)))

    if marker_start_ts is not None and marker_end_ts is not None and marker_end_ts >= marker_start_ts:
        timestamps = [ts for ts in timestamps if marker_start_ts <= ts <= marker_end_ts]
        markers = {
            marker: ts for marker, ts in markers.items()
            if marker_start_ts <= ts <= marker_end_ts
        }

    return timestamps, markers


def load_launch_ground_truth(path):
    if not path.exists():
        return {}

    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["episode"]: row
        for row in rows
        if row.get("episode")
    }


def load_gfxinfo_ground_truth(run_dir):
    ground_truth = {}
    for episode, filename in WORKLOAD_C_GFXINFO_FILES.items():
        path = run_dir / filename
        if path.exists():
            ground_truth[episode] = parse_gfxinfo(path)
    return ground_truth


def load_meminfo_ground_truth(run_dir):
    ground_truth = {}
    for episode, filename in WORKLOAD_C_MEMINFO_FILES.items():
        path = run_dir / filename
        if path.exists():
            ground_truth[episode] = parse_meminfo(path)
    for episode, filename in WORKLOAD_D_MEMINFO_FILES.items():
        path = run_dir / filename
        if path.exists():
            ground_truth[episode] = parse_meminfo(path)
    return ground_truth


def parse_gfxinfo(path):
    if not path.exists():
        return {}

    metrics = {}
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("Total frames rendered:"):
            metrics["total_frames_rendered"] = parse_first_int(stripped)
        elif stripped.startswith("Janky frames:"):
            metrics["janky_frames"] = parse_first_int(stripped)
            match = re.search(r"\(([-0-9.]+)%\)", stripped)
            if match:
                metrics["janky_frames_pct"] = float(match.group(1))
        elif stripped.startswith("50th percentile:"):
            metrics["frame_p50_ms"] = parse_first_ms(stripped)
        elif stripped.startswith("90th percentile:"):
            metrics["frame_p90_ms"] = parse_first_ms(stripped)
        elif stripped.startswith("95th percentile:"):
            metrics["frame_p95_ms"] = parse_first_ms(stripped)
        elif stripped.startswith("99th percentile:"):
            metrics["frame_p99_ms"] = parse_first_ms(stripped)
        elif stripped.startswith("Number Missed Vsync:"):
            metrics["missed_vsync"] = parse_first_int(stripped)
        elif stripped.startswith("Number High input latency:"):
            metrics["high_input_latency"] = parse_first_int(stripped)
        elif stripped.startswith("Number Slow UI thread:"):
            metrics["slow_ui_thread"] = parse_first_int(stripped)
        elif stripped.startswith("Number Slow bitmap uploads:"):
            metrics["slow_bitmap_uploads"] = parse_first_int(stripped)
        elif stripped.startswith("Number Slow issue draw commands:"):
            metrics["slow_issue_draw_commands"] = parse_first_int(stripped)
        elif stripped.startswith("Number Frame deadline missed:"):
            metrics["frame_deadline_missed"] = parse_first_int(stripped)
        elif stripped.startswith("Total ViewRootImpl"):
            metrics["total_viewrootimpl"] = parse_first_int(stripped)
        elif stripped.startswith("Total attached Views"):
            metrics["total_attached_views"] = parse_first_int(stripped)
        elif stripped.startswith("Total RenderNode"):
            metrics["total_rendernode_kb"] = parse_first_float(stripped)
    if "janky_frames_pct" not in metrics and metrics.get("total_frames_rendered", 0):
        metrics["janky_frames_pct"] = ratio(metrics.get("janky_frames", 0), metrics["total_frames_rendered"]) * 100.0
    return metrics


def parse_meminfo(path):
    if not path.exists():
        return {}

    metrics = {}
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("Native Heap"):
            metrics["native_heap_pss_kb"] = parse_first_int(stripped)
        elif stripped.startswith("Dalvik Heap"):
            metrics["dalvik_heap_pss_kb"] = parse_first_int(stripped)
        elif stripped.startswith("Graphics:"):
            metrics["graphics_pss_kb"] = parse_first_int(stripped)
        elif stripped.startswith("System:"):
            metrics["system_pss_kb"] = parse_first_int(stripped)
        elif stripped.startswith("TOTAL PSS:"):
            metrics["total_pss_kb"] = parse_first_int(stripped)
            match = re.search(r"TOTAL RSS:\s+(\d+)", stripped)
            if match:
                metrics["total_rss_kb"] = int(match.group(1))
            match = re.search(r"TOTAL SWAP PSS:\s+(\d+)", stripped)
            if match:
                metrics["total_swap_pss_kb"] = int(match.group(1))
        elif stripped.startswith("Views:"):
            metrics["views"] = parse_first_int(stripped)
        elif stripped.startswith("Activities:"):
            metrics["activities"] = parse_first_int(stripped)
        elif stripped.startswith("WebViews:"):
            metrics["webviews"] = parse_first_int(stripped)
    return metrics


def parse_first_int(text):
    match = re.search(r"(-?\d+)", text)
    return int(match.group(1)) if match else 0


def parse_first_float(text):
    match = re.search(r"(-?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else 0.0


def parse_first_ms(text):
    return parse_first_float(text)


def build_episode_rows(workload_name, run_name, run_index, timestamps, markers, gap_ms, launch_ground_truth, gfxinfo_ground_truth, meminfo_ground_truth, derived_metrics):
    rows = []
    marker_prefix = f"WORKLOAD_{workload_name}_RUN_{run_index}_"
    episode_specs = []
    if workload_name == "workload_b":
        episode_specs = [
            (episode_name, start_suffix, end_suffix, "launch")
            for episode_name, (start_suffix, end_suffix) in WORKLOAD_B_EPISODE_MARKERS.items()
        ]
    elif workload_name == "workload_c":
        episode_specs = [
            (episode_name, start_suffix, end_suffix, "scroll")
            for episode_name, (start_suffix, end_suffix) in WORKLOAD_C_EPISODE_MARKERS.items()
        ]
    elif workload_name == "workload_d":
        episode_specs = [
            (episode_name, start_suffix, end_suffix, "memory")
            for episode_name, (start_suffix, end_suffix) in WORKLOAD_D_EPISODE_MARKERS.items()
        ]
    else:
        return rows

    for episode_name, start_suffix, end_suffix, family in episode_specs:
        start_ts = markers.get(marker_prefix + start_suffix)
        end_ts = markers.get(marker_prefix + end_suffix)
        if start_ts is None:
            continue
        if workload_name == "workload_c" and episode_name == "page_load":
            settled_ts = markers.get(marker_prefix + "PAGE_SETTLED")
            if settled_ts is not None:
                end_ts = settled_ts
        if end_ts is None or end_ts < start_ts:
            continue

        episode_timestamps = [ts for ts in timestamps if start_ts <= ts <= end_ts]
        bursts = compute_bursts(episode_timestamps, gap_ms)
        episode_elapsed_s = max(end_ts - start_ts, 0.0)
        burst_metrics = compute_burst_metrics(bursts, episode_elapsed_s, episode_timestamps)
        launch_row = launch_ground_truth.get(episode_name, {})
        gfx_row = gfxinfo_ground_truth.get(episode_name, {})
        mem_row = meminfo_ground_truth.get(episode_name, {})

        row = {
            "workload": workload_name,
            "run": run_name,
            "episode": episode_name,
            "episode_family": family,
            "episode_start_ts": f"{start_ts:.6f}",
            "episode_end_ts": f"{end_ts:.6f}",
            "episode_elapsed_s": f"{episode_elapsed_s:.6f}",
            "burst_count": f"{burst_metrics['burst_count']:.6f}",
            "avg_burst_latency_ms": f"{burst_metrics['avg_burst_latency_ms']:.6f}",
            "p95_burst_latency_ms": f"{burst_metrics['p95_burst_latency_ms']:.6f}",
            "max_burst_latency_ms": f"{burst_metrics['max_burst_latency_ms']:.6f}",
            "avg_syscalls_per_burst": f"{burst_metrics['avg_syscalls_per_burst']:.6f}",
            "throughput_bursts_per_s": f"{burst_metrics['throughput_bursts_per_s']:.6f}",
            "trace_event_count": f"{burst_metrics['trace_event_count']:.6f}",
            "trace_elapsed_s": f"{burst_metrics['trace_elapsed_s']:.6f}",
            "ground_truth_status": launch_row.get("status", ""),
            "ground_truth_launch_state": launch_row.get("launch_state", ""),
            "ground_truth_activity": launch_row.get("activity", ""),
            "ground_truth_this_time_ms": launch_row.get("this_time_ms", ""),
            "ground_truth_total_time_ms": launch_row.get("total_time_ms", ""),
            "ground_truth_wait_time_ms": launch_row.get("wait_time_ms", ""),
            "ground_truth_error": launch_row.get("error", ""),
            "ground_truth_total_frames_rendered": str(gfx_row.get("total_frames_rendered", "")),
            "ground_truth_janky_frames": str(gfx_row.get("janky_frames", "")),
            "ground_truth_janky_frames_pct": str(gfx_row.get("janky_frames_pct", "")),
            "ground_truth_frame_p50_ms": str(gfx_row.get("frame_p50_ms", "")),
            "ground_truth_frame_p90_ms": str(gfx_row.get("frame_p90_ms", "")),
            "ground_truth_frame_p95_ms": str(gfx_row.get("frame_p95_ms", "")),
            "ground_truth_frame_p99_ms": str(gfx_row.get("frame_p99_ms", "")),
            "ground_truth_missed_vsync": str(gfx_row.get("missed_vsync", "")),
            "ground_truth_high_input_latency": str(gfx_row.get("high_input_latency", "")),
            "ground_truth_slow_ui_thread": str(gfx_row.get("slow_ui_thread", "")),
            "ground_truth_slow_bitmap_uploads": str(gfx_row.get("slow_bitmap_uploads", "")),
            "ground_truth_slow_issue_draw_commands": str(gfx_row.get("slow_issue_draw_commands", "")),
            "ground_truth_frame_deadline_missed": str(gfx_row.get("frame_deadline_missed", "")),
            "ground_truth_total_viewrootimpl": str(gfx_row.get("total_viewrootimpl", "")),
            "ground_truth_total_attached_views": str(gfx_row.get("total_attached_views", "")),
            "ground_truth_total_rendernode_kb": str(gfx_row.get("total_rendernode_kb", "")),
            "ground_truth_native_heap_pss_kb": str(mem_row.get("native_heap_pss_kb", "")),
            "ground_truth_dalvik_heap_pss_kb": str(mem_row.get("dalvik_heap_pss_kb", "")),
            "ground_truth_graphics_pss_kb": str(mem_row.get("graphics_pss_kb", "")),
            "ground_truth_system_pss_kb": str(mem_row.get("system_pss_kb", "")),
            "ground_truth_total_pss_kb": str(mem_row.get("total_pss_kb", "")),
            "ground_truth_total_rss_kb": str(mem_row.get("total_rss_kb", "")),
            "ground_truth_total_swap_pss_kb": str(mem_row.get("total_swap_pss_kb", "")),
            "ground_truth_views": str(mem_row.get("views", "")),
            "ground_truth_activities": str(mem_row.get("activities", "")),
            "ground_truth_webviews": str(mem_row.get("webviews", "")),
            "file_syscall_intensity": f"{derived_metrics['file_syscall_intensity']:.6f}",
            "read_dominance_ratio": f"{derived_metrics['read_dominance_ratio']:.6f}",
            "write_activity_ratio": f"{derived_metrics['write_activity_ratio']:.6f}",
            "allocation_volume": f"{derived_metrics['allocation_volume']:.6f}",
            "higher_order_allocation_share": f"{derived_metrics['higher_order_allocation_share']:.6f}",
            "fast_allocation_share": f"{derived_metrics['fast_allocation_share']:.6f}",
            "slow_allocation_share": f"{derived_metrics['slow_allocation_share']:.6f}",
            "long_tail_share": f"{derived_metrics['long_tail_share']:.6f}",
        }
        rows.append(row)

    return rows


def percentile(sorted_values, fraction):
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[int(position)])

    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    weight = position - lower
    return float(lower_value + (upper_value - lower_value) * weight)


def compute_bursts(timestamps, gap_ms):
    if not timestamps:
        return []

    gap_seconds = gap_ms / 1000.0
    bursts = []
    burst_start = timestamps[0]
    burst_end = timestamps[0]
    burst_count = 1

    for ts in timestamps[1:]:
        if ts - burst_end <= gap_seconds:
            burst_end = ts
            burst_count += 1
            continue

        bursts.append({
            "start_ts": burst_start,
            "end_ts": burst_end,
            "duration_ms": (burst_end - burst_start) * 1000.0,
            "syscall_count": burst_count,
        })
        burst_start = ts
        burst_end = ts
        burst_count = 1

    bursts.append({
        "start_ts": burst_start,
        "end_ts": burst_end,
        "duration_ms": (burst_end - burst_start) * 1000.0,
        "syscall_count": burst_count,
    })
    return bursts


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def ratio(numerator, denominator):
    return 0.0 if denominator == 0 else numerator / denominator


def format_ratio(numerator, denominator):
    return "n/a" if denominator == 0 else f"{number(numerator / denominator)}x"


def number(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def percent(value):
    return f"{value * 100:.2f}%"


def safe_float(metadata, key, default):
    value = metadata.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def compute_derived_metrics(raw):
    total_file = raw["openat"] + raw["read"] + raw["write"]
    allocation_volume = sum(raw[f"order_{i}"] for i in range(16))
    higher_order = sum(raw[f"order_{i}"] for i in range(1, 4))
    total_latency = sum(raw[f"latency_bucket_{i}"] for i in range(8))
    fast_alloc = raw["latency_bucket_0"] + raw["latency_bucket_1"] + raw["latency_bucket_2"]
    slow_alloc = sum(raw[f"latency_bucket_{i}"] for i in range(3, 8))
    long_tail = sum(raw[f"latency_bucket_{i}"] for i in range(4, 8))

    return {
        "file_syscall_intensity": total_file,
        "read_dominance_ratio": ratio(raw["read"], total_file),
        "write_activity_ratio": ratio(raw["write"], total_file),
        "allocation_volume": allocation_volume,
        "higher_order_allocation_share": ratio(higher_order, allocation_volume),
        "fast_allocation_share": ratio(fast_alloc, total_latency),
        "slow_allocation_share": ratio(slow_alloc, total_latency),
        "long_tail_share": ratio(long_tail, total_latency),
    }


def compute_burst_metrics(bursts, workload_elapsed_s, timestamps):
    durations = sorted(burst["duration_ms"] for burst in bursts)
    syscall_counts = [burst["syscall_count"] for burst in bursts]
    trace_elapsed_s = max((timestamps[-1] - timestamps[0]), 0.0) if len(timestamps) >= 2 else 0.0
    effective_elapsed_s = workload_elapsed_s if workload_elapsed_s > 0 else trace_elapsed_s

    return {
        "burst_count": len(bursts),
        "avg_burst_latency_ms": mean(durations),
        "p95_burst_latency_ms": percentile(durations, 0.95),
        "max_burst_latency_ms": max(durations) if durations else 0.0,
        "avg_syscalls_per_burst": mean(syscall_counts),
        "throughput_bursts_per_s": ratio(len(bursts), effective_elapsed_s),
        "trace_event_count": len(timestamps),
        "trace_elapsed_s": trace_elapsed_s,
        "workload_elapsed_s": effective_elapsed_s,
    }


def safe_float_value(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def rank_values(values):
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        jdx = idx + 1
        while jdx < len(indexed) and indexed[jdx][1] == indexed[idx][1]:
            jdx += 1
        average_rank = (idx + jdx - 1) / 2.0 + 1.0
        for pos in range(idx, jdx):
            ranks[indexed[pos][0]] = average_rank
        idx = jdx
    return ranks


def pearson_correlation(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0

    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    denominator = denom_x * denom_y
    if denominator == 0:
        return 0.0
    return numerator / denominator


def spearman_correlation(xs, ys):
    return pearson_correlation(rank_values(xs), rank_values(ys))


def linear_fit(xs, ys):
    if len(xs) != len(ys) or not xs:
        return 0.0, 0.0

    mean_x = mean(xs)
    mean_y = mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0, mean_y
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def regression_error(xs, ys, slope, intercept):
    if not xs:
        return 0.0, 0.0
    predictions = [slope * x + intercept for x in xs]
    errors = [pred - y for pred, y in zip(predictions, ys)]
    mae = mean([abs(error) for error in errors])
    rmse = math.sqrt(mean([error ** 2 for error in errors]))
    return mae, rmse


def collect_valid_rows(rows, target_field, proxy_field):
    xs = []
    ys = []
    for row in rows:
        x = safe_float_value(row.get(proxy_field))
        y = safe_float_value(row.get(target_field))
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def summarize_validation(rows, family, target_field, proxy_fields, gap_ms):
    summary_rows = []
    for proxy_field in proxy_fields:
        xs, ys = collect_valid_rows(rows, target_field, proxy_field)
        if len(xs) < 2:
            summary_rows.append({
                "family": family,
                "gap_ms": f"{gap_ms:.2f}",
                "target_metric": target_field,
                "proxy_metric": proxy_field,
                "sample_count": len(xs),
                "pearson_r": "",
                "spearman_r": "",
                "slope": "",
                "intercept": "",
                "mae_ms": "",
                "rmse_ms": "",
            })
            continue

        slope, intercept = linear_fit(xs, ys)
        mae, rmse = regression_error(xs, ys, slope, intercept)
        summary_rows.append({
            "family": family,
            "gap_ms": f"{gap_ms:.2f}",
            "target_metric": target_field,
            "proxy_metric": proxy_field,
            "sample_count": len(xs),
            "pearson_r": f"{pearson_correlation(xs, ys):.6f}",
            "spearman_r": f"{spearman_correlation(xs, ys):.6f}",
            "slope": f"{slope:.6f}",
            "intercept": f"{intercept:.6f}",
            "mae_ms": f"{mae:.6f}",
            "rmse_ms": f"{rmse:.6f}",
        })
    return summary_rows


def build_episode_validation_rows(rows, family, gap_ms, target_fields, proxy_fields):
    output_rows = []
    for row in rows:
        if row.get("episode_family") != family:
            continue
        output_row = {
            "workload": row.get("workload", ""),
            "run": row.get("run", ""),
            "episode": row.get("episode", ""),
            "episode_family": row.get("episode_family", ""),
            "gap_ms": f"{gap_ms:.2f}",
        }
        for field in target_fields:
            output_row[field] = row.get(field, "")
        for field in proxy_fields:
            output_row[field] = row.get(field, "")
        output_rows.append(output_row)
    return output_rows


def build_gap_sweep_rows(results_dir, family, target_field, proxy_fields, gaps):
    rows = []
    for gap_ms in gaps:
        _, _, episode_rows = load_runs(results_dir, gap_ms)
        family_rows = [row for row in episode_rows if row.get("episode_family") == family]
        for summary_row in summarize_validation(family_rows, family, target_field, proxy_fields, gap_ms):
            rows.append(summary_row)
    return rows


def format_validation_section(title, rows, primary_metric_label):
    lines = []
    lines.append(f"## {title}")
    lines.append("")
    if not rows:
        lines.append("No validated episodes were found for this section.")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"Best proxy fits for {primary_metric_label} across the available episodes.")
    lines.append("")
    lines.append("| Gap (ms) | Target | Proxy | N | Pearson r | Spearman r | Slope | Intercept | MAE | RMSE |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        lines.append(
            f"| {row['gap_ms']} | {row['target_metric']} | {row['proxy_metric']} | {row['sample_count']} | "
            f"{row['pearson_r']} | {row['spearman_r']} | {row['slope']} | {row['intercept']} | "
            f"{row['mae_ms']} | {row['rmse_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)


def best_validation_rows(rows):
    best_by_target = {}
    for row in rows:
        if not row.get("pearson_r"):
            continue
        if int(row.get("sample_count", 0)) < 2:
            continue
        target = row["target_metric"]
        score = abs(float(row["pearson_r"]))
        if target not in best_by_target or score > best_by_target[target][0]:
            best_by_target[target] = (score, row)
    return [entry[1] for _, entry in sorted(best_by_target.items())]


def best_validation_row(rows, target_metric, proxy_fields):
    best = None
    for row in rows:
        if row.get("target_metric") != target_metric:
            continue
        if row.get("proxy_metric") not in proxy_fields:
            continue
        if not row.get("pearson_r"):
            continue
        if int(row.get("sample_count", 0)) < 2:
            continue
        score = abs(float(row["pearson_r"]))
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best else None


def build_launch_validation_summary_rows(launch_gap_rows):
    latency_shaped_fields = [
        "episode_elapsed_s",
        "avg_burst_latency_ms",
        "p95_burst_latency_ms",
        "max_burst_latency_ms",
    ]
    proxy_fields = [
        "episode_elapsed_s",
        "avg_burst_latency_ms",
        "p95_burst_latency_ms",
        "max_burst_latency_ms",
        "avg_syscalls_per_burst",
        "throughput_bursts_per_s",
        "trace_event_count",
    ]
    summary_rows = []
    for target_metric in ["ground_truth_total_time_ms", "ground_truth_wait_time_ms"]:
        for proxy_group, fields in [("overall", proxy_fields), ("latency_shaped", latency_shaped_fields)]:
            row = best_validation_row(launch_gap_rows, target_metric, fields)
            if row is None:
                continue
            summary_rows.append({
                "target_metric": row["target_metric"],
                "proxy_group": proxy_group,
                "best_gap_ms": row["gap_ms"],
                "best_proxy_metric": row["proxy_metric"],
                "sample_count": row["sample_count"],
                "pearson_r": row["pearson_r"],
                "spearman_r": row["spearman_r"],
                "slope": row["slope"],
                "intercept": row["intercept"],
                "mae_ms": row["mae_ms"],
                "rmse_ms": row["rmse_ms"],
            })
    return summary_rows


def format_best_validation_section(title, rows):
    best_rows = best_validation_rows(rows)
    lines = []
    lines.append(f"## {title}")
    lines.append("")
    if not best_rows:
        lines.append("No best-fit validation rows are available yet.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Target | Best Gap (ms) | Best Proxy | N | Pearson r | Spearman r | MAE | RMSE |")
    lines.append("| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in best_rows:
        lines.append(
            f"| {row['target_metric']} | {row['gap_ms']} | {row['proxy_metric']} | "
            f"{row['sample_count']} | {row['pearson_r']} | {row['spearman_r']} | "
            f"{row['mae_ms']} | {row['rmse_ms']} |"
        )
    lines.append("")
    return "\n".join(lines)


def format_launch_summary_section(summary_rows, figure_paths):
    lines = []
    lines.append("## Launch Validation Summary")
    lines.append("")
    if not summary_rows:
        lines.append("No launch validation summary rows are available yet.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Target | Proxy Group | Best Gap (ms) | Best Proxy | N | Pearson r | Spearman r | MAE | RMSE |")
    lines.append("| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |")
    for row in summary_rows:
        lines.append(
            f"| {row['target_metric']} | {row['proxy_group']} | {row['best_gap_ms']} | "
            f"{row['best_proxy_metric']} | {row['sample_count']} | {row['pearson_r']} | "
            f"{row['spearman_r']} | {row['mae_ms']} | {row['rmse_ms']} |"
        )
    lines.append("")
    lines.append(
        "These rows compare eBeeMobile burst-derived proxy metrics directly against `am start -W` launch ground truth. "
        "The `overall` row allows any proxy metric to win; the `latency_shaped` row restricts the comparison to duration-like proxies."
    )
    lines.append("")
    if figure_paths:
        lines.append("Launch validation figures:")
        lines.append("")
        for label, path in figure_paths:
            lines.append(f"![{label}]({path})")
            lines.append("")
    return "\n".join(lines)


def load_runs(results_dir, gap_ms):
    runs = {}
    pseudo_requests = []
    episode_rows = []

    for workload_dir in sorted(results_dir.iterdir()):
        if not workload_dir.is_dir():
            continue

        workload_name = workload_dir.name
        runs[workload_name] = []

        for run_dir in sorted(workload_dir.iterdir()):
            if not run_dir.is_dir():
                continue

            file_stats = run_dir / "file_stats.txt"
            page_order = run_dir / "page_order.txt"
            alloc_latency = run_dir / "alloc_latency.txt"
            if not (file_stats.exists() and page_order.exists() and alloc_latency.exists()):
                continue

            raw = {}
            raw.update(parse_file_stats(file_stats))
            raw.update(parse_page_order(page_order))
            raw.update(parse_alloc_latency(alloc_latency))

            metadata = parse_metadata(run_dir / "metadata.txt")
            metadata["workload"] = workload_name
            run_suffix = run_dir.name.split("_")[-1]
            metadata["run_index"] = str(int(run_suffix))
            timestamps, markers = parse_syscall_trace(run_dir / "syscall_trace.txt", metadata)
            bursts = compute_bursts(timestamps, gap_ms)
            derived = compute_derived_metrics(raw)
            launch_ground_truth = load_launch_ground_truth(run_dir / "launch_ground_truth.csv")
            gfxinfo_ground_truth = load_gfxinfo_ground_truth(run_dir)
            meminfo_ground_truth = load_meminfo_ground_truth(run_dir)
            episode_rows.extend(
                build_episode_rows(
                    workload_name,
                    run_dir.name,
                    metadata["run_index"],
                    timestamps,
                    markers,
                    gap_ms,
                    launch_ground_truth,
                    gfxinfo_ground_truth,
                    meminfo_ground_truth,
                    derived,
                )
            )

            workload_elapsed_s = safe_float(metadata, "workload_elapsed_s", 0.0)
            burst_metrics = compute_burst_metrics(bursts, workload_elapsed_s, timestamps)

            for idx, burst in enumerate(bursts, start=1):
                pseudo_requests.append({
                    "workload": workload_name,
                    "run": run_dir.name,
                    "burst_index": idx,
                    "start_ts": f"{burst['start_ts']:.6f}",
                    "end_ts": f"{burst['end_ts']:.6f}",
                    "duration_ms": f"{burst['duration_ms']:.6f}",
                    "syscall_count": burst["syscall_count"],
                })

            runs[workload_name].append({
                "run_name": run_dir.name,
                "raw": raw,
                "derived": derived,
                "metadata": metadata,
                "burst_metrics": burst_metrics,
            })

    return runs, pseudo_requests, episode_rows


def aggregate_runs(runs):
    aggregated = {}
    for workload_name, workload_runs in runs.items():
        if not workload_runs:
            continue

        aggregated[workload_name] = {
            "count": len(workload_runs),
            "raw": {},
            "derived": {},
            "burst_metrics": {},
        }

        raw_keys = workload_runs[0]["raw"].keys()
        derived_keys = workload_runs[0]["derived"].keys()
        burst_metric_keys = workload_runs[0]["burst_metrics"].keys()

        for key in raw_keys:
            values = [run["raw"][key] for run in workload_runs]
            aggregated[workload_name]["raw"][key] = {
                "mean": mean(values),
                "min": min(values),
                "max": max(values),
                "stdev": stdev(values),
            }

        for key in derived_keys:
            values = [run["derived"][key] for run in workload_runs]
            aggregated[workload_name]["derived"][key] = {
                "mean": mean(values),
                "min": min(values),
                "max": max(values),
                "stdev": stdev(values),
            }

        for key in burst_metric_keys:
            values = [run["burst_metrics"][key] for run in workload_runs]
            aggregated[workload_name]["burst_metrics"][key] = {
                "mean": mean(values),
                "min": min(values),
                "max": max(values),
                "stdev": stdev(values),
            }

    return aggregated


def build_comparisons(aggregated):
    comparisons = []
    baseline = aggregated.get("workload_a")
    if baseline is None:
        return comparisons

    for workload_name in ["workload_b", "workload_c", "workload_d"]:
        if workload_name in aggregated:
            comparisons.append((f"{workload_name[-1].upper()}/A", aggregated[workload_name], baseline))

    if "workload_b" in aggregated and "workload_c" in aggregated:
        comparisons.append(("B/C", aggregated["workload_b"], aggregated["workload_c"]))

    if "workload_d" in aggregated and "workload_c" in aggregated:
        comparisons.append(("D/C", aggregated["workload_d"], aggregated["workload_c"]))

    return comparisons


def write_csv(path, rows, headers):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def union_fieldnames(rows):
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    return fieldnames


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

    colors = {
        "settings_launch": "#2563eb",
        "browser_launch": "#dc2626",
        "gallery_launch": "#16a34a",
    }
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
    for idx, (name, color) in enumerate(colors.items()):
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


def build_launch_figures(output_dir, results_dir, launch_gap_rows):
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


def generate_report(aggregated, comparisons, gap_ms):
    lines = []
    present_workloads = [name for name in ["workload_a", "workload_b", "workload_c", "workload_d"] if name in aggregated]

    lines.append("# Android eBPF Exploration Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "This report summarizes two layers of observability from the Android experiment suite. "
        "First, it reports workload-level kernel-visible I/O and memory behavior using the existing Task A/B/C eBPF probes. "
        "Second, it derives pseudo-request metrics by segmenting timestamped syscall events into bursts, following the same high-level idea as eBeeMetrics: infer latency-like and throughput-like metrics from low-level syscall observability."
    )
    lines.append("")
    lines.append(f"Burst segmentation rule: a new pseudo-request starts when the gap between syscall events exceeds {gap_ms:.2f} ms.")
    lines.append("")

    lines.append("## Averaged Raw Metrics")
    lines.append("")
    lines.append("| Workload | openat | read | write | File Syscall Intensity | Allocation Volume | Order 1-3 Share |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for workload_name in present_workloads:
        raw = aggregated[workload_name]["raw"]
        total_file = raw["openat"]["mean"] + raw["read"]["mean"] + raw["write"]["mean"]
        allocation_volume = sum(raw[f"order_{i}"]["mean"] for i in range(16))
        higher_order = sum(raw[f"order_{i}"]["mean"] for i in range(1, 4))
        lines.append(
            f"| {WORKLOAD_LABELS[workload_name]} | "
            f"{number(raw['openat']['mean'])} | {number(raw['read']['mean'])} | {number(raw['write']['mean'])} | "
            f"{number(total_file)} | {number(allocation_volume)} | {percent(ratio(higher_order, allocation_volume))} |"
        )
    lines.append("")

    lines.append("## Pseudo-Request Metrics")
    lines.append("")
    lines.append("| Workload | Burst Count | Avg Burst Latency (ms) | P95 Burst Latency (ms) | Avg Syscalls/Burst | Throughput (bursts/s) |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for workload_name in present_workloads:
        burst = aggregated[workload_name]["burst_metrics"]
        lines.append(
            f"| {WORKLOAD_LABELS[workload_name]} | "
            f"{number(burst['burst_count']['mean'])} | "
            f"{number(burst['avg_burst_latency_ms']['mean'])} | "
            f"{number(burst['p95_burst_latency_ms']['mean'])} | "
            f"{number(burst['avg_syscalls_per_burst']['mean'])} | "
            f"{number(burst['throughput_bursts_per_s']['mean'])} |"
        )
    lines.append("")

    lines.append("## Derived Workload Metrics")
    lines.append("")
    lines.append("| Workload | Read Dominance | Write Activity | Fast Allocation Share | Slow Allocation Share | Long-Tail Share |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for workload_name in present_workloads:
        derived = aggregated[workload_name]["derived"]
        lines.append(
            f"| {WORKLOAD_LABELS[workload_name]} | "
            f"{percent(derived['read_dominance_ratio']['mean'])} | "
            f"{percent(derived['write_activity_ratio']['mean'])} | "
            f"{percent(derived['fast_allocation_share']['mean'])} | "
            f"{percent(derived['slow_allocation_share']['mean'])} | "
            f"{percent(derived['long_tail_share']['mean'])} |"
        )
    lines.append("")

    lines.append("## Comparison Ratios")
    lines.append("")
    lines.append("| Comparison | File Intensity | Allocation Volume | Avg Burst Latency | Throughput | Avg Syscalls/Burst |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for label, lhs, rhs in comparisons:
        lines.append(
            f"| {label} | "
            f"{format_ratio(lhs['derived']['file_syscall_intensity']['mean'], rhs['derived']['file_syscall_intensity']['mean'])} | "
            f"{format_ratio(lhs['derived']['allocation_volume']['mean'], rhs['derived']['allocation_volume']['mean'])} | "
            f"{format_ratio(lhs['burst_metrics']['avg_burst_latency_ms']['mean'], rhs['burst_metrics']['avg_burst_latency_ms']['mean'])} | "
            f"{format_ratio(lhs['burst_metrics']['throughput_bursts_per_s']['mean'], rhs['burst_metrics']['throughput_bursts_per_s']['mean'])} | "
            f"{format_ratio(lhs['burst_metrics']['avg_syscalls_per_burst']['mean'], rhs['burst_metrics']['avg_syscalls_per_burst']['mean'])} |"
        )
    lines.append("")

    lines.append("## Collection Diagnostics")
    lines.append("")
    lines.append("| Workload | Runs | Trace Events | Trace Elapsed (s) | Workload Elapsed (s) | Max Burst Latency (ms) |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for workload_name in present_workloads:
        burst = aggregated[workload_name]["burst_metrics"]
        lines.append(
            f"| {WORKLOAD_LABELS[workload_name]} | "
            f"{aggregated[workload_name]['count']} | "
            f"{number(burst['trace_event_count']['mean'])} | "
            f"{number(burst['trace_elapsed_s']['mean'])} | "
            f"{number(burst['workload_elapsed_s']['mean'])} | "
            f"{number(burst['max_burst_latency_ms']['mean'])} |"
        )
    lines.append("")

    lines.append("## Artifact Guide")
    lines.append("")
    lines.append("- `raw_summary.csv`: averaged raw probe counters per workload")
    lines.append("- `derived_metrics.csv`: normalized workload metrics computed from raw counters")
    lines.append("- `burst_summary.csv`: burst-derived pseudo-request metrics and trace diagnostics")
    lines.append("- `pseudo_requests.csv`: one row per reconstructed burst")
    lines.append("- `episode_summary.csv`: episode-level proxy and ground-truth rows for validated launch and scroll episodes")
    lines.append("- `launch_episode_summary.csv`: launch-only episode rows for Workload B validation")
    lines.append("- `launch_validation_summary.csv`: compact best-fit launch validation rows")
    lines.append("- `launch_validation.csv`: launch episode rows with proxy and ground-truth fields")
    lines.append("- `scroll_validation.csv`: scroll episode rows with proxy and ground-truth fields")
    lines.append("- `memory_validation.csv`: background episode rows with proxy and ground-truth fields")
    lines.append("- `launch_gap_sweep.csv`: launch correlation and error metrics across burst-gap values")
    lines.append("- `gap_sweep_validation.csv`: compatibility copy of the launch gap sweep")
    lines.append("- `scroll_gap_sweep.csv`: scroll correlation and error metrics across burst-gap values")
    lines.append("- `memory_gap_sweep.csv`: memory correlation and error metrics across burst-gap values")
    lines.append("- `comparison_ratios.csv`: workload-to-workload metric ratios")
    lines.append("- `correlation_points.csv`: compact numeric export for downstream plotting and correlation analysis")
    lines.append("- `figures/`: SVG launch-validation plots when an output directory is provided")
    if all(aggregated[name]["burst_metrics"]["burst_count"]["mean"] == 0 for name in present_workloads):
        lines.append(
            "- Note: this dataset does not include syscall-trace capture, so pseudo-request rows are empty. Re-run collection with the updated experiment harness to populate burst metrics."
        )
    lines.append("")

    lines.append("## Report Positioning")
    lines.append("")
    lines.append("- eBeeMetrics: syscall-visible events -> request latency / throughput")
    lines.append("- This project: syscall-visible events -> user-interaction burst latency / throughput / activity intensity")
    lines.append("- The adaptation is domain-specific: HTTP request boundaries become Android pseudo-request boundaries defined by syscall bursts.")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze Android eBPF exploration runs.")
    parser.add_argument("results_dir", type=Path, help="Directory containing workload_a/workload_b/... runs")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated CSV and report files")
    parser.add_argument("--burst-gap-ms", type=float, default=5.0, help="Inter-event gap threshold for a new pseudo-request burst")
    args = parser.parse_args()

    runs, pseudo_requests, episode_rows = load_runs(args.results_dir, args.burst_gap_ms)
    aggregated = aggregate_runs(runs)
    comparisons = build_comparisons(aggregated)

    if not aggregated:
        raise SystemExit("No valid runs found in results directory.")

    output_dir = args.output_dir
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    raw_rows = []
    derived_rows = []
    burst_rows = []
    comparison_rows = []
    correlation_rows = []
    launch_episode_rows = [row for row in episode_rows if row.get("episode_family") == "launch"]
    scroll_episode_rows = [row for row in episode_rows if row.get("episode_family") == "scroll"]
    memory_episode_rows = [row for row in episode_rows if row.get("episode_family") == "memory"]

    launch_target_fields = ["ground_truth_total_time_ms", "ground_truth_wait_time_ms"]
    launch_proxy_fields = [
        "episode_elapsed_s",
        "avg_burst_latency_ms",
        "p95_burst_latency_ms",
        "max_burst_latency_ms",
        "avg_syscalls_per_burst",
        "throughput_bursts_per_s",
        "trace_event_count",
    ]
    scroll_target_fields = [
        "ground_truth_total_frames_rendered",
        "ground_truth_janky_frames",
        "ground_truth_janky_frames_pct",
        "ground_truth_frame_p50_ms",
        "ground_truth_frame_p90_ms",
        "ground_truth_frame_p95_ms",
        "ground_truth_frame_p99_ms",
    ]
    scroll_proxy_fields = [
        "avg_burst_latency_ms",
        "p95_burst_latency_ms",
        "max_burst_latency_ms",
        "avg_syscalls_per_burst",
        "throughput_bursts_per_s",
        "trace_event_count",
        "burst_count",
    ]
    memory_target_fields = [
        "ground_truth_total_pss_kb",
        "ground_truth_total_swap_pss_kb",
        "ground_truth_graphics_pss_kb",
        "ground_truth_native_heap_pss_kb",
        "ground_truth_dalvik_heap_pss_kb",
    ]
    memory_proxy_fields = [
        "allocation_volume",
        "higher_order_allocation_share",
        "slow_allocation_share",
        "long_tail_share",
        "file_syscall_intensity",
        "avg_burst_latency_ms",
        "avg_syscalls_per_burst",
        "trace_event_count",
    ]
    validation_gaps = [1, 2, 5, 10, 20, 50]
    launch_gap_rows = []
    launch_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "launch", "ground_truth_total_time_ms", launch_proxy_fields, validation_gaps))
    launch_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "launch", "ground_truth_wait_time_ms", launch_proxy_fields, validation_gaps))
    launch_validation_summary_rows = build_launch_validation_summary_rows(launch_gap_rows)
    scroll_gap_rows = []
    scroll_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "scroll", "ground_truth_total_frames_rendered", scroll_proxy_fields, validation_gaps))
    scroll_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "scroll", "ground_truth_janky_frames_pct", scroll_proxy_fields, validation_gaps))
    scroll_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "scroll", "ground_truth_frame_p95_ms", scroll_proxy_fields, validation_gaps))
    memory_gap_rows = []
    memory_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "memory", "ground_truth_total_pss_kb", memory_proxy_fields, validation_gaps))
    memory_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "memory", "ground_truth_total_swap_pss_kb", memory_proxy_fields, validation_gaps))
    memory_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "memory", "ground_truth_graphics_pss_kb", memory_proxy_fields, validation_gaps))
    launch_validation_rows = build_episode_validation_rows(launch_episode_rows, "launch", args.burst_gap_ms, launch_target_fields, launch_proxy_fields)
    scroll_validation_rows = build_episode_validation_rows(scroll_episode_rows, "scroll", args.burst_gap_ms, scroll_target_fields, scroll_proxy_fields)
    memory_validation_rows = build_episode_validation_rows(memory_episode_rows, "memory", args.burst_gap_ms, memory_target_fields, memory_proxy_fields)

    for workload_name, summary in aggregated.items():
        raw_row = {"workload": workload_name, "runs": summary["count"]}
        raw_row.update({key: number(stats["mean"]) for key, stats in summary["raw"].items()})
        raw_rows.append(raw_row)

        derived_row = {"workload": workload_name, "runs": summary["count"]}
        derived_row.update({key: f"{stats['mean']:.6f}" for key, stats in summary["derived"].items()})
        derived_rows.append(derived_row)

        burst_row = {"workload": workload_name, "runs": summary["count"]}
        burst_row.update({key: f"{stats['mean']:.6f}" for key, stats in summary["burst_metrics"].items()})
        burst_rows.append(burst_row)

        correlation_rows.append({
            "workload": workload_name,
            "avg_burst_latency_ms": f"{summary['burst_metrics']['avg_burst_latency_ms']['mean']:.6f}",
            "throughput_bursts_per_s": f"{summary['burst_metrics']['throughput_bursts_per_s']['mean']:.6f}",
            "avg_syscalls_per_burst": f"{summary['burst_metrics']['avg_syscalls_per_burst']['mean']:.6f}",
            "allocation_volume": f"{summary['derived']['allocation_volume']['mean']:.6f}",
            "long_tail_share": f"{summary['derived']['long_tail_share']['mean']:.6f}",
            "file_syscall_intensity": f"{summary['derived']['file_syscall_intensity']['mean']:.6f}",
        })

    for label, lhs, rhs in comparisons:
        comparison_rows.append({
            "comparison": label,
            "file_syscall_intensity_ratio": f"{ratio(lhs['derived']['file_syscall_intensity']['mean'], rhs['derived']['file_syscall_intensity']['mean']):.6f}",
            "allocation_volume_ratio": f"{ratio(lhs['derived']['allocation_volume']['mean'], rhs['derived']['allocation_volume']['mean']):.6f}",
            "avg_burst_latency_ratio": f"{ratio(lhs['burst_metrics']['avg_burst_latency_ms']['mean'], rhs['burst_metrics']['avg_burst_latency_ms']['mean']):.6f}",
            "throughput_ratio": f"{ratio(lhs['burst_metrics']['throughput_bursts_per_s']['mean'], rhs['burst_metrics']['throughput_bursts_per_s']['mean']):.6f}",
            "avg_syscalls_per_burst_ratio": f"{ratio(lhs['burst_metrics']['avg_syscalls_per_burst']['mean'], rhs['burst_metrics']['avg_syscalls_per_burst']['mean']):.6f}",
        })

    figure_paths = []
    if output_dir is not None and launch_gap_rows:
        figure_paths = build_launch_figures(output_dir, args.results_dir, launch_gap_rows)

    report = generate_report(aggregated, comparisons, args.burst_gap_ms)
    if launch_validation_summary_rows:
        report += "\n" + format_launch_summary_section(launch_validation_summary_rows, figure_paths)
    if launch_gap_rows:
        report += "\n" + format_best_validation_section("Launch Validation Best Fits", launch_gap_rows)
        report += "\n" + format_validation_section("Launch Validation", launch_gap_rows, "launch latency")
    if scroll_gap_rows:
        report += "\n" + format_best_validation_section("Scroll Validation Best Fits", scroll_gap_rows)
        report += "\n" + format_validation_section("Scroll Validation", scroll_gap_rows, "scroll responsiveness")
    if memory_gap_rows:
        report += "\n" + format_best_validation_section("Memory Validation Best Fits", memory_gap_rows)
        report += "\n" + format_validation_section("Memory Validation", memory_gap_rows, "memory pressure")

    if output_dir is not None:
        write_csv(output_dir / "raw_summary.csv", raw_rows, ["workload", "runs"] + list(raw_rows[0].keys())[2:])
        write_csv(output_dir / "derived_metrics.csv", derived_rows, ["workload", "runs"] + list(derived_rows[0].keys())[2:])
        write_csv(output_dir / "burst_summary.csv", burst_rows, ["workload", "runs"] + list(burst_rows[0].keys())[2:])
        write_csv(output_dir / "pseudo_requests.csv", pseudo_requests, [
            "workload", "run", "burst_index", "start_ts", "end_ts", "duration_ms", "syscall_count"
        ])
        if episode_rows:
            write_csv(output_dir / "episode_summary.csv", episode_rows, union_fieldnames(episode_rows))
        if launch_episode_rows:
            write_csv(output_dir / "launch_episode_summary.csv", launch_episode_rows, union_fieldnames(launch_episode_rows))
        if launch_validation_summary_rows:
            write_csv(output_dir / "launch_validation_summary.csv", launch_validation_summary_rows, union_fieldnames(launch_validation_summary_rows))
        if launch_validation_rows:
            write_csv(output_dir / "launch_validation.csv", launch_validation_rows, union_fieldnames(launch_validation_rows))
        if scroll_validation_rows:
            write_csv(output_dir / "scroll_validation.csv", scroll_validation_rows, union_fieldnames(scroll_validation_rows))
        if memory_validation_rows:
            write_csv(output_dir / "memory_validation.csv", memory_validation_rows, union_fieldnames(memory_validation_rows))
        if launch_gap_rows:
            write_csv(output_dir / "launch_gap_sweep.csv", launch_gap_rows, list(launch_gap_rows[0].keys()))
            write_csv(output_dir / "gap_sweep_validation.csv", launch_gap_rows, list(launch_gap_rows[0].keys()))
        if scroll_gap_rows:
            write_csv(output_dir / "scroll_gap_sweep.csv", scroll_gap_rows, list(scroll_gap_rows[0].keys()))
        if memory_gap_rows:
            write_csv(output_dir / "memory_gap_sweep.csv", memory_gap_rows, list(memory_gap_rows[0].keys()))
        write_csv(output_dir / "correlation_points.csv", correlation_rows, [
            "workload", "avg_burst_latency_ms", "throughput_bursts_per_s", "avg_syscalls_per_burst",
            "allocation_volume", "long_tail_share", "file_syscall_intensity"
        ])
        if comparison_rows:
            write_csv(output_dir / "comparison_ratios.csv", comparison_rows, list(comparison_rows[0].keys()))
        (output_dir / "report.md").write_text(report)

    print(report)


if __name__ == "__main__":
    main()
