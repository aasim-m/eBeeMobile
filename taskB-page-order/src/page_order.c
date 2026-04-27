#include <linux/bpf.h>
#include <stdint.h>
#include <bpf_helpers.h>

DEFINE_BPF_MAP(page_order_hist, ARRAY, uint32_t, uint64_t, 16);

struct mm_page_alloc_args {
    unsigned short common_type;
    unsigned char common_flags;
    unsigned char common_preempt_count;
    int common_pid;
    uint64_t pfn;
    uint32_t order;
    uint32_t pad;
    uint64_t gfp_flags;
    int32_t migratetype;
};

DEFINE_BPF_PROG("tracepoint/kmem/mm_page_alloc", AID_ROOT, AID_SYSTEM, tp_mm_page_alloc)
(struct mm_page_alloc_args *args) {
    uint32_t key = args->order;
    uint64_t one = 1;
    uint64_t *val;

    if (key >= 16) return 1;

    val = bpf_page_order_hist_lookup_elem(&key);
    if (val) {
        __sync_fetch_and_add(val, 1);
    } else {
        bpf_page_order_hist_update_elem(&key, &one, BPF_ANY);
    }

    return 1;
}

LICENSE("GPL");