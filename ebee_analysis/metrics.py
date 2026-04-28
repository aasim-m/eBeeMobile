from .constants import (
    WORKLOAD_B_EPISODE_MARKERS,
    WORKLOAD_C_EPISODE_MARKERS,
    WORKLOAD_D_EPISODE_MARKERS,
)
from .stats import mean, percentile, ratio, safe_float


def build_episode_rows(
    workload_name,
    run_name,
    run_index,
    timestamps,
    markers,
    gap_ms,
    launch_ground_truth,
    gfxinfo_ground_truth,
    meminfo_ground_truth,
    derived_metrics,
):
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


def compute_derived_metrics(raw):
    total_file = raw["openat"] + raw["read"] + raw["write"]
    allocation_volume = sum(raw[f"order_{i}"] for i in range(16))
    higher_order = sum(raw[f"order_{i}"] for i in range(1, 4))
    fast_alloc = raw["latency_bucket_0"] + raw["latency_bucket_1"] + raw["latency_bucket_2"]
    slow_alloc = allocation_volume - fast_alloc
    long_tail = (
        raw["latency_bucket_4"]
        + raw["latency_bucket_5"]
        + raw["latency_bucket_6"]
        + raw["latency_bucket_7"]
    )
    return {
        "file_syscall_intensity": total_file,
        "read_dominance_ratio": ratio(raw["read"], total_file),
        "write_activity_ratio": ratio(raw["write"], total_file),
        "allocation_volume": allocation_volume,
        "higher_order_allocation_share": ratio(higher_order, allocation_volume),
        "fast_allocation_share": ratio(fast_alloc, allocation_volume),
        "slow_allocation_share": ratio(slow_alloc, allocation_volume),
        "long_tail_share": ratio(long_tail, allocation_volume),
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

