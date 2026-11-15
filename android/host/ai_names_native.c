/* The world's names table during the adventure AI's estimates (huge maps).
 *
 * On a 256x256 map with underground (2026-11-15, ToE, 7 AI players) the AI's
 * turn spends ~2/3 of the game thread in the destination wave's object
 * estimates (00BC5740 -> 00BC5480): each simulated visit runs inside the
 * world's undo transaction, whose rollback (0050C7C0) reads
 * NWorld::CObjectsNamesTable back and commits it again (0050C550 -> 0050C3E0:
 * memory stream and CRC), i.e. three passes of 00C01130 over every object
 * name of the map per estimate. The hottest leaves of those passes are
 * replaced here, exactly:
 *
 *   00BD1150  find in a string-keyed hash map (thiscall, RET 4): hash
 *             h = 5h + c over the key's NUL-terminated text, bucket h % n,
 *             then the chain, comparing lengths and calling msvcr71's
 *             strncmp (IAT 00E0A2B0) on equal lengths. Same code in 1.6 and
 *             2.1 (0083AC00, 00B79FC0).
 *   00404150  string assign(first, last) (thiscall, RET 8): copy over the
 *             current text, then append the rest. ToE pushes each remaining
 *             byte through push_back (004041C0); 1.6 and 2.1 (00405200,
 *             00403870) call append(first, last) (004091D0 in ToE: 00401E10,
 *             004220E0) with its own loop. A push_back that must grow calls
 *             the lifted grow 00404220 (00401CE0, 00403200; it reallocates
 *             through the game allocator), in ToE through the lifted
 *             004041C0.
 *
 * Each kernel leaves what its production body leaves (tools/build_android.py
 * transforms: masked call protocol, local backward-branch counter): all eight
 * registers (the production exits publish 0xFF; inner calls publish only
 * EAX/ECX/EDX/ESP (and EBX into the legacy append), so callee frames save the
 * globals' callee-saved registers), the guest memory including the dead
 * frame slots below the final ESP, the backward-branch count; lazy flags are
 * not published by these bodies and stay untouched. Paths that the kernels do
 * not cover (a hand-over falling inside the copy or hash loops, a shorter
 * assign that would call memmove, an unexpected strncmp import, a zero bucket
 * count) run the original body. tests/test_ai_names_native.py compares both
 * against the production bodies of all three editions.
 *
 * Addresses are ToE's; tools/port_patches.py maps them for 1.6 and 2.1.
 * <data>/native-ai-original = 1 runs the originals (with native-ai-live). */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include "native_mode.h"

extern void sub_00BD1150(void);
extern void sub_00404150(void);
#ifndef HOMM5_LEGACY_UI
extern void sub_004041C0(void);
#else
extern void sub_00404220(void);
#endif

#define AI_STRNCMP_IAT 0x00E0A2B0u    /* H5_Game.exe import: msvcr71!strncmp */
#define AI_STRNCMP     0x13002955u    /* msvcr71!strncmp (common to all three editions) */

int void_ai_live_original(int cached);   /* ai_turn_native.c: native-ai-live */

static int names_native_enabled(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-ai-original", "[ai-names] original=%d (cached for this process)");
    return !void_ai_live_original(cached);
}

static inline uint8_t ld8(uint32_t va) { return *(const uint8_t *)GPTR(va); }
static inline uint32_t ld32(uint32_t va) { uint32_t v; memcpy(&v, GPTR(va), 4); return v; }
static inline void st8(uint32_t va, uint8_t v) { *(uint8_t *)GPTR(va) = v; }
static inline void st32(uint32_t va, uint32_t v) { memcpy(GPTR(va), &v, 4); }

#if defined(RECOMP_TRACE)
#define NAMES_ENTER(va) (g_cur_func = (va), g_enter_trace[g_enter_idx++ & (RECOMP_ENTER_SIZE - 1)] = (va))
#elif defined(RECOMP_CALL_DIAG)
#define NAMES_ENTER(va) (g_cur_func = (va))
#else
#define NAMES_ENTER(va) ((void)0)
#endif

/* A hand-over (RECOMP_BACKEDGE) would fall inside `count` more backward branches. */
static inline int names_yield_inside(uint64_t count)
{
    return recomp_yield_hook && (uint64_t)g_backedges + count >= RECOMP_YIELD_EVERY;
}

/* ------------------------------------------------------------ 00BD1150 */
/* msvcr71 strncmp (13002955) as the production body computes it: the result
 * in EAX and ECX (0, -1 when s1 < s2 at the first difference within the
 * scanned length, +1 when greater), EDX untouched. */
