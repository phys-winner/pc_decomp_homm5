"""Execute the real guest/native inflateBack adapter against installed zlib."""
from pathlib import Path
import random
import sys
import unittest
import zlib
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <zlib.h>
#include "fixtures.h"
static unsigned char memory[0x200000];
#undef GPTR
#define GPTR(va) (memory + (uint32_t)(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
#define MEM8(va) (*GPTR(va))
typedef void (*void_fn)(void);
static uint32_t g_esp = 0x1000, g_eax;
static uint32_t heap_top = 0x180000, guest_frees, guest_allocs;
static int fail_guest, fail_host, fail_native, native_live, host_live;
static void *bridge_calloc(size_t n, size_t size) {
    if (fail_host) return NULL;
    void *p = calloc(n, size); if (p) ++host_live; return p;
}
static void bridge_free(void *p) { if (p) --host_live; free(p); }
static uint32_t void_galloc(uint32_t size) {
    if (fail_guest) return 0;
    uint32_t out = heap_top; heap_top += (size + 7u) & ~7u;
    assert(heap_top < sizeof memory); ++guest_allocs; memset(GPTR(out), 0, size); return out;
}
static void void_gfree(uint32_t va) { assert(va >= 0x180000); ++guest_frees; }
static uint32_t void_gstrdup(const char *text) {
    uint32_t out = void_galloc((uint32_t)strlen(text) + 1u);
    if (out) strcpy((char *)GPTR(out), text); return out;
}
static int void_vm_readable(uint32_t va, uint32_t size) {
    return va >= 0x100 && (uint64_t)va + size <= sizeof memory;
}
static int void_vm_writable(uint32_t va, uint32_t size) { return void_vm_readable(va, size); }
static void void_log(const char *fmt, ...) { (void)fmt; }
static void_fn dispatch[5];
static int dispatch_slot(uint32_t va) {
    switch (va) {
    case 0x15004540: return 0; case 0x15004620: return 1; case 0x150054D0: return 2;
    case 0x800100: return 3; case 0x800200: return 4; default: return -1;
    }
}
static void_fn void_dispatch_find(uint32_t va) { int i = dispatch_slot(va); return i < 0 ? NULL : dispatch[i]; }
static void void_dispatch_add(uint32_t va, void_fn fn) { int i = dispatch_slot(va); assert(i >= 0); dispatch[i] = fn; }
static int original_calls[3];
static void old_init(void) { ++original_calls[0]; g_eax = 77; g_esp += 4; }
static void old_back(void) { ++original_calls[1]; g_eax = 78; g_esp += 4; }
static void old_end(void) { ++original_calls[2]; g_eax = 79; g_esp += 4; }
static int (*dll_init)(z_streamp, int, unsigned char *, const char *, int);
static int (*dll_back)(z_streamp, in_func, void *, out_func, void *);
static int (*dll_end)(z_streamp);
static int test_init(z_streamp s, int bits, unsigned char *window, const char *version, int size) {
    if (fail_native) return Z_MEM_ERROR;
    int result = dll_init(s, bits, window, version, size); if (result == Z_OK) ++native_live; return result;
}
static int test_back(z_streamp s, in_func in, void *in_desc, out_func out, void *out_desc) {
    return dll_back(s, in, in_desc, out, out_desc);
}
static int test_end(z_streamp s) { int result = dll_end(s); if (result == Z_OK) --native_live; return result; }
static uint32_t void_call_guest(uint32_t va, int n, const uint32_t *args, int pops);
#define calloc bridge_calloc
#define free bridge_free
#define inflateBackInit_ test_init
#define inflateBack test_back
#define inflateBackEnd test_end
#include "actual_zlib_native.h"
#undef calloc
#undef free
#undef inflateBackInit_
#undef inflateBack
#undef inflateBackEnd

