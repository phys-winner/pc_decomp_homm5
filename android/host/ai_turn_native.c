/* Adventure AI turn markers and the switches of the AI kernels (ai_*_native.c).
 *
 * NWorld::CPlayerAI's step 0086DD40 (vtable 00E4C8BC slot 0, thiscall, RET 8)
 * runs the AI's state machine (state at this+0x128: 0 INIT_DAY ... 9
 * RETURN_TURN; 00866550 names them) until one step takes aai_step_limit ms
 * (00F440D4, 30) or produces commands; the frame loop (006082F0) calls it
 * again. The turn of one AI player starts with INIT_DAY (state 0 on entry;
 * SFLB_InitDay 00867440 clears the call counter at this+0x10, the step adds
 * one) and ends when RETURN_TURN puts the state back to 0 (00868E00).
 *
 * void_ai_step (behind the step's dispatch row, tools/native_routes.py group
 * ai_step) calls the lifted body unchanged. It reads guest memory
 * and the clock only, so the game sees exactly the original. Per AI turn:
 *   [ai-turn] begin ai OBJECT day D
 *   [ai-turn] end ai OBJECT: wall W ms, ai A ms, calls C, longest L ms
 * wall = INIT_DAY call to the call that ended the turn, ai = time inside the
 * step (the AI's own work: waves, estimates, choices; not the frames and not
 * the playback of its commands), calls = step calls (at most one per frame).
 *
 * Switches for every AI kernel of this batch (ai_*_native.c):
 *   <data>/native-ai-original = 1   originals for the whole process
 *   <data>/native-ai-live           exists at the first query: its first byte
 *                                   is read again at most once a second
 *                                   ('1' originals, anything else kernels).
 * Addresses are ToE's; tools/port_patches.py maps them for 1.6 and 2.1
 * (config/{vanilla,hof}.patches.json: reference_addresses of this file). */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include "native_mode.h"

extern void sub_0086DD40(void);
void void_ai_undo_counts(uint64_t *estimates, uint64_t *elided, uint64_t *failures);   /* ai_undo_native.c */
uint32_t void_ai_undo_world(void);

/* CPlayerAI fields: ToE and 1.6 share the layout; 2.1 keeps its own start
 * time at +0x10 (world clock, vtable +0x9C), so the later fields move by 4
 * (00A79EE0 clears +0x14..+0x20, 00A801F0 switches on +0x130). */
#if defined(HOMM5_EDITION)
#define AI_HOF (HOMM5_EDITION[0] == 'h')
#else
#define AI_HOF 0
#endif
#define AI_STATE_OFFSET (AI_HOF ? 0x130u : 0x128u)   /* current step (00866550 names) */
#define AI_CALLS_OFFSET (AI_HOF ? 0x14u : 0x10u)     /* step calls of this turn */
#define AI_DAY_OFFSET (AI_HOF ? 0x24u : 0x20u)       /* the day this turn plays */

