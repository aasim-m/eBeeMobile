#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <linux/perf_event.h>
#include <linux/bpf.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char* ENTRY_PROG_PATH =
    "/sys/fs/bpf/prog_alloc_latency_kprobe___alloc_pages";
static const char* RET_PROG_PATH =
    "/sys/fs/bpf/prog_alloc_latency_kretprobe___alloc_pages";

static const char* KPROBE_TYPE_PATH =
    "/sys/bus/event_source/devices/kprobe/type";

static const char* TARGET_FUNC = "__alloc_pages";

static int bpf_obj_get_fd(const char* path) {
    union bpf_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.pathname = reinterpret_cast<uint64_t>(path);
    return syscall(__NR_bpf, BPF_OBJ_GET, &attr, sizeof(attr));
}

static int read_int_file(const char* path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;

    char buf[64] = {};
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;

    return std::atoi(buf);
}

static int perf_event_open_kprobe(int pmu_type, const char* func, bool retprobe) {
    struct perf_event_attr attr;
    std::memset(&attr, 0, sizeof(attr));

    attr.type = pmu_type;
    attr.size = sizeof(attr);
    attr.config = retprobe ? 1 : 0; // bit 0 = retprobe
    attr.sample_period = 1;
    attr.wakeup_events = 1;

    // For dynamic PMU kprobe
    attr.config1 = reinterpret_cast<uint64_t>(func);
    attr.config2 = 0; // probe offset

    return syscall(__NR_perf_event_open, &attr, -1, 0, -1, 0);
}

int main() {
    int entry_prog_fd = bpf_obj_get_fd(ENTRY_PROG_PATH);
    if (entry_prog_fd < 0) {
        std::cerr << "Failed to open entry program: " << ENTRY_PROG_PATH
                  << " error=" << std::strerror(errno) << std::endl;
        return 1;
    }

    int ret_prog_fd = bpf_obj_get_fd(RET_PROG_PATH);
    if (ret_prog_fd < 0) {
        std::cerr << "Failed to open return program: " << RET_PROG_PATH
                  << " error=" << std::strerror(errno) << std::endl;
        return 1;
    }

    int pmu_type = read_int_file(KPROBE_TYPE_PATH);
    if (pmu_type < 0) {
        std::cerr << "Failed to read kprobe PMU type from " << KPROBE_TYPE_PATH
                  << std::endl;
        return 1;
    }

    int entry_perf_fd = perf_event_open_kprobe(pmu_type, TARGET_FUNC, false);
    if (entry_perf_fd < 0) {
        std::cerr << "perf_event_open entry failed: "
                  << std::strerror(errno) << std::endl;
        return 1;
    }

    int ret_perf_fd = perf_event_open_kprobe(pmu_type, TARGET_FUNC, true);
    if (ret_perf_fd < 0) {
        std::cerr << "perf_event_open return failed: "
                  << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(entry_perf_fd, PERF_EVENT_IOC_SET_BPF, entry_prog_fd) != 0) {
        std::cerr << "SET_BPF entry failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(ret_perf_fd, PERF_EVENT_IOC_SET_BPF, ret_prog_fd) != 0) {
        std::cerr << "SET_BPF return failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(entry_perf_fd, PERF_EVENT_IOC_ENABLE, 0) != 0) {
        std::cerr << "ENABLE entry failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(ret_perf_fd, PERF_EVENT_IOC_ENABLE, 0) != 0) {
        std::cerr << "ENABLE return failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    std::cout << "Attached kprobe and kretprobe to " << TARGET_FUNC << std::endl;
    std::cout << "Keep this process running." << std::endl;

    while (true) {
        sleep(1000);
    }

    return 0;
}