import csv
import re

from .constants import (
    LATENCY_BUCKETS,
    MARKER_RE,
    TIMESTAMP_RE,
    WORKLOAD_C_GFXINFO_FILES,
    WORKLOAD_C_MEMINFO_FILES,
    WORKLOAD_D_MEMINFO_FILES,
)
from .stats import ratio


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
            if not match:
                match = re.search(r"TOTAL SWAP \(KB\):\s+(\d+)", stripped)
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
    match = re.search(r":\s*(-?\d+(?:\.\d+)?)\s*ms\b", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*ms\b", text)
    if match:
        return float(match.group(1))
    return parse_first_float(text)
