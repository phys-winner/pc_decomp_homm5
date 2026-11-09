/* Diagnostic-only, exact entry union. Does not read or change guest state. */
#pragma once
#include <stdint.h>
#include <stdatomic.h>
#include "function_coverage_ids.h"

#define VOID_FC_CUMULATIVE 1u
#define VOID_FC_WINDOW 2u
#define VOID_FC_WRITER 4u
#define VOID_FC_FLAGS 3u

extern _Atomic uint32_t void_fc_state;
extern _Atomic uint64_t void_fc_cumulative[VOID_FC_WORDS];
extern _Atomic uint64_t void_fc_window[VOID_FC_WORDS];
void void_function_coverage_mark(uint32_t word, uint64_t mask);

/* The only contended RMW is the first observation of an unseen ID in a bank.
 * Concurrent duplicate first observations are harmless; there is no event queue.
 */
static inline __attribute__((always_inline)) void void_function_coverage_hit(uint32_t id)
{
    if (id >= VOID_FC_COUNT) return;
    const uint32_t state = atomic_load_explicit(&void_fc_state, memory_order_relaxed);
    if (!(state & VOID_FC_FLAGS)) return;
    const uint32_t word = id >> 6;
    const uint64_t mask = UINT64_C(1) << (id & 63);
    if ((!(state & VOID_FC_CUMULATIVE) ||
         (atomic_load_explicit(&void_fc_cumulative[word], memory_order_relaxed) & mask)) &&
        (!(state & VOID_FC_WINDOW) ||
         (atomic_load_explicit(&void_fc_window[word], memory_order_relaxed) & mask))) return;
    void_function_coverage_mark(word, mask);
}
#define VOID_FUNCTION_COVERAGE_HIT(id) void_function_coverage_hit(id)

/* Single capture per process: cumulative starts statically before guest startup.
 * Arm and stop are called by one monitor; stop closes both banks and drains writers.
 */
int void_function_coverage_arm(void);
void void_function_coverage_stop(void);
int void_function_coverage_export(const char *path, uint64_t accepted_ns,
    uint64_t start_before_ns, uint64_t start_after_ns, uint64_t stop_before_ns,
    uint64_t stop_after_ns, uint64_t warmup_ms, uint64_t duration_ms);
int void_function_coverage_begin(const char *userdata);
int void_function_coverage_finish(void);
