#include "prefix.h"
NOINLINE int bounds_baseline(d3d_buffer *ib, const void *up_indices, int up_i32,
    uint32_t start, uint32_t count, int indexed, uint32_t base, uint32_t start_index,
    uint32_t *first, uint32_t *last)
{
    if (!count) return 0;
    if (!indexed) {
        uint64_t end = (uint64_t)start + count - 1u;
        if (end > UINT32_MAX) return 0;
        *first = start; *last = (uint32_t)end; return 1;
    }
    int i32 = up_indices ? up_i32 : ib && ib->format == 102;
    const uint8_t *indices = (const uint8_t *)up_indices;
    if (!indices) {
        uint64_t offset = (uint64_t)start_index * (i32 ? 4u : 2u);
        uint64_t end = offset + (uint64_t)count * (i32 ? 4u : 2u);
        if (!ib || end > ib->size) return 0;
        indices = (const uint8_t *)GPTR(ib->shadow) + offset;
    }
    uint32_t lo = UINT32_MAX, hi = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t v;
        if (i32) memcpy(&v, indices + (size_t)i * 4u, 4);
        else { uint16_t s; memcpy(&s, indices + (size_t)i * 2u, 2); v = s; }
        if (v < lo) lo = v;
        if (v > hi) hi = v;
    }
    int64_t low = (int64_t)lo + (int32_t)base, high = (int64_t)hi + (int32_t)base;
    if (low < 0 || high > UINT32_MAX) return 0;
    *first = (uint32_t)low; *last = (uint32_t)high; return 1;
}