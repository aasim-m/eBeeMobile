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
        return []

    start_marker = f"WORKLOAD_{metadata.get('workload', '')}_RUN_{metadata.get('run_index', '')}_START"
    end_marker = f"WORKLOAD_{metadata.get('workload', '')}_RUN_{metadata.get('run_index', '')}_END"

    timestamps = []
    marker_start_ts = None
    marker_end_ts = None

    for line in path.read_text(errors="replace").splitlines():
        marker_match = MARKER_RE.search(line)
        if marker_match:
            ts = float(marker_match.group(1))
            marker_text = marker_match.group(2).strip()
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

    return timestamps


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


def load_runs(results_dir, gap_ms):
    runs = {}
    pseudo_requests = []

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
            timestamps = parse_syscall_trace(run_dir / "syscall_trace.txt", metadata)
            bursts = compute_bursts(timestamps, gap_ms)

            workload_elapsed_s = safe_float(metadata, "workload_elapsed_s", 0.0)
            derived = compute_derived_metrics(raw)
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

    return runs, pseudo_requests


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
    lines.append("- `comparison_ratios.csv`: workload-to-workload metric ratios")
    lines.append("- `correlation_points.csv`: compact numeric export for downstream plotting and correlation analysis")
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

    runs, pseudo_requests = load_runs(args.results_dir, args.burst_gap_ms)
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

    report = generate_report(aggregated, comparisons, args.burst_gap_ms)

    if output_dir is not None:
        write_csv(output_dir / "raw_summary.csv", raw_rows, ["workload", "runs"] + list(raw_rows[0].keys())[2:])
        write_csv(output_dir / "derived_metrics.csv", derived_rows, ["workload", "runs"] + list(derived_rows[0].keys())[2:])
        write_csv(output_dir / "burst_summary.csv", burst_rows, ["workload", "runs"] + list(burst_rows[0].keys())[2:])
        write_csv(output_dir / "pseudo_requests.csv", pseudo_requests, [
            "workload", "run", "burst_index", "start_ts", "end_ts", "duration_ms", "syscall_count"
        ])
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
