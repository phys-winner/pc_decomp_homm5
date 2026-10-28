/* DirectSound 8 on a host software mixer.
 *
 * Secondary buffers live in guest memory (Lock returns pointers into them).
 * A mixer thread advances every playing buffer's play cursor in real time,
 * mixes PCM with volume, pan, frequency and a simple 3D model, fires position
 * notifications, and hands the stereo result to the audio backend (null until
 * an output is attached), so streaming code sees DirectSound's timing. */
#define _GNU_SOURCE
#include "com.h"
#include <errno.h>
#include <math.h>
#include <sched.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

#define DS_OK 0u
#define DSERR_INVALIDPARAM 0x80070057u
#define DSERR_INVALIDCALL 0x88780032u
#define DSERR_UNSUPPORTED 0x80004001u
#define DSERR_CONTROLUNAVAIL 0x8878001Eu

#define DSBCAPS_PRIMARYBUFFER 0x1u
#define DSBCAPS_CTRL3D 0x10u
#define DSBCAPS_CTRLPOSITIONNOTIFY 0x100u
#define DSBSTATUS_PLAYING 0x1u
#define DSBSTATUS_LOOPING 0x4u
#define DSBPLAY_LOOPING 0x1u

#define MIX_RATE 48000
#define MIX_CHUNK 480                  /* 10 ms */
#define MIX_CATCHUP 8                  /* extra chunks per wake that refill the output queue */

static const uint8_t IID_IUnknown[16] = {0,0,0,0,0,0,0,0,0xC0,0,0,0,0,0,0,0x46};
static const uint8_t IID_IDirectSound8[16] = {0x93,0x7E,0x0A,0xC5,0x95,0xF3,0x34,0x48,0x9E,0xF6,0x7F,0xA9,0x9D,0xE5,0x09,0x66};   /* {C50A7E93-F395-4834-9EF6-7FA99DE50966} */
static const uint8_t IID_IDirectSound[16] = {0x83,0xFA,0x9A,0x27,0x81,0x49,0xCE,0x11,0xA5,0x21,0x00,0x20,0xAF,0x0B,0xE5,0x60};
static const uint8_t IID_IDirectSoundBuffer[16] = {0x85,0xFA,0x9A,0x27,0x81,0x49,0xCE,0x11,0xA5,0x21,0x00,0x20,0xAF,0x0B,0xE5,0x60};
static const uint8_t IID_IDirectSoundBuffer8[16] = {0x49,0xA4,0x25,0x68,0x24,0x75,0x82,0x4D,0x92,0x0F,0x50,0xE3,0x6A,0xB3,0xAB,0x1E};
static const uint8_t IID_IDirectSound3DBuffer[16] = {0x86,0xFA,0x9A,0x27,0x81,0x49,0xCE,0x11,0xA5,0x21,0x00,0x20,0xAF,0x0B,0xE5,0x60};
static const uint8_t IID_IDirectSound3DListener[16] = {0x84,0xFA,0x9A,0x27,0x81,0x49,0xCE,0x11,0xA5,0x21,0x00,0x20,0xAF,0x0B,0xE5,0x60};
static const uint8_t IID_IDirectSoundNotify[16] = {0x83,0x07,0x21,0xB0,0xCD,0x89,0xD0,0x11,0xAF,0x08,0x00,0xA0,0xC9,0x25,0xCD,0x16};

typedef struct dsbuf dsbuf_t;
typedef struct { void_com_object com; dsbuf_t *owner; } facet_t;

/* Kaiser-windowed sinc for buffers at another rate (FMOD mixes at 44.1 kHz):
 * cutoff 0.92 of the source Nyquist, beta 9, linear between 256 phases. At
 * 44.1 -> 48 kHz every tone up to 18 kHz keeps 94-110 dB SINAD (-0.3 dB at
 * 18 kHz); repeating the nearest frame left a 5 kHz tone at 14 dB. Higher
 * rates are not band-limited to the output (no game buffer uses one). */
#define RS_TAPS 32u
#define RS_HALF 16u
#define RS_MASK 31u
#define RS_PHASES 256u
#define RS_CUTOFF 0.92
#define RS_BETA 9.0

struct dsbuf {
    void_com_object com;
    facet_t f3d, notify;            /* the 3D / notify interfaces of this buffer */
    int primary;
    uint32_t flags;
    uint32_t data, size;            /* guest PCM */
    uint32_t channels, rate, bits, block;
    uint32_t frequency;
    int32_t volume, pan;
    uint32_t play_pos;              /* bytes */
    double frac;                    /* fractional source position */
    int playing, looping;
    uint32_t notify_count;
    uint32_t notify_offset[64], notify_event[64];
    uint32_t locks, last_status;    /* VOID_DSOUND_TRACE bookkeeping */
    uint32_t unlocks, live_unlocks, wrap_unlocks, unchanged_wraps, wrap_seen;
    uint64_t lock_ns, max_refill_ns;
    float pos[3], min_distance, max_distance;
    uint32_t mode3d;
    dsbuf_t *next;
    /* Interpolation window: frames rs_frame-15 .. rs_frame+16, each read once
     * while still ahead of the play cursor, because the application may
     * refill the PCM behind the cursor at any time. */
    float rs_window[2][RS_TAPS];
    uint32_t rs_frame, rs_head;
    int rs_valid;
};

static float rs_table[RS_PHASES + 1][RS_TAPS];
static int rs_ready;

static pthread_mutex_t mix_lock = PTHREAD_MUTEX_INITIALIZER;
static dsbuf_t *buffers;
static float listener_pos[3], listener_front[3] = {0, 0, 1}, listener_top[3] = {0, 1, 0};
static float rolloff = 1.0f, distance_factor = 1.0f;
static pthread_t mixer_thread;
static int mixer_running;

/* VOID_DSOUND_TRACE=1 or userdata/audio_trace: buffer lifecycle plus bounded
 * refill/freshness telemetry, independently of expensive renderer logging. */