/* ---------------------------------------------------------------- mode */
static int ai_live_read(char *first)
{
    char path[1024];
    const char *directory = void_data_dir();
    int length = directory ? snprintf(path, sizeof path, "%s/native-ai-live", directory) : -1;
    if (length < 0 || (size_t)length >= sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    int c = fgetc(file);
    fclose(file);
    *first = c == EOF ? 0 : (char)c;
    return 1;
}

/* Shared by the AI kernels (ai_*_native.c): the live choice over their cached one. */
int void_ai_live_original(int cached)
{
    static _Atomic(int) live = -2;          /* -2 not looked at, -1 no live file, 0/1 the live choice */
    static _Atomic(uint64_t) next_read;
    int choice = __c11_atomic_load(&live, __ATOMIC_ACQUIRE);
    if (choice == -1) return cached;
    char first = 0;
    if (choice == -2) {
        if (!ai_live_read(&first)) {
            __c11_atomic_store(&live, -1, __ATOMIC_RELEASE);
            return cached;
        }
    } else {
        const uint64_t now = void_perf_now_ns();
        if (now < __c11_atomic_load(&next_read, __ATOMIC_RELAXED)) return choice;
        if (!ai_live_read(&first)) first = choice ? '1' : '0';
    }
    const int next = first == '1';
    __c11_atomic_store(&next_read, void_perf_now_ns() + 1000000000ull, __ATOMIC_RELAXED);
    if (next != choice) void_log("[ai-native] live original=%d", next);
    __c11_atomic_store(&live, next, __ATOMIC_RELEASE);
    return next;
}

int void_ai_native_enabled(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-ai-original", "[ai-native] original=%d (cached for this process)");
    return !void_ai_live_original(cached);
}

/* ------------------------------------------------------------ markers */
static inline uint32_t ld32(uint32_t va) { uint32_t v; memcpy(&v, GPTR(va), 4); return v; }

/* ------------------------------------------------------------ digest */
/* <data>/ai-digest = 1 (read once per process): at the end of every AI turn
 * the player and each of its heroes are hashed with the game's own CRC of an
 * object, 00B62380 (fastcall: seed ECX, object EDX; a CWorldCRCSaver runs the
 * object's save serialization through adler32 and counts object references
 * in first-seen order, so the value does not depend on heap addresses):
 *   [ai-digest] ai OBJECT day D: player CRC, heroes N, CRC CRC ...
 * The game's own serialization allocates and frees memory, so this mode is a
 * diagnostic for comparing runs, not part of normal play; every register,
 * the lazy flags and the backward-branch counter are kept around it. */
#define AI_OBJECT_CRC 0x00B62380u
#define AI_PLAYER_HEROES 0xC0u          /* player vtable: the vector of its heroes */

/* A diagnostic flag, not a native-mode switch: read once by the game thread
 * (the only caller), so a plain atomic cache is enough. */
static int ai_digest_enabled(void)
{
    static _Atomic(int) digest = -2;
    int value = __c11_atomic_load(&digest, __ATOMIC_ACQUIRE);
    if (value != -2) return value;
    char path[1024];
    const char *directory = void_data_dir();
    int length = directory ? snprintf(path, sizeof path, "%s/ai-digest", directory) : -1;
    value = 0;
    if (length >= 0 && (size_t)length < sizeof path) {
        FILE *file = fopen(path, "rb");
        if (file) {
            value = fgetc(file) == '1';
            fclose(file);
        }
    }
    void_log("[ai-digest] mode=%d (read once for this process)", value);
    __c11_atomic_store(&digest, value, __ATOMIC_RELEASE);
    return value;
}

typedef struct ai_saved {
    uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi, flag_k, flag_a, flag_b, flag_cf, backedges;
} ai_saved;

static void ai_save(ai_saved *s)
{
    *s = (ai_saved){g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi,
                    g_flag_k, g_flag_a, g_flag_b, g_flag_cf, g_backedges};
}

static void ai_restore(const ai_saved *s)
{
    g_eax = s->eax; g_ecx = s->ecx; g_edx = s->edx; g_ebx = s->ebx;
    g_esp = s->esp; g_ebp = s->ebp; g_esi = s->esi; g_edi = s->edi;
    g_flag_k = s->flag_k; g_flag_a = s->flag_a; g_flag_b = s->flag_b; g_flag_cf = s->flag_cf;
    g_backedges = s->backedges;
}

/* The object's virtual base (refcount, alive bit at +11) must be readable. */
static int ai_object_alive(uint32_t object)
{
    if (!object || !void_vm_readable(object, 8)) return 0;
    const uint32_t bases = ld32(object + 4);
    if (!void_vm_readable(bases, 8)) return 0;
    const uint32_t base = object + 4 + ld32(bases + 4);
    return void_vm_readable(base, 12) && !(*(const uint8_t *)GPTR(base + 11) & 0x80u);
}

static uint32_t ai_object_crc(uint32_t object)
{
    if (!ai_object_alive(object)) return 0;
    g_ecx = 0;
    g_edx = object;
    return void_call_guest(AI_OBJECT_CRC, 0, NULL, 0);
}

static void ai_digest(uint32_t object)
{
    const uint32_t player = ld32(object + 8u);
    if (!ai_object_alive(player) || !void_vm_readable(ld32(player), AI_PLAYER_HEROES + 4)) return;
    ai_saved saved;
    ai_save(&saved);
    char line[1536];
    const uint32_t player_crc = ai_object_crc(player);
    const uint32_t heroes = void_call_guest_this(ld32(ld32(player) + AI_PLAYER_HEROES), player, 0, NULL);
    uint32_t begin = 0, end = 0;
    if (heroes && void_vm_readable(heroes, 8)) { begin = ld32(heroes); end = ld32(heroes + 4); }
    const uint32_t count = end >= begin && end - begin < 4096 ? (end - begin) / 4u : 0;
    int used = snprintf(line, sizeof line, "player %08X, heroes %u, CRC", player_crc, count);
    for (uint32_t i = 0; i < count && used > 0 && (size_t)used < sizeof line - 12; ++i) {
        const uint32_t hero = ld32(begin + 4u * i);
        used += snprintf(line + used, sizeof line - (size_t)used, " %08X", ai_object_crc(hero));
    }
    ai_restore(&saved);
    const uint32_t world = void_ai_undo_world();     /* the world's RNG seed (slot 8 draws from +0x64) */
    const uint32_t seed = world && void_vm_readable(world + 0x64u, 4) ? ld32(world + 0x64u) : 0;
    void_log("[ai-digest] ai %08X day %u: %s; rng %08X", object, ld32(object + AI_DAY_OFFSET), line, seed);
}


typedef struct ai_turn {
    uint32_t object;        /* CPlayerAI */
    int active;
    uint64_t begin_ns, ai_ns, longest_ns;
    uint32_t calls;
    uint32_t state_calls[16];   /* step calls by the state they entered with */
    uint64_t state_ns[16];
} ai_turn;

static ai_turn turns[16];

static ai_turn *ai_turn_of(uint32_t object)
{
    ai_turn *free_slot = NULL;
    for (unsigned i = 0; i < sizeof turns / sizeof *turns; ++i) {
        if (turns[i].object == object) return &turns[i];
        if (!turns[i].object && !free_slot) free_slot = &turns[i];
    }
    if (!free_slot) free_slot = &turns[0];
    memset(free_slot, 0, sizeof *free_slot);
    free_slot->object = object;
    return free_slot;
}


static void ai_turn_end(ai_turn *turn, uint64_t end, const char *how)
{
    char states[512];
    size_t used = 0;
    states[0] = 0;
    for (unsigned i = 0; i < 16 && used < sizeof states; ++i) {
        if (!turn->state_calls[i]) continue;
        int n = snprintf(states + used, sizeof states - used, " %u:%u/%.1f", i, turn->state_calls[i],
                         (double)turn->state_ns[i] / 1e6);
        if (n < 0) break;
        used += (size_t)n;
    }
    uint64_t estimates = 0, elided = 0, failures = 0;
    void_ai_undo_counts(&estimates, &elided, &failures);
    void_log("[ai-turn] end ai %08X%s: wall %.1f ms, ai %.1f ms, calls %u, longest %.1f ms; by state%s; "
             "names snapshots elided %llu in %llu estimates%s",
             turn->object, how, (double)(end - turn->begin_ns) / 1e6, (double)turn->ai_ns / 1e6, turn->calls,
             (double)turn->longest_ns / 1e6, states, (unsigned long long)elided, (unsigned long long)estimates,
             failures ? " (switched off: a rollback did not restore an entry)" : "");
    turn->active = 0;
    if (ai_digest_enabled()) ai_digest(turn->object);
}

void void_ai_step(void)
{
    const uint32_t object = g_ecx;
    const int readable = void_vm_readable(object, AI_STATE_OFFSET + 4);
    const uint32_t before = readable ? ld32(object + AI_STATE_OFFSET) : ~0u;
    const uint64_t start = void_perf_now_ns();
    sub_0086DD40();
    const uint64_t end = void_perf_now_ns();
    if (!readable || !void_vm_readable(object, AI_STATE_OFFSET + 4)) return;
    const uint32_t after = ld32(object + AI_STATE_OFFSET), calls = ld32(object + AI_CALLS_OFFSET);
    ai_turn *turn = ai_turn_of(object);
    if (before == 0u && calls == 1u) {
        if (turn->active) ai_turn_end(turn, start, " unseen");
        turn->active = 1;
        turn->begin_ns = start;
        turn->ai_ns = turn->longest_ns = 0;
        turn->calls = 0;
        memset(turn->state_calls, 0, sizeof turn->state_calls);
        memset(turn->state_ns, 0, sizeof turn->state_ns);
        void_log("[ai-turn] begin ai %08X day %u", object, ld32(object + AI_DAY_OFFSET));
    }
    if (!turn->active) return;
    turn->ai_ns += end - start;
    if (end - start > turn->longest_ns) turn->longest_ns = end - start;
    ++turn->calls;
    ++turn->state_calls[before & 15u];
    turn->state_ns[before & 15u] += end - start;
    if (after == 0u) ai_turn_end(turn, end, "");
}

/* The step's dispatch row (tools/native_routes.py): the markers never change the step. */
void void_ai_step_dispatch(void) { void_ai_step(); }
