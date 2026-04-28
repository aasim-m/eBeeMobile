from .metrics import build_episode_rows, compute_burst_metrics, compute_derived_metrics, compute_bursts
from .parsing import (
    load_gfxinfo_ground_truth,
    load_launch_ground_truth,
    load_meminfo_ground_truth,
    parse_alloc_latency,
    parse_file_stats,
    parse_metadata,
    parse_page_order,
    parse_syscall_trace,
)
from .stats import mean, safe_float, stdev


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
    import csv

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