static int dstrace;
#define DSTRACE(...) do { if (dstrace) void_log("[dsound] " __VA_ARGS__); } while (0)

/* Audio backend hook (null by default): receives interleaved stereo int16 and
 * returns how many frames its device queue could take at once. */
__attribute__((weak)) uint32_t void_audio_output(const int16_t *frames, uint32_t count) { (void)frames; (void)count; return 0; }

static void signal_event(uint32_t handle)
{
    void_object *o = void_handle_get(handle, VOID_OBJ_EVENT);
    if (o) void_object_signal(o);
}

/* Read one sample (as float, channel c) of buffer b at byte position pos. */
static float sample_at(dsbuf_t *b, uint32_t frame, uint32_t c)
{
    uint32_t offset = frame * b->block + (c < b->channels ? c : 0) * (b->bits / 8);
    if (offset + b->bits / 8 > b->size) return 0.0f;
    if (b->bits == 16) return (float)(int16_t)MEM16(b->data + offset) / 32768.0f;
    return ((float)MEM8(b->data + offset) - 128.0f) / 128.0f;
}

static double bessel_i0(double x)
{
    double sum = 1.0, term = 1.0;
    for (int k = 1; k < 64 && term > sum * 1e-12; ++k) {
        double half = x / (2.0 * k);
        term *= half * half;
        sum += term;
    }
    return sum;
}

static void rs_build(void)
{
    const double pi = 3.14159265358979323846;
    for (uint32_t p = 0; p <= RS_PHASES; ++p) {
        double t = (double)p / RS_PHASES, h[RS_TAPS], sum = 0.0;
        for (uint32_t k = 0; k < RS_TAPS; ++k) {
            double x = (double)k - (double)(RS_HALF - 1) - t, u = x / RS_HALF;
            double w = u * u < 1.0 ? bessel_i0(RS_BETA * sqrt(1.0 - u * u)) / bessel_i0(RS_BETA) : 0.0;
            double s = x == 0.0 ? 1.0 : sin(pi * RS_CUTOFF * x) / (pi * RS_CUTOFF * x);
            h[k] = RS_CUTOFF * s * w;
            sum += h[k];
        }
        for (uint32_t k = 0; k < RS_TAPS; ++k) rs_table[p][k] = (float)(h[k] / sum);
    }
}

/* Frame g of a buffer of total frames: a looping buffer continues from its
 * start, a one-shot buffer is silent past its end. */
static float rs_source(dsbuf_t *b, uint32_t g, uint32_t total, uint32_t c)
{
    if (g >= total) {
        if (!b->looping) return 0.0f;
        g %= total;
    }
    return sample_at(b, g, c);
}

/* Bring the window centre to frame f: slide it by up to a window, otherwise
 * refill it (silence before f, as at a fresh start). */
static void rs_seek(dsbuf_t *b, uint32_t f, uint32_t total)
{
    uint32_t distance = !b->rs_valid ? RS_TAPS + 1 : f >= b->rs_frame ? f - b->rs_frame : f + total - b->rs_frame;
    if (distance > RS_TAPS) {
        b->rs_frame = f;
        b->rs_head = 0;
        for (uint32_t k = 0; k < RS_TAPS; ++k) {
            /* Slot k holds frame f + k for k <= 16 and f + k - 32 above. */
            int offset = k <= RS_HALF ? (int)k : (int)k - (int)RS_TAPS;
            for (uint32_t c = 0; c < 2; ++c)
                b->rs_window[c][k] = offset < 0 ? 0.0f : rs_source(b, f + (uint32_t)offset, total, c);
        }
        b->rs_valid = 1;
        return;
    }
    while (distance--) {
        b->rs_frame = b->rs_frame + 1 < total ? b->rs_frame + 1 : 0;
        b->rs_head = (b->rs_head + 1) & RS_MASK;
        uint32_t slot = (b->rs_head + RS_HALF) & RS_MASK;
        for (uint32_t c = 0; c < 2; ++c)
            b->rs_window[c][slot] = rs_source(b, b->rs_frame + RS_HALF, total, c);
    }
}

/* Output at fractional position t past the window centre. */
static void rs_frame_at(const dsbuf_t *b, float t, float *l, float *r)
{
    float position = t * (float)RS_PHASES;
    uint32_t phase = (uint32_t)position;
    if (phase >= RS_PHASES) phase = RS_PHASES - 1;
    float a = position - (float)phase, sl = 0.0f, sr = 0.0f;
    const float *h0 = rs_table[phase], *h1 = rs_table[phase + 1];
    for (uint32_t k = 0; k < RS_TAPS; ++k) {
        float h = h0[k] + a * (h1[k] - h0[k]);
        uint32_t slot = (b->rs_head + k + 1 - RS_HALF) & RS_MASK;   /* frame rs_frame + k - 15 */
        sl += h * b->rs_window[0][slot];
        sr += h * b->rs_window[1][slot];
    }
    *l = sl;
    *r = sr;
}

static void notify_passed(dsbuf_t *b, uint32_t from, uint32_t to, int wrapped)
{
    for (uint32_t i = 0; i < b->notify_count; ++i) {
        uint32_t off = b->notify_offset[i];
        if (off == 0xFFFFFFFFu) continue;
        int hit = wrapped ? (off >= from || off < to) : (off >= from && off < to);
        if (hit) signal_event(b->notify_event[i]);
    }
}

