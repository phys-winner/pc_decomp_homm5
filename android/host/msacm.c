/* The Audio Compression Manager streams (msacm32.dll) FMOD Ex uses, in all three editions, for WAVE formats
 * its codec_wav does not decode itself (ToE 0x1101F655: PCM and IMA ADPCM are its own, MPEG goes elsewhere,
 * any other tag asks ACM). Hammers of Fate and Tribes of the East ship exactly five such files, all MS ADPCM
 * (WAVE_FORMAT_ADPCM, 4-bit, mono, 44.1 kHz, 1024-byte blocks): the random sounds of the snow terrain
 * ambience (Sounds/_(Sound)/Ambients/SnowAmbientSet 01/02/03/05/07, in soundsfx.pak / a1-sound.pak).
 * Without these exports the first of them to play (a few seconds on snow, or a battle on a snow arena)
 * reached the missing-import trap. FMOD asks acmFormatSuggest for
 * PCM, acmStreamOpen(NONREALTIME), acmStreamSize(SOURCE) for the whole data chunk, then per read one
 * header through Prepare/Convert(0)/Unprepare and uses only cbDstLengthUsed (0x1101F94D). Decoding follows
 * the Microsoft ADPCM block format: per channel a predictor index, delta and two history samples, the two
 * history samples output first, then signed nibbles (high first; stereo interleaves left/right). */
#include "host.h"
#include <stdlib.h>
#include <string.h>

#define MSACM "msacm32.dll"

#define WAVE_FORMAT_PCM 1u
#define WAVE_FORMAT_ADPCM 2u
#define MMSYSERR_INVALHANDLE 5u
#define MMSYSERR_NOMEM 7u
#define MMSYSERR_NOTSUPPORTED 8u
#define MMSYSERR_INVALFLAG 10u
#define MMSYSERR_INVALPARAM 11u
#define ACMERR_NOTPOSSIBLE 512u
#define ACMERR_UNPREPARED 514u
#define ACM_FORMATSUGGESTF_WFORMATTAG 0x00010000u
#define ACM_FORMATSUGGESTF_NCHANNELS 0x00020000u
#define ACM_FORMATSUGGESTF_NSAMPLESPERSEC 0x00040000u
#define ACM_FORMATSUGGESTF_WBITSPERSAMPLE 0x00080000u
#define ACM_FORMATSUGGESTF_TYPEMASK 0x00FF0000u
#define ACM_STREAMOPENF_QUERY 0x1u
#define ACM_STREAMOPENF_ASYNC 0x2u
#define ACM_STREAMOPENF_NONREALTIME 0x4u
#define ACM_STREAMSIZEF_DESTINATION 0x1u
#define ACM_STREAMCONVERTF_BLOCKALIGN 0x4u
#define ACM_STREAMCONVERTF_START 0x10u
#define ACM_STREAMCONVERTF_END 0x20u
#define ACMSTREAMHEADER_SIZE 0x54u
#define ACMSTREAMHEADER_STATUSF_DONE 0x00010000u
#define ACMSTREAMHEADER_STATUSF_PREPARED 0x00020000u
#define ACM_STREAMS 64
#define ACM_HANDLE_BASE 0x41434D00u   /* 'ACM\0' + slot + 1: opaque to FMOD, never dereferenced */
#define ADPCM_COEFS 32

/* The standard coefficient pairs (MS ADPCM's seven), used when a format carries none. */
static const int16_t adpcm_standard[7][2] = {{256, 0}, {512, -256}, {0, 0}, {192, 64}, {240, 0}, {460, -208}, {392, -232}};
static const int16_t adpcm_adapt[16] = {230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230};

typedef struct {
    int used;
    uint32_t rate;
    unsigned channels, block, samples, bits, coefs;   /* source block bytes, samples per block, output bits */
    int16_t coef[ADPCM_COEFS][2];
} acm_stream;
static acm_stream acm_streams[ACM_STREAMS];

