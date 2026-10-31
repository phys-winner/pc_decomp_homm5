"""The ACM streams FMOD Ex needs for MS ADPCM decode exactly as Windows' own msadp32 codec does."""
import struct
import sys
import unittest
import zipfile
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from editions import game_directory   # noqa: E402

# The game's only MS ADPCM files: Sounds/_(Sound)/Ambients/SnowAmbientSet 01, 02, 03, 05 and 07.
SNOW = ("3D555841-D868-41AC-8015-28E79EBC5A81", "1D4371AB-FFD8-4119-B901-B0B8758F36D3",
        "E30E4385-D797-407C-B4C8-EAB05FE3D65B", "FBB4C69E-35C6-4B21-ACF0-C13CD8B5AA69",
        "A47801E6-E41D-4326-8767-A61E9AB61F6F")

FAKE_HOST = r'''
#pragma once
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
static unsigned char memory[1 << 22];
#undef GPTR   /* winbase.h: GlobalAlloc flags */
#define GPTR(p) (memory + (uint32_t)(p))
#define MEM8(p) (*(uint8_t *)GPTR(p))
#define MEM16(p) (*(uint16_t *)GPTR(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
static uint32_t g_eax, g_esp;
#define ARG(i) MEM32(g_esp + 4u + 4u * (uint32_t)(i))
static int void_vm_readable(uint32_t a, uint32_t n) { return a >= 0x1000 && (uint64_t)a + n <= sizeof memory; }
static int void_vm_writable(uint32_t a, uint32_t n) { return a >= 0x1000 && (uint64_t)a + n <= sizeof memory; }
static int log_lines;
static void void_log(const char *format, ...) { (void)format; ++log_lines; }
typedef void (*void_fn)(void);
typedef struct void_shim { const char *dll; const char *name; uint32_t ordinal; void_fn fn; } void_shim;
#define VOID_SHIM_SECTION
#define WINAPI_EXPORT(dll, name, nargs) \
    static uint32_t name##_impl(void); \
    static void name##_entry(void) { uint32_t _r = name##_impl(); g_eax = _r; g_esp += 4u + 4u * (nargs); } \
    static const void_shim name##_shim VOID_SHIM_SECTION = { dll, #name, 0, name##_entry }; \
    static uint32_t name##_impl(void)
'''

