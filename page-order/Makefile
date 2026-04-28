NDK ?= $(ANDROID_NDK_HOME)
DEPS ?= $(ANDROID_EBPF_DEPS)
CLANG=$(NDK)/toolchains/llvm/prebuilt/linux-x86_64/bin/clang

ifndef NDK
$(error Set NDK or ANDROID_NDK_HOME to your Android NDK root)
endif

ifndef DEPS
$(error Set DEPS or ANDROID_EBPF_DEPS to your android-ebpf-deps root)
endif

all: ebpf-build

ebpf-build:
	$(CLANG) \
	--target=bpf \
	-c \
	-nostdlibinc -no-canonical-prefixes -O2 \
	-isystem $(DEPS)/bionic/libc/include \
	-isystem $(DEPS)/bionic/libc/kernel/uapi \
	-isystem $(DEPS)/bionic/libc/kernel/uapi/asm-arm64 \
	-isystem $(DEPS)/bionic/libc/kernel/android/uapi \
	-I $(DEPS)/packages/modules/Connectivity/bpf/headers/include \
	-I $(DEPS)/system/core/libcutils/include \
	-I $(DEPS)/system/bpf/progs/include \
	-MD -MF page_order.d -o page_order.o src/page_order.c

clean:
	rm -f page_order.o page_order.d