/* An MS ADPCM WAVEFORMATEX (with its ADPCMWAVEFORMAT tail) at a guest address, 0 when not decodable. */
static int adpcm_format(uint32_t wfx, acm_stream *out)
{
    if (!wfx || !void_vm_readable(wfx, 18) || MEM16(wfx) != WAVE_FORMAT_ADPCM) return 0;
    unsigned channels = MEM16(wfx + 2), block = MEM16(wfx + 12), bits = MEM16(wfx + 14), extra = MEM16(wfx + 16);
    uint32_t rate = MEM32(wfx + 4);
    if (channels < 1 || channels > 2 || bits != 4 || !rate || block < 7 * channels) return 0;
    /* Each channel's header holds two samples; the rest of the block is one nibble per sample. */
    unsigned samples = 2 + (block - 7 * channels) * 2 / channels, coefs = 0;
    if (extra >= 4 && void_vm_readable(wfx + 18, 4)) {
        unsigned declared = MEM16(wfx + 18), count = MEM16(wfx + 20);
        if (declared) {
            if (declared < 2 || declared > samples) return 0;
            samples = declared;
        }
        if (count && count <= ADPCM_COEFS && extra >= 4 + 4 * count && void_vm_readable(wfx + 22, 4 * count)) coefs = count;
    }
    memset(out, 0, sizeof *out);
    out->rate = rate; out->channels = channels; out->block = block; out->samples = samples; out->bits = 16;
    if (coefs) {
        out->coefs = coefs;
        for (unsigned i = 0; i < coefs; ++i) {
            out->coef[i][0] = (int16_t)MEM16(wfx + 22 + 4 * i);
            out->coef[i][1] = (int16_t)MEM16(wfx + 24 + 4 * i);
        }
    } else {
        out->coefs = 7;
        memcpy(out->coef, adpcm_standard, sizeof adpcm_standard);
    }
    return 1;
}

/* A PCM destination this stream can fill: same channels and rate, 8 or 16 bits. */
static int pcm_target(uint32_t wfx, const acm_stream *stream, unsigned *bits)
{
    if (!wfx || !void_vm_readable(wfx, 16) || MEM16(wfx) != WAVE_FORMAT_PCM) return 0;
    unsigned b = MEM16(wfx + 14);
    if (MEM16(wfx + 2) != stream->channels || MEM32(wfx + 4) != stream->rate || (b != 8 && b != 16) ||
        MEM16(wfx + 12) != stream->channels * b / 8) return 0;
    *bits = b;
    return 1;
}

static unsigned frame_bytes(const acm_stream *stream) { return stream->channels * stream->bits / 8; }

static void adpcm_put(uint8_t **dst, int sample, unsigned bits)
{
    if (bits == 16) { (*dst)[0] = (uint8_t)sample; (*dst)[1] = (uint8_t)(sample >> 8); *dst += 2; }
    else *(*dst)++ = (uint8_t)((sample >> 8) + 128);
}

/* One block: src holds stream->block bytes, dst room for stream->samples frames. */
static void adpcm_block(const acm_stream *stream, const uint8_t *src, uint8_t *dst)
{
    unsigned channels = stream->channels;
    int coef1[2], coef2[2], delta[2], s1[2], s2[2];
    for (unsigned c = 0; c < channels; ++c) {
        unsigned predictor = src[c] < stream->coefs ? src[c] : 0;
        coef1[c] = stream->coef[predictor][0]; coef2[c] = stream->coef[predictor][1];
        const uint8_t *h = src + channels + 2 * c;
        delta[c] = (int16_t)(h[0] | h[1] << 8);
        s1[c] = (int16_t)(h[2 * channels] | h[2 * channels + 1] << 8);
        s2[c] = (int16_t)(h[4 * channels] | h[4 * channels + 1] << 8);
    }
    for (unsigned c = 0; c < channels; ++c) adpcm_put(&dst, s2[c], stream->bits);
    for (unsigned c = 0; c < channels; ++c) adpcm_put(&dst, s1[c], stream->bits);
    const uint8_t *data = src + 7 * channels;
    unsigned nibbles = (stream->samples - 2) * channels;
    for (unsigned i = 0; i < nibbles; ++i) {
        unsigned c = i % channels, nibble = i & 1 ? data[i >> 1] & 15 : data[i >> 1] >> 4;
        /* Floor, as msadp32's arithmetic shift (division would round negative predictions up). */
        int64_t weighted = (int64_t)s1[c] * coef1[c] + (int64_t)s2[c] * coef2[c];
        int64_t prediction = weighted >= 0 ? weighted / 256 : -((-weighted + 255) / 256);
        prediction += (int64_t)((int)nibble - (nibble & 8 ? 16 : 0)) * delta[c];
        int sample = prediction > 32767 ? 32767 : prediction < -32768 ? -32768 : (int)prediction;
        s2[c] = s1[c]; s1[c] = sample;
        int64_t next = (int64_t)delta[c] * adpcm_adapt[nibble] / 256;
        delta[c] = next < 16 ? 16 : next > 0x7FFFFF ? 0x7FFFFF : (int)next;
        adpcm_put(&dst, sample, stream->bits);
    }
}

