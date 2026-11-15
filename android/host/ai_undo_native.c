/* The names table's snapshots in the adventure AI's estimate rollbacks (port option port_fast_ai).
 *
 * An object estimate of the destination wave, 00BC5480 (1.6 004847F0, 2.1 00848150), simulates a
 * visit inside the world's undo transaction and rolls it back to the transaction id it saved
 * (estimate +0x14) through the world's slot 2, 0050C7C0 (00A566E0, 004DC770):
 *  1. commit (slot 0, 0050C550; 00A56470, 004DC500): for every object the visit touched, a new
 *     history record takes the entry's state (snapshot bytes, checksum +28, flag +32, CRC +36),
 *     then 0050C3E0 (00A56300, 004DC390) snapshots the object's current state into the entry:
 *     CChunklessSerializer save, checksum 00B62340, CWorldCRCSaver object CRC 00B62380;
 *  2. pop: every transaction newer than the target is undone and each record is copied back
 *     into its entry (008C7E70 frees the entry's bytes and copies the record's; +28/+32/+36
 *     from the record), so what step 1 wrote into an entry is never read;
 *  3. the references of the restored snapshots are collected and the touched objects are read
 *     back from them.
 * Nothing between 1 and 2 reads an entry; 0050C4A0 (00A563C0, 004DC450), which snapshots every
 * object when a full snapshot is pending, is never skipped.
 *
 * On a huge map the visits touch NWorld::CObjectsNamesTable, whose serializer 00C01130 (vtable
 * slot 3; 00B5AAA0, 009E3C60) walks every object name of the map; its save and CRC in step 1
 * were ~29% of the game thread on a 256x256 map (2026-11-15). Only those two calls are skipped:
 * the snapshot's save stream and its CRC saver get an empty chunk, and the world's "references
 * written" byte (+16) gets the value a real save of this table leaves. After the rollback the
 * entry must hold its pre-commit +28/+32/+36 again, else the skipping stops for the process and
 * the log says so. The history record, the pop, the read-back and the world CRCs that LAN and
 * replays compare (slots 3 and 4: sums of +28 and +36 over the entries) read exactly what the
 * original path gives them. What differs is the heap: the skipped passes do not allocate and
 * free their temporary strings, vectors and stream bytes.
 *
 * Any failed condition runs the original: the port option port_fast_ai is on,
 * <data>/native-ai-original is not 1 (with native-ai-live), no socket has been opened in
 * this process (network.c; network games keep the original path), the rollback is the estimate's own
 * (called within UNDO_ROLLBACK_REACH below it, target = estimate +0x14, and the commit's
 * transaction is popped again: target <= world +24), the commit is that rollback's (entry ESP
 * UNDO_COMMIT_BELOW_ROLLBACK below it, same world), the snapshot is that commit's history-record
 * snapshot (flag argument 1, object not new: +13 == 0, entry +24 is the object) of an object
 * whose serializer is 00C01130, no full snapshot is running, the streams are that snapshot's
 * (save: CChunklessSerializer, mode 2, owner world +8, target the entry; then a CWorldCRCSaver)
 * and a real save of the table has shown its +16 value. Frames are per host thread.
 *
 * Addresses are ToE's; tools/port_patches.py maps them for 1.6 and 2.1. */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include "native_mode.h"

extern void sub_00BC5480(void);
extern void sub_0050C7C0(void);
extern void sub_0050C550(void);
extern void sub_0050C4A0(void);
extern void sub_0050C3E0(void);
extern void sub_00C01130(void);

int void_port_fast_ai(void);            /* port_settings.c: the fast AI turn option */
int void_network_started(void);         /* network.c: WinSock started in this process */
int void_ai_live_original(int cached);  /* ai_turn_native.c: native-ai-live */

#define UNDO_CHUNKLESS 0x00E8D7BCu          /* CChunklessSerializer vtable (00C48D10 builds it) */
#define UNDO_CRC_SAVER 0x00E93664u          /* CWorldCRCSaver vtable (00CAB350) */
#define UNDO_NAMES_SERIALIZE 0x00C01130u    /* the names table's slot 3 */
#define UNDO_COMMIT_BELOW_ROLLBACK 0x54u    /* sub esp,40h; 4 pushes; call [eax] */
#define UNDO_ROLLBACK_REACH 0x200u          /* the estimate calls its rollback itself */

static inline uint8_t ld8(uint32_t va) { return *(const uint8_t *)GPTR(va); }
static inline uint32_t ld32(uint32_t va) { uint32_t v; memcpy(&v, GPTR(va), 4); return v; }
static inline void st8(uint32_t va, uint8_t v) { *(uint8_t *)GPTR(va) = v; }