static void mix_chunk(float *mix, uint32_t frames)
{
    memset(mix, 0, sizeof(float) * 2 * frames);
    if (!rs_ready) {
        rs_build();
        rs_ready = 1;
    }
    for (dsbuf_t *b = buffers; b; b = b->next) {
        if (b->primary || !b->playing || !b->size || !b->block) continue;
        float vol = b->volume <= -10000 ? 0.0f : powf(10.0f, (float)b->volume / 2000.0f);
        float pan = (float)b->pan / 10000.0f;
        float gl = vol * (pan > 0 ? powf(10.0f, -pan * 5.0f) : 1.0f);
        float gr = vol * (pan < 0 ? powf(10.0f, pan * 5.0f) : 1.0f);
        if (b->flags & DSBCAPS_CTRL3D && b->mode3d != 2) {       /* not DS3DMODE_DISABLE */
            float d[3];
            float dist = 0.0f;
            for (int k = 0; k < 3; ++k) {
                d[k] = b->mode3d == 1 ? b->pos[k] : (b->pos[k] - listener_pos[k]);   /* HEADRELATIVE */
                dist += d[k] * d[k];
            }
            dist = sqrtf(dist) * distance_factor;
            float atten = 1.0f;
            if (dist > b->min_distance && b->min_distance > 0.0f) {
                float dd = dist > b->max_distance ? b->max_distance : dist;
                atten = b->min_distance / (b->min_distance + rolloff * (dd - b->min_distance));
            }
            /* Right vector = top x front; pan from the projection. */
            float right[3] = {
                listener_top[1] * listener_front[2] - listener_top[2] * listener_front[1],
                listener_top[2] * listener_front[0] - listener_top[0] * listener_front[2],
                listener_top[0] * listener_front[1] - listener_top[1] * listener_front[0] };
            float side = 0.0f;
            if (dist > 0.0001f) side = (d[0] * right[0] + d[1] * right[1] + d[2] * right[2]) / (dist / distance_factor);
            gl *= atten * (side > 0 ? 1.0f - 0.5f * side : 1.0f);
            gr *= atten * (side < 0 ? 1.0f + 0.5f * side : 1.0f);
        }
        uint32_t total = b->size / b->block;
        double step = (double)b->frequency / MIX_RATE;
        uint32_t start = b->play_pos;
        double frame = (double)(b->play_pos / b->block) + b->frac;
        int wrapped = 0, stopped = 0;
        int resample = step != 1.0;
        if (!resample) b->rs_valid = 0;
        for (uint32_t i = 0; i < frames; ++i) {
            uint32_t f = (uint32_t)frame;
            if (f >= total) {
                if (!b->looping) { stopped = 1; break; }
                frame -= total; f = (uint32_t)frame; wrapped = 1;
            }
            float l, r;
            if (resample) {
                rs_seek(b, f, total);
                rs_frame_at(b, (float)(frame - (double)f), &l, &r);
            } else {
                l = sample_at(b, f, 0);
                r = b->channels > 1 ? sample_at(b, f, 1) : l;
            }
            mix[2 * i] += l * gl;
            mix[2 * i + 1] += r * gr;
            frame += step;
        }
        /* The chunk can end exactly on the last frame (a sound whose length is
         * a whole number of 10 ms ticks): a one-shot buffer stops there; the
         * modulo below would otherwise restart it from 0 for ever. */
        if (frame >= total) {
            if (b->looping) { frame = fmod(frame, (double)total); wrapped = 1; }
            else stopped = 1;
        }
        /* Diagnostic only: AAudio underruns cannot reveal replay of old guest
         * PCM. After a live refill, count whole ring laps with no completed
         * write. Static loops (filled before Play) are deliberately excluded.
         * This is a lower bound: one late/partial refill can hide a stale half. */
        if (dstrace && wrapped && b->live_unlocks) {
            if (b->wrap_seen && b->wrap_unlocks == b->unlocks) ++b->unchanged_wraps;
            b->wrap_unlocks = b->unlocks;
            b->wrap_seen = 1;
        }
        uint32_t f = (uint32_t)frame;
        if (f > total) f = total;
        b->frac = frame - (double)(uint32_t)frame;
        b->play_pos = (f * b->block) % (b->size ? b->size : 1);
        if (stopped) {
            DSTRACE("buffer %08X reached its end (%u bytes)", b->com.guest, b->size);
            b->playing = 0;
            b->play_pos = 0;
            b->frac = 0;
            b->rs_valid = 0;
            for (uint32_t k = 0; k < b->notify_count; ++k) if (b->notify_offset[k] == 0xFFFFFFFFu) signal_event(b->notify_event[k]);
        }
        notify_passed(b, start, stopped ? b->size : b->play_pos, wrapped);
    }
}

/* The mixer inherits a guest thread's big-core mask, and Android left it at
 * nice 4 under normal output (P smart), below the game threads' -10. Ask for
 * the audio priority (-16, granted only to some apps), else the game's own
 * THREAD_PRIORITY_VIDEO (-10), on any core; re-asserted every second. */
static void mixer_priority(void)
{
    int nice = getpriority(PRIO_PROCESS, 0);
    if (nice > -16 && setpriority(PRIO_PROCESS, 0, -16) && nice > -10) setpriority(PRIO_PROCESS, 0, -10);
}

static void mixer_cores(void)
{
    cpu_set_t all;
    CPU_ZERO(&all);
    long cores = sysconf(_SC_NPROCESSORS_CONF);
    for (long i = 0; i < cores && i < CPU_SETSIZE; ++i) CPU_SET(i, &all);
    if (cores > 0) sched_setaffinity(0, sizeof all, &all);
}

