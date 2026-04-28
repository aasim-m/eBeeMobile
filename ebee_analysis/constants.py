import re


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

WORKLOAD_B_EPISODE_MARKERS = {
    "settings_launch": ("SETTINGS_LAUNCH_START", "SETTINGS_LAUNCH_END"),
    "browser_launch": ("BROWSER_LAUNCH_START", "BROWSER_LAUNCH_END"),
    "gallery_launch": ("GALLERY_LAUNCH_START", "GALLERY_LAUNCH_END"),
}

WORKLOAD_C_EPISODE_MARKERS = {
    "page_load": ("PAGE_LOAD_START", "PAGE_SETTLED"),
    "swipe_1": ("SWIPE_1_START", "SWIPE_1_END"),
    "swipe_2": ("SWIPE_2_START", "SWIPE_2_END"),
    "swipe_3": ("SWIPE_3_START", "SWIPE_3_END"),
}

WORKLOAD_C_GFXINFO_FILES = {
    "page_load": "ground_truth_page_load_gfxinfo.txt",
    "swipe_1": "ground_truth_swipe_1_gfxinfo.txt",
    "swipe_2": "ground_truth_swipe_2_gfxinfo.txt",
    "swipe_3": "ground_truth_swipe_3_gfxinfo.txt",
}

WORKLOAD_C_MEMINFO_FILES = {
    "page_load": "ground_truth_page_load_meminfo.txt",
    "swipe_1": "ground_truth_swipe_1_meminfo.txt",
    "swipe_2": "ground_truth_swipe_2_meminfo.txt",
    "swipe_3": "ground_truth_swipe_3_meminfo.txt",
}

WORKLOAD_D_EPISODE_MARKERS = {
    "background_window": ("BACKGROUND_WINDOW_START", "BACKGROUND_WINDOW_END"),
}

WORKLOAD_D_GFXINFO_FILES = {
    "background_window": "ground_truth_background_gfxinfo.txt",
}

WORKLOAD_D_MEMINFO_FILES = {
    "background_window": "ground_truth_background_meminfo.txt",
}

GAP_INVARIANT_PROXIES = {
    "episode_elapsed_s",
    "trace_event_count",
    "allocation_volume",
    "higher_order_allocation_share",
    "slow_allocation_share",
    "long_tail_share",
    "file_syscall_intensity",
}

