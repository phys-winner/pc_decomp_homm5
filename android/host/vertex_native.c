/* NGScene's software vertex pipeline: four per-vertex loops that the profile
 * of a battle puts at about a fifth of the game thread (ToE, 2026-11-14):
 *
 *   00CF92C0  directional light: per vertex normal (4 packed bytes) . light
 *             direction (PMADDWD), front/back colour pair (PMULHW), two
 *             packed colours out (diffuse, specular); calls the vector resize
 *             00738840 twice and, for a back light, 00CF8AC0/00CF88F0 first.
 *   00CF8D80  point light: |L|^2 test and colour scale on the x87, then per
 *             vertex the clamped N.L times the light colour, saturating-added
 *             to a 4x16-bit accumulator.
 *   00CF8F30  the accumulated light through a cubic curve and a 32 KiB table
 *             (0x010C5990) into packed colours, usually in place.
 *   00C687C0  SSE bone blend: up to four 4x4 bone matrices weighted per
 *             vertex, transposed, applied to the position.
 *
 * Each kernel reproduces what its production body leaves behind (tools/
 * build_android.py: x87 precision rounding and x87 locals, packed SSE with the
 * x86 NaN rules, the masked call protocol whose exits publish all eight
 * registers): guest memory including the stack slots below the final ESP, all
 * GPRs, ESP after `ret n`, the MMX/SSE registers, the x87 compare state and
 * the loop's backward-branch count. Lazy flags and the x87 window are left
 * alone, as the production bodies do (flags_out false; x87 c=0/p=0).
 *
 * A kernel runs natively only when it can prove the result equals the
 * original's: no read range may overlap a range it writes (the stack frame
 * included), no range may wrap the 4 GiB space, and no cooperative hand-over
 * (RECOMP_BACKEDGE) may fall inside its loop. Otherwise, before any side
 * effect, it runs the original lifted body. 00CF92C0 calls guest functions
 * first, so its loop also has an exact literal form for those cases.
 *
 * Addresses are ToE's; tools/port_patches.py maps them for 1.6 and 2.1
 * (config/{vanilla,hof}.patches.json: reference_addresses of this file).
 * <data>/native-vertex-original = 1 runs the originals; no file runs the kernels. */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include "native_mode.h"

extern void sub_00CF8D80(void);
extern void sub_00CF8F30(void);
extern void sub_00C687C0(void);
extern void sub_00CF92C0(void);
extern void sub_00738840(void);
extern void sub_00CF8AC0(void);
extern void sub_00CF88F0(void);

#define VERTEX_POINT_MIN   0x00E12F24u   /* float: smallest |L|^2 the point light accepts */
#define VERTEX_POINT_SCALE 0x00E951A0u   /* float: colour scale to 16-bit fixed point */
#define VERTEX_CURVE_TABLE 0x010C5990u   /* 32 KiB: 15-bit light to a colour byte */

/* ---------------------------------------------------------------- mode */
/* <data>/native-vertex-original = 1 runs the original bodies (A/B and rollback),
 * cached once per process like every native group (native_mode.h).
 *
 * Same-process A/B for measurements: when <data>/native-vertex-live exists at the
 * first call, its first byte is read again at most once a second ('1' runs the
 * originals, anything else the kernels; a removed file keeps the last choice).
 * Both paths leave the same guest state, so a switch between two calls is not
 * visible to the game. Without that file at the first call nothing more is read. */
