from .constants import WORKLOAD_LABELS
from .stats import format_ratio, number, percent, ratio


def format_gap_list(gaps):
    return ", ".join(f"{gap:.2f}" for gap in gaps)


def format_validation_target_guide():
    lines = []
    lines.append("## Validation Target Guide")
    lines.append("")
    lines.append("Primary validation targets used in the current gap sweeps:")
    lines.append("")
    lines.append("- `ground_truth_total_time_ms`: Android `am start -W` `TotalTime`, the end-to-end launch duration reported by ActivityManager.")
    lines.append("- `ground_truth_wait_time_ms`: Android `am start -W` `WaitTime`, the broader launch wait duration including system-side waiting around the start request.")
    lines.append("- `ground_truth_total_frames_rendered`: total frames rendered during the captured `gfxinfo` episode.")
    lines.append("- `ground_truth_janky_frames_pct`: percentage of rendered frames flagged as janky by `dumpsys gfxinfo`.")
    lines.append("- `ground_truth_janky_frames`: raw janky-frame count from `dumpsys gfxinfo`.")
    lines.append("- `ground_truth_frame_p50_ms`, `ground_truth_frame_p90_ms`, `ground_truth_frame_p95_ms`, `ground_truth_frame_p99_ms`: frame-duration percentiles from `dumpsys gfxinfo`.")
    lines.append("- `ground_truth_total_pss_kb`: total proportional set size from `dumpsys meminfo`, used as a coarse memory-footprint target.")
    lines.append("- `ground_truth_total_swap_pss_kb`: total swap-backed proportional set size from `dumpsys meminfo`, used when swap activity is present.")
    lines.append("- `ground_truth_graphics_pss_kb`: graphics-related proportional set size from `dumpsys meminfo`, used as a GPU/UI-memory target.")
    lines.append("- `ground_truth_native_heap_pss_kb`, `ground_truth_dalvik_heap_pss_kb`: heap-specific proportional set size targets from `dumpsys meminfo`.")
    lines.append("")
    lines.append("Additional ground-truth fields exported into episode CSVs:")
    lines.append("")
    lines.append("- Launch: `ground_truth_status`, `ground_truth_launch_state`, `ground_truth_activity`, `ground_truth_this_time_ms`, `ground_truth_error`.")
    lines.append("- Scroll / gfxinfo: `ground_truth_missed_vsync`, `ground_truth_high_input_latency`, `ground_truth_slow_ui_thread`, `ground_truth_slow_bitmap_uploads`, `ground_truth_slow_issue_draw_commands`, `ground_truth_frame_deadline_missed`, `ground_truth_total_viewrootimpl`, `ground_truth_total_attached_views`, `ground_truth_total_rendernode_kb`.")
    lines.append("- Memory / meminfo: `ground_truth_system_pss_kb`, `ground_truth_total_rss_kb`, `ground_truth_views`, `ground_truth_activities`, `ground_truth_webviews`.")
    lines.append("")
    lines.append("Interpretation notes:")
    lines.append("")
    lines.append("- Lower is better for launch times, frame times, jank targets, and memory-footprint targets.")
    lines.append("- Higher is better for `ground_truth_total_frames_rendered` because it usually means more rendering work completed during the episode window.")
    lines.append("- Some targets can be omitted from validation tables when they are constant or missing across the dataset, because correlation would be misleading in that case.")
    lines.append("")
    return "\n".join(lines)


def generate_report(aggregated, comparisons, gap_ms, validation_gaps):
    lines = []
    present_workloads = [name for name in ["workload_a", "workload_b", "workload_c", "workload_d"] if name in aggregated]

    lines.append("# Android eBPF Exploration Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        "This report summarizes two layers of observability from the Android experiment suite. "
        "First, it reports workload-level kernel-visible I/O and memory behavior using the existing file-stats, page-order, and alloc-latency eBPF probes. "
        "Second, it derives pseudo-request metrics by segmenting timestamped syscall events into bursts, following the same high-level idea as eBeeMetrics: infer latency-like and throughput-like metrics from low-level syscall observability."
    )
    lines.append("")
    lines.append(
        f"Default burst segmentation rule for the workload summary tables: a new pseudo-request starts when the gap between syscall events exceeds {gap_ms:.2f} ms. "
        f"Validation sections below also sweep {format_gap_list(validation_gaps)} ms and report the best-fitting gap per target."
    )
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
    lines.append("- `episode_summary.csv`: episode-level proxy and ground-truth rows for validated launch, scroll, and memory episodes")
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
    lines.append("- `figures/`: SVG validation plots when an output directory is provided")
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
    lines.append(format_validation_target_guide())
    lines.append("")

    return "\n".join(lines)
