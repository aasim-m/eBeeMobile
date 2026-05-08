# Device Setup and Troubleshooting

This guide explains how to prepare an Android device for running eBeeMobile experiments.

eBeeMobile requires:

- `adb` access from the host machine
- an authorized Android device
- device-side `su`
- Android eBPF/tracing support
- eBPF object files installed under `/system/etc/bpf/`
- userspace attach, monitor, and reset binaries available on the device

If the phone has been reset, reflashed, or updated, the eBPF objects and pinned maps may need to be restored before experiments can run.

## Common Error

If you see:

```text
Failed to open map: No such file or directory
```

the userspace monitor or reset binary could not find the expected pinned eBPF map. This usually means that the eBPF objects were not installed, Android did not load/pin them, or the attach process is not running.

## 1. Re-enable adb after reset

On the phone:

1. Enable Developer options.
2. Enable USB debugging.
3. Connect the phone to the host.
4. Accept the adb authorization prompt.

Verify the connection:

```bash
adb devices
adb shell
```

If supported by the device image, restart adb as root:

```bash
adb root
```

## 2. Remount `/system` writable

If the device has been reset or reflashed, remount `/system` so the eBPF object files can be restored.

```bash
adb root
adb disable-verity
adb reboot
adb wait-for-device
adb root
adb remount
```

## 3. Install eBPF objects

From the root of the eBeeMobile repository, push the eBPF object files to a temporary location:

```bash
adb push file-stats/file_stats.o /data/local/tmp/
adb push page-order/page_order.o /data/local/tmp/
adb push alloc-latency/alloc_latency.o /data/local/tmp/
```

Copy them into `/system/etc/bpf/`:

```bash
adb shell "su 0 cp /data/local/tmp/file_stats.o /system/etc/bpf/file_stats.o"
adb shell "su 0 cp /data/local/tmp/page_order.o /system/etc/bpf/page_order.o"
adb shell "su 0 cp /data/local/tmp/alloc_latency.o /system/etc/bpf/alloc_latency.o"
```

Adjust the local paths if your eBPF object files are stored elsewhere.

## 4. Reboot and verify BPF entries

Reboot so Android reloads and pins the eBPF objects:

```bash
adb reboot
adb wait-for-device
adb root
```

Verify that the expected BPF entries exist:

```bash
adb shell "su 0 ls -l /sys/fs/bpf | grep -E 'file_stats|page_order|alloc_latency'"
```

If this command prints no matching entries, the eBPF objects were not loaded or pinned correctly.

## 5. Push userspace binaries manually

The experiment runner normally pushes the required binaries automatically. For manual setup or debugging, push them yourself:

```bash
adb push file-stats/attach/libs/arm64-v8a/file_stats_attach /data/local/tmp/
adb push file-stats/monitor/libs/arm64-v8a/file_stats_monitor /data/local/tmp/
adb push file-stats/monitor/libs/arm64-v8a/file_stats_reset /data/local/tmp/

adb push page-order/attach/libs/arm64-v8a/page_order_attach /data/local/tmp/
adb push page-order/monitor/libs/arm64-v8a/page_order_monitor /data/local/tmp/
adb push page-order/monitor/libs/arm64-v8a/page_order_reset /data/local/tmp/

adb push alloc-latency/attach/libs/arm64-v8a/alloc_latency_attach /data/local/tmp/
adb push alloc-latency/monitor/libs/arm64-v8a/alloc_latency_monitor /data/local/tmp/
adb push alloc-latency/monitor/libs/arm64-v8a/alloc_latency_reset /data/local/tmp/

adb shell "su 0 chmod +x /data/local/tmp/*_attach /data/local/tmp/*_monitor /data/local/tmp/*_reset"
```

## 6. Start attachers manually

Use three separate terminals because each attacher must stay running.

Terminal 1:

```bash
adb shell "su 0 /data/local/tmp/file_stats_attach"
```

Terminal 2:

```bash
adb shell "su 0 /data/local/tmp/page_order_attach"
```

Terminal 3:

```bash
adb shell "su 0 /data/local/tmp/alloc_latency_attach"
```

## 7. Run a quick monitor test

In a fourth terminal, reset all maps:

```bash
adb shell "su 0 /data/local/tmp/file_stats_reset"
adb shell "su 0 /data/local/tmp/page_order_reset"
adb shell "su 0 /data/local/tmp/alloc_latency_reset"
```

Run a small Android workload:

```bash
adb shell "am start -W -a android.settings.SETTINGS"
adb shell "input keyevent KEYCODE_HOME"
```

Inspect monitor outputs:

```bash
adb shell "su 0 /data/local/tmp/file_stats_monitor"
adb shell "su 0 /data/local/tmp/page_order_monitor"
adb shell "su 0 /data/local/tmp/alloc_latency_monitor"
```

If the monitors print counters or histograms instead of `Failed to open map`, the device setup is working.

## 8. Run the full experiment script

After the quick test succeeds, run eBeeMobile normally:

```bash
./scripts/run_exploration_experiment.sh --output-dir ./runs --repetitions 10
```

## Troubleshooting

### `Failed to open map: No such file or directory`

Likely causes:

* the phone was reset, reflashed, or updated;
* the eBPF object files are missing from `/system/etc/bpf/`;
* Android did not reload or pin the eBPF objects after reboot;
* the attach process is not running;
* the monitor/reset binary expects a map that was not created.

Fix:

1. Repeat the device setup steps above.
2. Verify `/sys/fs/bpf`.
3. Start the attachers manually.
4. Run the quick monitor test.
5. Then run the full experiment script.

### `adb root` does not work

The device image may not allow root adb. eBeeMobile currently targets controlled research devices where privileged access is available. Without root or `su`, new experiments may not run, although the curated validation artifacts can still be inspected and analyzed.

### Attach process exits immediately

Check that the matching `.o` file exists under `/system/etc/bpf/`, rebooted after installation, and that the userspace binary matches the eBPF object/map names expected by the current build.

### Runner starts but monitor outputs are empty

Confirm that:

* the attachers are still running;
* reset binaries succeed;
* the workload actually executed;
* the BPF maps exist under `/sys/fs/bpf`;
* the correct binaries are being pushed by the runner.