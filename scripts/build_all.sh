#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NDK_ROOT="${NDK:-${ANDROID_NDK_HOME:-}}"
DEPS_ROOT="${DEPS:-${ANDROID_EBPF_DEPS:-}}"

if [[ -z "${NDK_ROOT}" ]]; then
  echo "Set NDK or ANDROID_NDK_HOME to your Android NDK root." >&2
  exit 1
fi

if [[ -z "${DEPS_ROOT}" ]]; then
  echo "Set DEPS or ANDROID_EBPF_DEPS to your android-ebpf-deps root." >&2
  exit 1
fi

NDK_BUILD="${NDK_ROOT}/ndk-build"
if [[ ! -x "${NDK_BUILD}" ]]; then
  echo "Could not find ndk-build at ${NDK_BUILD}" >&2
  exit 1
fi

build_task() {
  local task_dir="$1"
  echo "Building ${task_dir##*/} eBPF object..."
  make -C "${task_dir}" NDK="${NDK_ROOT}" DEPS="${DEPS_ROOT}"

  echo "Building ${task_dir##*/} attach binary..."
  (
    cd "${task_dir}/attach/jni"
    "${NDK_BUILD}"
  )

  echo "Building ${task_dir##*/} monitor/reset binaries..."
  (
    cd "${task_dir}/monitor/jni"
    "${NDK_BUILD}"
  )
}

build_task "${ROOT_DIR}/file-stats"
build_task "${ROOT_DIR}/page-order"
build_task "${ROOT_DIR}/alloc-latency"

echo "Build complete."