static void *mixer_main(void *arg)
{
    (void)arg;
    float mix[2 * MIX_CHUNK];
    int16_t out[2 * MIX_CHUNK];
    struct timespec next;
    uint32_t ticks = 0, wakes = 0;
    mixer_cores();
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (mixer_running) {
        if (wakes++ % 100 == 0) mixer_priority();
        next.tv_nsec += 10000000L;
        if (next.tv_nsec >= 1000000000L) { next.tv_nsec -= 1000000000L; next.tv_sec++; }
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL) == EINTR) {}
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        /* Consume PCM at its normal rate after a late wake, without replaying
         * the missed deadlines as a burst that can overtake a stream refill. */
        int64_t late = ((int64_t)now.tv_sec - (int64_t)next.tv_sec) * 1000000000LL + now.tv_nsec - next.tv_nsec;
        if (late >= 10000000LL)
            next = now;
        /* A late wake or an output underrun leaves the device queue short of
         * its buffer, and pacing alone never refills it: later wakes would
         * underrun again. The output reports the shortfall; mix it at once
         * (bounded), so the next late wake finds a cushion. */
        uint32_t wanted = MIX_CHUNK;
        for (unsigned chunk = 0; chunk <= MIX_CATCHUP && wanted >= MIX_CHUNK && mixer_running; ++chunk) {
            pthread_mutex_lock(&mix_lock);
            mix_chunk(mix, MIX_CHUNK);
            if (dstrace && ++ticks % 500 == 0)
                for (dsbuf_t *b = buffers; b; b = b->next)
                    if (b->playing) DSTRACE("tick %u: buffer %08X at %u of %u, %u Hz x %u bytes, ring %.3f s, unlocks %u live %u unchanged-laps %u max-refill %.1f ms",
                        ticks, b->com.guest, b->play_pos, b->size, b->frequency, b->block,
                        b->frequency && b->block ? b->size / ((double)b->frequency * b->block) : 0.0,
                        b->unlocks, b->live_unlocks, b->unchanged_wraps, (double)b->max_refill_ns / 1000000.0);
            pthread_mutex_unlock(&mix_lock);
            for (int i = 0; i < 2 * MIX_CHUNK; ++i) {
                float v = mix[i] * 32767.0f;
                out[i] = (int16_t)(v > 32767.0f ? 32767 : v < -32768.0f ? -32768 : (int)v);
            }
            wanted = void_audio_output(out, MIX_CHUNK);
        }
    }
    return NULL;
}

static void start_mixer(void)
{
    if (mixer_running) return;
    mixer_running = 1;
    if (!pthread_create(&mixer_thread, NULL, mixer_main, NULL)) pthread_setname_np(mixer_thread, "dsound mixer");
}

/* ------------------------------------------------------------- buffers */
static void_com_class buffer_class, ds3d_class, notify_class, listener_class;

static void buffer_destroy(void_com_object *o)
{
    dsbuf_t *b = (dsbuf_t *)o;
    DSTRACE("buffer %08X released (playing %d at %u of %u)", b->com.guest, b->playing, b->play_pos, b->size);
    pthread_mutex_lock(&mix_lock);
    for (dsbuf_t **p = &buffers; *p; p = &(*p)->next) if (*p == b) { *p = b->next; break; }
    pthread_mutex_unlock(&mix_lock);
    if (b->data) void_gfree(b->data);
    free(b);
}

static dsbuf_t *buffer_of(uint32_t guest)
{
    void_com_object *o = (void_com_object *)void_com_host(guest);
    if (o->cls == &buffer_class) return (dsbuf_t *)o;
    return ((facet_t *)o)->owner;
}

static uint32_t buffer_query(dsbuf_t *b, uint32_t riid, uint32_t out)
{
    if (void_guid_equal(riid, IID_IDirectSoundBuffer) || void_guid_equal(riid, IID_IDirectSoundBuffer8) ||
        void_guid_equal(riid, IID_IUnknown)) {
        void_com_addref(&b->com); MEM32(out) = b->com.guest; return 0;
    }
    if (void_guid_equal(riid, IID_IDirectSound3DBuffer) && (b->flags & DSBCAPS_CTRL3D) && !b->primary) {
        if (!b->f3d.com.guest) { b->f3d.owner = b; void_com_wrap(&b->f3d.com, &ds3d_class, 0); b->f3d.com.refs = 1000000; }
        void_com_addref(&b->com); MEM32(out) = b->f3d.com.guest; return 0;
    }
    if (void_guid_equal(riid, IID_IDirectSound3DListener) && b->primary) {
        if (!b->f3d.com.guest) { b->f3d.owner = b; void_com_wrap(&b->f3d.com, &listener_class, 0); b->f3d.com.refs = 1000000; }
        void_com_addref(&b->com); MEM32(out) = b->f3d.com.guest; return 0;
    }
    if (void_guid_equal(riid, IID_IDirectSoundNotify) && !b->primary) {
        if (!b->notify.com.guest) { b->notify.owner = b; void_com_wrap(&b->notify.com, &notify_class, 0); b->notify.com.refs = 1000000; }
        void_com_addref(&b->com); MEM32(out) = b->notify.com.guest; return 0;
    }
    char g[40];
    void_guid_format(riid, g);
    void_log("[dsound] QueryInterface(%s) unsupported", g);
    MEM32(out) = 0;
    return E_NOINTERFACE_;
}

#define BUFF buffer_of(THIS_)
/* mix_lock protects the play/frequency/playing snapshot in both callers. */
static uint32_t buffer_write_cursor(const dsbuf_t *b)
{
    if (!b->playing || !b->size) return b->play_pos;
    uint64_t lead = (uint64_t)b->frequency * MIX_CHUNK / MIX_RATE * b->block;
    return (uint32_t)(((uint64_t)b->play_pos + lead) % b->size);
}

