#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iostream>
#include <linux/perf_event.h>
#include <linux/bpf.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char* PROG_PATH =
    "/sys/fs/bpf/prog_file_stats_tracepoint_raw_syscalls_sys_enter";
static const char* TP_ID_PATH =
    "/sys/kernel/tracing/events/raw_syscalls/sys_enter/id";

static int bpf_obj_get_fd(const char* path) {
    union bpf_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.pathname = reinterpret_cast<uint64_t>(path);
    return syscall(__NR_bpf, BPF_OBJ_GET, &attr, sizeof(attr));
}

static int read_tracepoint_id(const char* path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;

    char buf[64] = {};
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;

    return std::atoi(buf);
}

static int perf_event_open_tracepoint(int tp_id) {
    struct perf_event_attr attr;
    std::memset(&attr, 0, sizeof(attr));
    attr.type = PERF_TYPE_TRACEPOINT;
    attr.size = sizeof(attr);
    attr.config = tp_id;
    attr.sample_period = 1;
    attr.wakeup_events = 1;

    return syscall(__NR_perf_event_open, &attr, -1, 0, -1, 0);
}

int main() {
    int prog_fd = bpf_obj_get_fd(PROG_PATH);
    if (prog_fd < 0) {
        std::cerr << "Failed to open pinned program: " << PROG_PATH
                  << " error=" << std::strerror(errno) << std::endl;
        return 1;
    }

    int tp_id = read_tracepoint_id(TP_ID_PATH);
    if (tp_id < 0) {
        std::cerr << "Failed to read tracepoint id from " << TP_ID_PATH << std::endl;
        return 1;
    }

    int perf_fd = perf_event_open_tracepoint(tp_id);
    if (perf_fd < 0) {
        std::cerr << "perf_event_open failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(perf_fd, PERF_EVENT_IOC_SET_BPF, prog_fd) != 0) {
        std::cerr << "SET_BPF failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    if (ioctl(perf_fd, PERF_EVENT_IOC_ENABLE, 0) != 0) {
        std::cerr << "ENABLE failed: " << std::strerror(errno) << std::endl;
        return 1;
    }

    std::cout << "Attached file-stats program to raw_syscalls:sys_enter" << std::endl;
    std::cout << "Keep this process running." << std::endl;

    while (true) {
        sleep(1000);
    }

    return 0;
}