static uint32_t names_strncmp(uint32_t s1, uint32_t s2, uint32_t n)
{
    if (!n) return 0;
    uint32_t scanned = 0;           /* repne scasb: bytes of s1 up to and including a NUL, at most n */
    while (scanned < n) {
        const uint8_t c = ld8(s1 + scanned);
        ++scanned;
        if (!c) break;
    }
    uint32_t i = 0;                 /* repe cmpsb over `scanned` bytes: stops after the first difference */
    uint8_t a = 0, b = 0;
    while (i < scanned) {
        a = ld8(s2 + i);
        b = ld8(s1 + i);
        ++i;
        if (a != b) break;
    }
    /* mov al,[esi-1]; cmp al,[edi-1]: the last compared bytes (s2 vs s1). */
    if (a > b) return 0xFFFFFFFFu;
    if (a == b) return 0;
    return 1;
}

void void_ai_name_find(void)
{
    const uint32_t ecx0 = g_ecx, ebx0 = g_ebx, esp0 = g_esp, ebp0 = g_ebp, esi0 = g_esi, edi0 = g_edi;
    const uint32_t key = ld32(esp0 + 4u), text = ld32(key);
    /* The hash loop: h = 5h + (signed char), one backward branch per byte. */
    uint32_t hash = 0, length = 0;
    for (uint8_t c; (c = ld8(text + length)) != 0; ++length) hash = hash * 5u + (uint32_t)(int32_t)(int8_t)c;
    const uint32_t buckets = (uint32_t)((int32_t)(ld32(ecx0 + 8u) - ld32(ecx0 + 4u)) >> 2);
    if (!buckets) { sub_00BD1150(); return; }       /* the lifted div's zero case: keep it literal */
    const uint32_t remainder = hash % buckets, head = ld32(ld32(ecx0 + 4u) + 4u * remainder);
    const uint32_t key_begin = ld32(key), key_len = ld32(key + 4u) - key_begin;
    if (head && ld32(AI_STRNCMP_IAT) != AI_STRNCMP) { sub_00BD1150(); return; }
    /* The chain (reads only): the match, the branch count and the last strncmp call. */
    uint32_t node = head, ecx = 0, call_node = 0, calls = 0;
    uint64_t chain_branches = 0;
    while (node) {
        const uint32_t b = ld32(node + 4u), len = ld32(node + 8u) - b;
        if (len == key_len) {
            ecx = names_strncmp(b, key_begin, len);
            call_node = node;
            ++calls;
            if (!ecx) break;
        } else {
            ecx = b;
        }
        node = ld32(node);
        ++chain_branches;
    }
    if (names_yield_inside((uint64_t)length + chain_branches)) { sub_00BD1150(); return; }
    NAMES_ENTER(0x00BD1150u);
    st32(esp0 - 4u, esi0);                          /* push esi; push edi */
    st32(esp0 - 8u, edi0);
    g_backedges += length + (uint32_t)chain_branches;
    g_ebx = ebx0; g_ebp = ebp0; g_esi = esi0; g_edi = edi0;
    g_esp = esp0 + 8u;
    if (!head) {                                    /* L_00BD11BE */
        g_eax = 0; g_ecx = ecx0; g_edx = remainder;
        return;
    }
    for (uint32_t i = 0; i < calls; ++i) NAMES_ENTER(AI_STRNCMP);   /* trace builds: each call's entry */
    (void)calls;
    st32(esp0 - 12u, ebx0);                         /* push ebx; push ebp */
    st32(esp0 - 16u, ebp0);
    if (call_node) {                                /* the last strncmp call's frame */
        st32(esp0 - 20u, key_len);                  /* push eax: the length */
        st32(esp0 - 24u, key_begin);                /* push edx */
        st32(esp0 - 28u, ld32(call_node + 4u));     /* push ecx */
        st32(esp0 - 32u, RECOMP_RETADDR);
        st32(esp0 - 36u, ebp0);                     /* strncmp saves EBP/EDI/ESI/EBX: unpublished */
        st32(esp0 - 40u, edi0);                     /* across that call, their entry values */
        st32(esp0 - 44u, esi0);
        st32(esp0 - 48u, ebx0);
    }
    g_eax = node;                                   /* the match, or 0 at the end of the chain */
    g_ecx = ecx;
    g_edx = key_begin;
}

/* ------------------------------------------------------------ 00404150 */
/* RECOMP_CALL_P(.., 0x17, 0x17, 0, ..): EAX/ECX/EDX/ESP out and in. */
static inline void names_call(void (*function)(void), uint32_t *eax, uint32_t *ecx, uint32_t *edx, uint32_t *esp)
{
    *esp -= 4u;
    st32(*esp, RECOMP_RETADDR);
    g_eax = *eax; g_ecx = *ecx; g_edx = *edx; g_esp = *esp;
    function();
    *eax = g_eax; *ecx = g_ecx; *edx = g_edx; *esp = g_esp;
}

