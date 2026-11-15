/* Grid dilation 00B3EFB0: a battle calls it every frame of a player's turn
 * (2026-11-15 profile of a duel's first turn: 6.5% of the game thread), with
 * k = 2 for big creatures. A cell (x, y), 1 <= x < W, 1 <= y < H, is set when
 * the k x k window x-k+1..x, y-k+1..y of a snapshot holds a set bit or leaves
 * the snapshot.
 *
 * thiscall: ECX grid {int32 W; bitmap {data, rows, stride, H}}, EDX k; RET.
 * The snapshot comes from the bitmap copy constructor 004F8260 (thiscall,
 * RET 4) and goes back through 00879240 (free, cdecl); both are called as the
 * production body calls them (RECOMP_CALL_P: EAX/ECX/EDX/ESP published and
 * reloaded). In between, when nothing the loops read can change while they
 * run (no hand-over inside them, no row written over the frame, the header,
 * the row tables or the snapshot), all rows are done at once with 64-bit
 * words; otherwise the loops run stepwise in the original's memory order:
 * each frame slot, header word, row pointer and snapshot byte is read and
 * written where the original does, so any aliasing behaves the same, a window
 * ends at its first hit (the rest of the original window only counts down)
 * and adds its backward branches at once when no hand-over can fall inside
 * it, else it runs branch by branch with the hand-over. Either way registers,
 * the frame below the final ESP and g_backedges end as the production body
 * leaves them; its lazy flags stay local there, as here.
 *
 * Addresses are ToE's; tools/port_patches.py maps them for 1.6 and 2.1
 * (config/{vanilla,hof}.patches.json: reference_addresses of this file).
 * <data>/native-dilate-original = 1 runs the original; no file runs the kernel. */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include "native_mode.h"

extern void sub_00B3EFB0(void);
extern void sub_004F8260(void);
extern void sub_00879240(void);

/* ---------------------------------------------------------------- mode */
/* <data>/native-dilate-original = 1 runs the original body (A/B and rollback),
 * cached once per process like every native group (native_mode.h).
 *
 * Same-process A/B for measurements: when <data>/native-dilate-live exists at the
 * first call, its first byte is read again at most once a second ('1' runs the
 * original, anything else the kernel; a removed file keeps the last choice).
 * Both paths leave the same guest state, so a switch between two calls is not
 * visible to the game. Without that file at the first call nothing more is read. */
