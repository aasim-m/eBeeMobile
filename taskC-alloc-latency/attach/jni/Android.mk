LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := alloc_latency_attach
LOCAL_SRC_FILES := ../alloc_latency_attach.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)