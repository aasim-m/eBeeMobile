#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${ROOT_DIR}/runs/$(date +%Y%m%d_%H%M%S)"
REPETITIONS=5
IDLE_SECONDS=10
BACKGROUND_SECONDS=20
SETTLE_SECONDS=2
PAGE_SETTLE_SECONDS=5
SWIPE_PAUSE_SECONDS=1
SCREEN_BRIGHTNESS=128
DEVICE_DIR="/data/local/tmp/eBeeMobile"
TRACEFS_DIR="/sys/kernel/tracing"
BURST_GAP_MS=5
TRACE_BUFFER_KB=65536
WORKLOAD_B_BROWSER_URL="about:blank"
WORKLOAD_B_BROWSER_COMPONENT="${WORKLOAD_B_BROWSER_COMPONENT:-org.chromium.webview_shell/.WebViewBrowserActivity}"
SCROLL_URL="${SCROLL_URL:-https://www.pexels.com/search/nature/}"
BROWSER_CLEAR_PACKAGES="${BROWSER_CLEAR_PACKAGES:-org.chromium.webview_shell,com.android.chrome,com.google.android.apps.chrome}"

usage() {
  cat <<'EOF'
Usage:
  run_exploration_experiment.sh [--output-dir DIR] [--repetitions N] [--idle-seconds N]

Options:
  --output-dir DIR     Host-side directory for collected results
  --repetitions N      Number of repetitions per workload (default: 5)
  --idle-seconds N     Idle duration for Workload A (default: 10)
  --background-seconds N  Background duration for Workload D (default: 20)
  --page-settle-seconds N  Post-page-load settle time for Workloads C/D (default: 5)
  --swipe-pause-seconds N  Pause between swipe gestures in Workload C (default: 1)
  --brightness N       Manual screen brightness 0-255 (default: 128)
  --workload-b-browser-component CMP  Explicit browser component for Workload B about:blank launch
  --scroll-url URL     Scrollable URL for Workloads C/D (default: Pexels nature search)
  --browser-clear-packages CSV  Comma-separated browser packages to clear before Workloads C/D
  --device-dir DIR     Device-side staging directory
  --help               Show this message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --repetitions)
      REPETITIONS="$2"
      shift 2
      ;;
    --idle-seconds)
      IDLE_SECONDS="$2"
      shift 2
      ;;
    --background-seconds)
      BACKGROUND_SECONDS="$2"
      shift 2
      ;;
    --page-settle-seconds)
      PAGE_SETTLE_SECONDS="$2"
      shift 2
      ;;
    --swipe-pause-seconds)
      SWIPE_PAUSE_SECONDS="$2"
      shift 2
      ;;
    --brightness)
      SCREEN_BRIGHTNESS="$2"
      shift 2
      ;;
    --workload-b-browser-component)
      WORKLOAD_B_BROWSER_COMPONENT="$2"
      shift 2
      ;;
    --scroll-url)
      SCROLL_URL="$2"
      shift 2
      ;;
    --browser-clear-packages)
      BROWSER_CLEAR_PACKAGES="$2"
      shift 2
      ;;
    --device-dir)
      DEVICE_DIR="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

IFS=',' read -r -a BROWSER_CLEAR_PACKAGES_ARR <<< "${BROWSER_CLEAR_PACKAGES}"
for idx in "${!BROWSER_CLEAR_PACKAGES_ARR[@]}"; do
  BROWSER_CLEAR_PACKAGES_ARR[$idx]="$(trim_whitespace "${BROWSER_CLEAR_PACKAGES_ARR[$idx]}")"
done

TASKA_ATTACH="${TASKA_ATTACH:-${ROOT_DIR}/taskA-file-stats/attach/libs/arm64-v8a/file_stats_attach}"
TASKA_MONITOR="${TASKA_MONITOR:-${ROOT_DIR}/taskA-file-stats/monitor/libs/arm64-v8a/file_stats_monitor}"
TASKA_RESET="${TASKA_RESET:-${ROOT_DIR}/taskA-file-stats/monitor/libs/arm64-v8a/file_stats_reset}"

TASKB_ATTACH="${TASKB_ATTACH:-${ROOT_DIR}/taskB-page-order/attach/libs/arm64-v8a/page_order_attach}"
TASKB_MONITOR="${TASKB_MONITOR:-${ROOT_DIR}/taskB-page-order/monitor/libs/arm64-v8a/page_order_monitor}"
TASKB_RESET="${TASKB_RESET:-${ROOT_DIR}/taskB-page-order/monitor/libs/arm64-v8a/page_order_reset}"

