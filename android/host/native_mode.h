/* One process-wide choice per native group. Only the initializing caller
 * reads the file; no caller can observe a temporary fallback choice. */
#ifndef VOID_NATIVE_MODE_H
#define VOID_NATIVE_MODE_H
#include <stdio.h>

/* The pinned compiler is Clang on both Android and host differential tests.
 * Its C11 atomic intrinsics avoid a platform-specific stdatomic.h adapter. */
typedef _Atomic(int) void_native_mode_cache;
#define VOID_NATIVE_MODE_CACHE_INIT (-1)

static inline int void_native_mode_get(void_native_mode_cache *cache,
        const char *filename, const char *log_format)
{
    int mode = __c11_atomic_load(cache, __ATOMIC_ACQUIRE);
    if (mode >= 0) return mode;

    int expected = -1;
    if (__c11_atomic_compare_exchange_strong(cache, &expected, -2,
            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        mode = 0;
        char path[1024], value[3];
        const char *directory = void_data_dir();
        int length = directory ? snprintf(path, sizeof path, "%s/%s", directory, filename) : -1;
        if (length >= 0 && (size_t)length < sizeof path) {
            FILE *file = fopen(path, "rb");
            if (file) {
                size_t size = fread(value, 1, sizeof value, file);
                mode = (size == 1 || (size == 2 && value[1] == '\n')) && value[0] == '1';
                fclose(file);
            }
        }
        void_log(log_format, mode);
        __c11_atomic_store(cache, mode, __ATOMIC_RELEASE);
        return mode;
    }

    /* Initialization reads three bytes once. No OS-specific wait API or
     * dependency is needed; the atomic acquire load cannot be hoisted. */
    do {
        mode = __c11_atomic_load(cache, __ATOMIC_ACQUIRE);
    } while (mode < 0);
    return mode;
}
#endif