enum { STREAM = 0x2000, SECOND = 0x2100, WINDOW = 0x4000, DATA_IN = 0x10000, OUTPUT = 0x80000, VERSION = 0x3000 };
static uint32_t input_size, input_used, output_used, input_chunk, output_limit;
static uint32_t input_calls, output_calls, input_stop, output_error, invalid_input;
static int try_reenter;
static int invoke(int slot, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e) {
    uint32_t saved = g_esp; g_esp = 0x1000;
    MEM32(g_esp) = 0xDEADBEEF;
    MEM32(g_esp + 4) = a; MEM32(g_esp + 8) = b; MEM32(g_esp + 12) = c;
    MEM32(g_esp + 16) = d; MEM32(g_esp + 20) = e;
    dispatch[slot](); assert(g_esp == 0x1004); g_esp = saved; return (int)g_eax;
}
static uint32_t void_call_guest(uint32_t va, int n, const uint32_t *args, int pops) {
    assert(!pops);
    if (va == 0x800100) {
        assert(n == 2 && args[0] == 123 && void_vm_writable(args[1], 4));
        ++input_calls;
        if (input_stop || input_used == input_size) { MEM32(args[1]) = 0; return 0; }
        if (invalid_input) { MEM32(args[1]) = sizeof memory - 2; return UINT32_MAX; }
        uint32_t amount = input_size - input_used;
        if (amount > input_chunk) amount = input_chunk;
        MEM32(args[1]) = DATA_IN + input_used; input_used += amount; return amount;
    }
    assert(va == 0x800200 && n == 3 && args[0] == 456);
    assert(args[1] >= WINDOW && (uint64_t)args[1] + args[2] <= WINDOW + output_limit);
    assert(args[2] <= output_limit && output_used + args[2] <= sizeof expected);
    ++output_calls;
    if (try_reenter) {
        assert(invoke(2, STREAM, 0, 0, 0, 0) == Z_STREAM_ERROR);
        assert(invoke(1, STREAM, 0x800100, 123, 0x800200, 456) == Z_STREAM_ERROR);
        try_reenter = 0;
    }
    if (output_error) return output_error;
    memcpy(GPTR(OUTPUT + output_used), GPTR(args[1]), args[2]); output_used += args[2]; return 0;
}
static void load_proc(HMODULE dll, const char *name, void *target, size_t size) {
    FARPROC p = GetProcAddress(dll, name); assert(p && size == sizeof p); memcpy(target, &p, size);
}
static void reset(const unsigned char *data, size_t size, unsigned bits) {
    assert(!streams && !native_live && !host_live);
    memset(GPTR(STREAM), 0, 56); memset(GPTR(WINDOW), 0, 32768);
    memcpy(GPTR(DATA_IN), data, size); strcpy((char *)GPTR(VERSION), "1.2.3");
    input_size = (uint32_t)size; input_used = output_used = input_calls = output_calls = 0;
    input_chunk = 17; output_limit = 1u << bits; input_stop = output_error = invalid_input = 0;
    MEM32(STREAM + 8) = 0x12345678; MEM32(STREAM + 12) = 0x87654321;
    MEM32(STREAM + 16) = 12345; MEM32(STREAM + 20) = 98765;
    MEM32(STREAM + 44) = 0x11111111; MEM32(STREAM + 48) = 0x22222222; MEM32(STREAM + 52) = 0x33333333;
}
static void begin(unsigned bits) {
    assert(invoke(0, STREAM, bits, WINDOW, VERSION, 56) == Z_OK);
    assert(MEM32(STREAM + 28) >= 0x180000 && streams && native_live == 1 && host_live == 1);
    assert(MEM32(STREAM + 32) == GUEST_ZALLOC && MEM32(STREAM + 36) == GUEST_ZFREE);
}
static int run(void) { return invoke(1, STREAM, 0x800100, 123, 0x800200, 456); }
static void end(void) {
    uint32_t frees = guest_frees; assert(invoke(2, STREAM, 0, 0, 0, 0) == Z_OK);
    assert(!MEM32(STREAM + 28) && !streams && !native_live && !host_live && guest_frees == frees + 1);
    assert(MEM32(STREAM + 8) == 0x12345678 && MEM32(STREAM + 12) == 0x87654321);
    assert(MEM32(STREAM + 16) == 12345 && MEM32(STREAM + 20) == 98765);
    assert(MEM32(STREAM + 44) == 0x11111111 && MEM32(STREAM + 48) == 0x22222222 && MEM32(STREAM + 52) == 0x33333333);
}
int main(void) {
    HMODULE dll = LoadLibraryA(ZLIB_DLL); assert(dll);
    load_proc(dll, "inflateBackInit_", &dll_init, sizeof dll_init);
    load_proc(dll, "inflateBack", &dll_back, sizeof dll_back);
    load_proc(dll, "inflateBackEnd", &dll_end, sizeof dll_end);
    dispatch[0] = old_init; dispatch[1] = old_back; dispatch[2] = old_end;
    dispatch[3] = old_back; dispatch[4] = old_back;
    void_zlib_init(); void_zlib_init(); assert(original_init == old_init);
    /* Default allocator, all input initially available, trailing bytes preserved. */
    reset(compressed, sizeof compressed, 15); begin(15);
    MEM32(STREAM) = DATA_IN; MEM32(STREAM + 4) = input_size;
    try_reenter = 1;
    assert(run() == Z_STREAM_END && !input_calls && output_calls > 1);
    assert(output_used == sizeof expected && !memcmp(GPTR(OUTPUT), expected, sizeof expected));
    assert(MEM32(STREAM) == DATA_IN + sizeof compressed - 2 && MEM32(STREAM + 4) == 2);
    /* The same initialized stream supports another complete raw stream. */
    input_used = output_used = input_calls = output_calls = 0;
    MEM32(STREAM) = MEM32(STREAM + 4) = 0;
    assert(run() == Z_STREAM_END && input_calls > 100 && output_calls > 1);
    assert(output_used == sizeof expected && !memcmp(GPTR(OUTPUT), expected, sizeof expected)); end();
    /* Stored blocks, smallest supported window, one byte per callback. */
    reset(stored, sizeof stored, 8); begin(8); input_chunk = 1;
    assert(run() == Z_STREAM_END && output_calls > 100 && output_used == sizeof expected);
    assert(!memcmp(GPTR(OUTPUT), expected, sizeof expected)); end();
    /* Existing default allocator fields (e.g. after inflateInit_) are accepted. */
    reset(empty, sizeof empty, 15); MEM32(STREAM + 32) = GUEST_ZALLOC; MEM32(STREAM + 36) = GUEST_ZFREE;
    MEM32(STREAM + 40) = 999; begin(15); assert(MEM32(STREAM + 40) == 999);
    assert(run() == Z_STREAM_END && !output_used); end();
    /* Game's wrapped-data path consumes its header using lifted inflate first. */
    reset(wrapped, sizeof wrapped, 15); begin(15);
    MEM32(STREAM) = DATA_IN + 2; MEM32(STREAM + 4) = input_size - 2;
    assert(run() == Z_STREAM_END && !input_calls && output_used == sizeof expected);
    assert(!memcmp(GPTR(OUTPUT), expected, sizeof expected) && MEM32(STREAM + 4) == 4); end();
    /* Output callback's arbitrary nonzero result becomes Z_BUF_ERROR. */
    reset(compressed, sizeof compressed, 15); begin(15); output_error = UINT32_MAX;
    assert(run() == Z_BUF_ERROR && output_calls == 1 && !output_used && MEM32(STREAM)); end();
    reset(compressed, sizeof compressed, 15); begin(15); input_stop = 1;
    assert(run() == Z_BUF_ERROR && !MEM32(STREAM) && !output_calls); end();
    reset(compressed, sizeof compressed, 15); begin(15); invalid_input = 1;
    assert(run() == Z_BUF_ERROR && !MEM32(STREAM)); end();
    /* Raw API rejects malformed and zlib-wrapped input with a readable message. */
    reset(invalid, sizeof invalid, 15); begin(15); assert(run() == Z_DATA_ERROR);
    uint32_t message = MEM32(STREAM + 24); assert(message && strlen((char *)GPTR(message)));
    end(); assert(strlen((char *)GPTR(message)));
    reset(wrapped, sizeof wrapped, 15); begin(15); assert(run() == Z_DATA_ERROR); end();
    /* Two simultaneous initialized streams have independent tokens and lifetime. */
    reset(empty, sizeof empty, 15); begin(15); memset(GPTR(SECOND), 0, 56);
    assert(invoke(0, SECOND, 15, WINDOW, VERSION, 56) == Z_OK && native_live == 2);
    assert(MEM32(SECOND + 28) != MEM32(STREAM + 28));
    assert(invoke(2, SECOND, 0, 0, 0, 0) == Z_OK); end();
    /* Host/native/guest allocation failures release every partial allocation. */
    reset(empty, sizeof empty, 15);
    fail_host = 1; assert(invoke(0, STREAM, 15, WINDOW, VERSION, 56) == Z_MEM_ERROR); fail_host = 0;
    fail_native = 1; assert(invoke(0, STREAM, 15, WINDOW, VERSION, 56) == Z_MEM_ERROR); fail_native = 0;
    fail_guest = 1; assert(invoke(0, STREAM, 15, WINDOW, VERSION, 56) == Z_MEM_ERROR); fail_guest = 0;
    assert(!streams && !native_live && !host_live && !MEM32(STREAM + 28));
    /* Unsupported allocator/version requests and unowned streams use the old trio. */
    MEM32(STREAM + 32) = 0x800333;
    assert(invoke(0, STREAM, 15, WINDOW, VERSION, 56) == 77);
    assert(invoke(1, STREAM, 0x800100, 123, 0x800200, 456) == 78);
    assert(invoke(2, STREAM, 0, 0, 0, 0) == 79);
    MEM32(STREAM + 32) = 0;
    assert(invoke(0, STREAM, 15, WINDOW, VERSION, 112) == 77);
    assert(original_calls[0] == 2 && original_calls[1] == 1 && original_calls[2] == 1);
    puts("PASS actual native inflateBack: raw roundtrips, callbacks, 256/32768 windows, leftovers, errors, fallback, reentry, multiple streams and allocation cleanup");
    return 0;
}
'''


class ZlibNativeTest(unittest.TestCase):
    def test_native_back_roundtrips(self):
        dll = Path(sys.executable).parent / "DLLs/zlib1.dll"
        self.assertTrue(dll.is_file(), "Use the installed Python zlib DLL; no dependency fetch")
        rng = random.Random(2348)
        expected = rng.randbytes(70000) + b"Heroes V resource window\0" * 5300 + rng.randbytes(7132)
        raw = zlib.compressobj(6, wbits=-15)
        stored = zlib.compressobj(0, wbits=-15)
        blobs = {
            "expected": expected,
            "compressed": raw.compress(expected) + raw.flush() + b"\xcc\xdd",
            "stored": stored.compress(expected) + stored.flush(),
            "empty": b"\x03\x00",
            "invalid": b"\x07",
            "wrapped": zlib.compress(expected),
        }
        fixtures = "\n".join(f"static const unsigned char {key}[] = {{" + ",".join(map(str, value)) + "};" for key, value in blobs.items())
        fixtures += '\n#define ZLIB_DLL "' + dll.as_posix() + '"\n'
        source = (ROOT / "android/host/zlib_native.c").read_text().replace('#include "host.h"', "")
        compile_probe("zlib_native", HARNESS, {"actual_zlib_native.h": source, "fixtures.h": fixtures},
                      ["/I" + str(ROOT / "reference/zlib"), "/wd4459"])

    def test_dispatch_and_system_library_integration(self):
        core = (ROOT / "android/host/core.c").read_text()
        builder = (ROOT / "tools/build_android.py").read_text()
        self.assertIn("void_zlib_init();", core)
        self.assertIn('"-lz"', builder)
        self.assertNotIn('"sub_15004540"', builder)
        self.assertNotIn('"sub_15004620"', builder)
        self.assertNotIn('"sub_150054D0"', builder)


if __name__ == "__main__":
    unittest.main()
