/* Optional diagnostic runtime: independent of guest globals and guest locking. */
#define _POSIX_C_SOURCE 200809L
#include "function_coverage_runtime.h"
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

_Atomic uint32_t void_fc_state = VOID_FC_CUMULATIVE;
_Atomic uint64_t void_fc_cumulative[VOID_FC_WORDS];
_Atomic uint64_t void_fc_window[VOID_FC_WORDS];
static _Atomic int void_fc_armed;

__attribute__((noinline)) void void_function_coverage_mark(uint32_t word, uint64_t mask)
{
    if (word >= VOID_FC_WORDS) return;
    uint32_t state = atomic_load_explicit(&void_fc_state, memory_order_relaxed);
    for (;;) {
        if (!(state & VOID_FC_FLAGS)) return;
        /* Admission and the open/closed state are one atomic operation. Stop
         * cannot miss a writer that was admitted before closing the banks. */
        if (atomic_compare_exchange_weak_explicit(&void_fc_state, &state,
                state + VOID_FC_WRITER, memory_order_acquire, memory_order_relaxed)) break;
    }
#ifdef VOID_FC_TEST_HOOK
    extern void void_fc_test_admitted(uint32_t word, uint64_t mask);
    void_fc_test_admitted(word, mask);
#endif
    if (state & VOID_FC_CUMULATIVE)
        atomic_fetch_or_explicit(&void_fc_cumulative[word], mask, memory_order_relaxed);
    if (state & VOID_FC_WINDOW)
        atomic_fetch_or_explicit(&void_fc_window[word], mask, memory_order_relaxed);
    atomic_fetch_sub_explicit(&void_fc_state, VOID_FC_WRITER, memory_order_release);
}

int void_function_coverage_arm(void)
{
    int expected = 0;
    if (!atomic_compare_exchange_strong(&void_fc_armed, &expected, 1)) return 0;
    atomic_fetch_or_explicit(&void_fc_state, VOID_FC_WINDOW, memory_order_acq_rel);
    return 1;
}

void void_function_coverage_stop(void)
{
    atomic_fetch_and_explicit(&void_fc_state, ~VOID_FC_FLAGS, memory_order_acq_rel);
    while (atomic_load_explicit(&void_fc_state, memory_order_acquire) != 0) {
        /* At most one tiny atomic OR section per admitted first hit remains.
         * This is the monitor thread, never the game/render/audio thread. */
    }
}

static int write_u32(FILE *file, uint32_t value)
{
    unsigned char b[4];
    for (unsigned i = 0; i != 4; ++i) b[i] = (unsigned char)(value >> (i * 8));
    return fwrite(b, 1, sizeof b, file) == sizeof b;
}

static int write_u64(FILE *file, uint64_t value)
{
    unsigned char b[8];
    for (unsigned i = 0; i != 8; ++i) b[i] = (unsigned char)(value >> (i * 8));
    return fwrite(b, 1, sizeof b, file) == sizeof b;
}