COM_METHOD(dsb, QueryInterface, 3) { return buffer_query(BUFF, ARG(1), ARG(2)); }
COM_METHOD(dsb, AddRef, 1) { return void_com_addref(&BUFF->com); }
COM_METHOD(dsb, Release, 1) { return void_com_release(&BUFF->com); }
COM_METHOD(dsb, GetCaps, 2)
{
    dsbuf_t *b = BUFF;
    uint32_t c = ARG(1);
    MEM32(c + 4) = b->flags | 0x8u;   /* LOCSOFTWARE */
    MEM32(c + 8) = b->primary ? 65536u : b->size;
    MEM32(c + 12) = 0; MEM32(c + 16) = 0;
    return DS_OK;
}
COM_METHOD(dsb, GetCurrentPosition, 3)
{
    dsbuf_t *b = BUFF;
    pthread_mutex_lock(&mix_lock);
    uint32_t play = b->play_pos, write = buffer_write_cursor(b);
    pthread_mutex_unlock(&mix_lock);
    if (ARG(1)) MEM32(ARG(1)) = play;
    if (ARG(2)) MEM32(ARG(2)) = write;
    return DS_OK;
}
COM_METHOD(dsb, GetFormat, 4)
{
    dsbuf_t *b = BUFF;
    if (ARG(3)) MEM32(ARG(3)) = 18;
    if (!ARG(1)) return DS_OK;
    MEM16(ARG(1)) = 1; MEM16(ARG(1) + 2) = (uint16_t)b->channels; MEM32(ARG(1) + 4) = b->rate;
    MEM32(ARG(1) + 8) = b->rate * b->block; MEM16(ARG(1) + 12) = (uint16_t)b->block; MEM16(ARG(1) + 14) = (uint16_t)b->bits;
    if (ARG(2) >= 18) MEM16(ARG(1) + 16) = 0;
    return DS_OK;
}
COM_METHOD(dsb, GetVolume, 2) { MEM32(ARG(1)) = (uint32_t)BUFF->volume; return DS_OK; }
COM_METHOD(dsb, GetPan, 2) { MEM32(ARG(1)) = (uint32_t)BUFF->pan; return DS_OK; }
COM_METHOD(dsb, GetFrequency, 2) { MEM32(ARG(1)) = BUFF->frequency; return DS_OK; }
COM_METHOD(dsb, GetStatus, 2)
{
    dsbuf_t *b = BUFF;
    uint32_t status = (b->playing ? DSBSTATUS_PLAYING : 0) | (b->playing && b->looping ? DSBSTATUS_LOOPING : 0);
    if (dstrace && status != b->last_status) {
        DSTRACE("buffer %08X status %X at %u of %u", b->com.guest, status, b->play_pos, b->size);
        b->last_status = status;
    }
    MEM32(ARG(1)) = status;
    return DS_OK;
}
COM_METHOD(dsb, Initialize, 3) { return DS_OK; }

COM_METHOD(dsb, Lock, 8)
{
    dsbuf_t *b = BUFF;
    uint32_t offset = ARG(1), bytes = ARG(2), flags = ARG(7);
    if (b->primary || !b->size) return DSERR_INVALIDCALL;
    if (flags & 1u) {                                    /* DSBLOCK_FROMWRITECURSOR */
        pthread_mutex_lock(&mix_lock);
        offset = buffer_write_cursor(b);
        pthread_mutex_unlock(&mix_lock);
    }
    if (flags & 2u) bytes = b->size;                      /* DSBLOCK_ENTIREBUFFER */
    if (offset >= b->size || bytes > b->size) return DSERR_INVALIDPARAM;
    if (dstrace && (b->locks < 4 || !(b->locks & 63)))
        DSTRACE("buffer %08X lock #%u offset %u bytes %u flags %X (play %u)", b->com.guest, b->locks, offset, bytes, flags, b->play_pos);
    ++b->locks;
    uint32_t first = bytes <= b->size - offset ? bytes : b->size - offset;
    MEM32(ARG(3)) = b->data + offset;
    MEM32(ARG(4)) = first;
    if (ARG(5)) MEM32(ARG(5)) = first < bytes ? b->data : 0;
    if (ARG(6)) MEM32(ARG(6)) = bytes - first;
    if (dstrace) {
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        b->lock_ns = (uint64_t)now.tv_sec * 1000000000u + now.tv_nsec;
    }
    return DS_OK;
}

COM_METHOD(dsb, Play, 4)
{
    dsbuf_t *b = BUFF;
    pthread_mutex_lock(&mix_lock);
    if (!b->playing) {
        b->wrap_seen = 0;
        b->rs_valid = 0;
    }
    b->playing = 1;
    b->looping = (ARG(3) & DSBPLAY_LOOPING) != 0;
    pthread_mutex_unlock(&mix_lock);
    DSTRACE("buffer %08X play flags %X at %u of %u, %u Hz", b->com.guest, ARG(3), b->play_pos, b->size, b->frequency);
    start_mixer();
    return DS_OK;
}
COM_METHOD(dsb, SetCurrentPosition, 2)
{
    dsbuf_t *b = BUFF;
    pthread_mutex_lock(&mix_lock);
    b->play_pos = b->size ? (ARG(1) % b->size) / (b->block ? b->block : 1) * (b->block ? b->block : 1) : 0;
    b->frac = 0;
    b->wrap_seen = 0;
    b->rs_valid = 0;
    pthread_mutex_unlock(&mix_lock);
    DSTRACE("buffer %08X position %u", b->com.guest, ARG(1));
    return DS_OK;
}
COM_METHOD(dsb, SetFormat, 2) { return DS_OK; }
COM_METHOD(dsb, SetVolume, 2) { BUFF->volume = (int32_t)ARG(1); return DS_OK; }
COM_METHOD(dsb, SetPan, 2) { BUFF->pan = (int32_t)ARG(1); return DS_OK; }
COM_METHOD(dsb, SetFrequency, 2)
{
    dsbuf_t *b = BUFF;
    pthread_mutex_lock(&mix_lock);
    b->frequency = ARG(1) ? ARG(1) : b->rate;
    pthread_mutex_unlock(&mix_lock);
    if (dstrace && b->frequency != b->rate) DSTRACE("buffer %08X frequency %u (rate %u)", b->com.guest, b->frequency, b->rate);
    return DS_OK;
}
COM_METHOD(dsb, Stop, 1)
{
    dsbuf_t *b = BUFF;
    pthread_mutex_lock(&mix_lock);
    int was = b->playing;
    b->playing = 0;
    pthread_mutex_unlock(&mix_lock);
    DSTRACE("buffer %08X stop (was %d) at %u of %u", b->com.guest, was, b->play_pos, b->size);
    if (was) for (uint32_t k = 0; k < b->notify_count; ++k) if (b->notify_offset[k] == 0xFFFFFFFFu) signal_event(b->notify_event[k]);
    return DS_OK;
}
COM_METHOD(dsb, Unlock, 5)
{
    if (dstrace && (ARG(2) || ARG(4))) {
        dsbuf_t *b = BUFF;
        struct timespec now;
        clock_gettime(CLOCK_MONOTONIC, &now);
        uint64_t elapsed = (uint64_t)now.tv_sec * 1000000000u + now.tv_nsec - b->lock_ns;
        pthread_mutex_lock(&mix_lock);
        ++b->unlocks;
        if (b->playing) ++b->live_unlocks;
        if (elapsed > b->max_refill_ns) b->max_refill_ns = elapsed;
        pthread_mutex_unlock(&mix_lock);
    }
    return DS_OK;
}
COM_METHOD(dsb, Restore, 1) { return DS_OK; }
COM_METHOD(dsb, SetFX, 4) { return DSERR_CONTROLUNAVAIL; }
COM_METHOD(dsb, AcquireResources, 4) { return DS_OK; }
COM_METHOD(dsb, GetObjectInPath, 5) { return DSERR_UNSUPPORTED; }

