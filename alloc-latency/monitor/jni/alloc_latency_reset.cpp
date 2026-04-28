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

static int bpf_update_elem_fd(int fd, const void* key, const void* value) {
    union bpf_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.map_fd = fd;
    attr.key = reinterpret_cast<uint64_t>(key);
    attr.value = reinterpret_cast<uint64_t>(value);
    attr.flags = BPF_ANY;
    return syscall(__NR_bpf, BPF_MAP_UPDATE_ELEM, &attr, sizeof(attr));
}

int main() {
    int fd = bpf_obj_get_fd(BPF_MAP_PATH);
    if (fd < 0) {
        std::cerr << "Failed to open map: " << std::strerror(errno) << std::endl;
        return 1;
    }

    for (uint32_t i = 0; i < NUM_BUCKETS; ++i) {
        uint64_t zero = 0;
        if (bpf_update_elem_fd(fd, &i, &zero) != 0) {
            std::cerr << "Failed to reset bucket " << i << ": "
                      << std::strerror(errno) << std::endl;
            close(fd);
            return 1;
        }
    }

    std::cout << "Latency histogram reset complete." << std::endl;
    close(fd);
    return 0;
}