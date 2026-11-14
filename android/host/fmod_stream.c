/* FMOD's stream worker passes a nominal 10 ms to 1102BC0B even when waiting
 * for the guest machine takes longer.  Only its already-seeded EOF drain is
 * corrected here.  The original decoder, cursor, fades and stop callback run
 * unchanged, once per call.  Expiration is left at zero for the NEXT original
 * pass to perform the stop; this deliberately adds at most one worker pass.
 *
 * All helpers are host-only: they never call guest code, touch the register /
 * flag / FPU files, or add a trace entry.  Consequently the lifted callee's
 * complete ABI result survives without a costly register save/restore.
 */
#include "host.h"

#ifndef VOID_ANDROID_APP
uint64_t void_audio_pause_state(void) { return 0; }
#endif

#define FMOD_CONTEXT 0x110472D0u
#define STREAM_LIMIT 32u
#define NOMINAL_Q8 (10u * 256u)
#define MAX_INTERVAL_NS UINT64_C(250000000)

extern void sub_1102BC0B_lifted(void);

/* All these original entries can hide a reset or a pause/resume entirely
 * between two worker observations.  Even an equal-valued reseed is an epoch
 * change.  The overlapping decoder entries are real dispatch entries too.
 * Guest calls are serialized by the machine lock, including these hooks. */
static uint64_t reset_epoch;
static void trace_refill_call(void);
static int readable(uint32_t address, uint32_t size);
typedef struct { uint32_t stream, sample, handle; int normal; } decoder_epoch;

/* A normal refill of another stream is not an EOF reset. Retain the epoch
 * guard for an active countdown (including an equal-valued reseed), a newly
 * seeded EOF, or an identity change across a decoder that can yield. */
static decoder_epoch decoder_begin(uint32_t stream)
{
    decoder_epoch epoch = { .stream = stream };
    if (readable(stream, 0x4DC)) {
        epoch.sample = MEM32(stream + 0x30);
        epoch.handle = MEM32(stream + 0x2F0);
        epoch.normal = MEM32(stream + 0x374) == UINT32_MAX;
    }
    if (!epoch.normal) ++reset_epoch;
    return epoch;
}

static void decoder_end(decoder_epoch epoch)
{
    if (epoch.normal && (!readable(epoch.stream, 0x4DC) ||
        MEM32(epoch.stream + 0x30) != epoch.sample || MEM32(epoch.stream + 0x2F0) != epoch.handle ||
        MEM32(epoch.stream + 0x374) != UINT32_MAX)) ++reset_epoch;
}