static const void_fn buffer_methods[] = {
    dsb_QueryInterface, dsb_AddRef, dsb_Release, dsb_GetCaps, dsb_GetCurrentPosition, dsb_GetFormat, dsb_GetVolume,
    dsb_GetPan, dsb_GetFrequency, dsb_GetStatus, dsb_Initialize, dsb_Lock, dsb_Play, dsb_SetCurrentPosition,
    dsb_SetFormat, dsb_SetVolume, dsb_SetPan, dsb_SetFrequency, dsb_Stop, dsb_Unlock, dsb_Restore, dsb_SetFX,
    dsb_AcquireResources, dsb_GetObjectInPath,
};
static void_com_class buffer_class = { "IDirectSoundBuffer8", 24, buffer_methods, 0 };

/* -------------------------------------------------------- 3D buffer facet */
static float fval(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }
#define B3 (((facet_t *)void_com_host(THIS_))->owner)
COM_METHOD(d3b, QueryInterface, 3) { return buffer_query(B3, ARG(1), ARG(2)); }
COM_METHOD(d3b, AddRef, 1) { return void_com_addref(&B3->com); }
COM_METHOD(d3b, Release, 1) { return void_com_release(&B3->com); }
COM_METHOD(d3b, GetAllParameters, 2) { memset(GPTR(ARG(1) + 4), 0, 60); return DS_OK; }
COM_METHOD(d3b, GetConeAngles, 3) { if (ARG(1)) MEM32(ARG(1)) = 360; if (ARG(2)) MEM32(ARG(2)) = 360; return DS_OK; }
COM_METHOD(d3b, GetConeOrientation, 2) { memset(GPTR(ARG(1)), 0, 12); return DS_OK; }
COM_METHOD(d3b, GetConeOutsideVolume, 2) { MEM32(ARG(1)) = 0; return DS_OK; }
COM_METHOD(d3b, GetMaxDistance, 2) { memcpy(GPTR(ARG(1)), &B3->max_distance, 4); return DS_OK; }
COM_METHOD(d3b, GetMinDistance, 2) { memcpy(GPTR(ARG(1)), &B3->min_distance, 4); return DS_OK; }
COM_METHOD(d3b, GetMode, 2) { MEM32(ARG(1)) = B3->mode3d; return DS_OK; }
COM_METHOD(d3b, GetPosition, 2) { memcpy(GPTR(ARG(1)), B3->pos, 12); return DS_OK; }
COM_METHOD(d3b, GetVelocity, 2) { memset(GPTR(ARG(1)), 0, 12); return DS_OK; }
COM_METHOD(d3b, SetAllParameters, 3)
{
    dsbuf_t *b = B3;
    uint32_t p = ARG(1);
    memcpy(b->pos, GPTR(p + 4), 12);
    memcpy(&b->min_distance, GPTR(p + 52), 4);
    memcpy(&b->max_distance, GPTR(p + 56), 4);
    b->mode3d = MEM32(p + 60);
    return DS_OK;
}
COM_METHOD(d3b, SetConeAngles, 4) { return DS_OK; }
COM_METHOD(d3b, SetConeOrientation, 5) { return DS_OK; }
COM_METHOD(d3b, SetConeOutsideVolume, 3) { return DS_OK; }
COM_METHOD(d3b, SetMaxDistance, 3) { B3->max_distance = fval(ARG(1)); return DS_OK; }
COM_METHOD(d3b, SetMinDistance, 3) { B3->min_distance = fval(ARG(1)); return DS_OK; }
COM_METHOD(d3b, SetMode, 3) { B3->mode3d = ARG(1); return DS_OK; }
COM_METHOD(d3b, SetPosition, 5) { dsbuf_t *b = B3; b->pos[0] = fval(ARG(1)); b->pos[1] = fval(ARG(2)); b->pos[2] = fval(ARG(3)); return DS_OK; }
COM_METHOD(d3b, SetVelocity, 5) { return DS_OK; }
static const void_fn ds3d_methods[] = {
    d3b_QueryInterface, d3b_AddRef, d3b_Release, d3b_GetAllParameters, d3b_GetConeAngles, d3b_GetConeOrientation,
    d3b_GetConeOutsideVolume, d3b_GetMaxDistance, d3b_GetMinDistance, d3b_GetMode, d3b_GetPosition, d3b_GetVelocity,
    d3b_SetAllParameters, d3b_SetConeAngles, d3b_SetConeOrientation, d3b_SetConeOutsideVolume, d3b_SetMaxDistance,
    d3b_SetMinDistance, d3b_SetMode, d3b_SetPosition, d3b_SetVelocity,
};
static void_com_class ds3d_class = { "IDirectSound3DBuffer8", 21, ds3d_methods, 0 };

