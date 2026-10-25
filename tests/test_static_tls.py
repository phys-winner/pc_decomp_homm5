"""Execute the real PE TLS helpers with bounded guest memory and callback spies."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define STATIC_TLS_MODULES 64
static unsigned char memory[0x40000];
#define GPTR(va) (memory + (uint32_t)(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
typedef struct void_thread { uint32_t tib, static_tls; struct void_thread *next_thread; } void_thread;
static void_thread *all_threads;
static int threads_lock, lock_depth;
static int pthread_mutex_lock(int *unused) { (void)unused; assert(!lock_depth++); return 0; }
static int pthread_mutex_unlock(int *unused) { (void)unused; assert(!--lock_depth); return 0; }
static void void_fatal(const char *format, ...) { fprintf(stderr, "%s\n", format); abort(); }
static uint32_t allocated = 0x10000;
static uint32_t void_galloc(uint32_t size) {
    uint32_t out = allocated;
    allocated += (size + 7) & ~7u;
    assert(allocated <= sizeof memory);
    memset(GPTR(out), 0, size);
    return out;
}
static int void_vm_readable(uint32_t address, uint32_t size) {
    return address >= 0x100 && (uint64_t)address + size <= sizeof memory;
}
static int void_vm_writable(uint32_t address, uint32_t size) { return void_vm_readable(address, size); }
static uint32_t called_base[32], called_reason[32], calls;
static uint32_t void_call_guest(uint32_t va, int count, const uint32_t *args, int pops) {
    assert(va == 0x401000 && count == 3 && pops == 1 && args[2] == 0);
    assert(calls < 32);
    called_base[calls] = args[0]; called_reason[calls++] = args[1]; return 0;
}
#include "static_tls_helpers.h"
int main(void) {
    uint32_t directory = 0x100, index = 0x200, raw = 0x300, callbacks = 0x400;
    MEM32(directory) = raw; MEM32(directory + 4) = raw + 3;
    MEM32(directory + 8) = index; MEM32(directory + 12) = callbacks;
    MEM32(directory + 16) = 5; MEM32(directory + 20) = 6u << 20;
    MEM32(callbacks) = 0x401000; MEM32(callbacks + 4) = 0;
    memcpy(GPTR(raw), "ABC", 3);
    assert(void_tls_register(0x400000, directory));
    assert(MEM32(index) == 0 && static_tls_count == 1);
    void_thread first = {0x1000, 0, NULL};
    tls_thread_init(&first); all_threads = &first;
    assert(MEM32(first.tib + 0x2C) == first.static_tls);
    assert(first.static_tls != first.tib + 0xE10);
    uint32_t block = MEM32(first.static_tls);
    assert(!(block & 31) && !memcmp(GPTR(block), "ABC\0\0\0\0\0", 8));
    MEM32(first.tib + 0xE10) = 0x12345678;
    memory[block] = 'Z';
    void_thread second = {0x2000, 0, &first};
    tls_thread_init(&second); all_threads = &second;
    assert(MEM32(second.static_tls) != block && memory[MEM32(second.static_tls)] == 'A');
    assert(memory[block] == 'Z' && MEM32(first.tib + 0xE10) == 0x12345678);
    MEM32(directory + 8) = index + 4;
    assert(void_tls_register(0x500000, directory) && MEM32(index + 4) == 1);
    assert(MEM32(first.static_tls + 4) && MEM32(second.static_tls + 4));
    assert(MEM32(first.static_tls + 4) != MEM32(second.static_tls + 4));
    MEM32(index + 4) = 99;
    assert(void_tls_register(0x500000, directory) && MEM32(index + 4) == 1 && static_tls_count == 2);
    tls_thread_callbacks(2); assert(!calls);
    void_tls_callbacks(0x400000, 1); void_tls_callbacks(0x500000, 1);
    tls_thread_callbacks(2); tls_thread_callbacks(3);
    assert(calls == 6 && called_reason[0] == 1 && called_reason[2] == 2 && called_reason[4] == 3);
    assert(called_base[2] == 0x400000 && called_base[3] == 0x500000);
    assert(called_base[4] == 0x500000 && called_base[5] == 0x400000);
    void_tls_callbacks(0x400000, 0); tls_thread_callbacks(2);
    assert(calls == 8 && called_base[7] == 0x500000);
    assert(void_tls_register(0x600000, 0));
    assert(!void_tls_register(0x600000, sizeof memory - 12));
    MEM32(directory + 4) = raw - 1; assert(!void_tls_register(0x600000, directory));
    MEM32(directory + 4) = raw + 3;
    MEM32(directory + 16) = UINT32_MAX; assert(!void_tls_register(0x600000, directory));
    MEM32(directory + 16) = 5;
    MEM32(directory + 8) = 0; assert(!void_tls_register(0x600000, directory));
    MEM32(directory + 8) = index;
    MEM32(directory + 20) = 15u << 20; assert(!void_tls_register(0x600000, directory));
    MEM32(directory + 20) = 0;
    MEM32(directory + 12) = UINT32_MAX - 1; assert(!void_tls_register(0x600000, directory));
    MEM32(directory + 12) = 0x800;
    for (unsigned i = 0; i < 1024; ++i) MEM32(0x800 + 4 * i) = 0x401000;
    assert(!void_tls_register(0x600000, directory));
    assert(!lock_depth);
    puts("PASS static TLS: templates, zero-fill, alignment, isolation, late registration, callback order, invalid inputs");
    return 0;
}
'''


def compile_probe(name, harness, headers, extra_flags=(), compiler_override=None):
    out = ROOT / "build/tests" / name
    out.mkdir(parents=True, exist_ok=True)
    for filename, text in headers.items():
        (out / filename).write_text(text, encoding="utf-8")
    (out / "probe.c").write_text(harness, encoding="utf-8")
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], text=True).strip())
    msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    compiler = msvc / "bin/Hostx64/x64/cl.exe"
    env = os.environ.copy()
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared", sdk / f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk / f"Lib/{version}/ucrt/x64", sdk / f"Lib/{version}/um/x64"]))
    outputs = ["/c", "/Foprobe.obj"] if compiler_override else ["/Fe:probe.exe"]
    compiled = subprocess.run([str(compiler_override or compiler), "/nologo", "/W4", "/WX", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS", *extra_flags, "probe.c", *outputs], cwd=out, env=env, text=True, capture_output=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    if compiler_override:
        linked = subprocess.run([str(compiler), "/nologo", "probe.obj", "/Fe:probe.exe"], cwd=out, env=env, text=True, capture_output=True)
        assert linked.returncode == 0, linked.stdout + linked.stderr
    tested = subprocess.run([str(out / "probe.exe")], text=True, capture_output=True, timeout=10)
    assert tested.returncode == 0, tested.stdout + tested.stderr
    print(tested.stdout.strip())


class StaticTlsTest(unittest.TestCase):
    def test_helpers(self):
        text = (ROOT / "android/host/threads.c").read_text(encoding="utf-8")
        helpers = text[text.index("typedef struct {\n    uint32_t base, raw,"):text.index("/* ---------------------------------------------------------- machine lock */")]
        compile_probe("static_tls", HARNESS, {"static_tls_helpers.h": helpers})


if __name__ == "__main__":
    unittest.main()
