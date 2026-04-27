LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := page_order_monitor
LOCAL_SRC_FILES := page_order_monitor.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)

include $(CLEAR_VARS)
LOCAL_MODULE := page_order_reset
LOCAL_SRC_FILES := page_order_reset.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)