from .constants import GAP_INVARIANT_PROXIES
from .pipeline import load_runs
from .stats import (
    linear_fit,
    pearson_correlation,
    regression_error,
    safe_float_value,
    spearman_correlation,
)


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


def validation_diagnostic(xs, ys):
    if len(xs) < 2:
        return "insufficient_samples"
    if len(set(ys)) < 2:
        return "constant_target"
    if len(set(xs)) < 2:
        return "constant_proxy"
    return "ok"


def summarize_validation(rows, family, target_field, proxy_fields, gap_ms):
    summary_rows = []
    for proxy_field in proxy_fields:
        xs, ys = collect_valid_rows(rows, target_field, proxy_field)
        diagnostic = validation_diagnostic(xs, ys)
        if diagnostic != "ok":
            summary_rows.append({
                "family": family,
                "gap_ms": f"{gap_ms:.2f}",
                "target_metric": target_field,
                "proxy_metric": proxy_field,
                "sample_count": len(xs),
                "diagnostic_status": diagnostic,
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
            "diagnostic_status": diagnostic,
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


def build_gap_sweep_rows(results_dir, family, target_field, proxy_fields, gaps, episode_rows_by_gap=None):
    rows = []
    for gap_ms in gaps:
        if episode_rows_by_gap is not None and gap_ms in episode_rows_by_gap:
            episode_rows = episode_rows_by_gap[gap_ms]
        else:
            _, _, episode_rows = load_runs(results_dir, gap_ms)
        family_rows = [row for row in episode_rows if row.get("episode_family") == family]
        rows.extend(summarize_validation(family_rows, family, target_field, proxy_fields, gap_ms))
    return rows


def non_informative_target_notes(rows):
    informative_targets = {
        row["target_metric"]
        for row in rows
        if row.get("diagnostic_status", "ok") == "ok"
    }
    target_issues = {}
    for row in rows:
        diagnostic = row.get("diagnostic_status", "ok")
        if diagnostic == "ok":
            continue
        target_issues.setdefault(row["target_metric"], set()).add(diagnostic)

    messages = []
    for target_metric in sorted(target_issues):
        if target_metric in informative_targets:
            continue
        statuses = target_issues[target_metric]
        if statuses == {"constant_target"}:
            reason = "target was constant across all valid samples, so correlation was not meaningful."
        elif statuses == {"constant_proxy"}:
            reason = "every tested proxy was constant across all valid samples."
        elif statuses == {"insufficient_samples"}:
            reason = "fewer than two valid samples were available."
        else:
            reason = "no statistically informative fit was available."
        messages.append(f"- Omitted `{target_metric}`: {reason}")
    return messages


def format_validation_section(title, rows, primary_metric_label):
    lines = [f"## {title}", ""]
    if not rows:
        lines.append("No validated episodes were found for this section.")
        lines.append("")
        return "\n".join(lines)

    informative_rows = [row for row in rows if row.get("diagnostic_status", "ok") == "ok"]
    lines.append(f"Best proxy fits for {primary_metric_label} across the available episodes.")
    lines.append("")
    if informative_rows:
        lines.append("| Gap (ms) | Target | Proxy | N | Pearson r | Spearman r | Slope | Intercept | MAE | RMSE | Diagnostic |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for row in informative_rows:
            lines.append(
                f"| {row['gap_ms']} | {row['target_metric']} | {row['proxy_metric']} | {row['sample_count']} | "
                f"{row['pearson_r']} | {row['spearman_r']} | {row['slope']} | {row['intercept']} | "
                f"{row['mae_ms']} | {row['rmse_ms']} | {row['diagnostic_status']} |"
            )
        lines.append("")
    else:
        lines.append("No statistically informative validation fits were available for this section.")
        lines.append("")

    notes = non_informative_target_notes(rows)
    if notes:
        lines.extend(notes)
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
    lines = [f"## {title}", ""]
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
    lines = ["## Launch Validation Summary", ""]
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
        for label, path, *rest in figure_paths:
            caption = rest[0] if rest else "Compares the selected launch proxy against ground-truth launch time."
            lines.append(f"![{label}]({path})")
            lines.append("")
            lines.append(f"*{caption}*")
            lines.append("")
    return "\n".join(lines)


def gap_recommendation_note(proxy_metric):
    if proxy_metric in GAP_INVARIANT_PROXIES:
        return "proxy is mostly gap-invariant"
    return "proxy meaning changes with burst segmentation"


def format_validation_recommendations_section(title, rows):
    best_rows = best_validation_rows(rows)
    lines = [f"## {title}", ""]
    if not best_rows:
        lines.append("No recommendation rows are available yet.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Target | Recommended Gap (ms) | Best Proxy | Pearson r | Note |")
    lines.append("| --- | ---: | --- | ---: | --- |")
    for row in best_rows:
        lines.append(
            f"| {row['target_metric']} | {row['gap_ms']} | {row['proxy_metric']} | "
            f"{row['pearson_r']} | {gap_recommendation_note(row['proxy_metric'])} |"
        )
    lines.append("")
    return "\n".join(lines)
