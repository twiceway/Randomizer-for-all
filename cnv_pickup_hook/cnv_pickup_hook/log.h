#pragma once
#include <cstdarg>
#include <cstdio>
#include <mutex>

inline std::mutex g_log_mutex;
inline FILE* g_log_file = nullptr;

inline void LogInit() {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (g_log_file) {
        return;
    }
    CreateDirectoryA("mod\\dll\\logs", nullptr);
    fopen_s(&g_log_file, "mod\\dll\\logs\\cnv_pickup_hook.log", "a");
}

inline void LogLine(const char* fmt, ...) {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (!g_log_file) {
        return;
    }
    SYSTEMTIME st{};
    GetLocalTime(&st);
    fprintf(g_log_file, "[%04u-%02u-%02u %02u:%02u:%02u] ",
            st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log_file, fmt, args);
    va_end(args);
    fprintf(g_log_file, "\n");
    fflush(g_log_file);
}
