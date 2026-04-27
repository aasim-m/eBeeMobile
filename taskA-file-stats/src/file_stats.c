#include <linux/bpf.h>
#include <stdint.h>
#include <bpf_helpers.h>

DEFINE_BPF_MAP(file_op_stats_map, ARRAY, uint32_t, uint64_t, 3);

/*
 * raw_syscalls:sys_enter
 *
 * Common format on arm64:
 *   common trace header
 *   long id
 *   unsigned long args[6]
 *
 * We only need id.
 */
struct raw_syscalls_sys_enter_args {
    unsigned short common_type;
    unsigned char common_flags;
    unsigned char common_preempt_count;
    int common_pid;
    long id;
    unsigned long args[6];
};

static __always_inline void inc_counter(uint32_t key) {
    uint64_t one = 1;
    uint64_t *val = bpf_file_op_stats_map_lookup_elem(&key);

    if (val) {
        __sync_fetch_and_add(val, 1);
    } else {
        bpf_file_op_stats_map_update_elem(&key, &one, BPF_ANY);
    }
}

DEFINE_BPF_PROG("tracepoint/raw_syscalls/sys_enter", AID_ROOT, AID_SYSTEM, tp_sys_enter)
(struct raw_syscalls_sys_enter_args *ctx) {
    /*
     * arm64 syscall numbers:
     * openat = 56
     * read   = 63
     * write  = 64
     */
    if (ctx->id == 56) {
        inc_counter(0);
    } else if (ctx->id == 63) {
        inc_counter(1);
    } else if (ctx->id == 64) {
        inc_counter(2);
    }

    return 1;
}

LICENSE("GPL");