static int dilate_live_read(char *first)
{
    char path[1024];
    const char *directory = void_data_dir();
    int length = directory ? snprintf(path, sizeof path, "%s/native-dilate-live", directory) : -1;
    if (length < 0 || (size_t)length >= sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    int c = fgetc(file);
    fclose(file);
    *first = c == EOF ? 0 : (char)c;
    return 1;
}

static int dilate_original_choice(int cached)
{
    static _Atomic(int) live = -2;          /* -2 not looked at, -1 no live file, 0/1 the live choice */
    static _Atomic(uint64_t) next_read;
    int choice = __c11_atomic_load(&live, __ATOMIC_ACQUIRE);
    if (choice == -1) return cached;
    char first = 0;
    if (choice == -2) {
        if (!dilate_live_read(&first)) {
            __c11_atomic_store(&live, -1, __ATOMIC_RELEASE);
            return cached;
        }
    } else {
        const uint64_t now = void_perf_now_ns();
        if (now < __c11_atomic_load(&next_read, __ATOMIC_RELAXED)) return choice;
        if (!dilate_live_read(&first)) first = choice ? '1' : '0';
    }
    const int next = first == '1';
    __c11_atomic_store(&next_read, void_perf_now_ns() + 1000000000ull, __ATOMIC_RELAXED);
    if (next != choice) void_log("[dilate-native] live original=%d", next);
    __c11_atomic_store(&live, next, __ATOMIC_RELEASE);
    return next;
}

static int dilate_native_enabled(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-dilate-original", "[dilate-native] original=%d (cached for this process)");
    return !dilate_original_choice(cached);
}

/* ------------------------------------------------------------ helpers */
/* Plain guest accesses, wrapping like the production body's MEM8/MEM32. */
static inline uint8_t ld8(uint32_t va) { return *(const uint8_t *)GPTR(va); }
static inline uint32_t ld32(uint32_t va) { uint32_t v; memcpy(&v, GPTR(va), 4); return v; }
static inline void st8(uint32_t va, uint8_t v) { *(uint8_t *)GPTR(va) = v; }
static inline void st32(uint32_t va, uint32_t v) { memcpy(GPTR(va), &v, 4); }

/* The production body's entry record (trace/diagnostic builds only). */
#if defined(RECOMP_TRACE)
#define DILATE_ENTER(va) (g_cur_func = (va), g_enter_trace[g_enter_idx++ & (RECOMP_ENTER_SIZE - 1)] = (va))
#elif defined(RECOMP_CALL_DIAG)
#define DILATE_ENTER(va) (g_cur_func = (va))
#else
#define DILATE_ENTER(va) ((void)0)
#endif

typedef struct grid_regs { uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi; } grid_regs;

static inline uint32_t lo8(uint32_t reg, uint32_t byte) { return (reg & ~0xFFu) | (byte & 0xFFu); }

/* RECOMP_BACKEDGE(): every register goes to the globals around a hand-over. */
static inline void grid_backedge(grid_regs *r)
{
    if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {
        g_backedges = 0;
        g_eax = r->eax; g_ecx = r->ecx; g_edx = r->edx; g_ebx = r->ebx;
        g_esp = r->esp; g_ebp = r->ebp; g_esi = r->esi; g_edi = r->edi;
        recomp_yield_hook();
        r->eax = g_eax; r->ecx = g_ecx; r->edx = g_edx; r->ebx = g_ebx;
        r->esp = g_esp; r->ebp = g_ebp; r->esi = g_esi; r->edi = g_edi;
    }
}

/* RECOMP_CALL_P(.., 0x17, 0x17, 0, ..): return slot, EAX/ECX/EDX/ESP out and in. */
static inline void grid_call(void (*function)(void), grid_regs *r)
{
    r->esp -= 4u;
    st32(r->esp, RECOMP_RETADDR);
    g_eax = r->eax; g_ecx = r->ecx; g_edx = r->edx; g_esp = r->esp;
    function();
    r->eax = g_eax; r->ecx = g_ecx; r->edx = g_edx; r->esp = g_esp;
}

/* One step of the window at x = EAX, y = EDI, row pointer slot ESI
 * (0x00B3F040..0x00B3F072): CL = 1 on a hit or outside the snapshot. */
static inline void grid_check(grid_regs *r)
{
    const uint32_t s = r->esp;
    if ((uint8_t)r->ecx || (int32_t)r->eax < 0 || (int32_t)r->eax >= (int32_t)ld32(s + 0x2Cu) ||
        (int32_t)r->edi < 0 || (int32_t)r->edi >= (int32_t)ld32(s + 0x3Cu)) {
        r->ecx = lo8(r->ecx, 1u);
        return;
    }
    r->ebx = ld32(r->esi);
    r->edx = (uint32_t)((int32_t)r->eax >> 3);
    r->edx = lo8(r->edx, ld8(r->edx + r->ebx));
    r->ecx = lo8(r->ecx, r->eax & 7u);
    r->edx = lo8(r->edx, (uint8_t)r->edx >> (r->ecx & 7u));
    r->ecx = lo8(r->ecx, ((uint8_t)r->edx & 1u) ? 1u : 0u);
}

/* The window of one cell (0x00B3F030..0x00B3F087): [esp+0x24] columns from
 * x = EAX down, [esp+0x20] rows each from y = [esp+0x10] down. */
static void grid_window(grid_regs *r)
{
    const uint32_t s = r->esp, columns = ld32(s + 0x24u), rows = ld32(s + 0x20u);
    const uint64_t branches = (uint64_t)columns * rows + columns;
    if (columns - 1u < 0x10000u && rows - 1u < 0x10000u &&
        (!recomp_yield_hook || (uint64_t)g_backedges + branches < RECOMP_YIELD_EVERY)) {
        /* No hand-over can fall inside: after a hit the rest only counts. The
         * column counter holds its original value while a step reads memory. */
        const uint32_t x = r->eax;
        for (uint32_t column = 0; column < columns && !(uint8_t)r->ecx; ++column) {
            if (column) st32(s + 0x24u, columns - column);
            r->eax = x - column;
            r->edi = ld32(s + 0x10u);
            r->esi = ld32(s + 0x28u);
            for (uint32_t row = 0; row < rows && !(uint8_t)r->ecx; ++row) {
                grid_check(r);
                r->esi -= 4u;
                r->edi -= 1u;
            }
        }
        r->eax = x - columns;
        r->edi = ld32(s + 0x10u) - rows;
        r->esi = ld32(s + 0x28u) - 4u * rows;
        r->ebp = 0;
        st32(s + 0x24u, 0);
        g_backedges += (uint32_t)branches;
        return;
    }
    for (;;) {
        r->edi = ld32(s + 0x10u);
        r->esi = ld32(s + 0x28u);
        r->ebp = ld32(s + 0x20u);
        for (;;) {
            grid_check(r);
            r->esi -= 4u;
            r->edi -= 1u;
            r->ebp -= 1u;
            const int more = r->ebp != 0;
            grid_backedge(r);
            if (!more) break;
        }
        r->eax -= 1u;
        const uint32_t left = ld32(s + 0x24u) - 1u;
        st32(s + 0x24u, left);
        grid_backedge(r);
        if (!left) break;
    }
}

/* One cell (0x00B3F011..0x00B3F0D4); returns whether the row goes on. */
static inline int grid_cell(grid_regs *r)
{
    r->ecx &= ~0xFFu;
    if ((int32_t)r->ebx > 0) {
        r->eax = ld32(r->esp + 0x34u);
        r->edx = ld32(r->esp + 0x14u) + r->eax;
        st32(r->esp + 0x28u, r->edx);
        r->eax = r->esi;
        st32(r->esp + 0x24u, r->ebx);
        grid_window(r);
        const int hit = (uint8_t)r->ecx != 0;
        r->esi = ld32(r->esp + 0x1Cu);
        r->edi = ld32(r->esp + 0x18u);
        if (hit && (int32_t)r->esi >= 0 && (int32_t)r->esi < (int32_t)ld32(r->edi)) {
            r->eax = ld32(r->esp + 0x14u);
            if ((int32_t)r->eax >= 0) {
                r->ecx = ld32(r->esp + 0x10u);
                if ((int32_t)r->ecx < (int32_t)ld32(r->edi + 0x10u)) {
                    r->edx = ld32(r->edi + 8u);
                    r->edx = ld32(r->edx + r->eax);
                    r->ecx = (uint32_t)((int32_t)r->esi >> 3);
                    r->eax = r->edx + r->ecx;
                    r->ecx = r->esi & 7u;
                    r->edx = lo8(r->edx, 1u << r->ecx);
                    st8(r->eax, (uint8_t)(ld8(r->eax) | (uint8_t)r->edx));
                }
            }
        }
    }
    r->ebx = ld32(r->esp + 0x20u);
    r->esi += 1u;
    const int more = (int32_t)r->esi < (int32_t)ld32(r->edi);
    st32(r->esp + 0x1Cu, r->esi);
    grid_backedge(r);
    return more;
}

/* All rows at once (0x00B3F000..0x00B3F0F2) when nothing the loops read can
 * change while they run: no hand-over inside them, no row written over the
 * frame, the grid header, its row table, the snapshot or its row table, and
 * neither the snapshot nor the header in the frame. Each row then ORs the
 * snapshot rows of its window and spreads them over k columns (64-bit words;
 * bit x of a row is bit x & 7 of byte x >> 3). Leaves what the stepwise loops
 * leave: the frame slots, ECX/EDX of the last cell, the branch count. */
enum { DILATE_FAST_BYTES = 1024, DILATE_FAST_ROWS = 1024, DILATE_FAST_K = 32 };
#ifdef DILATE_NATIVE_COUNTERS   /* tests/test_dilate_native.py: how often the rows ran at once */
unsigned dilate_fast_runs;
#define DILATE_FAST_RUN() (++dilate_fast_runs)
#else
#define DILATE_FAST_RUN() ((void)0)
#endif

static inline int apart(uint64_t a0, uint64_t a1, uint64_t b0, uint64_t b1) { return a1 <= b0 || b1 <= a0; }

/* How often the rows ran at once: logged every 65536 calls (a battle turn calls
 * the dilation every frame, often more than once). */
static uint32_t dilate_calls, dilate_rows_at_once;

static int grid_rows_fast(grid_regs *r)
{
    const uint32_t s = r->esp, grid = r->edi;
    const int32_t width = (int32_t)ld32(grid), height = (int32_t)ld32(grid + 0x10u), k = (int32_t)r->ebx;
    if (width <= 1 || height <= 1 || k <= 0 || k > DILATE_FAST_K || width > DILATE_FAST_BYTES * 8 ||
        height > DILATE_FAST_ROWS || (int32_t)ld32(s + 0x2Cu) != width || (int32_t)ld32(s + 0x20u) != k)
        return 0;
    const uint64_t cell = 1u + (uint64_t)k * (uint32_t)k + (uint32_t)k;
    const uint64_t total = (uint64_t)(height - 1) * (1u + (uint64_t)(width - 1) * cell);
    if (recomp_yield_hook && (uint64_t)g_backedges + total >= RECOMP_YIELD_EVERY) return 0;
    const uint32_t bytes = ((uint32_t)(width - 1) >> 3) + 1u, table = ld32(grid + 8u), copy = ld32(s + 0x34u);
    const int32_t copy_height = (int32_t)ld32(s + 0x3Cu);
    const uint64_t frame0 = s, frame1 = (uint64_t)s + 0x48u;
    const uint64_t header0 = grid, header1 = (uint64_t)grid + 0x14u;
    const uint64_t rows0 = (uint64_t)table + 4u, rows1 = (uint64_t)table + 4u * (uint32_t)height;
    if (frame1 > 0x100000000ull || header1 > 0x100000000ull || rows1 > 0x100000000ull ||
        !apart(header0, header1, frame0, frame1) || !apart(rows0, rows1, frame0, frame1))
        return 0;
    uint64_t write0 = UINT64_MAX, write1 = 0;
    for (int32_t y = 1; y < height; ++y) {
        const uint64_t row = ld32(table + 4u * (uint32_t)y);
        if (row + bytes > 0x100000000ull) return 0;
        if (row < write0) write0 = row;
        if (row + bytes > write1) write1 = row + bytes;
    }
    /* The snapshot's row table and its rows are separate heap blocks: each is
     * checked on its own (one span over both may well cover the grid). */
    const int32_t first = 2 - k > 0 ? 2 - k : 0, last = height - 1 < copy_height - 1 ? height - 1 : copy_height - 1;
    uint64_t read0 = UINT64_MAX, read1 = 0, list0 = 0, list1 = 0;
    if (first <= last) {
        list0 = (uint64_t)copy + 4u * (uint32_t)first;
        list1 = (uint64_t)copy + 4u * (uint32_t)last + 4u;
        if (list1 > 0x100000000ull || !apart(list0, list1, frame0, frame1)) return 0;
        for (int32_t y = first; y <= last; ++y) {
            const uint64_t row = ld32(copy + 4u * (uint32_t)y);
            if (row + bytes > 0x100000000ull) return 0;
            if (row < read0) read0 = row;
            if (row + bytes > read1) read1 = row + bytes;
        }
        if (!apart(read0, read1, frame0, frame1)) return 0;
    }
    if (!apart(write0, write1, read0, read1) || !apart(write0, write1, list0, list1) ||
        !apart(write0, write1, frame0, frame1) || !apart(write0, write1, header0, header1) ||
        !apart(write0, write1, rows0, rows1))
        return 0;

    const uint32_t words = (bytes + 7u) >> 3;
    uint64_t sum[DILATE_FAST_BYTES / 8 + 1], hit[DILATE_FAST_BYTES / 8 + 1];
    int earlier = 0, last_hit = 0;
    for (int32_t y = 1; y < height; ++y) {
        if (y - k + 1 < 0 || y >= copy_height) {
            /* A window row outside the snapshot: every cell of the row hits. */
            for (uint32_t w = 0; w < words; ++w) hit[w] = ~0ull;
        } else {
            memset(sum, 0, words * 8u);
            for (int32_t yy = y - k + 1; yy <= y; ++yy) {
                const uint32_t row = ld32(copy + 4u * (uint32_t)yy);
                for (uint32_t b = 0; b < bytes; ++b) sum[b >> 3] |= (uint64_t)ld8(row + b) << (8u * (b & 7u));
            }
            for (uint32_t w = 0; w < words; ++w) hit[w] = sum[w];
            for (int32_t shift = 1; shift < k; ++shift)
                for (uint32_t w = words; w-- > 0;)
                    hit[w] |= sum[w] << shift | (w ? sum[w - 1] >> (64 - shift) : 0);
            /* Columns left of the snapshot: x < k - 1 hits. */
            for (int32_t x = 0; x < k - 1 && x < width; ++x) hit[x >> 6] |= 1ull << (x & 63);
        }
        hit[0] &= ~1ull;                                   /* x = 0 is never a cell */
        const uint32_t end = (uint32_t)width;               /* cells x < width */
        if (end & 63u) hit[end >> 6] &= (1ull << (end & 63u)) - 1u;
        for (uint32_t w = (end >> 6) + ((end & 63u) ? 1u : 0u); w < words; ++w) hit[w] = 0;
        /* Whether a cell before the last one hit (its ECX has no high bits then)
         * and whether the last one did. */
        if (y == height - 1) {
            const uint32_t final_x = (uint32_t)width - 1u;
            const uint64_t bit = 1ull << (final_x & 63u);
            last_hit = (hit[final_x >> 6] & bit) != 0;
            hit[final_x >> 6] &= ~bit;
            for (uint32_t w = 0; w < words; ++w) earlier |= hit[w] != 0;
            if (last_hit) hit[final_x >> 6] |= bit;
        } else {
            for (uint32_t w = 0; w < words && !earlier; ++w) earlier |= hit[w] != 0;
        }
        const uint32_t row = ld32(table + 4u * (uint32_t)y);
        for (uint32_t b = 0; b < bytes; ++b) {
            const uint8_t bits = (uint8_t)(hit[b >> 3] >> (8u * (b & 7u)));
            if (bits) st8(row + b, (uint8_t)(ld8(row + b) | bits));
        }
    }
    /* The last cell's registers (0x00B3F0B4..0x00B3F0C5 on a hit, else the
     * window's last step at x - k + 1, y - k + 1). */
    const uint32_t x = (uint32_t)width - 1u, y = (uint32_t)height - 1u;
    if (last_hit) {
        r->ecx = x & 7u;
        r->edx = lo8(ld32(table + 4u * y), 1u << (x & 7u));
    } else {
        const uint32_t xx = x - (uint32_t)k + 1u, yy = y - (uint32_t)k + 1u;
        const uint32_t row = ld32(copy + 4u * yy);
        r->ecx = earlier ? 0u : r->ecx & ~0xFFu;
        r->edx = lo8(xx >> 3, ld8((xx >> 3) + row) >> (xx & 7u));
    }
    r->eax = (uint32_t)height;
    r->ebx = (uint32_t)k;
    r->esi = (uint32_t)width;
    r->ebp = 0;
    st32(s + 0x10u, (uint32_t)height);
    st32(s + 0x14u, 4u * (uint32_t)height);
    st32(s + 0x1Cu, (uint32_t)width);
    st32(s + 0x24u, 0);
    st32(s + 0x28u, copy + 4u * y);
    g_backedges += (uint32_t)total;
    DILATE_FAST_RUN();
    ++dilate_rows_at_once;
    return 1;
}

/* 00B3EFB0 with EDX != 1: the prologue, the snapshot, the rows, the frees. */
static void grid_dilate(void)
{
    grid_regs r = {g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi};
    r.esp -= 0x34u;
    r.esp -= 4u; st32(r.esp, r.ebx);
    r.ebx = r.edx;
    r.esp -= 4u; st32(r.esp, r.edi);
    r.edi = r.ecx;
    st32(r.esp + 0x18u, r.ebx);
    st32(r.esp + 0x10u, r.edi);
    r.eax = ld32(r.edi);
    r.ecx = r.edi + 4u;
    r.esp -= 4u; st32(r.esp, r.ecx);
    r.ecx = r.esp + 0x2Cu;
    st32(r.esp + 0x28u, r.eax);
    grid_call(sub_004F8260, &r);
    const int rows = (int32_t)ld32(r.edi + 0x10u) > 1;
    st32(r.esp + 0x8u, 1u);
    if (rows) {
        r.esp -= 4u; st32(r.esp, r.ebp);
        r.esp -= 4u; st32(r.esp, r.esi);
        st32(r.esp + 0x14u, 4u);
        if (!grid_rows_fast(&r)) for (;;) {
            r.esi = 1u;
            const int cells = (int32_t)ld32(r.edi) > 1;
            st32(r.esp + 0x1Cu, r.esi);
            if (cells) while (grid_cell(&r)) {}
            r.eax = ld32(r.esp + 0x10u);
            st32(r.esp + 0x14u, ld32(r.esp + 0x14u) + 4u);
            r.eax += 1u;
            const int more = (int32_t)r.eax < (int32_t)ld32(r.edi + 0x10u);
            st32(r.esp + 0x10u, r.eax);
            grid_backedge(&r);
            if (!more) break;
        }
        r.esi = ld32(r.esp); r.esp += 4u;
        r.ebp = ld32(r.esp); r.esp += 4u;
    }
    r.eax = ld32(r.esp + 0x28u);
    if (r.eax) {
        r.esp -= 4u; st32(r.esp, r.eax);
        grid_call(sub_00879240, &r);
        r.esp += 4u;
    }
    r.eax = ld32(r.esp + 0x2Cu);
    if (r.eax) {
        r.esp -= 4u; st32(r.esp, r.eax);
        grid_call(sub_00879240, &r);
        r.esp += 4u;
    }
    r.edi = ld32(r.esp); r.esp += 4u;
    r.ebx = ld32(r.esp); r.esp += 4u;
    r.esp += 0x34u + 4u;
    g_eax = r.eax; g_ecx = r.ecx; g_edx = r.edx; g_ebx = r.ebx;
    g_esp = r.esp; g_ebp = r.ebp; g_esi = r.esi; g_edi = r.edi;
}

/* k == 1 returns at once in the original; it keeps that path. */
void void_dilate_grid(void)
{
    if (g_edx == 1u) { sub_00B3EFB0(); return; }
    DILATE_ENTER(0x00B3EFB0u);
    grid_dilate();
    if (!(++dilate_calls & 0xFFFFu))
        void_log("[dilate-native] %u calls, rows at once %u", dilate_calls, dilate_rows_at_once);
}

void void_dilate_grid_dispatch(void) { if (dilate_native_enabled()) void_dilate_grid(); else sub_00B3EFB0(); }