static acm_stream *acm_stream_get(uint32_t handle)
{
    uint32_t slot = handle - ACM_HANDLE_BASE - 1;
    return slot < ACM_STREAMS && acm_streams[slot].used ? &acm_streams[slot] : NULL;
}

/* MMRESULT acmFormatSuggest(HACMDRIVER, LPWAVEFORMATEX src, LPWAVEFORMATEX dst, DWORD size, DWORD flags) */
WINAPI_EXPORT(MSACM, acmFormatSuggest, 5)
{
    uint32_t src = ARG(1), dst = ARG(2), size = ARG(3), flags = ARG(4);
    acm_stream stream;
    if (flags & ~ACM_FORMATSUGGESTF_TYPEMASK) return MMSYSERR_INVALFLAG;
    if (!dst || size < 16 || !void_vm_writable(dst, size < 18 ? 16 : 18)) return MMSYSERR_INVALPARAM;
    if (!adpcm_format(src, &stream)) return ACMERR_NOTPOSSIBLE;
    unsigned bits = flags & ACM_FORMATSUGGESTF_WBITSPERSAMPLE ? MEM16(dst + 14) : 16;
    if ((flags & ACM_FORMATSUGGESTF_WFORMATTAG && MEM16(dst) != WAVE_FORMAT_PCM) ||
        (flags & ACM_FORMATSUGGESTF_NCHANNELS && MEM16(dst + 2) != stream.channels) ||
        (flags & ACM_FORMATSUGGESTF_NSAMPLESPERSEC && MEM32(dst + 4) != stream.rate) || (bits != 8 && bits != 16))
        return ACMERR_NOTPOSSIBLE;
    MEM16(dst) = WAVE_FORMAT_PCM; MEM16(dst + 2) = (uint16_t)stream.channels; MEM32(dst + 4) = stream.rate;
    MEM16(dst + 12) = (uint16_t)(stream.channels * bits / 8); MEM32(dst + 8) = stream.rate * MEM16(dst + 12);
    MEM16(dst + 14) = (uint16_t)bits;
    if (size >= 18) MEM16(dst + 16) = 0;
    return 0;
}

/* MMRESULT acmStreamOpen(LPHACMSTREAM, HACMDRIVER, src, dst, LPWAVEFILTER, callback, instance, DWORD flags) */
WINAPI_EXPORT(MSACM, acmStreamOpen, 8)
{
    uint32_t out = ARG(0), src = ARG(2), dst = ARG(3), filter = ARG(4), flags = ARG(7);
    acm_stream stream;
    unsigned bits;
    if (flags & ~(ACM_STREAMOPENF_QUERY | ACM_STREAMOPENF_ASYNC | ACM_STREAMOPENF_NONREALTIME | 0x00070000u))
        return MMSYSERR_INVALFLAG;
    if (!(flags & ACM_STREAMOPENF_QUERY) && (!out || !void_vm_writable(out, 4))) return MMSYSERR_INVALPARAM;
    if (out && void_vm_writable(out, 4)) MEM32(out) = 0;
    if (filter || !adpcm_format(src, &stream) || !pcm_target(dst, &stream, &bits)) return ACMERR_NOTPOSSIBLE;
    if (flags & ACM_STREAMOPENF_ASYNC) return MMSYSERR_NOTSUPPORTED;   /* no callback thread: FMOD never asks */
    if (flags & ACM_STREAMOPENF_QUERY) return 0;
    stream.bits = bits;
    for (unsigned slot = 0; slot < ACM_STREAMS; ++slot) {
        if (acm_streams[slot].used) continue;
        acm_streams[slot] = stream;
        acm_streams[slot].used = 1;
        MEM32(out) = ACM_HANDLE_BASE + slot + 1;
        void_log("[acm] MS ADPCM stream %u: %u ch, %u Hz, block %u, %u samples, %u-bit PCM", slot + 1,
                 stream.channels, stream.rate, stream.block, stream.samples, bits);
        return 0;
    }
    return MMSYSERR_NOMEM;
}

/* MMRESULT acmStreamSize(HACMSTREAM, DWORD input, LPDWORD output, DWORD flags) */
WINAPI_EXPORT(MSACM, acmStreamSize, 4)
{
    acm_stream *stream = acm_stream_get(ARG(0));
    uint32_t input = ARG(1), out = ARG(2), flags = ARG(3);
    if (!stream) return MMSYSERR_INVALHANDLE;
    if (flags & ~ACM_STREAMSIZEF_DESTINATION) return MMSYSERR_INVALFLAG;
    if (!out || !void_vm_writable(out, 4)) return MMSYSERR_INVALPARAM;
    uint32_t pcm = stream->samples * frame_bytes(stream), blocks;
    if (flags & ACM_STREAMSIZEF_DESTINATION) {
        if (!(blocks = input / pcm)) return ACMERR_NOTPOSSIBLE;
        MEM32(out) = blocks * stream->block;
    } else {
        if (!(blocks = input / stream->block)) return ACMERR_NOTPOSSIBLE;
        if (blocks > UINT32_MAX / pcm) return MMSYSERR_INVALPARAM;
        MEM32(out) = blocks * pcm;
    }
    return 0;
}

