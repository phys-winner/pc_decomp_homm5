"""Native deflate (android/host/zlib_deflate_native.c, hooked in zlib_native.c) versus the
game's own zlib1.dll 1.2.3, call by call.

A 32-bit Windows probe loads the original zlib1.dll (generated/input, the DLL the port lifts)
and links the engine. Both run the same streams: the two zlib payloads of a real save
(tools/harness/fixtures/pc-profile/Saves/save_6.sav, 32.8 MB and 1.7 MB) and synthetic data,
with the game's call patterns (deflateInit_ level -1 and deflateInit2_ level 9 raw -15; the
32 KiB chunk loop of 0x008C7FD0, the stream writer of 0x00D103B0, one-shot Z_FINISH of
0x0082D790/0x00AAABA0) plus random chunkings, levels and early ends. After every call the
probe compares the return code, next_in/avail_in/total_in, next_out/avail_out/total_out,
adler, data_type, msg and the bytes written; deflateEnd's result too; and the DLL's state
after init against the constants the hook writes.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import zlib

from test_mmx_packed import CLANG, command, environment
from test_static_tls import ROOT

HERE = ROOT / "build/tests/deflate-native"
ENGINE = Path(os.environ.get("DEFLATE_ENGINE_SOURCE", ROOT / "android/host/zlib_deflate_native.c"))
DLL = ROOT / "generated/input/zlib1.dll"
SAVE = ROOT / "tools/harness/fixtures/pc-profile/Saves/save_6.sav"

PROBE = r'''
#ifndef NATIVE_ONLY
#include <windows.h>
#else
#define __cdecl
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zlib_deflate_native.h"

typedef struct dll_stream {
    const uint8_t *next_in; uint32_t avail_in, total_in;
    uint8_t *next_out; uint32_t avail_out, total_out;
    const char *msg; void *state; void *zalloc, *zfree, *opaque;
    int32_t data_type; uint32_t adler, reserved;
} dll_stream;
#ifndef NATIVE_ONLY
typedef char layout_check[sizeof(dll_stream) == 56 ? 1 : -1];   /* zlib1.dll's z_stream */
#endif
typedef int (__cdecl *init_fn)(dll_stream *, int, const char *, int);
typedef int (__cdecl *init2_fn)(dll_stream *, int, int, int, int, int, const char *, int);
typedef int (__cdecl *run_fn)(dll_stream *, int);
typedef int (__cdecl *end_fn)(dll_stream *);
static init_fn d_init; static init2_fn d_init2; static run_fn d_run; static end_fn d_end;
static const char *const *d_errmsg;
static int msg_index(const char *m) { if (!m) return -1; for (int i = 0; i < 10; i++) if (m == d_errmsg[i]) return i; return 99; }
/* The engine's side of every case, folded together (compared across architectures). */
static uint64_t digest = 1469598103934665603ull;
static void mix(const void *p, size_t n) { const uint8_t *b = (const uint8_t *)p; for (size_t i = 0; i < n; i++) { digest ^= b[i]; digest *= 1099511628211ull; } }

static uint32_t rs = 1;
static uint32_t rnd(void) { rs ^= rs << 13; rs ^= rs >> 17; rs ^= rs << 5; return rs; }

typedef struct fields { int rc; uint32_t in_off, avail_in, total_in, out_off, avail_out, total_out, adler; int data_type, msg; } fields;
typedef struct pair {
    dll_stream d; h5z_stream *n; h5z_io io;
    const uint8_t *in; uint8_t *out_d, *out_n; uint32_t cap;
    int level, bits, raw, calls; long long failures;
    const char *name;
} pair;
static long long total_calls, total_cases, total_failures, total_bytes;

static void report(pair *p, const char *what, const fields *a, const fields *b) {
    if (++p->failures > 3) return;
    fprintf(stderr, "DIFF %s level %d bits %d call %d %s: rc %d/%d in %u/%u avail_in %u/%u total_in %u/%u out %u/%u avail_out %u/%u total_out %u/%u adler %08x/%08x type %d/%d msg %d/%d\n",
            p->name, p->level, p->bits, p->calls, what, a->rc, b->rc, a->in_off, b->in_off, a->avail_in, b->avail_in, a->total_in, b->total_in,
            a->out_off, b->out_off, a->avail_out, b->avail_out, a->total_out, b->total_out, a->adler, b->adler, a->data_type, b->data_type, a->msg, b->msg);
}

static int pair_init(pair *p, const char *name, int level, int bits) {
    memset(p, 0, sizeof *p); p->name = name; p->level = level; p->bits = bits; p->raw = bits < 0;
    int b = h5z_deflate_init(&p->n, level, 8, bits, 8, 0);
    mix(&b, sizeof b);
#ifdef NATIVE_ONLY
    int a = b;
    p->d.data_type = 2; p->d.adler = 1; p->d.zalloc = p->d.zfree = p->d.state = (void *)1;
#else
    int a = (bits == 15) ? d_init(&p->d, level, "1.2.3", 56) : d_init2(&p->d, level, 8, bits, 8, 0, "1.2.3", 56);
#endif
    if (a != b) { fprintf(stderr, "DIFF %s init rc %d/%d\n", name, a, b); p->failures++; return 0; }
    if (a != 0) return 0;
    /* What the hook writes after a native init: msg 0, totals 0, data_type Z_UNKNOWN, adler 1,
     * default allocators, a state token. */
    if (p->d.msg || p->d.total_in || p->d.total_out || p->d.data_type != 2 || p->d.adler != 1 || !p->d.zalloc || !p->d.zfree || p->d.opaque || !p->d.state) {
        fprintf(stderr, "DIFF %s init fields msg %p totals %u/%u type %d adler %u\n", name, (void *)p->d.msg, p->d.total_in, p->d.total_out, p->d.data_type, p->d.adler);
        p->failures++;
    }
    p->io.total_in = 0; p->io.total_out = 0; p->io.adler = 1; p->io.data_type = 2; p->io.message = -1;
    return 1;
}

/* One deflate call on both sides; returns side A's fields (they match side B's unless reported). */
static fields pair_call(pair *p, int set_in, const uint8_t *in, uint32_t avail_in, int set_out, uint32_t avail_out, int flush) {
    if (set_in) { p->d.next_in = in; p->d.avail_in = avail_in; p->io.next_in = in; p->io.avail_in = avail_in; }
    if (set_out) { p->d.next_out = p->out_d; p->d.avail_out = avail_out; p->io.next_out = p->out_n; p->io.avail_out = avail_out; }
    const uint8_t *before_d = p->d.next_out, *before_n = p->io.next_out;
    fields a, b;
    memset(&a, 0, sizeof a); memset(&b, 0, sizeof b);
#ifndef NATIVE_ONLY
    a.rc = d_run(&p->d, flush);
#endif
    int msg_before = p->io.message;
    p->io.message = -1;
    b.rc = h5z_deflate(p->n, &p->io, flush);
    if (p->io.message < 0) p->io.message = msg_before;   /* the hook leaves msg alone then */
    a.in_off = p->d.next_in ? (uint32_t)(p->d.next_in - p->in) : 0xFFFFFFFFu; b.in_off = p->io.next_in ? (uint32_t)(p->io.next_in - p->in) : 0xFFFFFFFFu;
    a.avail_in = p->d.avail_in; b.avail_in = p->io.avail_in; a.total_in = p->d.total_in; b.total_in = p->io.total_in;
    a.out_off = (uint32_t)(p->d.next_out - p->out_d); b.out_off = (uint32_t)(p->io.next_out - p->out_n);
    a.avail_out = p->d.avail_out; b.avail_out = p->io.avail_out; a.total_out = p->d.total_out; b.total_out = p->io.total_out;
    a.adler = p->d.adler; b.adler = p->io.adler; a.data_type = p->d.data_type; b.data_type = p->io.data_type;
    a.msg = msg_index(p->d.msg); b.msg = p->io.message;
    mix(&b, sizeof b);
    mix(before_n, (size_t)(p->io.next_out - before_n));
#ifdef NATIVE_ONLY
    a = b;
    p->calls++; total_calls++; total_bytes += (size_t)(p->io.next_out - before_n);
    return a;
#endif
    p->calls++; total_calls++;
    if (memcmp(&a, &b, sizeof a)) report(p, "fields", &a, &b);
    else {
        size_t wrote = (size_t)(p->d.next_out - before_d);
        if ((size_t)(p->io.next_out - before_n) != wrote || memcmp(before_d, before_n, wrote)) report(p, "bytes", &a, &b);
        total_bytes += wrote;
    }
    return a;
}

static void pair_end(pair *p) {
    int b = h5z_deflate_end(p->n);
    mix(&b, sizeof b);
#ifdef NATIVE_ONLY
    int a = b;
#else
    int a = d_end(&p->d);
#endif
    if (a != b) { fprintf(stderr, "DIFF %s level %d bits %d end rc %d/%d after %d calls\n", p->name, p->level, p->bits, a, b, p->calls); p->failures++; }
    total_cases++; total_failures += p->failures != 0;
}

enum { CHUNK = 0x8000 };
static uint8_t *out_d, *out_n;

/* 0x008C7FD0: 32 KiB input chunks, 32 KiB output, again while the output fills. */
static void pattern_loop(const char *name, const uint8_t *in, uint32_t size, int level, int bits) {
    pair p; if (!pair_init(&p, name, level, bits)) { total_cases++; total_failures += p.failures != 0; return; }
    p.in = in; p.out_d = out_d; p.out_n = out_n;
    uint32_t at = 0;
    for (;;) {
        uint32_t take = size - at <= CHUNK ? size - at : CHUNK;
        int flush = at + take >= size ? 4 : 0;
        fields f = pair_call(&p, 1, in + at, take, 1, CHUNK, flush);
        while (f.avail_out == 0 && p.failures == 0) f = pair_call(&p, 0, 0, 0, 1, CHUNK, flush);
        if (flush == 4 || p.failures) break;
        at += CHUNK;
    }
    pair_end(&p);
}

/* 0x00D103B0: writes of any size, each driven until the 32 KiB buffer is not full. */
static void pattern_writer(const char *name, const uint8_t *in, uint32_t size, int level, int bits, uint32_t seed) {
    pair p; if (!pair_init(&p, name, level, bits)) { total_cases++; total_failures += p.failures != 0; return; }
    p.in = in; p.out_d = out_d; p.out_n = out_n; rs = seed | 1u;
    uint32_t at = 0;
    for (;;) {
        uint32_t r = rnd() % 10u, take = r < 4 ? 1 + rnd() % 16u : r < 8 ? 17 + rnd() % 4080u : 4096 + rnd() % 61440u;
        if (take > size - at) take = size - at;
        int flush = at + take >= size ? 4 : 0;
        fields f = pair_call(&p, 1, in + at, take, 1, CHUNK, flush);
        while (f.avail_out == 0 && p.failures == 0) f = pair_call(&p, 0, 0, 0, 1, CHUNK, flush);
        at += take;
        if (flush == 4 || p.failures) break;
    }
    pair_end(&p);
}

/* 0x0082D790 / 0x00AAABA0: one Z_FINISH into one buffer (here also a short one, then more). */
static void pattern_oneshot(const char *name, const uint8_t *in, uint32_t size, int level, int bits, uint32_t cap) {
    pair p; if (!pair_init(&p, name, level, bits)) { total_cases++; total_failures += p.failures != 0; return; }
    p.in = in; p.out_d = out_d; p.out_n = out_n;
    fields f = pair_call(&p, 1, in, size, 1, cap, 4);
    for (int i = 0; i < 64 && f.rc == 0 && p.failures == 0; i++) f = pair_call(&p, 0, 0, 0, 1, cap, 4);
    if (f.rc == 1 && p.failures == 0) pair_call(&p, 0, 0, 0, 1, cap, 4);   /* finishing twice */
    pair_end(&p);
}

/* Random chunkings: input and output sizes from 0 to 70 KiB, empty calls, early ends. */
static void pattern_fuzz(const char *name, const uint8_t *in, uint32_t size, int level, int bits, uint32_t seed) {
    pair p; if (!pair_init(&p, name, level, bits)) { total_cases++; total_failures += p.failures != 0; return; }
    p.in = in; p.out_d = out_d; p.out_n = out_n; rs = seed | 1u;
    uint32_t at = 0; int finishing = 0;
    uint32_t stop = rnd() % 13u == 0 ? 1 + rnd() % 6u : 0xFFFFFFFFu;   /* ended early sometimes */
    for (uint32_t call = 0; call < 20000 && p.failures == 0 && call < stop; call++) {
        uint32_t give = rnd() % 8u == 0 ? 0 : rnd() % 70000u;
        if (give > size - at) give = size - at;
        uint32_t room = rnd() % 16u == 0 ? 0 : 1 + rnd() % 70000u;
        if (at + give >= size) finishing = 1;
        int flush = finishing ? 4 : 0;
        fields f = pair_call(&p, 1, in + at, give, 1, room, flush);
        at += give - f.avail_in;
        if (f.rc == 1) { if (rnd() & 1) pair_call(&p, 1, in + at, 0, 1, room ? room : 1, 4); break; }
    }
    pair_end(&p);
}

static uint8_t *make(int kind, uint32_t size, uint32_t seed) {
    uint8_t *b = (uint8_t *)malloc(size ? size : 1); rs = seed | 1u;
    static const char words[] = "the knight rides north; gold 1500, wood 20, ore 20. ";
    for (uint32_t i = 0; i < size; i++) {
        uint32_t r = rnd();
        switch (kind) {
        case 0: b[i] = 0; break;                                            /* zeros */
        case 1: b[i] = (uint8_t)r; break;                                   /* noise */
        case 2: b[i] = (uint8_t)words[i % (sizeof words - 1)]; break;       /* text */
        case 3: { static const uint8_t gray[] = {7, 8, 11, 12, 26, 27, 'a', 'b', ' ', '\n'}; b[i] = gray[r % 10u]; break; }
        case 4: b[i] = (uint8_t)(r % 5u == 0 ? r >> 8 : (i / 64u) & 0x3Fu); break;  /* runs and noise */
        default: b[i] = (uint8_t)((r & 7u) == 0 || !i ? r >> 16 : b[i - 1]); break;   /* long repeats */
        }
    }
    return b;
}

static uint8_t *load(const char *path, uint32_t *size) {
    FILE *f = fopen(path, "rb"); if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t *b = (uint8_t *)malloc((size_t)n + 1); if (fread(b, 1, (size_t)n, f) != (size_t)n) exit(2); fclose(f);
    *size = (uint32_t)n; return b;
}

int main(int argc, char **argv) {
#ifndef NATIVE_ONLY
    HMODULE z = LoadLibraryA("zlib1.dll");
    if (!z) { fprintf(stderr, "no zlib1.dll\n"); return 2; }
    d_init = (init_fn)GetProcAddress(z, "deflateInit_"); d_init2 = (init2_fn)GetProcAddress(z, "deflateInit2_");
    d_run = (run_fn)GetProcAddress(z, "deflate"); d_end = (end_fn)GetProcAddress(z, "deflateEnd");
    d_errmsg = (const char *const *)((uintptr_t)z + 0xEDD8u);
    if (!d_init || !d_init2 || !d_run || !d_end || strcmp(d_errmsg[7], "buffer error")) { fprintf(stderr, "unexpected zlib1.dll\n"); return 2; }
#endif
    out_d = (uint8_t *)malloc(70000 + 0x100000); out_n = (uint8_t *)malloc(70000 + 0x100000);
#ifndef NATIVE_ONLY
    if (argc == 4 && !strcmp(argv[1], "dll-compress")) {
        uint32_t size; uint8_t *in = load(argv[2], &size);
        FILE *o = fopen(argv[3], "wb"); if (!o) return 2;
        dll_stream d; memset(&d, 0, sizeof d);
        if (d_init(&d, -1, "1.2.3", 56)) return 3;
        uint32_t at = 0; int flush, rc = 0;
        do {
            uint32_t take = size - at <= CHUNK ? size - at : CHUNK;
            flush = at + take >= size ? 4 : 0;
            d.next_in = in + at; d.avail_in = take;
            do { d.next_out = out_d; d.avail_out = CHUNK; rc = d_run(&d, flush); fwrite(out_d, 1, CHUNK - d.avail_out, o); } while (d.avail_out == 0);
            at += take;
        } while (flush != 4);
        fclose(o);
        printf("dll-compress %u -> %u bytes, rc %d, end %d\n", size, d.total_out, rc, d_end(&d));
        return 0;
    }
#endif
    int quick = argc > 1 && !strcmp(argv[1], "quick");
    /* The save payloads with the game's patterns at the game's parameters. */
    for (int a = quick ? 4 : 1; a < argc; a++) {
        uint32_t size; uint8_t *in = load(argv[a], &size);
        char name[64]; snprintf(name, sizeof name, "payload%d", a);
        pattern_loop(name, in, size, -1, 15);
        pattern_writer(name, in, size, -1, 15, 77u + (uint32_t)a);
        pattern_oneshot(name, in, size, 9, -15, size + size / 8u + 64u > 0x100000u ? 0x100000u : size + size / 8u + 64u);
        pattern_fuzz(name, in, size, -1, 15, 991u + (uint32_t)a);
        pattern_loop(name, in, size, 9, -15);
        free(in);
    }
    /* Synthetic data: every level and both wrappings, every pattern. */
    static const uint32_t sizes[] = {0, 1, 2, 7, 100, 1000, 32767, 32768, 32769, 65541, 300000};
    static const int levels[] = {-1, 1, 2, 3, 4, 5, 6, 7, 8, 9};
    uint32_t seed = 12345;
    for (unsigned s = 0; s < sizeof sizes / sizeof *sizes; s++)
        for (int kind = 0; kind < 6; kind++) {
            uint8_t *in = make(kind, sizes[s], seed++);
            char name[64]; snprintf(name, sizeof name, "kind%d-size%u", kind, sizes[s]);
            for (unsigned l = 0; l < sizeof levels / sizeof *levels; l++)
                for (int w = 0; w < 2; w++) {
                    int bits = w ? -15 : 15;
                    pattern_loop(name, in, sizes[s], levels[l], bits);
                    pattern_writer(name, in, sizes[s], levels[l], bits, seed * 31u + (uint32_t)l);
                    pattern_oneshot(name, in, sizes[s], levels[l], bits, sizes[s] + sizes[s] / 8u + 64u);
                    pattern_oneshot(name, in, sizes[s], levels[l], bits, sizes[s] / 3u + 1u);
                    pattern_fuzz(name, in, sizes[s], levels[l], bits, seed * 7u + (uint32_t)l * 3u + (uint32_t)w);
                }
            free(in);
        }
    /* Ends before any call, after an empty call, after an unfinished call. */
    static const uint8_t tiny[16] = "0123456789abcdef";
    for (int w = 0; w < 2; w++) {
        pair p; int bits = w ? -15 : 15;
        if (pair_init(&p, "end-unused", 6, bits)) { p.in = tiny; p.out_d = out_d; p.out_n = out_n; pair_end(&p); }
        if (pair_init(&p, "end-empty", 6, bits)) { p.in = tiny; p.out_d = out_d; p.out_n = out_n; pair_call(&p, 1, tiny, 0, 1, 0, 0); pair_end(&p); }
        if (pair_init(&p, "end-busy", 6, bits)) { p.in = tiny; p.out_d = out_d; p.out_n = out_n; pair_call(&p, 1, tiny, 16, 1, 4096, 0); pair_end(&p); }
        if (pair_init(&p, "bad-flush", 6, bits)) { p.in = tiny; p.out_d = out_d; p.out_n = out_n; pair_call(&p, 1, tiny, 16, 1, 4096, 4); pair_call(&p, 0, 0, 0, 1, 4096, 0); pair_end(&p); }
    }
    printf("%s %lld cases, %lld calls, %lld bytes compared, %lld failing cases\n",
           total_failures ? "FAIL" : "PASS", total_cases, total_calls, total_bytes, total_failures);
    printf("ENGINE DIGEST %016llx\n", (unsigned long long)digest);
    return total_failures ? 1 : 0;
}
'''


def payloads():
    """The save's two zlib streams, inflated (the uncompressed data the game deflated)."""
    data = SAVE.read_bytes()
    found, at = [], 0
    for at in range(len(data) - 2):
        if data[at] == 0x78 and data[at + 1] == 0x9C:
            d = zlib.decompressobj()
            try:
                out = d.decompress(data[at:])
            except zlib.error:
                continue
            if d.eof and len(out) > 100000:
                found.append(out)
                if len(found) == 2:
                    break
    return found


class DeflateNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        HERE.mkdir(parents=True, exist_ok=True)
        cls.files = []
        for index, payload in enumerate(payloads(), 1):
            path = HERE / ("payload%d.bin" % index)
            if not path.is_file() or path.stat().st_size != len(payload):
                path.write_bytes(payload)
            cls.files.append(path)
        (HERE / "probe.c").write_text(PROBE, encoding="utf-8")
        shutil.copyfile(DLL, HERE / "zlib1.dll")
        env, linker = environment("x86")
        flags = [CLANG, "/nologo", "/W0", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS", "/clang:--target=i686-pc-windows-msvc",
                 "/I", str(ENGINE.parent)]
        command([*flags, "/c", "probe.c", "/Foprobe.obj"], HERE, env)
        command([*flags, "/c", str(ENGINE), "/Foengine.obj"], HERE, env)
        command([linker, "/nologo", "probe.obj", "engine.obj", "/OUT:probe.exe", "/STACK:8388608"], HERE, env)
        cls.env = env

    def run_probe(self, *args):
        return subprocess.run([str(HERE / "probe.exe"), *map(str, args)], cwd=HERE, env=self.env, text=True,
                              capture_output=True, timeout=3000, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_save_payloads_are_what_the_save_holds(self):
        self.assertEqual([p.stat().st_size for p in self.files], [32852557, 1718208])

    def test_every_call_equals_zlib1_dll(self):
        result = self.run_probe(*self.files)
        print(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-4000:])
        self.assertIn("PASS", result.stdout)
        cases, calls = map(int, re.search(r"(\d+) cases, (\d+) calls", result.stdout).groups())
        self.assertGreater(cases, 3000)
        self.assertGreater(calls, 30000)
        self.assertRegex(result.stdout, r"ENGINE DIGEST [0-9a-f]{16}")
        (HERE / "engine-digest-x86.txt").write_text(re.search(r"ENGINE DIGEST ([0-9a-f]{16})", result.stdout)[1] + "\n")


if __name__ == "__main__":
    unittest.main()
