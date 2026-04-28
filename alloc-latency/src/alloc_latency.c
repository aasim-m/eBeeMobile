#include <linux/bpf.h>
#include <stdint.h>
#include <bpf_helpers.h>

DEFINE_BPF_MAP(start_ns_map, HASH, uint32_t, uint64_t, 16384);
DEFINE_BPF_MAP(latency_hist_map, ARRAY, uint32_t, uint64_t, 8);

static __always_inline uint32_t bucket_ns(uint64_t delta) {
    if (delta < 1000ULL) return 0;          // < 1 us
    if (delta < 5000ULL) return 1;          // 1-5 us
    if (delta < 10000ULL) return 2;         // 5-10 us
    if (delta < 50000ULL) return 3;         // 10-50 us
    if (delta < 100000ULL) return 4;        // 50-100 us
    if (delta < 500000ULL) return 5;        // 100-500 us
    if (delta < 1000000ULL) return 6;       // 500 us - 1 ms
    return 7;                               // >= 1 ms
}

DEFINE_BPF_PROG("kprobe/__alloc_pages", AID_ROOT, AID_SYSTEM, kp_alloc_entry)
(void *ctx) {
    uint64_t pid_tgid = bpf_get_current_pid_tgid();
    uint32_t tid = (uint32_t)pid_tgid;
    uint64_t ts = bpf_ktime_get_ns();

    bpf_start_ns_map_update_elem(&tid, &ts, BPF_ANY);
    return 1;
}

DEFINE_BPF_PROG("kretprobe/__alloc_pages", AID_ROOT, AID_SYSTEM, krp_alloc_ret)
(void *ctx) {
    uint64_t pid_tgid = bpf_get_current_pid_tgid();
    uint32_t tid = (uint32_t)pid_tgid;
    uint64_t now = bpf_ktime_get_ns();
    uint64_t *start;
    uint64_t delta;
    uint32_t bucket;
    uint64_t one = 1;
    uint64_t *val;

    start = bpf_start_ns_map_lookup_elem(&tid);
    if (!start) {
        return 1;
    }

    delta = now - *start;
    bucket = bucket_ns(delta);

    val = bpf_latency_hist_map_lookup_elem(&bucket);
    if (val) {
        __sync_fetch_and_add(val, 1);
    } else {
        bpf_latency_hist_map_update_elem(&bucket, &one, BPF_ANY);
    }

    bpf_start_ns_map_delete_elem(&tid);
    return 1;
}

LICENSE("GPL");