/* The ACMSTREAMHEADER fields the calls use: cbStruct +0, fdwStatus +4, pbSrc +C, cbSrcLength +10,
 * cbSrcLengthUsed +14, pbDst +1C, cbDstLength +20, cbDstLengthUsed +24. */
static uint32_t acm_header(uint32_t handle, uint32_t header, uint32_t flags, uint32_t allowed)
{
    if (!acm_stream_get(handle)) return MMSYSERR_INVALHANDLE;
    if (flags & ~allowed) return MMSYSERR_INVALFLAG;
    if (!header || !void_vm_writable(header, ACMSTREAMHEADER_SIZE) || MEM32(header) < ACMSTREAMHEADER_SIZE)
        return MMSYSERR_INVALPARAM;
    return 0;
}

/* MMRESULT acmStreamPrepareHeader(HACMSTREAM, LPACMSTREAMHEADER, DWORD flags) */
WINAPI_EXPORT(MSACM, acmStreamPrepareHeader, 3)
{
    uint32_t header = ARG(1), result = acm_header(ARG(0), header, ARG(2), 0);
    if (!result) MEM32(header + 4) = (MEM32(header + 4) & ~ACMSTREAMHEADER_STATUSF_DONE) | ACMSTREAMHEADER_STATUSF_PREPARED;
    return result;
}

/* MMRESULT acmStreamConvert(HACMSTREAM, LPACMSTREAMHEADER, DWORD flags): whole blocks only, as msadp32. */
WINAPI_EXPORT(MSACM, acmStreamConvert, 3)
{
    uint32_t handle = ARG(0), header = ARG(1);
    uint32_t result = acm_header(handle, header, ARG(2),
                                 ACM_STREAMCONVERTF_BLOCKALIGN | ACM_STREAMCONVERTF_START | ACM_STREAMCONVERTF_END);
    if (result) return result;
    if (!(MEM32(header + 4) & ACMSTREAMHEADER_STATUSF_PREPARED)) return ACMERR_UNPREPARED;
    const acm_stream *stream = acm_stream_get(handle);
    uint32_t src = MEM32(header + 0xC), dst = MEM32(header + 0x1C), pcm = stream->samples * frame_bytes(stream);
    uint32_t blocks = MEM32(header + 0x10) / stream->block, room = MEM32(header + 0x20) / pcm;
    if (room < blocks) blocks = room;
    if (blocks && (!void_vm_readable(src, blocks * stream->block) || !void_vm_writable(dst, blocks * pcm)))
        return MMSYSERR_INVALPARAM;
    for (uint32_t i = 0; i < blocks; ++i)
        adpcm_block(stream, GPTR(src + i * stream->block), GPTR(dst + i * pcm));
    MEM32(header + 0x14) = blocks * stream->block;
    MEM32(header + 0x24) = blocks * pcm;
    MEM32(header + 4) |= ACMSTREAMHEADER_STATUSF_DONE;
    return 0;
}

/* MMRESULT acmStreamUnprepareHeader(HACMSTREAM, LPACMSTREAMHEADER, DWORD flags) */
WINAPI_EXPORT(MSACM, acmStreamUnprepareHeader, 3)
{
    uint32_t header = ARG(1), result = acm_header(ARG(0), header, ARG(2), 0);
    if (result) return result;
    if (!(MEM32(header + 4) & ACMSTREAMHEADER_STATUSF_PREPARED)) return ACMERR_UNPREPARED;
    MEM32(header + 4) &= ~ACMSTREAMHEADER_STATUSF_PREPARED;
    return 0;
}

/* MMRESULT acmStreamClose(HACMSTREAM, DWORD flags) */
WINAPI_EXPORT(MSACM, acmStreamClose, 2)
{
    acm_stream *stream = acm_stream_get(ARG(0));
    if (!stream) return MMSYSERR_INVALHANDLE;
    if (ARG(1)) return MMSYSERR_INVALFLAG;
    memset(stream, 0, sizeof *stream);
    return 0;
}
