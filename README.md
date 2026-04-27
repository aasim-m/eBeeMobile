# eBeeMobile

eBeeMobile is an Android eBPF observability project inspired by eBeeMetrics. It adapts the idea of deriving higher-level performance signals from low-level kernel events to mobile workloads.

It combines existing eBPF probes with an experiment harness and a post-processing pipeline to:

- collect kernel-visible I/O and memory signals during Android workloads
- capture timestamped syscall traces for pseudo-request reconstruction
- segment syscalls into bursts that approximate user interaction episodes
- generate report-ready summaries for workload comparison

## Overview

The central question in eBeeMobile is:

**Can low-overhead eBPF tracing infer higher-level mobile activity cost by quantifying kernel-visible I/O and memory behavior during app launch, interaction, and background execution?**

Workload roles:

- `Workload A`: idle baseline
- `Workload B`: app launch burst
- `Workload C`: browser interaction / scrolling
- `Workload D`: background activity after returning home

Primary comparisons:

- `B vs A`
- `C vs A`

Secondary comparison:

- `B vs C`
- `D vs A`

The project uses the following mapping from eBeeMetrics to Android:

- eBeeMetrics request: `HTTP request`
- eBeeMobile request proxy: `syscall burst`
- eBeeMetrics latency: `request duration`
- eBeeMobile latency proxy: `burst duration`
- eBeeMetrics throughput: `requests/s`
- eBeeMobile throughput proxy: `bursts/s`

## Repository Layout

- `taskA-file-stats/`: Task A eBPF program, attach tool, and monitor/reset binaries for file-operation statistics
- `taskB-page-order/`: Task B eBPF program, attach tool, and monitor/reset binaries for page-allocation order
- `taskC-alloc-latency/`: Task C eBPF program, attach tool, and monitor/reset binaries for allocation-latency histograms
- [run_exploration_experiment.sh](run_exploration_experiment.sh): experiment runner for repeated Android workloads and trace capture
- [analyze_results.py](analyze_results.py): burst segmentation and report generation
- [build_all.sh](build_all.sh): rebuilds the eBPF objects and Android user-space binaries
- `runs/`: generated experiment outputs, optional to version

## Derived Metrics

The analysis pipeline computes higher-level metrics from the existing monitor outputs:

- `File Syscall Intensity` = `openat + read + write`
- `Read Dominance Ratio` = `read / total file syscalls`
- `Write Activity Ratio` = `write / total file syscalls`
- `Allocation Volume` = total page allocations
- `Higher-Order Allocation Share` = `(orders 1-3) / total allocations`
- `Fast Allocation Share` = `(latency buckets <10 us) / total allocations`
- `Slow Allocation Share` = `(latency buckets >=10 us) / total allocations`
- `Long-Tail Share` = `(latency buckets >=50 us) / total allocations`

It also computes eBeeMetrics-style pseudo-request metrics by grouping timestamped syscall events into bursts:

- `Burst Count`
- `Average Burst Latency`
- `P95 Burst Latency`
- `Throughput (bursts/s)`
- `Average Syscalls per Burst`

## Requirements

- `adb` installed on the host
- a connected and authorized Android device
- `su` available on the device
- the bundled Task A, Task B, and Task C binaries present under this repository
- Android NDK installed if you want to rebuild the bundled binaries
- the Android eBPF dependency tree available if you want to rebuild the `.o` eBPF objects

## Building

Rebuild all eBPF objects and Android user-space binaries:

```bash
export ANDROID_NDK_HOME=/path/to/android-ndk
export ANDROID_EBPF_DEPS=/path/to/android-ebpf-deps
./build_all.sh
```

The bundled binaries under `attach/libs/arm64-v8a/` and `monitor/libs/arm64-v8a/` are device-side executables for `arm64-v8a`.

## Running Experiments

Example:

```bash
cd eBeeMobile
./run_exploration_experiment.sh --output-dir ./runs --repetitions 5
```

Optional fixed brightness override:

```bash
./run_exploration_experiment.sh --output-dir ./runs --repetitions 5 --brightness 128
```

Optional workload-tuning overrides:

```bash
./run_exploration_experiment.sh \
  --output-dir ./runs \
  --repetitions 5 \
  --workload-b-browser-component org.chromium.webview_shell/.WebViewBrowserActivity \
  --scroll-url https://www.pexels.com/search/nature/ \
  --page-settle-seconds 5 \
  --browser-clear-packages org.chromium.webview_shell,com.android.chrome
```