/* ------------------------------------------------------------- listener */
COM_METHOD(lst, QueryInterface, 3) { return buffer_query(B3, ARG(1), ARG(2)); }
COM_METHOD(lst, AddRef, 1) { return void_com_addref(&B3->com); }
COM_METHOD(lst, Release, 1) { return void_com_release(&B3->com); }
COM_METHOD(lst, GetAllParameters, 2) { memset(GPTR(ARG(1) + 4), 0, 60); return DS_OK; }
COM_METHOD(lst, GetDistanceFactor, 2) { memcpy(GPTR(ARG(1)), &distance_factor, 4); return DS_OK; }
COM_METHOD(lst, GetDopplerFactor, 2) { float one = 1.0f; memcpy(GPTR(ARG(1)), &one, 4); return DS_OK; }
COM_METHOD(lst, GetOrientation, 3) { memcpy(GPTR(ARG(1)), listener_front, 12); memcpy(GPTR(ARG(2)), listener_top, 12); return DS_OK; }
COM_METHOD(lst, GetPosition, 2) { memcpy(GPTR(ARG(1)), listener_pos, 12); return DS_OK; }
COM_METHOD(lst, GetRolloffFactor, 2) { memcpy(GPTR(ARG(1)), &rolloff, 4); return DS_OK; }
COM_METHOD(lst, GetVelocity, 2) { memset(GPTR(ARG(1)), 0, 12); return DS_OK; }
COM_METHOD(lst, SetAllParameters, 3)
{
    uint32_t p = ARG(1);
    memcpy(listener_pos, GPTR(p + 4), 12);
    memcpy(&distance_factor, GPTR(p + 28), 4);
    memcpy(&rolloff, GPTR(p + 32), 4);
    memcpy(listener_front, GPTR(p + 40), 12);
    memcpy(listener_top, GPTR(p + 52), 12);
    return DS_OK;
}
COM_METHOD(lst, SetDistanceFactor, 3) { distance_factor = fval(ARG(1)); return DS_OK; }
COM_METHOD(lst, SetDopplerFactor, 3) { return DS_OK; }
COM_METHOD(lst, SetOrientation, 8)
{
    listener_front[0] = fval(ARG(1)); listener_front[1] = fval(ARG(2)); listener_front[2] = fval(ARG(3));
    listener_top[0] = fval(ARG(4)); listener_top[1] = fval(ARG(5)); listener_top[2] = fval(ARG(6));
    return DS_OK;
}
COM_METHOD(lst, SetPosition, 5) { listener_pos[0] = fval(ARG(1)); listener_pos[1] = fval(ARG(2)); listener_pos[2] = fval(ARG(3)); return DS_OK; }
COM_METHOD(lst, SetRolloffFactor, 3) { rolloff = fval(ARG(1)); return DS_OK; }
COM_METHOD(lst, SetVelocity, 5) { return DS_OK; }
COM_METHOD(lst, CommitDeferredSettings, 1) { return DS_OK; }
static const void_fn listener_methods[] = {
    lst_QueryInterface, lst_AddRef, lst_Release, lst_GetAllParameters, lst_GetDistanceFactor, lst_GetDopplerFactor,
    lst_GetOrientation, lst_GetPosition, lst_GetRolloffFactor, lst_GetVelocity, lst_SetAllParameters,
    lst_SetDistanceFactor, lst_SetDopplerFactor, lst_SetOrientation, lst_SetPosition, lst_SetRolloffFactor,
    lst_SetVelocity, lst_CommitDeferredSettings,
};
static void_com_class listener_class = { "IDirectSound3DListener8", 18, listener_methods, 0 };

/* ---------------------------------------------------------------- notify */
COM_METHOD(ntf, QueryInterface, 3) { return buffer_query(B3, ARG(1), ARG(2)); }
COM_METHOD(ntf, AddRef, 1) { return void_com_addref(&B3->com); }
COM_METHOD(ntf, Release, 1) { return void_com_release(&B3->com); }
COM_METHOD(ntf, SetNotificationPositions, 3)
{
    dsbuf_t *b = B3;
    uint32_t count = ARG(1), list = ARG(2);
    if (count > 64) return DSERR_INVALIDPARAM;
    pthread_mutex_lock(&mix_lock);
    b->notify_count = count;
    for (uint32_t i = 0; i < count; ++i) { b->notify_offset[i] = MEM32(list + 8 * i); b->notify_event[i] = MEM32(list + 8 * i + 4); }
    pthread_mutex_unlock(&mix_lock);
    return DS_OK;
}
static const void_fn notify_methods[] = { ntf_QueryInterface, ntf_AddRef, ntf_Release, ntf_SetNotificationPositions };
static void_com_class notify_class = { "IDirectSoundNotify8", 4, notify_methods, 0 };

/* ------------------------------------------------------------- IDirectSound8 */
typedef struct { void_com_object com; } dsound_t;
#define DSND ((dsound_t *)void_com_host(THIS_))

