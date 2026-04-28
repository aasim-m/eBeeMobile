LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)
LOCAL_MODULE := file_stats_attach
LOCAL_SRC_FILES := ../file_stats_attach.cpp
LOCAL_LDFLAGS := -pie
include $(BUILD_EXECUTABLE)