#ifndef HOMM5_LEGACY_UI
static void names_assign(void)
{
    const uint32_t ecx0 = g_ecx, edx0 = g_edx, ebx0 = g_ebx, esp0 = g_esp, ebp0 = g_ebp, esi0 = g_esi, edi0 = g_edi;
    const uint32_t first = ld32(esp0 + 4u), last = ld32(esp0 + 8u);
    const uint32_t begin = ld32(ecx0), end = ld32(ecx0 + 4u);
    const uint32_t source = last - first, current = end - begin;
    /* The copy loop runs while both have bytes. A shorter source erases the
     * tail through memmove and an empty source with a non-empty string does
     * too: both stay literal. */
    if (first == last ? begin != end : source < current) { sub_00404150(); return; }
    const uint32_t copied = first == last ? 0 : current;
    if (names_yield_inside(copied)) { sub_00404150(); return; }
    NAMES_ENTER(0x00404150u);
    st32(esp0 - 4u, ebx0);                          /* push ebx; push esi; push edi */
    st32(esp0 - 8u, esi0);
    st32(esp0 - 12u, edi0);
    /* Registers as the production body holds them: EBX = last, EDI = this. */
    uint32_t eax = first, ecx = ecx0, edx = edx0, ebx = last, esp = esp0 - 12u, esi = begin, edi = ecx0, ebp = ebp0;
    for (uint32_t i = 0; i < copied; ++i) {         /* mov cl,[eax]; mov [esi],cl: in order */
        const uint8_t c = ld8(eax);
        st8(esi, c);
        ecx = (ecx & ~0xFFu) | c;
        ++eax; ++esi;
    }
    g_backedges += copied;
    if (eax != ebx) {
        /* push_back loop (004041A3): mov al,[esi]; mov ecx,edi; push eax; call 004041C0.
         * EBX/ESI/EDI/EBP stay unpublished in the globals except at a hand-over. */
        for (esi = eax;;) {
            const uint8_t c = ld8(esi);
            eax = (eax & ~0xFFu) | c;
            ecx = edi;
            esp -= 4u;
            st32(esp, eax);
            const uint32_t tail = ld32(edi + 4u);
            if (tail + 1u == ld32(edi + 8u)) {
                names_call(sub_004041C0, &eax, &ecx, &edx, &esp);   /* grows: the lifted push_back */
            } else {                                /* 004041C0 without growth */
                NAMES_ENTER(0x004041C0u);
                const uint32_t p = esp - 4u;        /* its return slot */
                st32(p, RECOMP_RETADDR);
                st32(p - 12u, g_esi);               /* sub esp,8; push esi: the global ESI */
                st8(tail + 1u, 0);
                st8(tail, c);
                st32(edi + 4u, tail + 1u);
                eax = tail;
                ecx = tail;
                edx = (edx & ~0xFFu) | c;
                esp += 4u;                          /* ret 4 */
            }
            ++esi;
            const int more = esi != ebx;            /* cmp esi, ebx before the hand-over */
            if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {
                g_backedges = 0;                    /* RECOMP_BACKEDGE: every register out and in */
                g_eax = eax; g_ecx = ecx; g_edx = edx; g_ebx = ebx; g_esp = esp; g_ebp = ebp; g_esi = esi; g_edi = edi;
                recomp_yield_hook();
                eax = g_eax; ecx = g_ecx; edx = g_edx; ebx = g_ebx; esp = g_esp; ebp = g_ebp; esi = g_esi; edi = g_edi;
            }
            if (!more) break;
        }
    }
    /* mov eax,edi; pop edi; pop esi; pop ebx; ret 8 */
    g_eax = edi; g_ecx = ecx; g_edx = edx;
    g_edi = ld32(esp); g_esi = ld32(esp + 4u); g_ebx = ld32(esp + 8u); g_ebp = ebp;
    g_esp = esp + 24u;
}
#else
/* 1.6 / 2.1 (00405200 / 00403870): the copy moves bytes through DL, the rest
 * goes to append(first, last) (004091D0: 00401E10 / 004220E0). */