COM_METHOD(ds, QueryInterface, 3)
{
    if (void_guid_equal(ARG(1), IID_IDirectSound8) || void_guid_equal(ARG(1), IID_IDirectSound) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&DSND->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(ds, AddRef, 1) { return void_com_addref(&DSND->com); }
COM_METHOD(ds, Release, 1) { return void_com_release(&DSND->com); }

COM_METHOD(ds, CreateSoundBuffer, 4)
{
    uint32_t desc = ARG(1), out = ARG(2);
    uint32_t flags = MEM32(desc + 4), bytes = MEM32(desc + 8), wfx = MEM32(desc + 16);
    dsbuf_t *b = (dsbuf_t *)calloc(1, sizeof *b);
    b->flags = flags;
    b->primary = (flags & DSBCAPS_PRIMARYBUFFER) != 0;
    b->min_distance = 1.0f;
    b->max_distance = 1e9f;
    if (wfx) {
        b->channels = MEM16(wfx + 2); b->rate = MEM32(wfx + 4); b->block = MEM16(wfx + 12); b->bits = MEM16(wfx + 14);
    } else {
        b->channels = 2; b->rate = 44100; b->bits = 16; b->block = 4;
    }
    b->frequency = b->rate;
    if (!b->primary) {
        if (!bytes || !b->block) { free(b); return DSERR_INVALIDPARAM; }
        b->size = bytes - bytes % b->block;
        b->data = void_galloc(b->size);
    }
    MEM32(out) = void_com_wrap(&b->com, &buffer_class, 0);
    b->com.destroy = buffer_destroy;
    pthread_mutex_lock(&mix_lock);
    b->next = buffers;
    buffers = b;
    pthread_mutex_unlock(&mix_lock);
    if (dstrace || void_verbose)
        void_log("[dsound] buffer %08X flags %08X %u bytes %u Hz %u ch %u bit", MEM32(out), flags, b->size, b->rate, b->channels, b->bits);
    return DS_OK;
}

COM_METHOD(ds, GetCaps, 2)
{
    uint32_t c = ARG(1), size = MEM32(c);
    memset(GPTR(c + 4), 0, size > 4 ? size - 4 : 0);
    MEM32(c + 4) = 0x0F5Fu;     /* continuous rate, mono/stereo, 8/16 bit, emulated=no */
    MEM32(c + 8) = 100; MEM32(c + 12) = 200000;
    MEM32(c + 20) = 64; MEM32(c + 24) = 64; MEM32(c + 28) = 64;     /* max hw mixing buffers */
    return DS_OK;
}

COM_METHOD(ds, DuplicateSoundBuffer, 3)
{
    dsbuf_t *src = buffer_of(ARG(1));
    dsbuf_t *b = (dsbuf_t *)calloc(1, sizeof *b);
    *b = *src;
    memset(&b->com, 0, sizeof b->com);
    memset(&b->f3d, 0, sizeof b->f3d);
    memset(&b->notify, 0, sizeof b->notify);
    b->playing = 0; b->play_pos = 0; b->frac = 0; b->notify_count = 0; b->rs_valid = 0;
    b->unlocks = b->live_unlocks = b->wrap_unlocks = b->unchanged_wraps = b->wrap_seen = 0;
    b->lock_ns = b->max_refill_ns = 0;
    /* A duplicate shares the PCM in D3D; copy it so lifetimes stay simple. */
    b->data = void_galloc(src->size);
    memcpy(GPTR(b->data), GPTR(src->data), src->size);
    MEM32(ARG(2)) = void_com_wrap(&b->com, &buffer_class, 0);
    b->com.destroy = buffer_destroy;
    pthread_mutex_lock(&mix_lock);
    b->next = buffers;
    buffers = b;
    pthread_mutex_unlock(&mix_lock);
    DSTRACE("buffer %08X duplicates %08X (%u bytes)", MEM32(ARG(2)), ARG(1), b->size);
    return DS_OK;
}

COM_METHOD(ds, SetCooperativeLevel, 3) { return DS_OK; }
COM_METHOD(ds, Compact, 1) { return DS_OK; }
COM_METHOD(ds, GetSpeakerConfig, 2) { MEM32(ARG(1)) = 4; return DS_OK; }   /* DSSPEAKER_STEREO */
COM_METHOD(ds, SetSpeakerConfig, 2) { return DS_OK; }
COM_METHOD(ds, Initialize, 2) { return DS_OK; }
COM_METHOD(ds, VerifyCertification, 2) { MEM32(ARG(1)) = 0; return DS_OK; }

static const void_fn dsound_methods[] = {
    ds_QueryInterface, ds_AddRef, ds_Release, ds_CreateSoundBuffer, ds_GetCaps, ds_DuplicateSoundBuffer,
    ds_SetCooperativeLevel, ds_Compact, ds_GetSpeakerConfig, ds_SetSpeakerConfig, ds_Initialize, ds_VerifyCertification,
};
static void_com_class dsound_class = { "IDirectSound8", 12, dsound_methods, 0 };

/* dsound.dll ordinal 11: DirectSoundCreate8(guid, ppDS8, outer). */
static uint32_t ds_create(uint32_t outer, uint32_t out)
{
    if (!out || !void_vm_writable(out, 4)) return DSERR_INVALIDPARAM;
    MEM32(out) = 0;
    if (outer) return 0x80040110u; /* CLASS_E_NOAGGREGATION */
    dsound_t *d = (dsound_t *)calloc(1, sizeof *d);
    if (!d) return 0x8007000Eu;
    const char *trace = getenv("VOID_DSOUND_TRACE");
    dstrace = trace && *trace == '1';
    if (!dstrace) {
        char path[1200];
        snprintf(path, sizeof path, "%s/audio_trace", void_data_dir());
        FILE *flag = fopen(path, "r");
        if (flag) { dstrace = 1; fclose(flag); }
    }
    MEM32(out) = void_com_wrap(&d->com, &dsound_class, 0);
    void_log("[dsound] DirectSoundCreate = %08X trace=%d", MEM32(out), dstrace);
    return DS_OK;
}

WINAPI_ORDINAL("dsound.dll", DirectSoundCreate8, 11, 3) { return ds_create(ARG(2), ARG(1)); }
WINAPI_ORDINAL("dsound.dll", DirectSoundCreate, 1, 3) { return ds_create(ARG(2), ARG(1)); }

WINAPI_ORDINAL("dsound.dll", DirectSoundEnumerateA, 2, 2)
{
    if (!ARG(0)) return DSERR_INVALIDPARAM;
    uint32_t description = void_gstrdup("Android DirectSound"), module = void_gstrdup("dsound.dll");
    uint32_t args[4] = {0, description, module, ARG(1)};
    void_call_guest(ARG(0), 4, args, 1);
    void_gfree(description);
    void_gfree(module);
    return DS_OK;
}