TASKC_ATTACH="${TASKC_ATTACH:-${ROOT_DIR}/taskC-alloc-latency/attach/libs/arm64-v8a/alloc_latency_attach}"
TASKC_MONITOR="${TASKC_MONITOR:-${ROOT_DIR}/taskC-alloc-latency/monitor/libs/arm64-v8a/alloc_latency_monitor}"
TASKC_RESET="${TASKC_RESET:-${ROOT_DIR}/taskC-alloc-latency/monitor/libs/arm64-v8a/alloc_latency_reset}"

require_host_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required host binary: $path" >&2
    exit 1
  fi
}

for path in \
  "$TASKA_ATTACH" "$TASKA_MONITOR" "$TASKA_RESET" \
  "$TASKB_ATTACH" "$TASKB_MONITOR" "$TASKB_RESET" \
  "$TASKC_ATTACH" "$TASKC_MONITOR" "$TASKC_RESET"; do
  require_host_file "$path"
done

run_adb() {
  adb "$@"
}

run_root_shell() {
  local cmd="$1"
  local escaped_cmd=${cmd//\'/\'\\\'\'}
  run_adb shell "su 0 sh -c '$escaped_cmd'"
}

run_device_shell() {
  local cmd="$1"
  run_adb shell "sh -c '$cmd'"
}

run_device_shell_capture() {
  local cmd="$1"
  run_adb shell "sh -c '$cmd'"
}

push_binary() {
  local src="$1"
  local dst="$2"
  run_adb push "$src" "$dst" >/dev/null
  run_root_shell "chmod 755 $dst"
}

start_attach() {
  local name="$1"
  local binary="$2"
  local binary_name
  local log_path="${binary}.log"
  local rc

  binary_name="$(basename "$binary")"

  echo "Launching attach process: ${name}"
  run_root_shell "pkill -x $binary_name >/dev/null 2>&1 || true"

  set +e
  run_root_shell "sh -c '$binary > $log_path 2>&1 </dev/null &'"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    echo "Attach launch command failed for ${name}" >&2
    echo "Attach command exit code: $rc" >&2
    exit 1
  fi

  sleep 1

  if ! run_root_shell "pidof $binary >/dev/null 2>&1 || pgrep -f $binary >/dev/null 2>&1"; then
    echo "Failed to start attach process: ${name}" >&2
    echo "Device log for ${name}:" >&2
    run_root_shell "test -f $log_path && cat $log_path || echo '<no log output>'" >&2
    exit 1
  fi

  echo "Started attach process: ${name}"
}

reset_maps() {
  run_root_shell "${DEVICE_DIR}/file_stats_reset"
  run_root_shell "${DEVICE_DIR}/page_order_reset"
  run_root_shell "${DEVICE_DIR}/alloc_latency_reset"
}

capture_monitors() {
  local outdir="$1"
  run_adb exec-out "su 0 sh -c '${DEVICE_DIR}/file_stats_monitor'" > "${outdir}/file_stats.txt"
  run_adb exec-out "su 0 sh -c '${DEVICE_DIR}/page_order_monitor'" > "${outdir}/page_order.txt"
  run_adb exec-out "su 0 sh -c '${DEVICE_DIR}/alloc_latency_monitor'" > "${outdir}/alloc_latency.txt"
}

set_device_brightness() {
  run_device_shell "settings put system screen_brightness_mode 0"
  run_device_shell "settings put system screen_brightness ${SCREEN_BRIGHTNESS}"
}

ensure_screen_on_and_unlocked() {
  run_device_shell "input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true"
  run_device_shell "wm dismiss-keyguard >/dev/null 2>&1 || true"
  run_device_shell "input keyevent KEYCODE_MENU >/dev/null 2>&1 || true"
  sleep 1
}

reset_to_home() {
  run_device_shell "input keyevent KEYCODE_HOME"
  sleep "${SETTLE_SECONDS}"
}

force_stop_browser_apps() {
  local pkg
  for pkg in "${BROWSER_CLEAR_PACKAGES_ARR[@]}"; do
    [[ -z "${pkg}" ]] && continue
    run_device_shell "am force-stop ${pkg} >/dev/null 2>&1 || true"
  done
}

force_stop_workload_apps() {
  local pkg
  for pkg in com.android.settings com.android.gallery3d; do
    run_device_shell "am force-stop ${pkg} >/dev/null 2>&1 || true"
  done
  force_stop_browser_apps
  sleep 1
}

clear_browser_app_data() {
  local pkg
  for pkg in "${BROWSER_CLEAR_PACKAGES_ARR[@]}"; do
    [[ -z "${pkg}" ]] && continue
    run_device_shell_capture "pm clear ${pkg} >/dev/null 2>&1 || true" >/dev/null
  done
  sleep 1
}

normalize_device_state() {
  ensure_screen_on_and_unlocked
  set_device_brightness
  force_stop_workload_apps
  reset_to_home
}

prepare_workload_state() {
  local workload="$1"
  case "$workload" in
    workload_c|workload_d)
      echo "Resetting browser state for ${workload}"
      clear_browser_app_data
      force_stop_browser_apps
      reset_to_home
      ;;
  esac
}

