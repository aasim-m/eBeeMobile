import argparse
from pathlib import Path

from .pipeline import aggregate_runs, build_comparisons, load_runs, union_fieldnames, write_csv
from .plotting import build_family_figures, build_launch_figures, format_figure_gallery
from .reporting import generate_report
from .stats import number, ratio
from .validation import (
    build_episode_validation_rows,
    build_gap_sweep_rows,
    build_launch_validation_summary_rows,
    format_best_validation_section,
    format_launch_summary_section,
    format_validation_recommendations_section,
    format_validation_section,
)


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
    episode_rows_by_gap = {args.burst_gap_ms: episode_rows}
    for gap_ms in validation_gaps:
        if gap_ms in episode_rows_by_gap:
            continue
        _, _, gap_episode_rows = load_runs(args.results_dir, gap_ms)
        episode_rows_by_gap[gap_ms] = gap_episode_rows

    launch_gap_rows = []
    launch_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "launch", "ground_truth_total_time_ms", launch_proxy_fields, validation_gaps, episode_rows_by_gap))
    launch_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "launch", "ground_truth_wait_time_ms", launch_proxy_fields, validation_gaps, episode_rows_by_gap))
    launch_validation_summary_rows = build_launch_validation_summary_rows(launch_gap_rows)

    scroll_gap_rows = []
    for target in [
        "ground_truth_total_frames_rendered",
        "ground_truth_janky_frames",
        "ground_truth_janky_frames_pct",
        "ground_truth_frame_p50_ms",
        "ground_truth_frame_p90_ms",
        "ground_truth_frame_p95_ms",
        "ground_truth_frame_p99_ms",
    ]:
        scroll_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "scroll", target, scroll_proxy_fields, validation_gaps, episode_rows_by_gap))

    memory_gap_rows = []
    for target in [
        "ground_truth_total_pss_kb",
        "ground_truth_total_swap_pss_kb",
        "ground_truth_graphics_pss_kb",
        "ground_truth_native_heap_pss_kb",
        "ground_truth_dalvik_heap_pss_kb",
    ]:
        memory_gap_rows.extend(build_gap_sweep_rows(args.results_dir, "memory", target, memory_proxy_fields, validation_gaps, episode_rows_by_gap))

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

    launch_figure_paths = []
    scroll_figure_paths = []
    memory_figure_paths = []
    if output_dir is not None and launch_gap_rows:
        launch_figure_paths = build_launch_figures(output_dir, args.results_dir, launch_gap_rows, episode_rows_by_gap)
    if output_dir is not None and scroll_gap_rows:
        scroll_figure_paths = build_family_figures(output_dir, args.results_dir, "scroll", "Scroll", scroll_gap_rows, episode_rows_by_gap)
    if output_dir is not None and memory_gap_rows:
        memory_figure_paths = build_family_figures(output_dir, args.results_dir, "memory", "Memory", memory_gap_rows, episode_rows_by_gap)

    report = generate_report(aggregated, comparisons, args.burst_gap_ms, validation_gaps)
    if launch_validation_summary_rows:
        report += "\n" + format_launch_summary_section(launch_validation_summary_rows, launch_figure_paths)
    if launch_gap_rows:
        report += "\n" + format_validation_recommendations_section("Launch Validation Recommendations", launch_gap_rows)
        report += "\n" + format_best_validation_section("Launch Validation Best Fits", launch_gap_rows)
        report += "\n" + format_validation_section("Launch Validation", launch_gap_rows, "launch latency")
    if scroll_gap_rows:
        report += "\n" + format_validation_recommendations_section("Scroll Validation Recommendations", scroll_gap_rows)
        report += "\n" + format_best_validation_section("Scroll Validation Best Fits", scroll_gap_rows)
        if scroll_figure_paths:
            report += "\n" + format_figure_gallery("Scroll validation figures", scroll_figure_paths)
        report += "\n" + format_validation_section("Scroll Validation", scroll_gap_rows, "scroll responsiveness")
    if memory_gap_rows:
        report += "\n" + format_validation_recommendations_section("Memory Validation Recommendations", memory_gap_rows)
        report += "\n" + format_best_validation_section("Memory Validation Best Fits", memory_gap_rows)
        if memory_figure_paths:
            report += "\n" + format_figure_gallery("Memory validation figures", memory_figure_paths)
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

