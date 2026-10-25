"""Run the real desktop/CRT compatibility bodies against bounded guest memory."""
import re
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x10000];
#define GPTR(va) (memory + (va))
#define MEM8(va) (*(uint8_t *)GPTR(va))
#define MEM16(va) (*(uint16_t *)GPTR(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
static uint32_t args[16], last_error;
#define ARG(n) args[n]
#define WINAPI_EXPORT(dll, name, nargs) uint32_t name##_impl(void)
#define ERROR_INVALID_HANDLE_ 6
#define ERROR_PATH_NOT_FOUND_ 3
static void void_set_last_error(uint32_t error) { last_error = error; }
static void void_input_screen_size(int *w, int *h) { *w = 1280; *h = 720; }
#include "strings.h"
static const char *cwd = "C:\\Games\\HeroesV\\bin";
static uint32_t void_cwd_get(char *out, uint32_t cap) { return (uint32_t)snprintf(out, cap, "%s", cwd); }
static int void_cwd_set(const char *path) { return !strcmp(path, cwd); }
static uint32_t void_process_heap(void) { return 0x6000; }
static uint32_t void_heap_size(uint32_t heap, uint32_t block) { assert(heap == 0x6000); return block == 0x800 ? 48 : UINT32_MAX; }
static uint32_t resized, zeroed;
static uint32_t void_heap_realloc(uint32_t heap, uint32_t block, uint32_t size, int zero, int inplace) {
    assert(heap == 0x6000 && block == 0x800 && !inplace); resized = size; zeroed = (uint32_t)zero; return 0x900;
}
#include "compat.h"
int main(void) {
    args[0] = 0x40001;
    args[1] = 88; assert(GetDeviceCaps_impl() == 96);
    args[1] = 90; assert(GetDeviceCaps_impl() == 96);
    args[1] = 8; assert(GetDeviceCaps_impl() == 1280);
    args[1] = 10; assert(GetDeviceCaps_impl() == 720);
    args[1] = 12; assert(GetDeviceCaps_impl() == 32);
    args[1] = 999; assert(GetDeviceCaps_impl() == 0);
    args[0] = 0; assert(GetDeviceCaps_impl() == 0 && last_error == 6);
    args[0] = 15; assert(GetSysColor_impl() == 0xC0C0C0 && GetSysColorBrush_impl() != 0);
    args[0] = 0xFFFFFFFF; assert(GetSysColor_impl() == 0 && GetSysColorBrush_impl() == 0);
    args[0] = 2; assert(SetErrorMode_impl() == 0);
    args[0] = 3; assert(SetErrorMode_impl() == 2);
    strcpy((char *)GPTR(0x100), "abc"); strcpy((char *)GPTR(0x200), "abd");
    args[0] = 0x100; args[1] = 0x200;
    assert((int32_t)lstrcmpA_impl() < 0 && lstrlenA_impl() == 3);
    args[0] = 0x300; args[1] = 0x100;
    assert(lstrcpyA_impl() == 0x300 && !strcmp((char *)GPTR(0x300), "abc"));
    assert(lstrcatA_impl() == 0x300 && !strcmp((char *)GPTR(0x300), "abcabc"));
    args[2] = 2; assert(lstrcpynA_impl() == 0x300 && !strcmp((char *)GPTR(0x300), "a"));
    args[2] = 1; lstrcpynA_impl(); assert(MEM8(0x300) == 0);
    MEM8(0x300) = 0x55; args[2] = 0; lstrcpynA_impl(); assert(MEM8(0x300) == 0x55);
    args[2] = UINT32_MAX; lstrcpynA_impl(); assert(MEM8(0x300) == 0x55);
    args[0] = 0; args[1] = 0x400;
    uint32_t length = (uint32_t)strlen(cwd);
    assert(GetCurrentDirectoryA_impl() == length + 1);
    args[0] = length; MEM8(0x400) = 0x55; assert(GetCurrentDirectoryA_impl() == length + 1 && MEM8(0x400) == 0x55);
    args[0] = length + 1; assert(GetCurrentDirectoryA_impl() == length && !strcmp((char *)GPTR(0x400), cwd));
    args[0] = 0x400; assert(SetCurrentDirectoryA_impl() == 1);
    args[0] = 0; assert(SetCurrentDirectoryA_impl() == 0 && last_error == 3);
    args[0] = length + 1; args[1] = 0x500;
    assert(GetCurrentDirectoryW_impl() == length && MEM16(0x500) == 'C' && MEM16(0x500 + 2 * length) == 0);
    args[0] = 0x500; assert(SetCurrentDirectoryW_impl() == 1);
    args[0] = 0x800; args[1] = 128; args[2] = 0x40;
    assert(GlobalReAlloc_impl() == 0x900 && resized == 128 && zeroed);
    args[2] = 0x80; assert(LocalReAlloc_impl() == 0x800);
    assert(GlobalHandle_impl() == 0x800 && GlobalFlags_impl() == 0);
    args[0] = 0x801; assert(GlobalHandle_impl() == 0 && GlobalFlags_impl() == 0x8000);
    puts("PASS compatibility: desktop metrics, system colours, string bounds, cwd buffer sizes, heap adapter");
    return 0;
}
'''


class CompatTest(unittest.TestCase):
    def test_bodies(self):
        def without_includes(name):
            return re.sub(r"^#include[^\n]*\n", "", (ROOT / "android/host" / name).read_text(encoding="utf-8"), flags=re.M)
        compile_probe("compat", HARNESS, {"compat.h": without_includes("compat.c"), "strings.h": without_includes("strings.c")})


if __name__ == "__main__":
    unittest.main()