prepare_syscall_trace() {
  run_root_shell "echo 0 > ${TRACEFS_DIR}/tracing_on"
  run_root_shell "echo ${TRACE_BUFFER_KB} > ${TRACEFS_DIR}/buffer_size_kb"
  run_root_shell "echo nop > ${TRACEFS_DIR}/current_tracer"
  run_root_shell ": > ${TRACEFS_DIR}/trace"
  run_root_shell ": > ${TRACEFS_DIR}/events/raw_syscalls/sys_enter/filter"
  run_root_shell "echo 'id == 56 || id == 63 || id == 64' > ${TRACEFS_DIR}/events/raw_syscalls/sys_enter/filter"
  run_root_shell "echo 1 > ${TRACEFS_DIR}/events/raw_syscalls/sys_enter/enable"
  run_root_shell "echo 1 > ${TRACEFS_DIR}/tracing_on"
}

cleanup_syscall_trace() {
  run_root_shell "echo 0 > ${TRACEFS_DIR}/events/raw_syscalls/sys_enter/enable"
  run_root_shell "echo 0 > ${TRACEFS_DIR}/tracing_on"
  run_root_shell ": > ${TRACEFS_DIR}/events/raw_syscalls/sys_enter/filter"
}

start_syscall_trace_capture() {
  prepare_syscall_trace
}

stop_syscall_trace_capture() {
  cleanup_syscall_trace
}

dump_syscall_trace() {
  local outfile="$1"
  run_adb exec-out "su 0 sh -c 'cat ${TRACEFS_DIR}/trace'" > "$outfile"
}

write_trace_marker() {
  local marker="$1"
  run_root_shell "echo ${marker} > ${TRACEFS_DIR}/trace_marker"
}

write_substep_marker() {
  local workload="$1"
  local run="$2"
  local marker="$3"
  write_trace_marker "WORKLOAD_${workload}_RUN_${run}_${marker}"
}

write_run_metadata() {
  local outdir="$1"
  local workload_name="$2"
  local start_ts="$3"
  local end_ts="$4"
  local elapsed="$5"

  cat > "${outdir}/metadata.txt" <<EOF
workload=${workload_name}
start_epoch_s=${start_ts}
end_epoch_s=${end_ts}
workload_elapsed_s=${elapsed}
burst_gap_ms=${BURST_GAP_MS}
EOF
}

run_marked_device_command() {
  local workload="$1"
  local run="$2"
  local marker_prefix="$3"
  local cmd="$4"

  write_substep_marker "$workload" "$run" "${marker_prefix}_START"
  run_device_shell "$cmd"
  write_substep_marker "$workload" "$run" "${marker_prefix}_END"
}