HARNESS = r'''
#include "host.h"
#include "msacm.c"
#undef WAVE_FORMAT_PCM
#undef WAVE_FORMAT_ADPCM
#undef MMSYSERR_INVALHANDLE
#undef MMSYSERR_NOMEM
#undef MMSYSERR_NOTSUPPORTED
#undef MMSYSERR_INVALFLAG
#undef MMSYSERR_INVALPARAM
#undef ACMERR_NOTPOSSIBLE
#undef ACMERR_UNPREPARED
#undef ACM_FORMATSUGGESTF_WFORMATTAG
#undef ACM_FORMATSUGGESTF_NCHANNELS
#undef ACM_FORMATSUGGESTF_NSAMPLESPERSEC
#undef ACM_FORMATSUGGESTF_WBITSPERSAMPLE
#undef ACM_FORMATSUGGESTF_TYPEMASK
#undef ACM_STREAMOPENF_QUERY
#undef ACM_STREAMOPENF_ASYNC
#undef ACM_STREAMOPENF_NONREALTIME
#undef ACM_STREAMSIZEF_DESTINATION
#undef ACM_STREAMCONVERTF_BLOCKALIGN
#undef ACM_STREAMCONVERTF_START
#undef ACM_STREAMCONVERTF_END
#undef ACMSTREAMHEADER_STATUSF_DONE
#undef ACMSTREAMHEADER_STATUSF_PREPARED
#undef MSACM
#include <mmsystem.h>
#include <mmreg.h>
#include <msacm.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#pragma comment(lib, "msacm32.lib")
#include "files.h"

#define CHECK(x) do { if (!(x)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #x); exit(1); } } while (0)
enum { STACK = 0x8000, SRC_FMT = 0x9000, DST_FMT = 0x9100, HANDLE_OUT = 0x9200, HEADER = 0x9300, DATA = 0x10000, PCM = 0x200000 };

static uint32_t call(void_fn entry, unsigned count, const uint32_t *args)
{
    MEM32(STACK) = 0xDEADBEEFu;
    for (unsigned i = 0; i < count; ++i) MEM32(STACK + 4 + 4 * i) = args[i];
    g_esp = STACK; g_eax = 0xCCCCCCCCu;
    entry();
    CHECK(g_esp == STACK + 4 + 4 * count);   /* stdcall: the callee pops its arguments */
    return g_eax;
}

/* FMOD's own sequence (0x1101F655, 0x1101F94D): suggest PCM, open, size of the whole chunk, then one
 * header per read through prepare/convert/unprepare, keeping only cbDstLengthUsed. */
static uint32_t shim_decode(const uint8_t *wfx, uint32_t wfx_size, const uint8_t *data, uint32_t size,
                            uint32_t chunk_blocks, uint8_t *out)
{
    memcpy(GPTR(SRC_FMT), wfx, wfx_size);
    memset(GPTR(DST_FMT), 0, 18); MEM16(DST_FMT) = 1;
    const uint32_t suggest[] = {0, SRC_FMT, DST_FMT, 0x12, 0x10000};
    CHECK(call(acmFormatSuggest_entry, 5, suggest) == 0);
    CHECK(MEM16(DST_FMT) == 1 && MEM16(DST_FMT + 2) == MEM16(SRC_FMT + 2) && MEM32(DST_FMT + 4) == MEM32(SRC_FMT + 4));
    CHECK(MEM16(DST_FMT + 14) == 16 && MEM16(DST_FMT + 12) == 2 * MEM16(SRC_FMT + 2) && !MEM16(DST_FMT + 16));
    const uint32_t open[] = {HANDLE_OUT, 0, SRC_FMT, DST_FMT, 0, 0, 0, 4};
    CHECK(call(acmStreamOpen_entry, 8, open) == 0);
    uint32_t stream = MEM32(HANDLE_OUT);
    const uint32_t sizing[] = {stream, size, HANDLE_OUT + 4, 0};
    CHECK(call(acmStreamSize_entry, 4, sizing) == 0);
    uint32_t expected = MEM32(HANDLE_OUT + 4), produced = 0, block = MEM16(SRC_FMT + 12);
    memcpy(GPTR(DATA), data, size);
    for (uint32_t at = 0; at < size; at += chunk_blocks * block) {
        uint32_t length = size - at < chunk_blocks * block ? size - at : chunk_blocks * block;
        memset(GPTR(HEADER), 0, 0x54);
        MEM32(HEADER) = 0x54; MEM32(HEADER + 0xC) = DATA + at; MEM32(HEADER + 0x10) = length;
        MEM32(HEADER + 0x1C) = PCM + produced; MEM32(HEADER + 0x20) = expected - produced;
        const uint32_t step[] = {stream, HEADER, 0};
        CHECK(call(acmStreamPrepareHeader_entry, 3, step) == 0);
        CHECK(call(acmStreamConvert_entry, 3, step) == 0);
        CHECK(MEM32(HEADER + 4) & 0x00010000u);
        CHECK(MEM32(HEADER + 0x14) == length / block * block);
        produced += MEM32(HEADER + 0x24);
        CHECK(call(acmStreamUnprepareHeader_entry, 3, step) == 0);
        CHECK(!(MEM32(HEADER + 4) & 0x00020000u));
    }
    CHECK(produced == expected);
    const uint32_t close[] = {stream, 0};
    CHECK(call(acmStreamClose_entry, 2, close) == 0);
    CHECK(call(acmStreamClose_entry, 2, close) == 5);   /* the handle is gone */
    memcpy(out, GPTR(PCM), produced);
    return produced;
}

/* The same data through Windows' Microsoft ADPCM codec (msadp32.acm). */
static uint32_t windows_decode(const uint8_t *wfx, const uint8_t *data, uint32_t size, uint8_t *out, uint32_t room)
{
    WAVEFORMATEX pcm;
    memset(&pcm, 0, sizeof pcm); pcm.wFormatTag = WAVE_FORMAT_PCM;
    CHECK(acmFormatSuggest(NULL, (LPWAVEFORMATEX)wfx, &pcm, sizeof pcm, ACM_FORMATSUGGESTF_WFORMATTAG) == 0);
    HACMSTREAM stream;
    CHECK(acmStreamOpen(&stream, NULL, (LPWAVEFORMATEX)wfx, &pcm, NULL, 0, 0, ACM_STREAMOPENF_NONREALTIME) == 0);
    DWORD expected = 0;
    CHECK(acmStreamSize(stream, size, &expected, ACM_STREAMSIZEF_SOURCE) == 0 && expected <= room);
    ACMSTREAMHEADER header;
    memset(&header, 0, sizeof header);
    header.cbStruct = sizeof header; header.pbSrc = (LPBYTE)data; header.cbSrcLength = size;
    header.pbDst = out; header.cbDstLength = expected;
    CHECK(acmStreamPrepareHeader(stream, &header, 0) == 0);
    CHECK(acmStreamConvert(stream, &header, 0) == 0);
    DWORD produced = header.cbDstLengthUsed;
    CHECK(acmStreamUnprepareHeader(stream, &header, 0) == 0);
    CHECK(acmStreamClose(stream, 0) == 0);
    CHECK(produced == expected);
    return produced;
}

/* PCM -> MS ADPCM with Windows' encoder: the synthetic inputs are real msadp32 streams. */
static uint32_t windows_encode(unsigned channels, const int16_t *samples, uint32_t frames, uint8_t *wfx, uint32_t wfx_room,
                               uint8_t *out, uint32_t room)
{
    WAVEFORMATEX pcm = {WAVE_FORMAT_PCM, (WORD)channels, 44100, 44100 * 2 * channels, (WORD)(2 * channels), 16, 0};
    memset(wfx, 0, wfx_room);
    ((WAVEFORMATEX *)wfx)->wFormatTag = WAVE_FORMAT_ADPCM;
    CHECK(acmFormatSuggest(NULL, &pcm, (LPWAVEFORMATEX)wfx, wfx_room, ACM_FORMATSUGGESTF_WFORMATTAG) == 0);
    HACMSTREAM stream;
    CHECK(acmStreamOpen(&stream, NULL, &pcm, (LPWAVEFORMATEX)wfx, NULL, 0, 0, ACM_STREAMOPENF_NONREALTIME) == 0);
    ACMSTREAMHEADER header;
    memset(&header, 0, sizeof header);
    header.cbStruct = sizeof header; header.pbSrc = (LPBYTE)samples; header.cbSrcLength = frames * 2 * channels;
    header.pbDst = out; header.cbDstLength = room;
    CHECK(acmStreamPrepareHeader(stream, &header, 0) == 0);
    CHECK(acmStreamConvert(stream, &header, ACM_STREAMCONVERTF_START | ACM_STREAMCONVERTF_END) == 0);
    uint32_t produced = header.cbDstLengthUsed;
    CHECK(acmStreamUnprepareHeader(stream, &header, 0) == 0);
    CHECK(acmStreamClose(stream, 0) == 0);
    return produced / ((WAVEFORMATEX *)wfx)->nBlockAlign * ((WAVEFORMATEX *)wfx)->nBlockAlign;
}

static uint8_t adpcm[1 << 20], expected_pcm[1 << 22], actual_pcm[1 << 22];

static void compare(const char *what, const uint8_t *wfx, uint32_t wfx_size, const uint8_t *data, uint32_t size)
{
    uint32_t want = windows_decode(wfx, data, size, expected_pcm, (uint32_t)sizeof expected_pcm);
    uint32_t block = ((const WAVEFORMATEX *)wfx)->nBlockAlign, blocks = size / block;
    uint32_t chunks[] = {1, 3, blocks ? blocks : 1};
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t got = shim_decode(wfx, wfx_size, data, size, chunks[i], actual_pcm);
        CHECK(got == want);
        if (memcmp(expected_pcm, actual_pcm, got)) {
            for (uint32_t at = 0; at < got; ++at) if (expected_pcm[at] != actual_pcm[at]) {
                printf("FAIL %s: chunk %u differs at byte %u\n", what, chunks[i], at); exit(1);
            }
        }
    }
    printf("%s: %u ADPCM bytes, %u PCM bytes identical to msadp32\n", what, size, want);
}

static void synthetic(unsigned channels)
{
    static int16_t samples[2 * 44100];
    const uint32_t frames = 44100;
    srand(7 + channels);
    for (uint32_t i = 0; i < frames; ++i) for (unsigned c = 0; c < channels; ++c) {
        double t = (double)i / 44100.0, sweep = sin(2 * 3.14159265358979 * (200 + 9000 * t) * t * (c + 1));
        double v = 26000 * sweep * (i % 11025 < 9000 ? 1.0 : 0.05) + (rand() % 2001 - 1000);
        samples[i * channels + c] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
    }
    uint8_t wfx[256];
    uint32_t size = windows_encode(channels, samples, frames, wfx, (uint32_t)sizeof wfx, adpcm, (uint32_t)sizeof adpcm);
    CHECK(((WAVEFORMATEX *)wfx)->wFormatTag == WAVE_FORMAT_ADPCM && size > 0);
    compare(channels == 1 ? "synthetic mono" : "synthetic stereo", wfx, 18 + ((WAVEFORMATEX *)wfx)->cbSize, adpcm, size);
}

static void contract(void)
{
    /* A mono 1024-byte-block format with the standard table, as the snow files carry it. */
    static const int16_t coef[7][2] = {{256, 0}, {512, -256}, {0, 0}, {192, 64}, {240, 0}, {460, -208}, {392, -232}};
    uint8_t wfx[50];
    memset(wfx, 0, sizeof wfx);
    WAVEFORMATEX *w = (WAVEFORMATEX *)wfx;
    w->wFormatTag = 2; w->nChannels = 1; w->nSamplesPerSec = 44100; w->nBlockAlign = 1024; w->wBitsPerSample = 4; w->cbSize = 32;
    w->nAvgBytesPerSec = 22311;
    uint16_t samples = 2036, count = 7;
    memcpy(wfx + 18, &samples, 2); memcpy(wfx + 20, &count, 2); memcpy(wfx + 22, coef, sizeof coef);
    memcpy(GPTR(SRC_FMT), wfx, sizeof wfx);
    memset(GPTR(DST_FMT), 0, 18); MEM16(DST_FMT) = 1;
    uint32_t args[8] = {0, SRC_FMT, DST_FMT, 0x12, 0x10000};
    CHECK(call(acmFormatSuggest_entry, 5, args) == 0 && MEM32(DST_FMT + 8) == 88200);
    MEM16(DST_FMT) = 0x11;   /* a requested IMA tag is not this codec's output */
    CHECK(call(acmFormatSuggest_entry, 5, args) == 512);
    MEM16(DST_FMT) = 1; args[4] = 1;
    CHECK(call(acmFormatSuggest_entry, 5, args) == 10);
    args[4] = 0x10000; args[3] = 15;
    CHECK(call(acmFormatSuggest_entry, 5, args) == 11);
    args[3] = 0x12; MEM16(SRC_FMT) = 1;   /* PCM never reaches this codec */
    CHECK(call(acmFormatSuggest_entry, 5, args) == 512);
    MEM16(SRC_FMT) = 2; MEM16(SRC_FMT + 18) = 2037;   /* more samples than a 1024-byte block holds */
    CHECK(call(acmFormatSuggest_entry, 5, args) == 512);
    MEM16(SRC_FMT + 18) = 2036;
    CHECK(call(acmFormatSuggest_entry, 5, args) == 0);
    uint32_t open[8] = {HANDLE_OUT, 0, SRC_FMT, DST_FMT, 0, 0, 0, 1};
    MEM32(HANDLE_OUT) = 77;
    CHECK(call(acmStreamOpen_entry, 8, open) == 0 && MEM32(HANDLE_OUT) == 0);   /* a query opens nothing */
    open[7] = 4; open[4] = 0x9400;
    CHECK(call(acmStreamOpen_entry, 8, open) == 512);                   /* no filters */
    open[4] = 0; MEM32(DST_FMT + 4) = 22050;
    CHECK(call(acmStreamOpen_entry, 8, open) == 512);                   /* no resampling */
    MEM32(DST_FMT + 4) = 44100; open[7] = 0x10000000;
    CHECK(call(acmStreamOpen_entry, 8, open) == 10);
    open[7] = 4;
    int lines = log_lines;
    CHECK(call(acmStreamOpen_entry, 8, open) == 0 && MEM32(HANDLE_OUT) == ACM_HANDLE_BASE + 1 && log_lines == lines + 1);
    uint32_t stream = MEM32(HANDLE_OUT);
    uint32_t size[4] = {stream, 1023, HANDLE_OUT + 4, 0};
    CHECK(call(acmStreamSize_entry, 4, size) == 512);                   /* less than one block */
    size[1] = 3 * 1024 + 5;
    CHECK(call(acmStreamSize_entry, 4, size) == 0 && MEM32(HANDLE_OUT + 4) == 3 * 2036 * 2);
    size[1] = 2 * 2036 * 2 + 1; size[3] = 1;
    CHECK(call(acmStreamSize_entry, 4, size) == 0 && MEM32(HANDLE_OUT + 4) == 2 * 1024);
    size[3] = 2;
    CHECK(call(acmStreamSize_entry, 4, size) == 10);
    size[0] = stream + 1; size[3] = 0;
    CHECK(call(acmStreamSize_entry, 4, size) == 5);
    memset(GPTR(HEADER), 0, 0x54); MEM32(HEADER) = 0x54;
    MEM32(HEADER + 0xC) = DATA; MEM32(HEADER + 0x10) = 1024; MEM32(HEADER + 0x1C) = PCM; MEM32(HEADER + 0x20) = 4072;
    uint32_t step[3] = {stream, HEADER, 0};
    CHECK(call(acmStreamConvert_entry, 3, step) == 514);                /* unprepared */
    CHECK(call(acmStreamUnprepareHeader_entry, 3, step) == 514);
    MEM32(HEADER) = 0x50;
    CHECK(call(acmStreamPrepareHeader_entry, 3, step) == 11);
    MEM32(HEADER) = 0x54; step[2] = 1;
    CHECK(call(acmStreamPrepareHeader_entry, 3, step) == 10);
    step[2] = 0;
    CHECK(call(acmStreamPrepareHeader_entry, 3, step) == 0);
    MEM32(HEADER + 0x20) = 4071;                                         /* no room for the block */
    CHECK(call(acmStreamConvert_entry, 3, step) == 0 && !MEM32(HEADER + 0x14) && !MEM32(HEADER + 0x24));
    MEM32(HEADER + 0x1C) = (uint32_t)(sizeof memory - 100); MEM32(HEADER + 0x20) = 4072;
    CHECK(call(acmStreamConvert_entry, 3, step) == 11);                 /* destination outside guest memory */
    MEM32(HEADER + 0x1C) = PCM;
    /* Predictor 9 is outside the seven pairs: the first pair, not a read past the table. */
    memset(GPTR(DATA), 0x77, 1024); MEM8(DATA) = 9; MEM16(DATA + 1) = 16; MEM16(DATA + 3) = 100; MEM16(DATA + 5) = 50;
    CHECK(call(acmStreamConvert_entry, 3, step) == 0 && MEM32(HEADER + 0x24) == 4072);
    CHECK(MEM16(PCM) == 50 && MEM16(PCM + 2) == 100 && (int16_t)MEM16(PCM + 4) == 100 + 7 * 16);
    CHECK(call(acmStreamUnprepareHeader_entry, 3, step) == 0);
    uint32_t close[2] = {stream, 1};
    CHECK(call(acmStreamClose_entry, 2, close) == 10);
    close[1] = 0;
    CHECK(call(acmStreamClose_entry, 2, close) == 0);
    for (unsigned i = 0; i < ACM_STREAMS; ++i) CHECK(call(acmStreamOpen_entry, 8, open) == 0);
    CHECK(call(acmStreamOpen_entry, 8, open) == 7);                     /* every slot in use */
    for (unsigned i = 0; i < ACM_STREAMS; ++i) {
        close[0] = ACM_HANDLE_BASE + 1 + i;
        CHECK(call(acmStreamClose_entry, 2, close) == 0);
    }
    puts("ACM contract: suggest/open/size/prepare/convert/unprepare/close results and stack pops");
}

static uint8_t *load(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    CHECK(f);
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc((size_t)n);
    CHECK(data && fread(data, 1, (size_t)n, f) == (size_t)n);
    fclose(f);
    *size = (uint32_t)n;
    return data;
}

int main(void)
{
    contract();
    synthetic(1);
    synthetic(2);
    for (unsigned i = 0; i < GAME_FILES; ++i) {
        uint32_t fmt_size, size;
        uint8_t *fmt = load(game_fmt[i], &fmt_size), *data = load(game_data[i], &size);
        compare(game_name[i], fmt, fmt_size, data, size);
        free(fmt); free(data);
    }
    printf("PASS msacm: %u game files\n", (unsigned)GAME_FILES);
    return 0;
}
'''


