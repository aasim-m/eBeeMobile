LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := page_order_attach
LOCAL_SRC_FILES := ../page_order_attach.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)