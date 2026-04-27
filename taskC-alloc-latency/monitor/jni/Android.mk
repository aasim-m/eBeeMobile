LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := alloc_latency_monitor
LOCAL_SRC_FILES := alloc_latency_monitor.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)

include $(CLEAR_VARS)
LOCAL_MODULE := alloc_latency_reset
LOCAL_SRC_FILES := alloc_latency_reset.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)