The runner:

1. Pushes the existing attach/reset/monitor binaries to `/data/local/tmp/eBeeMobile` on the device.
2. Starts the three attach processes on the device.
3. Normalizes the device state before each run by waking the display, dismissing keyguard, setting a fixed manual brightness, force-stopping workload apps, and returning to the home screen.
4. Clears browser app data before Workloads C and D so the browser-backed content workloads start from a cold-cache state.
5. Repeats Workloads A, B, C, and D for the requested number of runs.
6. Emits top-level and sub-episode trace markers so later analysis can isolate launches, page settling, swipes, and background windows.
7. Resets all maps before each run.
8. Captures a timestamped syscall trace for each run using `raw_syscalls:sys_enter`.
9. Captures monitor outputs into structured host-side directories.
10. Invokes the analysis script to generate report-ready summaries and pseudo-request metrics.

Workload definitions:

- Workload A: idle wait window
- Workload B:
  - `am start -W -a android.settings.SETTINGS`
  - `am start -W -n org.chromium.webview_shell/.WebViewBrowserActivity -d about:blank`
  - `am start -W -n com.android.gallery3d/com.android.gallery3d.app.Gallery`
  - `input keyevent KEYCODE_HOME`
- Workload C:
  - clear browser app data
  - `am start -W -a android.intent.action.VIEW -d https://www.pexels.com/search/nature/`
  - page-settle delay
  - `input swipe 500 1600 500 300 200`
  - inter-swipe pause
  - `input swipe 500 1600 500 300 200`
  - inter-swipe pause
  - `input swipe 500 300 500 1600 200`
- Workload D:
  - clear browser app data
  - `am start -W -a android.intent.action.VIEW -d https://www.pexels.com/search/nature/`
  - page-settle delay
  - `input keyevent KEYCODE_HOME`
  - sleep window for background activity

## Analyzing Results

Any results directory with the following layout can be analyzed:

```text
results/
  workload_a/
    run_01/
      file_stats.txt
      page_order.txt
      alloc_latency.txt
      syscall_trace.txt
      metadata.txt
  workload_b/
    run_01/
      ...
  workload_c/
    run_01/
      ...
  workload_d/
    run_01/
      ...
```

Example using any local results directory:

```bash
python3 analyze_results.py \
  runs/final_burst \
  --output-dir /tmp/android-ebpf-analysis
```

This generates:

- `raw_summary.csv`
- `derived_metrics.csv`
- `comparison_ratios.csv`
- `burst_summary.csv`
- `pseudo_requests.csv`
- `correlation_points.csv`
- `report.md`

## Notes

- The attach processes are designed to stay alive while measurements run. The host runner starts them once and then performs repeated reset / workload / monitor cycles.
- The runner enforces a consistent screen-on, unlocked, fixed-brightness setup for all workloads.
- Workload B stays launch-focused by using `about:blank` for its browser step instead of a live web page.
- Because `about:blank` may not resolve through a generic `VIEW` intent on all devices, Workload B uses a configurable explicit browser component via `--workload-b-browser-component` or `WORKLOAD_B_BROWSER_COMPONENT`.
- Workloads C and D use the same fixed Pexels URL so scrolling and post-home background activity come from one repeatable browser-content source.
- The runner force-stops `com.android.settings`, `com.android.gallery3d`, and the configured browser packages before each run. It also clears browser app data before Workloads C and D so the content loads begin from a cold-cache state.
- The runner writes sub-episode markers into the syscall trace for app launches, page loads, page-settle completion, swipe gestures, return-to-home, and background windows.
- The runner resolves Task A/B/C binary paths relative to this repository by default. If your layout differs, override them with environment variables such as `TASKA_ATTACH`, `TASKA_MONITOR`, and `TASKA_RESET`.
- Workload-tuning options include `--scroll-url`, `--page-settle-seconds`, `--swipe-pause-seconds`, and `--browser-clear-packages`. Equivalent environment variables are `SCROLL_URL` and `BROWSER_CLEAR_PACKAGES`.
- By default, raw generated outputs under `runs/` are best treated as local artifacts unless you intentionally want to publish selected summaries.
- Android background services, charging state, and thermal drift can add noise, so repeated runs and spread-aware reporting are recommended.
- The analysis pipeline makes conservative claims. It reports kernel-side cost signatures associated with activity episodes; it does not claim to measure exact user-perceived latency.