#define RESET_ENTRY(name) \
    extern void name##_lifted(void); \
    void name(void) { ++reset_epoch; name##_lifted(); }
RESET_ENTRY(sub_110277DD)
RESET_ENTRY(sub_1102B103)
extern void sub_1102B635_lifted(void);
void sub_1102B635(void)
{
    decoder_epoch epoch = decoder_begin(readable(g_esp, 8) ? ARG(0) : 0);
    trace_refill_call();
    decoder_end(epoch);
}
/* These overlapping original entries use the stream already held in ESI. */
#define DECODER_ENTRY(name) \
    extern void name##_lifted(void); \
    void name(void) { decoder_epoch epoch = decoder_begin(g_esi); name##_lifted(); decoder_end(epoch); }
DECODER_ENTRY(sub_1102B659)
DECODER_ENTRY(sub_1102B6BB)
DECODER_ENTRY(sub_1102B6F8)
DECODER_ENTRY(sub_1102B716)
DECODER_ENTRY(sub_1102B7CA)
DECODER_ENTRY(sub_1102B844)
DECODER_ENTRY(sub_1102B8A8)
DECODER_ENTRY(sub_1102B9C5)
DECODER_ENTRY(sub_1102BAB5)
DECODER_ENTRY(sub_1102BABE)
#undef DECODER_ENTRY
RESET_ENTRY(sub_1102BE47)
RESET_ENTRY(sub_1102D53A)
#undef RESET_ENTRY

typedef struct {
    uint32_t stream, sample, handle, channel, decode, length, rate;
    uint32_t remaining, half;
    int eligible;
} stream_state;

typedef struct {
    uint32_t context, worker, table, count, size;
    stream_state states[STREAM_LIMIT];
} stream_list;

typedef struct {
    stream_state state;
    uint64_t time_ns;
} drain_epoch;

static _Thread_local struct {
    uint32_t context, worker, table, count, size;
    uint64_t reset, pause;
    drain_epoch streams[STREAM_LIMIT];
} previous;

/* Bounded, read-only external diagnostic.  This records EOF fallback causes,
 * not PCM or ordinary decode passes.  No logging lock or guest call is taken.
 * Even sequence + stable double-read identifies a complete observation. */
enum {
    DRAIN_SEED = 1u, DRAIN_RESET = 2u, DRAIN_PAUSE = 4u,
    DRAIN_COUNTER = 8u, DRAIN_TICK = 16u, DRAIN_BACKWARD = 32u,
    DRAIN_LONG = 64u, DRAIN_CONTEXT = 128u
};
typedef struct {
    uint64_t now_ns, previous_ns, entry_ns, previous_reset, reset_before, reset_after;
    uint64_t previous_pause, pause_before, pause_after;
    uint32_t stream, handle, before_q8, after_q8, expected_q8, reasons, before_half, after_half;
} drain_trace_event;
typedef struct {
    uint64_t sequence, total, overflow, max_delta_ns, reasons[8];
    uint32_t magic, version, size, event_size, capacity, reserved;
    drain_trace_event events[64];
} drain_trace;
__attribute__((used)) volatile drain_trace void_fmod_drain_trace = {
    .magic = 0x48354644u, .version = 1, .size = sizeof(drain_trace),
    .event_size = sizeof(drain_trace_event), .capacity = 64
};

static void trace_drain(const stream_state *pre, const stream_state *post,
                        const drain_epoch *old, uint64_t now_ns, uint64_t entry_ns,
                        uint64_t reset, uint64_t pause, uint64_t post_pause,
                        uint32_t reasons)
{
    uint64_t delta = old && now_ns >= old->time_ns ? now_ns - old->time_ns : 0;
    if (!reasons && delta <= void_fmod_drain_trace.max_delta_ns) return;
    __atomic_add_fetch(&void_fmod_drain_trace.sequence, 1, __ATOMIC_ACQ_REL);
    if (delta > void_fmod_drain_trace.max_delta_ns) void_fmod_drain_trace.max_delta_ns = delta;
    if (reasons) {
        drain_trace_event event = {
            .now_ns = now_ns, .previous_ns = old ? old->time_ns : 0, .entry_ns = entry_ns,
            .previous_reset = previous.reset, .reset_before = reset, .reset_after = reset_epoch,
            .previous_pause = previous.pause, .pause_before = pause, .pause_after = post_pause,
            .stream = post->stream, .handle = post->handle,
            .before_q8 = pre->remaining, .after_q8 = post->remaining,
            .expected_q8 = old ? old->state.remaining : UINT32_MAX, .reasons = reasons,
            .before_half = pre->half, .after_half = post->half
        };
        uint64_t index = void_fmod_drain_trace.total;
        void_fmod_drain_trace.events[index % 64u] = event;
        void_fmod_drain_trace.total = index + 1;
        if (index >= 64) ++void_fmod_drain_trace.overflow;
        for (unsigned i = 0; i < 8; ++i)
            if (reasons & (1u << i)) ++void_fmod_drain_trace.reasons[i];
    }
    __atomic_add_fetch(&void_fmod_drain_trace.sequence, 1, __ATOMIC_RELEASE);
}

static int readable(uint32_t address, uint32_t size)
{
    return address >= 0x10000u && (uint64_t)address + size <= UINT64_C(0x100000000) &&
           void_vm_readable(address, size);
}

/* The public worker trace observes every completed software half refill,
 * including rare stalls between external memory samples. It never changes
 * playback, calls a guest helper, or snapshots PCM. Cursor crossing is direct
 * evidence that playback entered the half before this callback completed;
 * wall deadline alone is only a warning (the channel might have stalled too). */
typedef struct {
    uint64_t start_ns, end_ns, pause_before, pause_after, deadline_ns;
    uint32_t stream, sample, handle, channel, target_half, start_cursor, end_cursor;
    uint32_t frames, rate, bytes, pcm_offset, start_remaining, end_remaining, result, reasons;
    uint32_t lock_wait_us; /* Version 2 uses the former tail padding. */
} refill_event;
typedef struct {
    uint64_t sequence, total, cursor_crossings, overlap_starts, wall_late, state_changes, max_refill_ns;
    uint32_t magic, version, event_size, capacity;
    refill_event events[128];
} refill_trace;
__attribute__((used)) volatile refill_trace void_fmod_refill_trace = {
    .magic = 0x48354652u, .version = 2, .event_size = sizeof(refill_event), .capacity = 128
};

static int refill_before(refill_event *event)
{
    if (!readable(g_esp, 16) || !readable(FMOD_CONTEXT, 4)) return 0;
    uint32_t stream = ARG(0), destination = ARG(1), bytes = ARG(2);
    if (!readable(stream, 0x4DC) || MEM32(stream + 0x374) != UINT32_MAX ||
        !MEM8(stream + 0x4D4) || !MEM8(stream + 0x4D6) || MEM8(stream + 0x4D7)) return 0;
    uint32_t context = MEM32(FMOD_CONTEXT), sample = MEM32(stream + 0x30);
    if (!readable(context, 0x2990) || MEM32(context + 0x298C) != void_thread_id() ||
        !readable(sample, 0x19C) || MEM32(sample + 0x194) != 0x1101325Du ||
        MEM32(sample + 0x198) != 0x11013488u) return 0;
    uint32_t handle = MEM32(stream + 0x2F0), index = handle & 0xFFFu;
    uint64_t count = (uint64_t)MEM32(context + 0x14EC) + MEM32(context + 0x14D4);
    if ((int32_t)handle < 0 || !(handle & 0x7FFFF000u) || index >= count || count > 4096) return 0;
    uint64_t address = (uint64_t)MEM32(context + 0x14A8) + index * 0x1DCu;
    if (address > UINT32_MAX || !readable((uint32_t)address, 0x1DC)) return 0;
    uint32_t channel = (uint32_t)address, flags = MEM32(sample + 0x124);
    uint32_t frames = MEM32(sample + 0x10C), rate = MEM32(sample + 0x128), pcm = MEM32(sample + 0x104);
    if (MEM32(channel + 0x14) != handle || MEM32(channel + 0x5C) != sample ||
        MEM32(channel + 0x1B0) != 0x11013C79u || (int32_t)MEM32(channel + 0x20) <= 0 ||
        (MEM32(channel + 0x3C) & 0x10u) || flags & 0x04000000u || frames < 2 || frames & 1u ||
        !rate || rate > 384000 || destination < pcm) return 0;
    uint64_t half_bytes = (uint64_t)(frames / 2) * (flags & 0x10u ? 2u : 1u) * (flags & 0x40u ? 2u : 1u);
    uint32_t offset = destination - pcm, cursor = MEM32(channel + 0x80);
    if (!half_bytes || half_bytes > UINT32_MAX || bytes != half_bytes || cursor >= frames ||
        (offset && offset != half_bytes)) return 0;
    uint32_t half = offset ? 1u : 0u, boundary = half * (frames / 2);
    uint32_t distance = boundary >= cursor ? boundary - cursor : frames - cursor + boundary;
    *event = (refill_event){ .start_ns = void_monotonic_ns(), .pause_before = void_audio_pause_state(),
        .deadline_ns = (uint64_t)distance * UINT64_C(1000000000) / rate,
        .stream = stream, .sample = sample, .handle = handle, .channel = channel,
        .target_half = half, .start_cursor = cursor, .frames = frames, .rate = rate,
        .bytes = bytes, .pcm_offset = offset, .start_remaining = UINT32_MAX };
    if (cursor / (frames / 2) == half) event->reasons |= 1u;
    return 1;
}

static void trace_refill_call(void)
{
    refill_event event;
    int admitted = refill_before(&event);
    uint64_t wait_before = admitted ? void_lock_wait_ns() : 0;
    sub_1102B635_lifted();
    if (!admitted) return;
    event.end_ns = void_monotonic_ns();
    uint64_t wait_us = (void_lock_wait_ns() - wait_before) / 1000u;
    event.lock_wait_us = wait_us > UINT32_MAX ? UINT32_MAX : (uint32_t)wait_us;
    event.pause_after = void_audio_pause_state();
    event.result = g_eax & 0xFFu;
    uint64_t elapsed = event.end_ns >= event.start_ns ? event.end_ns - event.start_ns : 0;
    if (elapsed >= event.deadline_ns) event.reasons |= 4u;
    if (event.pause_before != event.pause_after || event.pause_before & 1u ||
        !readable(event.stream, 0x4DC) || !readable(event.channel, 0x1DC) ||
        MEM32(event.stream + 0x30) != event.sample || MEM32(event.stream + 0x2F0) != event.handle ||
        MEM32(event.channel + 0x14) != event.handle || MEM32(event.channel + 0x5C) != event.sample) {
        event.reasons |= 8u;
    } else {
        event.end_cursor = MEM32(event.channel + 0x80);
        event.end_remaining = MEM32(event.stream + 0x374);
        if (event.end_cursor >= event.frames) event.reasons |= 8u;
        else if (!(event.reasons & 1u)) {
            uint32_t advance = (uint32_t)(((uint64_t)event.end_cursor + event.frames - event.start_cursor) % event.frames);
            uint32_t boundary = event.target_half * (event.frames / 2);
            uint32_t distance = (uint32_t)(((uint64_t)boundary + event.frames - event.start_cursor) % event.frames);
            if (advance >= distance) event.reasons |= 2u;
        }
    }
    __atomic_add_fetch(&void_fmod_refill_trace.sequence, 1, __ATOMIC_ACQ_REL);
    uint64_t index = void_fmod_refill_trace.total;
    void_fmod_refill_trace.events[index % 128u] = event;
    void_fmod_refill_trace.total = index + 1;
    if (event.reasons & 1u) ++void_fmod_refill_trace.overlap_starts;
    if (event.reasons & 2u) ++void_fmod_refill_trace.cursor_crossings;
    if (event.reasons & 4u) ++void_fmod_refill_trace.wall_late;
    if (event.reasons & 8u) ++void_fmod_refill_trace.state_changes;
    if (elapsed > void_fmod_refill_trace.max_refill_ns) void_fmod_refill_trace.max_refill_ns = elapsed;
    __atomic_add_fetch(&void_fmod_refill_trace.sequence, 1, __ATOMIC_RELEASE);
}

static int snapshot(stream_list *list)
{
    memset(list, 0, sizeof *list);
    if (!readable(FMOD_CONTEXT, 4)) return 0;
    uint32_t context = MEM32(FMOD_CONTEXT);
    if (!readable(context, 0x2990)) return 0;
    list->context = context;
    list->worker = MEM32(context + 0x298C);
    if (!list->worker || list->worker != void_thread_id()) return 0;
    list->table = MEM32(context + 0x14A8);
    uint64_t count = (uint64_t)MEM32(context + 0x14EC) + MEM32(context + 0x14D4);
    if (!count || count > 4096 || !readable(list->table, (uint32_t)count * 0x1DCu)) return 0;
    list->count = (uint32_t)count;
    uint32_t sentinel = context + 0x295C, stream = MEM32(sentinel);
    while (stream != sentinel) {
        if (list->size == STREAM_LIMIT || !readable(stream, 0x4DC)) return 0;
        for (uint32_t i = 0; i < list->size; ++i)
            if (list->states[i].stream == stream) return 0;
        stream_state *state = &list->states[list->size++];
        state->stream = stream;
        state->sample = MEM32(stream + 0x30);
        state->handle = MEM32(stream + 0x2F0);
        state->decode = MEM32(stream + 0x2C4);
        state->remaining = MEM32(stream + 0x374);
        state->half = MEM32(stream + 0x2E8);
        uint32_t index = state->handle & 0xFFFu;
        /* Stopped/resident streams are normal; they do not invalidate the
         * other live streams, and are never dereferenced through a handle. */
        if (state->decode && (int32_t)state->remaining >= 0 &&
            !MEM8(stream + 0x4D5) && MEM8(stream + 0x4D6) && !MEM8(stream + 0x4D7) &&
            MEM8(stream + 0x4D4) && (int32_t)state->handle >= 0 &&
            (state->handle & 0x7FFFF000u) && index < list->count &&
            readable(state->sample, 0x12C)) {
            state->channel = list->table + index * 0x1DCu;
            state->length = MEM32(state->sample + 0x10C);
            state->rate = MEM32(state->sample + 0x128);
            state->eligible = MEM32(state->channel + 0x14) == state->handle &&
                MEM32(state->channel + 0x5C) == state->sample &&
                !(MEM32(state->channel + 0x3C) & 0x10u) &&
                state->length >= 2 && state->rate && state->rate <= 384000u &&
                void_vm_writable(stream + 0x374, 4);
        }
        stream = MEM32(stream);
    }
    return 1;
}

static int same_stream(const stream_state *a, const stream_state *b)
{
    return a->eligible && b->eligible && a->stream == b->stream && a->sample == b->sample &&
        a->handle == b->handle && a->channel == b->channel && a->decode == b->decode &&
        a->length == b->length && a->rate == b->rate;
}

static void trace_skips(const stream_list *before, const stream_list *after,
                        uint64_t now_ns, uint64_t entry_ns, uint64_t reset, uint64_t pause,
                        uint64_t post_pause, int continuing)
{
    for (uint32_t i = 0; i < after->size; ++i) {
        const stream_state *post = &after->states[i], *pre = NULL;
        const drain_epoch *old = NULL;
        if (!post->eligible) continue;
        for (uint32_t j = 0; j < before->size; ++j)
            if (before->states[j].stream == post->stream && before->states[j].sample == post->sample &&
                before->states[j].handle == post->handle && before->states[j].decode == post->decode) {
                pre = &before->states[j]; break;
            }
        if (!pre) continue;
        if ((int32_t)pre->remaining < 0) {
            trace_drain(pre, post, NULL, now_ns, entry_ns, reset, pause, post_pause, DRAIN_SEED);
            continue;
        }
        if (!same_stream(pre, post) || previous.context != after->context ||
            previous.worker != after->worker || previous.table != after->table || previous.count != after->count) continue;
        for (uint32_t j = 0; j < previous.size; ++j)
            if (same_stream(&previous.streams[j].state, post)) { old = &previous.streams[j]; break; }
        if (!old) continue;
        uint32_t reasons = 0;
        if (previous.reset != reset || reset != reset_epoch) reasons |= DRAIN_RESET;
        if (previous.pause != pause || pause != post_pause) reasons |= DRAIN_PAUSE;
        if (old->state.remaining != pre->remaining) reasons |= DRAIN_COUNTER;
        if (pre->remaining <= NOMINAL_Q8 || post->remaining != pre->remaining - NOMINAL_Q8) reasons |= DRAIN_TICK;
        if (now_ns < old->time_ns) reasons |= DRAIN_BACKWARD;
        else if (now_ns - old->time_ns > MAX_INTERVAL_NS) reasons |= DRAIN_LONG;
        if (!continuing && !reasons) reasons |= DRAIN_CONTEXT;
        trace_drain(pre, post, old, now_ns, entry_ns, reset, pause, post_pause, reasons);
    }
}

/* Absolute Q8 milliseconds telescope without dropping fractional ms each
 * iteration; division before multiplication also avoids uint64 overflow. */
static uint64_t q8_time(uint64_t ns)
{
    return (ns / UINT64_C(1000000)) * 256u + (ns % UINT64_C(1000000)) * 256u / 1000000u;
}

void sub_1102BC0B(void)
{
    stream_list before, after;
    uint64_t pause = void_audio_pause_state(), reset = reset_epoch;
    int admitted = !(pause & 1u) && readable(g_esp, 8) && ARG(0) == 10 && snapshot(&before);
    uint64_t entry_ns = 0;
    if (admitted) for (uint32_t i = 0; i < before.size; ++i)
        if (before.states[i].eligible) { entry_ns = void_monotonic_ns(); break; }
    sub_1102BC0B_lifted();
    uint64_t now_ns = void_monotonic_ns(), now = q8_time(now_ns);
    uint64_t post_pause = void_audio_pause_state();
    if (!admitted || pause != post_pause || (post_pause & 1u) || !snapshot(&after) ||
        before.context != after.context || before.worker != after.worker ||
        before.table != after.table || before.count != after.count) {
        memset(&previous, 0, sizeof previous);
        return;
    }
    int continuing = previous.context == after.context && previous.worker == after.worker &&
        previous.table == after.table && previous.count == after.count &&
        previous.pause == pause && previous.reset == reset && reset == reset_epoch;
    trace_skips(&before, &after, now_ns, entry_ns, reset, pause, post_pause, continuing);
    for (uint32_t i = 0; i < after.size; ++i) {
        stream_state *post = &after.states[i];
        if (!post->eligible || !continuing) continue;
        const stream_state *pre = NULL;
        const drain_epoch *old = NULL;
        for (uint32_t j = 0; j < before.size; ++j)
            if (same_stream(&before.states[j], post)) { pre = &before.states[j]; break; }
        for (uint32_t j = 0; j < previous.size; ++j)
            if (same_stream(&previous.streams[j].state, post)) { old = &previous.streams[j]; break; }
        if (!pre || !old || old->state.remaining != pre->remaining ||
            pre->remaining <= NOMINAL_Q8 || post->remaining != pre->remaining - NOMINAL_Q8 ||
            now_ns < old->time_ns || now_ns - old->time_ns > MAX_INTERVAL_NS) continue;
        uint64_t elapsed = now - q8_time(old->time_ns);
        post->remaining = elapsed >= pre->remaining ? 0 : pre->remaining - (uint32_t)elapsed;
        MEM32(post->stream + 0x374) = post->remaining;
    }
    previous.context = after.context; previous.worker = after.worker;
    previous.table = after.table; previous.count = after.count;
    previous.pause = post_pause; previous.reset = reset_epoch; previous.size = after.size;
    for (uint32_t i = 0; i < after.size; ++i) {
        previous.streams[i].state = after.states[i]; previous.streams[i].time_ns = now_ns;
    }
}
