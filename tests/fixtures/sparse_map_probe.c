/* Differential oracle: the previous separate generation/dense direct map. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fail_next, allocations;
static void *checked_calloc(size_t count, size_t size) {
    ++allocations;
    if (fail_next) { fail_next = 0; return NULL; }
    return calloc(count, size);
}
#define calloc checked_calloc
#include "sparse_map.h"
#undef calloc

typedef struct { uint32_t generation, dense; } old_entry;
static old_entry *old_map;
static uint32_t old_capacity, old_generation;
static uint32_t *old_indices, *old_vertices;
static unsigned cases;

static int old_draw_sparse_map(const uint8_t *source, uint32_t unit, uint32_t count, uint32_t base,
    uint32_t first, uint32_t last, uint32_t *unique_count)
{
    uint32_t span = last - first + 1u;
    if (old_capacity < span) {
        uint32_t capacity = 4096;
        while (capacity < span) capacity *= 2;
        old_entry *map = checked_calloc(capacity, sizeof *map);
        if (!map) return 0;
        free(old_map);
        old_map = map; old_capacity = capacity; old_generation = 0;
    }
    if (!++old_generation) {
        memset(old_map, 0, (size_t)old_capacity * sizeof *old_map);
        old_generation = 1;
    }
    uint32_t generation = old_generation, unique = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t raw;
        if (unit == 4) memcpy(&raw, source + (size_t)i * 4u, 4);
        else { uint16_t value; memcpy(&value, source + (size_t)i * 2u, 2); raw = value; }
        int64_t vertex = (int64_t)raw + (int32_t)base;
        if (vertex < first || vertex > last) return 0;
        old_entry *e = &old_map[(uint32_t)vertex - first];
        if (e->generation != generation) {
            e->generation = generation;
            e->dense = unique;
            old_vertices[unique++] = (uint32_t)vertex;
        }
        old_indices[i] = e->dense;
    }
    *unique_count = unique;
    return 1;
}

static void compare(const void *source, uint32_t unit, uint32_t count, uint32_t base,
    uint32_t first, uint32_t last, int fail, int expected)
{
    size_t bytes = (size_t)count * unit;
    uint8_t *saved = malloc(bytes ? bytes : 1); assert(saved);
    memcpy(saved, source, bytes);
    uint32_t old_unique = UINT32_MAX, unique = UINT32_MAX;
    allocations = 0; fail_next = fail;
    int before = old_draw_sparse_map(source, unit, count, base, first, last, &old_unique);
    int old_allocations = allocations;
    allocations = 0; fail_next = fail;
    int after = draw_sparse_map(source, unit, count, base, first, last, &unique);
    assert(before == after && after == expected && old_allocations == allocations);
    assert(old_unique == unique && !memcmp(source, saved, bytes));
    if (after) {
        assert(unique <= count);
        assert(!memcmp(old_indices, sparse_indices, (size_t)count * sizeof *old_indices));
        assert(!memcmp(old_vertices, sparse_vertices, (size_t)unique * sizeof *old_vertices));
        /* Read exactly the vertex addressed by each remapped index. */
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t raw;
            if (unit == 4) memcpy(&raw, (const uint8_t *)source + 4u * i, 4);
            else { uint16_t value; memcpy(&value, (const uint8_t *)source + 2u * i, 2); raw = value; }
            assert(sparse_indices[i] < unique);
            assert(sparse_vertices[sparse_indices[i]] == (uint32_t)((int64_t)raw + (int32_t)base));
        }
    }
    assert(old_capacity == sparse_map_capacity);
    free(saved); ++cases;
}

static uint32_t random_state = 0x5831F792u;
static uint32_t next_random(void) {
    random_state ^= random_state << 13; random_state ^= random_state >> 17;
    random_state ^= random_state << 5; return random_state;
}