static void names_assign(void)
{
    const uint32_t ecx0 = g_ecx, edx0 = g_edx, ebx0 = g_ebx, esp0 = g_esp, ebp0 = g_ebp, esi0 = g_esi, edi0 = g_edi;
    const uint32_t first = ld32(esp0 + 4u), last = ld32(esp0 + 8u);
    const uint32_t begin = ld32(ecx0), end = ld32(ecx0 + 4u);
    const uint32_t source = last - first, current = end - begin;
    if (first == last ? begin != end : source < current) { sub_00404150(); return; }
    const uint32_t copied = first == last ? 0 : current;
    if (names_yield_inside(copied)) { sub_00404150(); return; }
    NAMES_ENTER(0x00404150u);
    st32(esp0 - 4u, esi0);                          /* push esi; push edi */
    st32(esp0 - 8u, edi0);
    /* mov edi,ecx; mov ecx,[esp+0x10] (last); mov esi,[edi] */
    uint32_t eax = first, ecx = last, edx = edx0, esi = begin, edi = ecx0;
    for (uint32_t i = 0; i < copied; ++i) {         /* mov dl,[eax]; mov [esi],dl: in order */
        const uint8_t c = ld8(eax);
        st8(esi, c);
        edx = (edx & ~0xFFu) | c;
        ++eax; ++esi;
    }
    g_backedges += copied;
    if (eax == last) {                              /* L_0040522B: push ebx; the tail is empty */
        st32(esp0 - 12u, ebx0);
        g_eax = edi; g_ecx = ecx; g_edx = edx; g_ebx = ebx0; g_ebp = ebp0;
        g_edi = ld32(esp0 - 8u); g_esi = ld32(esp0 - 4u);
        g_esp = esp0 + 12u;
        return;
    }
    /* L_00405253: push ecx; push eax; mov ecx,edi; call append (in: EAX ECX EDX EBX ESP). */
    st32(esp0 - 12u, ecx);
    st32(esp0 - 16u, eax);
    uint32_t esp = esp0 - 20u;
    st32(esp, RECOMP_RETADDR);
    const uint32_t entry = esp;                     /* append's entry ESP */
    NAMES_ENTER(0x004091D0u);
    /* push ecx; push esi; push edi (the globals: the assign published neither); then
     * mov edi,[esp+0x10] (first); mov esi,ecx; push ebx; push ebp; mov ebp,1. */
    uint32_t ebx = ebx0, ebp;
    ecx = edi;
    st32(entry - 4u, ecx);
    st32(entry - 8u, g_esi);
    st32(entry - 12u, g_edi);
    edi = ld32(entry + 4u);
    esi = ecx;
    st32(entry - 16u, ebx);
    st32(entry - 20u, g_ebp);
    esp = entry - 20u;
    ebp = 1;
    for (;;) {                                      /* L_00401E26 */
        eax = ld32(esi + 4u);
        ebx = (ebx & ~0xFFu) | ld8(edi);            /* mov bl,[edi] */
        ecx = eax + 1u;
        if (ecx == ld32(esi + 8u)) {                /* grows: lifted 00404220(size + max(size, 1)) */
            eax -= ld32(esi);
            st32(esp + 0x18u, ebp);
            st32(esp + 0x10u, eax);
            ecx = eax < ebp ? esp + 0x18u : esp + 0x10u;
            edx = ld32(ecx) + eax;
            esp -= 4u;
            st32(esp, edx);
            ecx = esi;
            names_call(sub_00404220, &eax, &ecx, &edx, &esp);
        }
        eax = ld32(esi + 4u);
        st8(eax + 1u, 0);
        ecx = ld32(esi + 4u);
        st8(ecx, (uint8_t)ebx);
        st32(esi + 4u, ld32(esi + 4u) + ebp);
        edi += ebp;
        const int more = edi != ld32(esp + 0x1Cu);  /* cmp edi,[esp+0x1c] before the hand-over */
        if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {
            g_backedges = 0;                        /* RECOMP_BACKEDGE: every register out and in */
            g_eax = eax; g_ecx = ecx; g_edx = edx; g_ebx = ebx; g_esp = esp; g_ebp = ebp; g_esi = esi; g_edi = edi;
            recomp_yield_hook();
            eax = g_eax; ecx = g_ecx; edx = g_edx; ebx = g_ebx; esp = g_esp; ebp = g_ebp; esi = g_esi; edi = g_edi;
        }
        if (!more) break;
    }
    /* pop ebp; pop ebx; pop edi; mov eax,esi; pop esi; pop ecx; ret 8: of the
     * append's registers the assign takes EAX/ECX/EDX/ESP back, then
     * mov eax,edi; pop edi; pop esi; ret 8 with its own EBX/EBP/EDI. */
    ecx = ld32(esp + 16u);
    esp += 32u;
    g_eax = ecx0; g_ecx = ecx; g_edx = edx;
    g_ebx = ebx0; g_ebp = ebp0;
    g_edi = ld32(esp); g_esi = ld32(esp + 4u);
    g_esp = esp + 20u;
}
#endif

void void_ai_string_assign(void) { names_assign(); }

void void_ai_name_find_dispatch(void) { if (names_native_enabled()) void_ai_name_find(); else sub_00BD1150(); }
void void_ai_string_assign_dispatch(void) { if (names_native_enabled()) void_ai_string_assign(); else sub_00404150(); }
