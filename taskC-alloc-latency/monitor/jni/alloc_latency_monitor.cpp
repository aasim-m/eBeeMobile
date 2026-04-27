#include <cerrno>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <linux/bpf.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char* BPF_MAP_PATH = "/sys/fs/bpf/map_alloc_latency_latency_hist_map";
static constexpr uint32_t NUM_BUCKETS = 8;

static int bpf_obj_get_fd(const char* path) {
    union bpf_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.pathname = reinterpret_cast<uint64_t>(path);
    return syscall(__NR_bpf, BPF_OBJ_GET, &attr, sizeof(attr));
}

static int bpf_lookup_elem_fd(int fd, const void* key, void* value) {
    union bpf_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.map_fd = fd;
    attr.key = reinterpret_cast<uint64_t>(key);
    attr.value = reinterpret_cast<uint64_t>(value);
    return syscall(__NR_bpf, BPF_MAP_LOOKUP_ELEM, &attr, sizeof(attr));
}

int main() {
    const char* labels[NUM_BUCKETS] = {
        "< 1 us",
        "1 - 5 us",
        "5 - 10 us",
        "10 - 50 us",
        "50 - 100 us",
        "100 - 500 us",
        "500 us - 1 ms",
        ">= 1 ms"
    };

    int fd = bpf_obj_get_fd(BPF_MAP_PATH);
    if (fd < 0) {
        std::cerr << "Error: could not open pinned BPF map at " << BPF_MAP_PATH
                  << ": " << std::strerror(errno) << std::endl;
        return 1;
    }

    std::cout << "Page allocation latency histogram" << std::endl;
    std::cout << "Bucket            | Count" << std::endl;
    std::cout << "--------------------------" << std::endl;

    for (uint32_t i = 0; i < NUM_BUCKETS; ++i) {
        uint64_t count = 0;
        if (bpf_lookup_elem_fd(fd, &i, &count) != 0) {
            count = 0;
        }
        std::cout << labels[i] << " | " << count << std::endl;
    }

    close(fd);
    return 0;
}