int main(void)
{
    const uint32_t maximum = 262144u;
    assert(SPARSE_MAX_INDICES == maximum && sizeof *sparse_map == 4);
    sparse_indices = malloc((size_t)maximum * 2u * sizeof *sparse_indices); assert(sparse_indices);
    sparse_vertices = sparse_indices + maximum;
    old_indices = malloc((size_t)maximum * 2u * sizeof *old_indices); assert(old_indices);
    old_vertices = old_indices + maximum;
    uint32_t *raw = malloc((size_t)maximum * sizeof *raw); assert(raw);
    uint16_t *shorts = malloc(65536u * sizeof *shorts); assert(shorts);

    uint32_t small[] = {1003, 1000, 1999, 1003, 1999, 1000, 1003};
    compare(small, 4, 7, (uint32_t)-1000, 0, 999, 1, 0); /* initial OOM */
    assert(!sparse_map && !old_map && !sparse_map_generation);
    compare(small, 4, 7, (uint32_t)-1000, 0, 999, 0, 1);
    sparse_map_entry *map = sparse_map; old_entry *previous = old_map;
    uint32_t generation = sparse_map_generation;
    compare(small, 4, 7, (uint32_t)-1000, 0, (1u << 20) - 1u, 1, 0); /* growth OOM */
    assert(map == sparse_map && previous == old_map && generation == sparse_map_generation);
    compare(small, 4, 7, (uint32_t)-1000, 0, 999, 0, 1);
    compare(small, 4, 7, (uint32_t)-1000, 0, (1u << 20) - 1u, 0, 1);
    assert(sparse_map_capacity == 1u << 20);

    /* The final 18-bit dense value, plus the full 16-bit source domain. */
    for (uint32_t i = 0; i < maximum; ++i) raw[i] = maximum - i - 1u;
    compare(raw, 4, maximum, 0, 0, maximum - 1u, 0, 1);
    assert(sparse_indices[maximum - 1u] == maximum - 1u);
    for (uint32_t i = 0; i < 65536u; ++i) shorts[i] = (uint16_t)(65535u - i);
    compare(shorts, 2, 65536u, 0, 0, 65535u, 0, 1);
    uint32_t extremes[] = {UINT32_MAX, UINT32_MAX - 1u, UINT32_MAX, 0xFFFFF000u};
    compare(extremes, 4, 4, 0x80000000u, 0x7FFFF000u, 0x7FFFFFFFu, 0, 1);
    compare(extremes, 4, 4, 0, UINT32_MAX - 4095u, UINT32_MAX, 0, 1);
    old_generation = UINT32_MAX - 1u; sparse_map_generation = SPARSE_GENERATION_MAX - 1u;
    compare(raw, 4, maximum, 0, 0, maximum - 1u, 0, 1); /* UINT32_MAX is a valid packed entry. */
    compare(raw, 4, maximum, 0, 0, maximum - 1u, 0, 1); /* largest dense index across wrap */

    /* Invalid bounds after partial insertion must not leak into the next draw. */
    uint32_t invalid[] = {3, 999, 2}, negative[] = {4, 3};
    compare(invalid, 4, 3, 0, 0, 998, 0, 0);
    compare(negative, 4, 2, (uint32_t)-4, 0, 8, 0, 0);
    compare(small, 4, 7, (uint32_t)-1000, 0, 999, 0, 1);

    /* Preserve an old stamp-1 entry, then actually cross the 14-bit wrap. */
    memset(sparse_map, 0, (size_t)sparse_map_capacity * sizeof *sparse_map);
    memset(old_map, 0, (size_t)old_capacity * sizeof *old_map);
    sparse_map_generation = old_generation = 0;
    uint32_t one[] = {7}, two[] = {8}, wrapped[] = {7, 9, 7, 8};
    compare(one, 4, 1, 0, 0, 4095, 0, 1);
    for (uint32_t i = 1; i < SPARSE_GENERATION_MAX; ++i) compare(two, 4, 1, 0, 0, 4095, 0, 1);
    compare(wrapped, 4, 4, 0, 0, 4095, 0, 1);
    assert(sparse_map_generation == 1 && sparse_indices[3] == 2);
    old_generation = UINT32_MAX; sparse_map_generation = SPARSE_GENERATION_MAX;
    compare(wrapped, 4, 4, 0, 0, 4095, 0, 1); /* both generation schemes wrap */

    /* Deterministic mixed spans, duplicate rates, bases, ordering and formats. */
    for (unsigned trial = 0; trial < 2048; ++trial) {
        uint32_t count = 1u + next_random() % 4096u;
        uint32_t span = 1u << (4u + next_random() % 17u);
        uint32_t first = trial & 1u ? 1000000u : 0u;
        int32_t base = first ? -100000 : 0;
        for (uint32_t i = 0; i < count; ++i) raw[i] = first + next_random() % span - (uint32_t)base;
        compare(raw, 4, count, (uint32_t)base, first, first + span - 1u, 0, 1);
        for (uint32_t i = 0; i < count; ++i) shorts[i] = (uint16_t)next_random();
        compare(shorts, 2, count, 777u, 777u, 777u + 65535u, 0, 1);
    }

    free(sparse_map); free(old_map); free(sparse_indices); free(old_indices); free(raw); free(shorts);
    printf("PASS sparse map differential: %u draws; full 262144/65536 unique, raw32/signed base, invalid/partial, OOM/growth, actual generation wrap, order and vertex fetch\n", cases);
    return 0;
}