int void_function_coverage_export(const char *path, uint64_t accepted_ns,
    uint64_t start_before_ns, uint64_t start_after_ns, uint64_t stop_before_ns,
    uint64_t stop_after_ns, uint64_t warmup_ms, uint64_t duration_ms)
{
    if (atomic_load_explicit(&void_fc_state, memory_order_acquire) != 0) return 0;
    char temporary[2048];
    if (snprintf(temporary, sizeof temporary, "%s.tmp", path) >= (int)sizeof temporary) return 0;
    FILE *existing = fopen(path, "rb");
    if (existing) { fclose(existing); return 0; }
    FILE *file = fopen(temporary, "wbx");
    if (!file) return 0;
    int okay = fwrite("H5FCOV1\0", 1, 8, file) == 8;
    okay &= write_u32(file, 1) && write_u32(file, VOID_FC_COUNT) && write_u32(file, VOID_FC_WORDS) && write_u32(file, 0);
    okay &= write_u64(file, accepted_ns) && write_u64(file, start_before_ns) && write_u64(file, start_after_ns);
    okay &= write_u64(file, stop_before_ns) && write_u64(file, stop_after_ns);
    okay &= write_u64(file, warmup_ms) && write_u64(file, duration_ms);
    okay &= fwrite(VOID_FC_IDENTITY, 1, 64, file) == 64;
    for (uint32_t i = 0; i != VOID_FC_WORDS; ++i)
        okay &= write_u64(file, atomic_load_explicit(&void_fc_cumulative[i], memory_order_relaxed));
    for (uint32_t i = 0; i != VOID_FC_WORDS; ++i)
        okay &= write_u64(file, atomic_load_explicit(&void_fc_window[i], memory_order_relaxed));
    if (fclose(file)) okay = 0;
    if (!okay) { remove(temporary); return 0; }
    if (rename(temporary, path)) { remove(temporary); return 0; }
    return 1;
}

/* Request grammar: two unsigned decimal fields separated by whitespace. Parsing
 * against the field limits also rejects integer overflow before multiplication. */
int void_function_coverage_parse_request(const char *text, size_t length,
    uint64_t *warmup_ms, uint64_t *duration_ms)
{
    const uint64_t limits[2] = {3600000, 600000};
    uint64_t values[2] = {0, 0};
    size_t position = 0;
    for (unsigned field = 0; field != 2; ++field) {
        while (position < length && isspace((unsigned char)text[position])) ++position;
        const size_t first = position;
        while (position < length && text[position] >= '0' && text[position] <= '9') {
            const unsigned digit = (unsigned)(text[position++] - '0');
            if (values[field] > limits[field] / 10 ||
                (values[field] == limits[field] / 10 && digit > limits[field] % 10)) return 0;
            values[field] = values[field] * 10 + digit;
        }
        if (position == first) return 0;
        if (field == 0 && (position == length || !isspace((unsigned char)text[position]))) return 0;
    }
    while (position < length && isspace((unsigned char)text[position])) ++position;
    if (position != length || values[1] == 0) return 0;
    *warmup_ms = values[0];
    *duration_ms = values[1];
    return 1;
}


#ifndef VOID_FC_NO_MONITOR
#include <time.h>

static _Atomic int capture_phase;
static char capture_path[2048];
static uint64_t accepted_ns, start_before_ns, start_after_ns;

static uint64_t monotonic_ns(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    return (uint64_t)now.tv_sec * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
}

/* Explicit script-thread controls: no extra timer/monitor thread. Cumulative
 * entries have already been recorded since static initialization. */
int void_function_coverage_begin(const char *userdata)
{
    int expected = 0;
    if (!userdata || strlen(userdata) > 1900) return 0;
    if (!atomic_compare_exchange_strong(&capture_phase, &expected, 1)) return 0;
    snprintf(capture_path, sizeof capture_path, "%s/function-coverage.bin", userdata);
    accepted_ns = start_before_ns = monotonic_ns();
    if (!accepted_ns || !void_function_coverage_arm()) {
        atomic_store(&capture_phase, 4);
        return 0;
    }
    start_after_ns = monotonic_ns();
    atomic_store_explicit(&capture_phase, 2, memory_order_release);
    return 1;
}

int void_function_coverage_finish(void)
{
    int expected = 2;
    if (!atomic_compare_exchange_strong(&capture_phase, &expected, 3)) return 0;
    const uint64_t stop_before = monotonic_ns();
    void_function_coverage_stop();
    const uint64_t stop_after = monotonic_ns();
    /* Zero requested timing fields mean explicit fcstart/fcstop controls. */
    const int okay = void_function_coverage_export(capture_path, accepted_ns,
        start_before_ns, start_after_ns, stop_before, stop_after, 0, 0);
    atomic_store(&capture_phase, 4);
    return okay;
}
#endif
