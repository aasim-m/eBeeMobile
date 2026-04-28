LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := file_stats_monitor
LOCAL_SRC_FILES := file_stats_monitor.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)

include $(CLEAR_VARS)
LOCAL_MODULE := file_stats_reset
LOCAL_SRC_FILES := file_stats_reset.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)