static int vertex_live_read(char *first)
{
    char path[1024];
    const char *directory = void_data_dir();
    int length = directory ? snprintf(path, sizeof path, "%s/native-vertex-live", directory) : -1;
    if (length < 0 || (size_t)length >= sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    int c = fgetc(file);
    fclose(file);
    *first = c == EOF ? 0 : (char)c;
    return 1;
}

static int vertex_original_choice(int cached)
{
    static _Atomic(int) live = -2;          /* -2 not looked at, -1 no live file, 0/1 the live choice */
    static _Atomic(uint64_t) next_read;
    int choice = __c11_atomic_load(&live, __ATOMIC_ACQUIRE);
    if (choice == -1) return cached;
    char first = 0;
    if (choice == -2) {
        if (!vertex_live_read(&first)) {
            __c11_atomic_store(&live, -1, __ATOMIC_RELEASE);
            return cached;
        }
    } else {
        const uint64_t now = void_perf_now_ns();
        if (now < __c11_atomic_load(&next_read, __ATOMIC_RELAXED)) return choice;
        if (!vertex_live_read(&first)) first = choice ? '1' : '0';
    }
    const int next = first == '1';
    __c11_atomic_store(&next_read, void_perf_now_ns() + 1000000000ull, __ATOMIC_RELAXED);
    if (next != choice) void_log("[vertex-native] live original=%d", next);
    __c11_atomic_store(&live, next, __ATOMIC_RELEASE);
    return next;
}

static int vertex_native_enabled(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-vertex-original", "[vertex-native] original=%d (cached for this process)");
    return !vertex_original_choice(cached);
}

/* ------------------------------------------------------------ helpers */
/* Plain guest accesses: only the machine owner runs here and nothing hands
 * the machine over inside a fast loop. memcpy keeps unaligned data legal. */
static inline uint8_t ld8(uint32_t va) { return *(const uint8_t *)GPTR(va); }
static inline uint16_t ld16(uint32_t va) { uint16_t v; memcpy(&v, GPTR(va), 2); return v; }
static inline uint32_t ld32(uint32_t va) { uint32_t v; memcpy(&v, GPTR(va), 4); return v; }
static inline uint64_t ld64(uint32_t va) { uint64_t v; memcpy(&v, GPTR(va), 8); return v; }
static inline float ldf(uint32_t va) { float v; memcpy(&v, GPTR(va), 4); return v; }
static inline void st16(uint32_t va, uint16_t v) { memcpy(GPTR(va), &v, 2); }
static inline void st32(uint32_t va, uint32_t v) { memcpy(GPTR(va), &v, 4); }
static inline void st64(uint32_t va, uint64_t v) { memcpy(GPTR(va), &v, 8); }
static inline void stf(uint32_t va, float v) { memcpy(GPTR(va), &v, 4); }

/* Guest ranges as 64-bit spans: a span past 4 GiB never takes a fast path. */
static inline int fits(uint64_t at, uint64_t size) { return at + size <= 0x100000000ull; }
static inline int apart(uint64_t a, uint64_t an, uint64_t b, uint64_t bn) { return a + an <= b || b + bn <= a; }

/* True when `edges` more backward branches cannot reach a hand-over. The lifted
 * loop does `if (++counter >= RECOMP_YIELD_EVERY && hook) { counter = 0; ... }`. */
static inline int no_handover(uint64_t edges)
{
    return !recomp_yield_hook || (uint64_t)g_backedges + edges < RECOMP_YIELD_EVERY;
}

/* The production body's entry record (trace/diagnostic builds only). */
#if defined(RECOMP_TRACE)
#define VERTEX_ENTER(va) (g_cur_func = (va), g_enter_trace[g_enter_idx++ & (RECOMP_ENTER_SIZE - 1)] = (va))
#elif defined(RECOMP_CALL_DIAG)
#define VERTEX_ENTER(va) (g_cur_func = (va))
#else
#define VERTEX_ENTER(va) ((void)0)
#endif

/* --------------------------------------------------- 00CF8D80 point light */
/* EDX light {int16 x, y, z, w}, ECX colour float[3], EBX vertex count,
 * [esp+4] accumulator vector {begin..}, [esp+8] vertex stream (normal at +8,
 * stride 20); RET 8. */
static int vertex_point(void)
{
    const uint32_t E = g_esp, dir = g_edx, color = g_ecx, count = g_ebx;
    if (E < 0x40u || !fits(E, 12)) return 0;
    const uint32_t F = (E - 4u) & ~7u, S = F - 0x20u;
    const uint64_t frame = S - 8u, frame_size = (uint64_t)E + 12u - frame;
    if (!fits(dir, 8) || !fits(color, 12) || !apart(dir, 8, frame, frame_size) ||
        !apart(color, 12, frame, frame_size)) return 0;
    const int32_t n = (int32_t)count;
    uint32_t acc = 0, normals = 0;
    if (n > 0) {
        if (n > (1 << 24) || !no_handover((uint64_t)n)) return 0;
        const uint32_t vector = ld32(E + 4u);
        normals = ld32(E + 8u) + 8u;
        if (!fits(vector, 4) || !apart(vector, 4, frame, frame_size)) return 0;
        acc = ld32(vector);
        const uint64_t acc_size = 8ull * (uint64_t)n, normal_size = 20ull * (uint64_t)(n - 1) + 4u;
        if (!fits(acc, acc_size) || !fits(normals, normal_size) ||
            !apart(acc, acc_size, frame, frame_size) || !apart(acc, acc_size, dir, 8) ||
            !apart(acc, acc_size, normals, normal_size) || !apart(acc, acc_size, vector, 4) ||
            !apart(normals, normal_size, frame, frame_size)) return 0;
    }
    VERTEX_ENTER(0x00CF8D80u);

    /* push ebp; and esp, -8; sub esp, 0x20; three FILDs through [S]; push esi/edi. */
    st32(E - 4u, g_ebp);
    const int32_t z = (int16_t)ld16(dir + 4u), y = (int16_t)ld16(dir + 2u), x = (int16_t)ld16(dir);
    st32(S, (uint32_t)x);
    st32(S - 4u, g_esi);
    st32(S - 8u, g_edi);
    const double dx = (double)x, dy = (double)y, dz = (double)z;
    double sum = fp_pc_round(dx * dx);
    const double yy = fp_pc_round(dy * dy);
    sum = fp_pc_round(sum + yy);
    const double zz = fp_pc_round(dz * dz);
    sum = fp_pc_round(sum + zz);
    const int cmp = FPU_CMP(sum, (double)ldf(VERTEX_POINT_MIN));
    void_fpu_cmp = cmp;
    const uint32_t status = (cmp >= 0x10000) ? (uint32_t)(cmp & 0x4700) : cmp == 2 ? 0x4500u :
                            cmp < 0 ? 0x0100u : cmp == 0 ? 0x4000u : 0u;
    if (__builtin_parity((status >> 8) & 5u)) {      /* test ah, 5; jnp: the light is too short */
        g_eax = ((uint32_t)x & 0xFFFF0000u) | status;
        g_esp = E + 12u;
        return 1;
    }

    /* Colour words: each float * scale, stored as a float, reloaded and FISTP'd. */
    const double scale = (double)ldf(VERTEX_POINT_SCALE);
    double red = fp_pc_round((double)ldf(color) * scale);
    st16(S + 0x18u, 0x8000u); st16(S + 0x1Au, 0x8000u); st16(S + 0x1Cu, 0x8000u);
    const float red32 = fp_f32_round(red);
    stf(S, red32);
    st16(S + 8u, 0x1000u); st16(S + 0xCu, 0x1000u); st16(S + 0xEu, 0); st16(S + 0xAu, 0);
    const int32_t red_word = (int32_t)fp_round_i32((double)red32, g_fpu_cw);
    st32(S + 4u, (uint32_t)red_word);
    double green = fp_pc_round((double)ldf(color + 4u) * scale);
    st16(S + 0x14u, (uint16_t)red_word);
    const float green32 = fp_f32_round(green);
    stf(S + 4u, green32);
    const int32_t green_word = (int32_t)fp_round_i32((double)green32, g_fpu_cw);
    st32(S, (uint32_t)green_word);
    double blue = fp_pc_round((double)ldf(color + 8u) * scale);
    st16(S + 0x12u, (uint16_t)green_word);
    const float blue32 = fp_f32_round(blue);
    stf(S + 4u, blue32);
    const int32_t blue_word = (int32_t)fp_round_i32((double)blue32, g_fpu_cw);
    st32(S, (uint32_t)blue_word);
    st16(S + 0x10u, (uint16_t)blue_word);
    const uint64_t mm7 = ld64(S + 0x10u), mm5 = ld64(S + 8u);
    st32(S + 8u, dir);
    g_mm[7] = mm7;
    g_mm[5] = mm5;
    if (n <= 0) {
        g_eax = 0;
        g_ecx = (color & 0xFFFF0000u) | (uint16_t)blue_word;
        g_esp = E + 12u;
        return 1;
    }

    /* The bias qword includes the stack word at S+0x1E nobody wrote: as the original. */
    const uint64_t bias = ld64(S + 0x18u), light = ld64(dir);
    /* Lane math of the MMX sequence: PMADDWD pairs and PADDD wrap at 32 bits,
     * PACKSSDW saturates, the PMULHW/PMULLW pair is the exact 32-bit product,
     * mm5 adds 0x1000 to both dwords before PSRAD 13 (no wrap: |product| < 2^30). */
    int16_t bias_lane[4], light_lane[4], colour_lane[4];
    for (int k = 0; k < 4; ++k) {
        bias_lane[k] = (int16_t)(bias >> (16 * k));
        light_lane[k] = (int16_t)(light >> (16 * k));
        colour_lane[k] = (int16_t)(mm7 >> (16 * k));
    }
    const int32_t round_low = (int32_t)(uint32_t)mm5, round_high = (int32_t)(uint32_t)(mm5 >> 32);
    uint64_t contribution = mm7;
    uint64_t mm0 = g_mm[0], mm1 = g_mm[1], mm2 = g_mm[2], mm3 = g_mm[3], mm6 = g_mm[6];
    uint32_t previous = 0, normal = 0, slot = 0;
    int16_t strength = 0;
    int computed = 0, last_cached = 0;
    for (int32_t i = 0; i < n; ++i) {
        normal = ld32(normals + 20u * (uint32_t)i);
        slot = acc + 8u * (uint32_t)i;
        const uint64_t old = ld64(slot);
        if (normal == previous) {
            mm0 = mmx_paddsw(old, contribution);
            st64(slot, mm0);
            last_cached = 1;
            continue;
        }
        uint32_t dot = 0;
        for (int k = 0; k < 4; ++k) {
            const uint16_t word = (uint16_t)(((normal >> (8 * k)) & 0xFFu) * 0x101u);
            dot += (uint32_t)((int32_t)(int16_t)(uint16_t)(word - (uint16_t)bias_lane[k]) * (int32_t)light_lane[k]);
        }
        const int32_t scaled = (int32_t)dot >> 15;
        strength = scaled > 32767 ? 32767 : scaled > 0 ? (int16_t)scaled : 0;
        uint64_t packed = 0;
        for (int k = 0; k < 4; ++k) {
            /* PUNPCKLWD/PUNPCKHWD put products 0,1 and 2,3 in dword pairs: mm5 dword k&1. */
            const int32_t value = (int32_t)((uint32_t)((int32_t)strength * colour_lane[k]) +
                                            (uint32_t)((k & 1) ? round_high : round_low)) >> 13;
            packed |= (uint64_t)(uint16_t)(value > 32767 ? 32767 : value < -32768 ? -32768 : value) << (16 * k);
        }
        contribution = packed;
        mm6 = old;
        mm2 = mmx_paddsw(contribution, old);
        st64(slot, mm2);
        previous = normal;
        computed = 1;
        last_cached = 0;
    }
    if (computed) {
        /* The registers of the last computed vertex, then a later cached one's MM0. */
        const uint64_t splat = (uint64_t)(uint16_t)strength * 0x0001000100010001ull;
        const uint64_t high = mmx_pmulhw(splat, mm7), low = mmx_pmullw(splat, mm7);
        mm1 = low;
        mm3 = mmx_psrad(mmx_paddd(mmx_punpckhwd(low, high), mm5), 13);
        if (!last_cached) mm0 = high;
    }
    st32(S + 4u, normal);
    st32(S, slot);
    st64(S + 0x10u, contribution);
    g_mm[0] = mm0; g_mm[1] = mm1; g_mm[2] = mm2; g_mm[3] = mm3; g_mm[6] = mm6;
    g_backedges += (uint32_t)n;
    g_eax = (uint32_t)n;
    g_ecx = normal;
    g_edx = normals + 20u * (uint32_t)n;
    g_esp = E + 12u;
    return 1;
}

/* ------------------------------------------------- 00CF8F30 light curve */
/* EAX accumulator vector {begin, end} (8 bytes per vertex), EDX output
 * vector, [esp+4] input colour vector; RET 4. */
static int vertex_curve(void)
{
    const uint32_t E = g_esp, accumulators = g_eax, output = g_edx;
    if (E < 0x20u || !fits(E, 8)) return 0;
    const uint64_t frame = E - 20u, frame_size = 28;
    if (!fits(accumulators, 8) || !fits(output, 4) || !apart(accumulators, 8, frame, frame_size) ||
        !apart(output, 4, frame, frame_size)) return 0;
    const uint32_t acc = ld32(accumulators), acc_end = ld32(accumulators + 4u), out = ld32(output);
    const uint32_t input = ld32(E + 4u);
    if (!fits(input, 4) || !apart(input, 4, frame, frame_size)) return 0;
    const uint32_t in = ld32(input);
    const int32_t count = (int32_t)(acc_end - acc) >> 3;
    const uint32_t end = out + (uint32_t)count * 4u;
    uint32_t n = 0;
    if (out < end) {
        /* Only the plain forward walk; a wrapped bound runs the original. */
        if (count <= 0 || count > (1 << 24) || !fits(out, 4ull * (uint64_t)count)) return 0;
        n = (uint32_t)count;
        if (!no_handover(n)) return 0;
        /* Input, accumulators, table and output may overlap each other: the
         * loop reads and writes them in the original's order. The frame not. */
        if (!fits(acc, 8ull * n) || !fits(in, 4ull * n) ||
            !apart(acc, 8ull * n, frame, frame_size) || !apart(in, 4ull * n, frame, frame_size) ||
            !apart(out, 4ull * n, frame, frame_size) || !apart(VERTEX_CURVE_TABLE, 0x8000, frame, frame_size))
            return 0;
    }
    VERTEX_ENTER(0x00CF8F30u);
    st32(E - 4u, g_ecx);
    st32(E - 8u, g_ebp);
    st32(E - 12u, g_esi);
    st32(E - 16u, g_edi);
    st32(E - 4u, acc);
    const uint64_t mm7 = 0, mm6 = 0x4000400040004000ull;
    uint32_t eax = (uint32_t)count;
    if (n) {
        st32(E - 20u, g_ebx);
        uint64_t m0 = g_mm[0], m1 = g_mm[1], m2 = g_mm[2], m3 = g_mm[3];
        for (uint32_t i = 0; i < n; ++i) {
            const uint32_t colour = ld32(in + 4u * i);
            m0 = mmx_psrlw(mmx_punpcklbw(colour, colour), 1);
            m1 = m0;
            m0 = mmx_psllw(mmx_pmulhw(m0, m0), 1);
            m2 = m0;
            m0 = mmx_pmulhw(m0, m1);
            m2 = mmx_pmullw(m2, m1);
            m0 = mmx_psllw(m0, 1);
            m0 = mmx_paddsw(m0, ld64(acc + 8u * i));
            m0 = mmx_psrlw(m0, 1);
            m2 = mmx_psrlw(m2, 2) | mm6;
            m3 = mmx_pcmpeqw(m0, mm7);
            m2 &= m3;
            m3 = (~m3 & m0) | m2;
            const uint32_t low = (uint32_t)m3;
            m3 = mmx_psrlq(m3, 32);
            uint32_t value = ld8(VERTEX_CURVE_TABLE + (low & 0x7FFFu));
            value |= (uint32_t)ld8(VERTEX_CURVE_TABLE + ((low >> 16) & 0x7FFFu)) << 8;
            value |= (uint32_t)ld8(VERTEX_CURVE_TABLE + ((uint32_t)m3 & 0x7FFFu)) << 16;
            st32(out + 4u * i, value);
            eax = value;
        }
        st32(E + 4u, eax);
        st32(E - 4u, acc + 8u * n);
        g_mm[0] = m0; g_mm[1] = m1; g_mm[2] = m2; g_mm[3] = m3;
        g_backedges += n;
    }
    g_mm[6] = mm6;
    g_mm[7] = mm7;
    g_eax = eax;
    g_ecx = acc + 8u * n;
    g_edx = out + 4u * n;
    g_esp = E + 8u;
    return 1;
}

/* ------------------------------------------------- 00C687C0 bone blend */
typedef float vertex_f4 __attribute__((vector_size(16)));
typedef uint32_t vertex_u4 __attribute__((vector_size(16)));

/* tools/build_android.py packed_sse: the host product or sum, then x86's NaN
 * priority (destination, source, else the negative default NaN). */
static inline vertex_f4 sse_nan_rule(vertex_f4 r, vertex_f4 d, vertex_f4 s)
{
    vertex_u4 ru, du, su;
    memcpy(&ru, &r, sizeof ru); memcpy(&du, &d, sizeof du); memcpy(&su, &s, sizeof su);
    vertex_u4 rn = (ru & 0x7FFFFFFFu) > 0x7F800000u;
    if (__builtin_reduce_or(rn)) {
        vertex_u4 dn = (du & 0x7FFFFFFFu) > 0x7F800000u, sn = (su & 0x7FFFFFFFu) > 0x7F800000u;
        vertex_u4 nan = (dn & (du | 0x00400000u)) | (~dn & sn & (su | 0x00400000u)) | (~(dn | sn) & 0xFFC00000u);
        ru = (rn & nan) | (~rn & ru);
        memcpy(&r, &ru, sizeof r);
    }
    return r;
}
static inline vertex_f4 mulps(vertex_f4 d, vertex_f4 s) { return sse_nan_rule(d * s, d, s); }
static inline vertex_f4 addps(vertex_f4 d, vertex_f4 s) { return sse_nan_rule(d + s, d, s); }
static inline vertex_f4 ld128(uint32_t va) { vertex_f4 v; memcpy(&v, GPTR(va), 16); return v; }
static inline vertex_f4 splat(uint32_t bits)
{
    vertex_u4 u = {bits, bits, bits, bits};
    vertex_f4 v;
    memcpy(&v, &u, sizeof v);
    return v;
}
static inline uint32_t lane(vertex_f4 v, int i) { uint32_t b; memcpy(&b, (const char *)&v + 4 * i, 4); return b; }

/* One vertex of 00C687C0. `exact` applies the packed-SSE NaN rule to every
 * product and sum; regs receives xmm0..7 as the original leaves them. */
static inline __attribute__((always_inline)) vertex_f4 blend_vertex(uint32_t matrices, uint32_t weights, uint32_t in,
                                                                     int exact, vertex_f4 regs[8])
{
#define BLEND_MUL(d, s) (exact ? mulps((d), (s)) : (d) * (s))
#define BLEND_ADD(d, s) (exact ? addps((d), (s)) : (d) + (s))
    uint32_t bone = matrices + ((uint32_t)ld8(weights + 0x14u) << 6);
    vertex_f4 r0 = ld128(bone), r1 = ld128(bone + 0x10u), r2 = ld128(bone + 0x20u);
    const vertex_f4 r3 = ld128(bone + 0x30u);
    if (ld8(weights + 0x11u)) {
        vertex_f4 w = splat(ld32(weights));
        r0 = BLEND_MUL(r0, w); r1 = BLEND_MUL(r1, w); r2 = BLEND_MUL(r2, w);
        for (uint32_t k = 1; k < 4; ++k) {
            bone = matrices + ((uint32_t)ld8(weights + 0x14u + k) << 6);
            w = splat(ld32(weights + 4u * k));
            const vertex_f4 t0 = BLEND_MUL(ld128(bone), w), t1 = BLEND_MUL(ld128(bone + 0x10u), w),
                            t2 = BLEND_MUL(ld128(bone + 0x20u), w);
            r0 = BLEND_ADD(r0, t0); r1 = BLEND_ADD(r1, t1); r2 = BLEND_ADD(r2, t2);
            if (k == 3 || !ld8(weights + 0x11u + k)) break;
        }
    }
    /* The original's unpcklps/unpckhps transpose, as pure lane moves. */
    const vertex_f4 lo02 = __builtin_shufflevector(r0, r2, 0, 4, 1, 5), lo13 = __builtin_shufflevector(r1, r3, 0, 4, 1, 5),
                    hi02 = __builtin_shufflevector(r0, r2, 2, 6, 3, 7), hi13 = __builtin_shufflevector(r1, r3, 2, 6, 3, 7);
    const vertex_f4 c0 = __builtin_shufflevector(lo02, lo13, 0, 4, 1, 5), c1 = __builtin_shufflevector(lo02, lo13, 2, 6, 3, 7),
                    c2 = __builtin_shufflevector(hi02, hi13, 0, 4, 1, 5), c3 = __builtin_shufflevector(hi02, hi13, 2, 6, 3, 7);
    vertex_f4 p0 = BLEND_MUL(splat(ld32(in)), c0);
    vertex_f4 p1 = BLEND_MUL(splat(ld32(in + 4u)), c1);
    const vertex_f4 p2 = BLEND_MUL(splat(ld32(in + 8u)), c2);
    p0 = BLEND_ADD(p0, c3);
    p1 = BLEND_ADD(p1, p2);
    p0 = BLEND_ADD(p0, p1);
    regs[0] = splat(lane(p0, 2)); regs[1] = splat(lane(p0, 1)); regs[2] = p2; regs[3] = r3;
    regs[4] = c0; regs[5] = c1; regs[6] = c2; regs[7] = c3;
    return p0;
#undef BLEND_MUL
#undef BLEND_ADD
}

/* EAX vertex count, ECX -> bone matrix base (64 bytes each), [esp+4] positions
 * in, [esp+8] positions out (12 bytes each), [esp+12] weights (24 bytes:
 * float[4], 0x11..0x13 more-bone flags, 0x14..0x17 bone indices); RET 12. */
static int vertex_blend(void)
{
    const uint32_t E = g_esp, count = g_eax, matrix_pointer = g_ecx;
    if (E < 0x20u || !fits(E, 16)) return 0;
    const uint64_t frame = E - 20u, frame_size = 36;
    if (!fits(matrix_pointer, 4) || !apart(matrix_pointer, 4, frame, frame_size)) return 0;
    const int32_t n = (int32_t)count;
    uint32_t in = 0, out = 0, weights = 0;
    const uint32_t matrices = ld32(matrix_pointer);
    if (n > 0) {
        if (n > (1 << 24) || !no_handover((uint64_t)n)) return 0;
        in = ld32(E + 4u); out = ld32(E + 8u); weights = ld32(E + 12u);
        const uint64_t positions = 12ull * (uint64_t)n, records = 0x18ull * (uint64_t)n;
        /* Positions, weights and matrices may overlap each other: each vertex
         * reads all of its inputs before it writes, as the original. */
        if (!fits(in, positions) || !fits(out, positions) || !fits(weights, records) || !fits(matrices, 0x4000) ||
            !apart(in, positions, frame, frame_size) || !apart(out, positions, frame, frame_size) ||
            !apart(weights, records, frame, frame_size) || !apart(matrices, 0x4000, frame, frame_size)) return 0;
    }
    VERTEX_ENTER(0x00C687C0u);
    st32(E - 4u, g_ebp);
    st32(E - 8u, matrices);
    if (n <= 0) {
        g_edx = matrices;
        g_esp = E + 16u;
        return 1;
    }
    st32(E - 12u, g_ebx);
    st32(E - 16u, g_esi);
    st32(E - 20u, g_edi);
    vertex_f4 x[8];
    memcpy(x, g_xmm, sizeof x);
    for (int32_t i = 0; i < n; ++i, in += 12u, out += 12u, weights += 0x18u) {
        vertex_f4 p0;
        if (i + 1 < n) {
            /* Without the NaN rule first: a NaN anywhere in rows 0-2 or the
             * position reaches a stored lane (no arithmetic drops a NaN), so a
             * vertex whose three stored lanes are numbers has the exact bits.
             * Only the last vertex's registers are visible afterwards. */
            vertex_f4 scratch[8];
            p0 = blend_vertex(matrices, weights, in, 0, scratch);
            vertex_u4 bits;
            memcpy(&bits, &p0, sizeof bits);
            const vertex_u4 nan = (bits & 0x7FFFFFFFu) > 0x7F800000u;
            if (nan[0] | nan[1] | nan[2]) p0 = blend_vertex(matrices, weights, in, 1, scratch);
        } else {
            p0 = blend_vertex(matrices, weights, in, 1, x);
        }
        st32(out, lane(p0, 0));
        st32(out + 4u, lane(p0, 1));
        st32(out + 8u, lane(p0, 2));
    }
    memcpy(g_xmm, x, sizeof x);
    st32(E + 4u, in);
    st32(E + 8u, out);
    st32(E + 12u, weights);
    g_backedges += (uint32_t)n;
    g_eax = 0;
    g_ecx = 12;
    g_edx = matrices;
    g_esp = E + 16u;
    return 1;
}

/* -------------------------------------------- 00CF92C0 directional light */
/* EBX light {+0 base colour pair, +8/+10 front colours, +18 back colour,
 * +20 direction, +28 bias}, EDI index vector (only its length, 2 bytes per
 * vertex), stack: normal vector*, back-light flag (byte), back-light source,
 * diffuse vector*, specular vector*; RET 0x14. */
static void light_call(void (*function)(void), uint32_t eax, uint32_t ecx, uint32_t edx, uint32_t *esp)
{
    /* RECOMP_CALL_P(.., 0x17, 0x17, 0, ..): return slot, EAX/ECX/EDX/ESP in and out. */
    *esp -= 4u;
    st32(*esp, RECOMP_RETADDR);
    g_eax = eax; g_ecx = ecx; g_edx = edx; g_esp = *esp;
    function();
    *esp = g_esp;
}

typedef struct light_loop {
    uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi;
    uint64_t mm[8];
} light_loop;

/* One iteration exactly as the production body (memory re-read every time). */
static int light_step(light_loop *s)
{
    const uint32_t ebp = s->ebp, edi = s->edi;
    uint64_t *mm = s->mm;
    const uint32_t esp = s->esp;
    s->edx = ld32(esp + 0x2Cu);
    s->ecx = ld32(ld32(s->edx) + s->eax * 4u);
    const uint32_t previous = s->esi;
    st32(esp + 0x30u, s->ecx);
    if (s->ecx != previous) {
        s->esi = ld32(esp + 0x10u);
        mm[7] = (uint64_t)ld32(esp + 0x30u);
        mm[7] = mmx_punpcklbw(mm[7], mm[7]);
        mm[7] = mmx_psubw(mm[7], ld64(s->esi + 0x28u));
        mm[7] = mmx_pmaddwd(mm[7], ld64(s->esi + 0x20u));
        mm[6] = mmx_psrlq(mm[7], 32);
        mm[7] = mmx_paddd(mm[7], mm[6]);
        mm[7] = mmx_psrad(mm[7], 15);
        mm[7] = mmx_punpcklwd(mm[7], mm[7]);
        mm[7] = mmx_punpckldq(mm[7], mm[7]);
        mm[6] = mm[7];
        mm[5] = mm[7];
        mm[6] = mmx_psraw(mm[6], 16);
        mm[7] = mm[7] & mm[6];
        mm[6] = ~mm[6] & mm[5];
        mm[0] = mmx_pcmpeqw(mm[0], mm[0]);
        mm[7] = mm[7] ^ mm[0];
        mm[0] = ld64(s->esi);
        mm[1] = mm[0];
        mm[2] = ld64(s->esi + 8u);
        mm[3] = ld64(s->esi + 0x10u);
        mm[4] = ld64(s->esi + 0x18u);
        s->esi = ld32(esp + 0x3Cu);
        mm[5] = ld64(s->esi);
        mm[2] = mmx_pmulhw(mm[2], mm[6]);
        mm[3] = mmx_pmulhw(mm[3], mm[6]);
        mm[5] = mmx_pmulhw(mm[5], mm[7]);
        mm[4] = mmx_pmulhw(mm[4], mm[7]);
        mm[0] = mmx_paddw(mm[0], mm[2]);
        mm[1] = mmx_paddw(mm[1], mm[3]);
        mm[0] = mmx_paddw(mm[0], mm[5]);
        mm[1] = mmx_paddw(mm[1], mm[4]);
        mm[0] = mmx_psraw(mm[0], 4);
        mm[1] = mmx_psraw(mm[1], 4);
        mm[0] = mmx_packuswb(mm[0], mm[0]);
        mm[1] = mmx_packuswb(mm[1], mm[1]);
        st32(esp + 8u, (uint32_t)mm[0]);
        st32(esp + 0xCu, (uint32_t)mm[1]);
    }
    s->edx = ld32(ld32(esp + 0x38u));
    s->esi = ld32(esp + 8u);
    st32(s->edx + s->eax * 4u, s->esi);
    s->esi = ld32(esp + 0xCu);
    s->edx = ld32(ebp);
    st32(s->edx + s->eax * 4u, s->esi);
    s->esi = s->ecx;
    s->ecx = ld32(edi + 4u) - ld32(edi);
    s->eax += 1u;
    s->ecx = (uint32_t)((int32_t)s->ecx >> 1);
    return (int32_t)s->eax < (int32_t)s->ecx;
}

static int vertex_light(void)
{
    const uint32_t E = g_esp, ebx = g_ebx, edi = g_edi;
    if (E < 0x40u || !fits(E, 0x18)) return 0;
    VERTEX_ENTER(0x00CF92C0u);
    const uint32_t entry_ebp = g_ebp, entry_esi = g_esi;
    uint32_t esp = E - 0x20u;
    uint32_t eax = ld32(edi + 4u) - ld32(edi);
    uint32_t ecx = ld32(esp + 0x30u);
    esp -= 4u; st32(esp, entry_ebp);
    const uint32_t ebp = ld32(esp + 0x38u);
    esp -= 4u; st32(esp, entry_esi);
    eax = (uint32_t)((int32_t)eax >> 1);
    esp -= 4u; st32(esp, eax);
    light_call(sub_00738840, eax, ecx, g_edx, &esp);
    eax = g_eax; ecx = g_ecx; uint32_t edx = g_edx;
    ecx = ld32(edi + 4u) - ld32(edi);
    ecx = (uint32_t)((int32_t)ecx >> 1);
    esp -= 4u; st32(esp, ecx);
    ecx = ebp;
    light_call(sub_00738840, eax, ecx, edx, &esp);
    eax = g_eax; ecx = g_ecx; edx = g_edx;
    uint32_t esi = 0;
    const int back_light = ld8(esp + 0x30u) != 0;
    edx = ebx + 0x18u;
    st32(esp + 8u, esi);
    st32(esp + 0xCu, esi);
    st32(esp + 0x10u, ebx);
    st32(esp + 0x3Cu, edx);
    if (back_light) {
        ecx = ld32(esp + 0x34u);
        edx = ebx + 0x8Cu;
        eax = esp + 0x1Cu;
        light_call(sub_00CF8AC0, eax, ecx, edx, &esp);
        eax = g_eax; ecx = g_ecx; edx = g_edx;
        ecx = eax;
        eax = esp + 0x14u;
        light_call(sub_00CF88F0, eax, ecx, edx, &esp);
        eax = g_eax; ecx = g_ecx; edx = g_edx;
        st32(esp + 0x3Cu, eax);
    }
    ecx = ld32(edi + 4u) - ld32(edi);
    eax = 0;
    light_loop s;
    memcpy(s.mm, g_mm, sizeof s.mm);
    s.eax = eax; s.ecx = ecx; s.edx = edx; s.ebx = ebx; s.esp = esp; s.ebp = ebp; s.esi = esi; s.edi = edi;
    const int32_t masked = (int32_t)(ecx & 0xFFFFFFFEu);
    if (masked > 0) {
        /* Fast loop: everything it reads stays put while it writes the two
         * colour streams, and no hand-over falls inside it. */
        const uint32_t n = (uint32_t)((int32_t)ecx >> 1);
        const uint32_t normals_vector = ld32(esp + 0x2Cu), diffuse_vector = ld32(esp + 0x38u);
        const uint32_t light = ld32(esp + 0x10u), back = ld32(esp + 0x3Cu);
        const uint64_t frame = (uint64_t)esp, frame_size = 0x58;   /* spills .. the stack arguments */
        int fast = no_handover(n) && fits(normals_vector, 4) && fits(diffuse_vector, 4) && fits(ebp, 4) &&
                   fits(edi, 8) && fits(light, 0x30) && fits(back, 8);
        uint32_t normals = 0, diffuse = 0, specular = 0;
        if (fast) {
            normals = ld32(normals_vector); diffuse = ld32(diffuse_vector); specular = ld32(ebp);
            const uint64_t words = 4ull * n;
            fast = fits(normals, words) && fits(diffuse, words) && fits(specular, words);
            /* What the loop reads (frame, the three vector heads, the index vector
             * head, the light, the back colour, the normals) must not overlap what
             * it writes: the two streams and its own frame slots (the normal at
             * esp+0x30, the colour spills at esp+8). The streams may overlap each
             * other (written in the original's order), not the frame slots. */
            const uint64_t reads[][2] = {{frame, frame_size}, {normals_vector, 4}, {diffuse_vector, 4}, {ebp, 4},
                                         {edi, 8}, {light, 0x30}, {back, 8}, {normals, words}};
            const uint64_t writes[][2] = {{diffuse, words}, {specular, words}};
            const uint64_t slots[][2] = {{frame + 8u, 8}, {frame + 0x30u, 4}};
            for (unsigned w = 0; fast && w < 2; ++w)
                for (unsigned r = 0; fast && r < sizeof reads / sizeof reads[0]; ++r)
                    fast = apart(writes[w][0], writes[w][1], reads[r][0], reads[r][1]);
            for (unsigned w = 0; fast && w < 2; ++w)
                for (unsigned r = 1; fast && r < sizeof reads / sizeof reads[0]; ++r)
                    fast = apart(slots[w][0], slots[w][1], reads[r][0], reads[r][1]);
        }
        if (fast) {
            uint64_t *mm = s.mm;
            const uint64_t base_colour = ld64(light), front0 = ld64(light + 8u), front1 = ld64(light + 0x10u),
                           back1 = ld64(light + 0x18u), direction = ld64(light + 0x20u),
                           bias = ld64(light + 0x28u), back0 = ld64(back);
            /* Lane math: PMADDWD/PADDD wrap at 32 bits; PSRAD 15 and the two
             * unpacks keep the LOW word of the dword (no saturation here);
             * PMULHW is the high half of the signed product; PADDW wraps;
             * PSRAW 4 then PACKUSWB clamps to a byte. */
            int16_t bias_lane[4], direction_lane[4], base_lane[4], front0_lane[4], front1_lane[4], back0_lane[4], back1_lane[4];
            for (int k = 0; k < 4; ++k) {
                bias_lane[k] = (int16_t)(bias >> (16 * k)); direction_lane[k] = (int16_t)(direction >> (16 * k));
                base_lane[k] = (int16_t)(base_colour >> (16 * k));
                front0_lane[k] = (int16_t)(front0 >> (16 * k)); front1_lane[k] = (int16_t)(front1 >> (16 * k));
                back0_lane[k] = (int16_t)(back0 >> (16 * k)); back1_lane[k] = (int16_t)(back1 >> (16 * k));
            }
            uint32_t previous = 0, diffuse_value = ld32(esp + 8u), specular_value = ld32(esp + 0xCu), normal = 0;
            int16_t front = 0, behind = 0;
            int computed = 0;
            for (uint32_t i = 0; i < n; ++i) {
                normal = ld32(normals + 4u * i);
                if (normal != previous) {
                    uint32_t dot = 0;
                    for (int k = 0; k < 4; ++k) {
                        const uint16_t word = (uint16_t)(((normal >> (8 * k)) & 0xFFu) * 0x101u);
                        dot += (uint32_t)((int32_t)(int16_t)(uint16_t)(word - (uint16_t)bias_lane[k]) * (int32_t)direction_lane[k]);
                    }
                    const int16_t facing = (int16_t)(uint16_t)(uint32_t)((int32_t)dot >> 15);
                    front = facing < 0 ? 0 : facing;
                    behind = facing < 0 ? (int16_t)~facing : (int16_t)-1;
                    diffuse_value = specular_value = 0;
                    for (int k = 0; k < 4; ++k) {
                        const int16_t d = (int16_t)(uint16_t)((uint16_t)base_lane[k] +
                            (uint16_t)(((int32_t)front0_lane[k] * front) >> 16) + (uint16_t)(((int32_t)back0_lane[k] * behind) >> 16));
                        const int16_t s = (int16_t)(uint16_t)((uint16_t)base_lane[k] +
                            (uint16_t)(((int32_t)front1_lane[k] * front) >> 16) + (uint16_t)(((int32_t)back1_lane[k] * behind) >> 16));
                        const int d4 = d >> 4, s4 = s >> 4;
                        diffuse_value |= (uint32_t)(d4 < 0 ? 0 : d4 > 255 ? 255 : d4) << (8 * k);
                        specular_value |= (uint32_t)(s4 < 0 ? 0 : s4 > 255 ? 255 : s4) << (8 * k);
                    }
                    previous = normal;
                    computed = 1;
                }
                st32(diffuse + 4u * i, diffuse_value);
                st32(specular + 4u * i, specular_value);
            }
            if (computed) {
                /* The MMX registers as the last computed vertex left them. */
                mm[6] = (uint64_t)(uint16_t)front * 0x0001000100010001ull;
                mm[7] = (uint64_t)(uint16_t)behind * 0x0001000100010001ull;
                mm[2] = mmx_pmulhw(front0, mm[6]);
                mm[3] = mmx_pmulhw(front1, mm[6]);
                mm[5] = mmx_pmulhw(back0, mm[7]);
                mm[4] = mmx_pmulhw(back1, mm[7]);
                mm[0] = ((uint64_t)diffuse_value << 32) | diffuse_value;
                mm[1] = ((uint64_t)specular_value << 32) | specular_value;
            }
            st32(esp + 0x30u, normal);
            st32(esp + 8u, diffuse_value);
            st32(esp + 0xCu, specular_value);
            g_backedges += n;
            s.eax = n;
            s.ecx = n;
            s.edx = specular;
            s.esi = normal;
        } else {
            /* Literal loop with the hand-over at every backward branch: the
             * comparison is taken before it, the registers are reloaded after. */
            for (;;) {
                const int again = light_step(&s);
                if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {
                    g_backedges = 0;
                    g_eax = s.eax; g_ecx = s.ecx; g_edx = s.edx; g_ebx = s.ebx;
                    g_esp = s.esp; g_ebp = s.ebp; g_esi = s.esi; g_edi = s.edi;
                    memcpy(g_mm, s.mm, sizeof s.mm);
                    recomp_yield_hook();
                    s.eax = g_eax; s.ecx = g_ecx; s.edx = g_edx; s.ebx = g_ebx;
                    s.esp = g_esp; s.ebp = g_ebp; s.esi = g_esi; s.edi = g_edi;
                    memcpy(s.mm, g_mm, sizeof s.mm);
                }
                if (!again) break;
            }
        }
    }
    memcpy(g_mm, s.mm, sizeof s.mm);
    esp = s.esp;
    g_esi = ld32(esp);
    g_ebp = ld32(esp + 4u);
    g_eax = s.eax;
    g_ecx = s.ecx;
    g_edx = s.edx;
    g_ebx = s.ebx;
    g_edi = s.edi;
    g_esp = esp + 8u + 0x20u + 24u;
    return 1;
}

/* ------------------------------------------------------------- routes */
/* A kernel that cannot prove its fast path runs the original lifted body. */
void void_vertex_point(void) { if (!vertex_point()) sub_00CF8D80(); }
void void_vertex_curve(void) { if (!vertex_curve()) sub_00CF8F30(); }
void void_vertex_blend(void) { if (!vertex_blend()) sub_00C687C0(); }
void void_vertex_light(void) { if (!vertex_light()) sub_00CF92C0(); }

void void_vertex_point_dispatch(void) { if (vertex_native_enabled()) void_vertex_point(); else sub_00CF8D80(); }
void void_vertex_curve_dispatch(void) { if (vertex_native_enabled()) void_vertex_curve(); else sub_00CF8F30(); }
void void_vertex_blend_dispatch(void) { if (vertex_native_enabled()) void_vertex_blend(); else sub_00C687C0(); }
void void_vertex_light_dispatch(void) { if (vertex_native_enabled()) void_vertex_light(); else sub_00CF92C0(); }