typedef struct {
    uint32_t estimate_esp, estimate_this;   /* 00BC5480 */
    int allowed;
    uint32_t rollback_esp, world;           /* its rollback */
    uint32_t commit_esp;                    /* that rollback's commit */
    uint32_t full_esp;                      /* a running 0050C4A0 */
    uint32_t snap_esp, snap_entry, snap_this;   /* the running 0050C3E0 */
    int snap_elide, save_left, crc_left, save_skipped;
    uint32_t start_index, start[3];         /* the names entry when the estimate first snapshots it */
    int start_set, check_set;               /* ...and whether one of its snapshots was elided */
} undo_frames;

static _Thread_local undo_frames frames;
static _Atomic(int) names_flag = -1;        /* +16 after a real save of the names table */
static _Atomic(int) disabled;               /* a rollback did not restore an elided entry */
static _Atomic(uint64_t) estimates, elided, verified, failures;
static _Atomic(uint32_t) last_world;        /* for the turn digests: the world of the last rollback */

static int undo_allowed(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-ai-original", "[ai-undo] original=%d (cached for this process)");
    if (void_ai_live_original(cached) || __c11_atomic_load(&disabled, __ATOMIC_RELAXED)) return 0;
    return void_port_fast_ai() && !void_network_started();
}

uint32_t void_ai_undo_world(void) { return __c11_atomic_load(&last_world, __ATOMIC_RELAXED); }

/* For the AI turn markers: snapshots elided and estimates seen since the last call. */
void void_ai_undo_counts(uint64_t *estimates_out, uint64_t *elided_out, uint64_t *failures_out)
{
    *estimates_out = __c11_atomic_exchange(&estimates, 0, __ATOMIC_RELAXED);
    *elided_out = __c11_atomic_exchange(&elided, 0, __ATOMIC_RELAXED);
    *failures_out = __c11_atomic_load(&failures, __ATOMIC_RELAXED);
}

/* ------------------------------------------------------------ 00BC5480 */
void void_ai_estimate(void)
{
    const undo_frames outer = frames;
    memset(&frames, 0, sizeof frames);
    frames.estimate_esp = g_esp;
    frames.estimate_this = g_ecx;
    frames.allowed = undo_allowed();
    if (frames.allowed) __c11_atomic_fetch_add(&estimates, 1, __ATOMIC_RELAXED);
    sub_00BC5480();
    frames = outer;
}

/* ------------------------------------------------------------ 0050C7C0 */
/* The pop must have put the names entry back to its state at the estimate's start. */
static void undo_verify(uint32_t world)
{
    const uint32_t table = ld32(world + 28u), count = (ld32(world + 32u) - table) / 40u;
    const uint32_t entry = table + 40u * frames.start_index;
    if (frames.start_set && frames.start_index < count && ld32(entry + 28u) == frames.start[0] &&
        ld8(entry + 32u) == frames.start[1] && ld32(entry + 36u) == frames.start[2]) {
        __c11_atomic_fetch_add(&verified, 1, __ATOMIC_RELAXED);
        return;
    }
    __c11_atomic_store(&disabled, 1, __ATOMIC_RELAXED);
    if (__c11_atomic_fetch_add(&failures, 1, __ATOMIC_RELAXED) == 0)
        void_log("[ai-undo] rollback left entry %u at %08X/%02X/%08X, expected %08X/%02X/%08X: names snapshots "
                 "are taken again for this process", frames.start_index, frames.start_index < count ? ld32(entry + 28u) : 0,
                 frames.start_index < count ? ld8(entry + 32u) : 0, frames.start_index < count ? ld32(entry + 36u) : 0,
                 frames.start[0], frames.start[1], frames.start[2]);
}

void void_ai_rollback(void)
{
    const uint32_t esp = g_esp, world = g_ecx, target = ld32(esp + 4u);
    if (frames.estimate_esp) __c11_atomic_store(&last_world, world, __ATOMIC_RELAXED);
    if (!frames.allowed || !frames.estimate_esp || esp >= frames.estimate_esp ||
        frames.estimate_esp - esp > UNDO_ROLLBACK_REACH || frames.rollback_esp ||
        target != ld32(frames.estimate_this + 0x14u) || target > ld32(world + 24u)) {
        sub_0050C7C0();
        return;
    }
    frames.rollback_esp = esp;
    frames.world = world;
    frames.check_set = 0;
    sub_0050C7C0();
    if (frames.check_set) undo_verify(world);
    frames.rollback_esp = frames.world = frames.commit_esp = frames.full_esp = frames.snap_esp = 0;
    frames.check_set = 0;
}

/* ------------------------------------------------------------ 0050C550 */
void void_ai_commit(void)
{
    if (frames.rollback_esp && !frames.commit_esp && g_esp == frames.rollback_esp - UNDO_COMMIT_BELOW_ROLLBACK &&
        g_ecx == frames.world) {
        frames.commit_esp = g_esp;
        sub_0050C550();
        frames.commit_esp = 0;
        return;
    }
    sub_0050C550();
}