run_workload() {
  local workload="$1"
  local run="$2"
  case "$workload" in
    workload_a)
      run_device_shell "input keyevent KEYCODE_HOME; sleep ${IDLE_SECONDS}"
      ;;
    workload_b)
      run_marked_device_command "$workload" "$run" "SETTINGS_LAUNCH" \
        "am start -W -a android.settings.SETTINGS"
      sleep "${SETTLE_SECONDS}"
      run_marked_device_command "$workload" "$run" "BROWSER_LAUNCH" \
        "am start -W -n ${WORKLOAD_B_BROWSER_COMPONENT} -d ${WORKLOAD_B_BROWSER_URL}"
      sleep "${SETTLE_SECONDS}"
      run_marked_device_command "$workload" "$run" "GALLERY_LAUNCH" \
        "am start -W -n com.android.gallery3d/com.android.gallery3d.app.Gallery"
      sleep "${SETTLE_SECONDS}"
      run_marked_device_command "$workload" "$run" "RETURN_HOME" \
        "input keyevent KEYCODE_HOME"
      ;;
    workload_c)
      run_marked_device_command "$workload" "$run" "PAGE_LOAD" \
        "am start -W -a android.intent.action.VIEW -d ${SCROLL_URL}"
      sleep "${PAGE_SETTLE_SECONDS}"
      write_substep_marker "$workload" "$run" "PAGE_SETTLED"
      run_marked_device_command "$workload" "$run" "SWIPE_1" \
        "input swipe 500 1600 500 300 200"
      sleep "${SWIPE_PAUSE_SECONDS}"
      run_marked_device_command "$workload" "$run" "SWIPE_2" \
        "input swipe 500 1600 500 300 200"
      sleep "${SWIPE_PAUSE_SECONDS}"
      run_marked_device_command "$workload" "$run" "SWIPE_3" \
        "input swipe 500 300 500 1600 200"
      ;;
    workload_d)
      run_marked_device_command "$workload" "$run" "PAGE_LOAD" \
        "am start -W -a android.intent.action.VIEW -d ${SCROLL_URL}"
      sleep "${PAGE_SETTLE_SECONDS}"
      write_substep_marker "$workload" "$run" "PAGE_SETTLED"
      run_marked_device_command "$workload" "$run" "RETURN_HOME" \
        "input keyevent KEYCODE_HOME"
      write_substep_marker "$workload" "$run" "BACKGROUND_WINDOW_START"
      sleep "${BACKGROUND_SECONDS}"
      write_substep_marker "$workload" "$run" "BACKGROUND_WINDOW_END"
      ;;
    *)
      echo "Unknown workload: $workload" >&2
      exit 1
      ;;
  esac
}

mkdir -p "$OUTPUT_DIR"

echo "Checking adb connectivity..."
run_adb devices

echo "Preparing device directory: ${DEVICE_DIR}"
run_root_shell "mkdir -p ${DEVICE_DIR}"

echo "Normalizing device UI state..."
normalize_device_state

echo "Pushing binaries..."
push_binary "$TASKA_ATTACH" "${DEVICE_DIR}/file_stats_attach"
push_binary "$TASKA_MONITOR" "${DEVICE_DIR}/file_stats_monitor"
push_binary "$TASKA_RESET" "${DEVICE_DIR}/file_stats_reset"
push_binary "$TASKB_ATTACH" "${DEVICE_DIR}/page_order_attach"
push_binary "$TASKB_MONITOR" "${DEVICE_DIR}/page_order_monitor"
push_binary "$TASKB_RESET" "${DEVICE_DIR}/page_order_reset"
push_binary "$TASKC_ATTACH" "${DEVICE_DIR}/alloc_latency_attach"
push_binary "$TASKC_MONITOR" "${DEVICE_DIR}/alloc_latency_monitor"
push_binary "$TASKC_RESET" "${DEVICE_DIR}/alloc_latency_reset"

echo "Starting attachers..."
start_attach "Task A" "${DEVICE_DIR}/file_stats_attach"
start_attach "Task B" "${DEVICE_DIR}/page_order_attach"
start_attach "Task C" "${DEVICE_DIR}/alloc_latency_attach"

for workload in workload_a workload_b workload_c workload_d; do
  for run in $(seq 1 "$REPETITIONS"); do
    run_dir="${OUTPUT_DIR}/${workload}/run_$(printf '%02d' "$run")"
    mkdir -p "$run_dir"

    echo "Collecting ${workload} run $(printf '%02d' "$run")"
    normalize_device_state
    prepare_workload_state "$workload"
    reset_maps
    sleep 1
    start_syscall_trace_capture
    start_ts="$(date +%s.%N)"
    write_trace_marker "WORKLOAD_${workload}_RUN_${run}_START"
    run_workload "$workload" "$run"
    write_trace_marker "WORKLOAD_${workload}_RUN_${run}_END"
    sleep "${SETTLE_SECONDS}"
    end_ts="$(date +%s.%N)"
    elapsed_s="$(python3 - <<PY
start = float("${start_ts}")
end = float("${end_ts}")
print(f"{end - start:.6f}")
PY
)"
    stop_syscall_trace_capture
    capture_monitors "$run_dir"
    dump_syscall_trace "${run_dir}/syscall_trace.txt"
    write_run_metadata "$run_dir" "$workload" "$start_ts" "$end_ts" "$elapsed_s"
  done
done

echo "Analyzing results..."
python3 "${ROOT_DIR}/analyze_results.py" "$OUTPUT_DIR" --output-dir "$OUTPUT_DIR" --burst-gap-ms "$BURST_GAP_MS"

echo "Experiment complete."
echo "Results directory: ${OUTPUT_DIR}"
