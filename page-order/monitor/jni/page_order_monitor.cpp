#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <linux/bpf.h>
#include <string>
#include <sys/syscall.h>
#include <unistd.h>

static const char* BPF_MAP_PATH = "/sys/fs/bpf/map_page_order_page_order_hist";
static constexpr uint32_t MAX_ORDER = 15;

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
    int fd = bpf_obj_get_fd(BPF_MAP_PATH);
    if (fd < 0) {
        std::cerr << "Error: could not open pinned BPF map at " << BPF_MAP_PATH
                  << ": " << std::strerror(errno) << std::endl;
        return 1;
    }

    std::cout << "Page allocation order histogram" << std::endl;
    std::cout << "Order | Count" << std::endl;
    std::cout << "----------------" << std::endl;

    for (uint32_t order = 0; order <= MAX_ORDER; ++order) {
        uint64_t count = 0;
        if (bpf_lookup_elem_fd(fd, &order, &count) == 0) {
            std::cout << order << "     | " << count << std::endl;
        } else {
            std::cout << order << "     | 0" << std::endl;
        }
    }

    close(fd);
    return 0;
}