/* ------------------------------------------------------------ 0050C4A0 */
void void_ai_full_snapshot(void)
{
    const uint32_t outer = frames.full_esp;
    if (!outer) frames.full_esp = g_esp;
    sub_0050C4A0();
    frames.full_esp = outer;
}

/* ------------------------------------------------------------ 0050C3E0 */
void void_ai_snapshot(void)
{
    const uint32_t esp = g_esp, world = g_ecx, entry = ld32(esp + 4u), object = ld32(esp + 8u);
    const uint32_t self = object ? ld32(ld32(object + 4u) + 4u) + object + 4u : 0;   /* 0050C3E0's target */
    const uint32_t outer_esp = frames.snap_esp, outer_entry = frames.snap_entry, outer_this = frames.snap_this;
    const int outer_elide = frames.snap_elide;
    int elide = 0;
    const int names = self && ld32(ld32(self) + 12u) == UNDO_NAMES_SERIALIZE;
    const int recorded = names && (ld32(esp + 12u) & 0xFFu) == 1u && ld8(object + 13u) == 0 && ld32(entry + 24u) == object;
    const uint32_t table = ld32(world + 28u);
    const int indexed = entry >= table && (entry - table) % 40u == 0;
    if (recorded && indexed && frames.estimate_esp && esp < frames.estimate_esp && !frames.start_set) {
        frames.start_set = 1;                   /* the history record takes this state */
        frames.start_index = (entry - table) / 40u;
        frames.start[0] = ld32(entry + 28u);
        frames.start[1] = ld8(entry + 32u);
        frames.start[2] = ld32(entry + 36u);
    }
    if (recorded && indexed && frames.start_set && frames.start_index == (entry - table) / 40u && frames.commit_esp &&
        esp < frames.commit_esp && !frames.full_esp && !outer_esp && world == frames.world &&
        __c11_atomic_load(&names_flag, __ATOMIC_RELAXED) >= 0)
        elide = 1;
    frames.snap_esp = esp;
    frames.snap_entry = entry;
    frames.snap_this = self;
    frames.snap_elide = elide;
    frames.save_left = frames.crc_left = elide;
    frames.save_skipped = 0;
    sub_0050C3E0();
    if (elide && frames.save_skipped) {
        frames.check_set = 1;
        __c11_atomic_fetch_add(&elided, 1, __ATOMIC_RELAXED);
    }
    frames.snap_esp = outer_esp;
    frames.snap_entry = outer_entry;
    frames.snap_this = outer_this;
    frames.snap_elide = outer_elide;
    frames.save_left = frames.crc_left = frames.save_skipped = 0;
}

/* ------------------------------------------------------------ 00C01130 */
static void undo_skip(uint32_t esp)
{
    g_eax = 0;                  /* xor eax,eax; ret 4 */
    g_esp = esp + 8u;
}

void void_ai_names_serialize(void)
{
    const uint32_t esp = g_esp, stream = ld32(esp + 4u);
    const int ours = frames.snap_esp && esp < frames.snap_esp && g_ecx == frames.snap_this;
    const uint32_t vtable = stream ? ld32(stream) : 0;
    const int save = ours && vtable == UNDO_CHUNKLESS && ld32(stream + 24u) == 2u && ld32(stream + 20u) == frames.snap_entry;
    if (save && frames.snap_elide && frames.save_left && ld32(stream + 16u) == frames.world + 8u) {
        frames.save_left = 0;
        frames.save_skipped = 1;
        st8(frames.world + 16u, (uint8_t)__c11_atomic_load(&names_flag, __ATOMIC_RELAXED));
        undo_skip(esp);
        return;
    }
    if (ours && frames.snap_elide && frames.save_skipped && frames.crc_left && vtable == UNDO_CRC_SAVER) {
        frames.crc_left = 0;
        undo_skip(esp);
        return;
    }
    if (ours && frames.snap_elide) frames.save_left = frames.crc_left = 0;   /* not the expected calls */
    const uint32_t owner = save ? ld32(stream + 16u) : 0;
    sub_00C01130();
    if (owner) __c11_atomic_store(&names_flag, ld8(owner + 8u), __ATOMIC_RELAXED);   /* +16 is 0 before the save */
}

/* The rows of tools/native_routes.py (groups ai_estimate ... ai_names_serialize). */
void void_ai_estimate_dispatch(void) { void_ai_estimate(); }
void void_ai_rollback_dispatch(void) { void_ai_rollback(); }
void void_ai_commit_dispatch(void) { void_ai_commit(); }
void void_ai_full_snapshot_dispatch(void) { void_ai_full_snapshot(); }
void void_ai_snapshot_dispatch(void) { void_ai_snapshot(); }
void void_ai_names_serialize_dispatch(void) { void_ai_names_serialize(); }