def snow_files(out):
    """fmt/data chunks of the game's MS ADPCM sounds, written next to the probe (none without the game)."""
    try:
        pak = game_directory("toe") / "data/soundsfx.pak"
    except (OSError, ValueError):
        return []
    if not pak.exists():
        return []
    files = []
    with zipfile.ZipFile(pak) as archive:
        for uid in SNOW:
            data = archive.read("bin/Sounds/" + uid)
            assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", uid
            chunks, at = {}, 12
            while at + 8 <= len(data):
                cid, size = data[at:at + 4], struct.unpack_from("<I", data, at + 4)[0]
                chunks[cid] = data[at + 8:at + 8 + size]
                at += 8 + size + (size & 1)
            fmt = chunks[b"fmt "]
            assert struct.unpack_from("<H", fmt)[0] == 2, uid   # WAVE_FORMAT_ADPCM
            out.mkdir(parents=True, exist_ok=True)
            (out / (uid + ".fmt")).write_bytes(fmt)
            (out / (uid + ".dat")).write_bytes(chunks[b"data"])
            files.append(uid)
    return files


class MsAcmTest(unittest.TestCase):
    def test_ms_adpcm_matches_windows_codec(self):
        out = ROOT / "build/tests/msacm"
        files = snow_files(out)
        quoted = lambda path: '"' + str(path).replace("\\", "/") + '"'
        listing = "\n".join([
            "#define GAME_FILES %d" % len(files),
            "static const char *game_name[] = {%s};" % ", ".join(['"snow %s"' % uid[:8] for uid in files] or ["0"]),
            "static const char *game_fmt[] = {%s};" % ", ".join([quoted(out / (uid + ".fmt")) for uid in files] or ["0"]),
            "static const char *game_data[] = {%s};" % ", ".join([quoted(out / (uid + ".dat")) for uid in files] or ["0"]),
        ]) + "\n"
        source = (ROOT / "android/host/msacm.c").read_text(encoding="utf-8")
        compile_probe("msacm", HARNESS, {"host.h": FAKE_HOST, "msacm.c": source, "files.h": listing})

    def test_all_editions_and_imports_fmod_uses(self):
        source = (ROOT / "android/host/msacm.c").read_text(encoding="utf-8")
        self.assertNotIn("HOMM5_LEGACY_UI", source)   # the legacy FMOD builds import the same seven calls
        for name in ("acmStreamConvert", "acmStreamUnprepareHeader", "acmStreamClose", "acmFormatSuggest",
                     "acmStreamOpen", "acmStreamSize", "acmStreamPrepareHeader"):
            self.assertIn("WINAPI_EXPORT(MSACM, %s," % name, source)


if __name__ == "__main__":
    unittest.main()
