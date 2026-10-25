"""Compare the actual timestamp exports with native Win32, without changing time."""
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static uint8_t memory[0x10000];
#undef GPTR
#define GPTR(va) ((void *)(memory + (va)))
#define MEM16(va) (*(uint16_t *)GPTR(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
#define MEM64(va) (*(uint64_t *)GPTR(va))
static uint32_t g_esp, g_eax;
#define ARG(i) MEM32(g_esp + 4u + 4u * (uint32_t)(i))
typedef void (*void_fn)(void);
typedef struct { const char *dll, *name; uint32_t ordinal; void_fn fn; } void_shim;
#define VOID_SHIM_SECTION
#include "exports.h"
#define K32 "kernel32.dll"
#define ERROR_INVALID_PARAMETER_ 87
static uint32_t last_error;
static void void_set_last_error(uint32_t error) { last_error = error; }
static int void_vm_readable(uint32_t va, uint32_t size) { return va >= 0x100 && (uint64_t)va + size <= sizeof memory; }
static int void_vm_writable(uint32_t va, uint32_t size) { return void_vm_readable(va, size); }

/* MSVC's CRT gmtime does not support the full Win32 range; use Win32 as its oracle. */
struct test_tm { int tm_year, tm_mon, tm_wday, tm_mday, tm_hour, tm_min, tm_sec; long tm_gmtoff; };
static struct test_tm *gmtime_r(const time_t *seconds, struct test_tm *out) {
    if (*seconds < -11644473600ll || *seconds > INT64_MAX / 10000000ll - 11644473600ll) return NULL;
    uint64_t ticks = (uint64_t)(*seconds + 11644473600ll) * 10000000ull;
    FILETIME ft = {(DWORD)ticks, (DWORD)(ticks >> 32)};
    SYSTEMTIME st;
    if (!FileTimeToSystemTime(&ft, &st)) return NULL;
    *out = (struct test_tm){st.wYear - 1900, st.wMonth - 1, st.wDayOfWeek, st.wDay, st.wHour, st.wMinute, st.wSecond, 0};
    return out;
}
static long current_offset;
static struct test_tm *localtime_r(const time_t *seconds, struct test_tm *out) {
    (void)seconds; memset(out, 0, sizeof *out); out->tm_gmtoff = current_offset; return out;
}
#define tm test_tm
#include "timestamps.h"
#undef tm

static unsigned checks;
static uint32_t invoke(void_fn fn, unsigned count, uint32_t first, uint32_t second, uint32_t third) {
    g_esp = 0x1000; g_eax = 0x12345678;
    MEM32(g_esp) = 0xDEADBEEF;
    MEM32(g_esp + 4) = first; MEM32(g_esp + 8) = second; MEM32(g_esp + 12) = third;
    fn(); assert(g_esp == 0x1004 + 4 * count && MEM32(0x1000) == 0xDEADBEEF);
    ++checks; return g_eax;
}

static void compare_systemtime(SYSTEMTIME st) {
    FILETIME expected = {0xCCCCCCCC, 0xCCCCCCCC};
    SetLastError(0); BOOL ok = SystemTimeToFileTime(&st, &expected); DWORD error = GetLastError();
    memcpy(GPTR(0x2000), &st, sizeof st); memset(GPTR(0x3000), 0xCC, 8); last_error = 0;
    assert(invoke(SystemTimeToFileTime_entry, 2, 0x2000, 0x3000, 0) == (uint32_t)ok);
    assert(!memcmp(GPTR(0x3000), &expected, 8));
    if (!ok) assert(last_error == error);
}

static void compare_filetime(uint64_t ticks) {
    FILETIME ft = {(DWORD)ticks, (DWORD)(ticks >> 32)};
    SYSTEMTIME expected; memset(&expected, 0xCC, sizeof expected);
    SetLastError(0); BOOL ok = FileTimeToSystemTime(&ft, &expected); DWORD error = GetLastError();
    MEM64(0x2000) = ticks; memset(GPTR(0x3000), 0xCC, 16); last_error = 0;
    assert(invoke(FileTimeToSystemTime_entry, 2, 0x2000, 0x3000, 0) == (uint32_t)ok);
    assert(!memcmp(GPTR(0x3000), &expected, 16));
    if (!ok) assert(last_error == error);
}

static void compare_dos(SYSTEMTIME st, uint32_t extra_ticks) {
    FILETIME ft; assert(SystemTimeToFileTime(&st, &ft));
    uint64_t ticks = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    ticks += extra_ticks; ft.dwLowDateTime = (DWORD)ticks; ft.dwHighDateTime = (DWORD)(ticks >> 32);
    WORD date = 0xCCCC, time = 0xCCCC;
    SetLastError(0); BOOL ok = FileTimeToDosDateTime(&ft, &date, &time); DWORD error = GetLastError();
    MEM64(0x2000) = ticks; MEM16(0x3000) = 0xCCCC; MEM16(0x3002) = 0xCCCC; last_error = 0;
    assert(invoke(FileTimeToDosDateTime_entry, 3, 0x2000, 0x3000, 0x3002) == (uint32_t)ok);
    assert(MEM16(0x3000) == date && MEM16(0x3002) == time);
    if (!ok) assert(last_error == error);
}

int main(void) {
    const WORD years[] = {1600, 1601, 1700, 1900, 1969, 1970, 1980, 2000, 2004, 2100, 2400, 30827, 30828};
    for (unsigned y = 0; y < sizeof years / sizeof years[0]; ++y)
        for (WORD month = 0; month <= 13; ++month)
            for (WORD day = 0; day <= 32; ++day) {
                SYSTEMTIME st = {years[y], month, 0xFFFF, day, 23, 59, 59, 999};
                compare_systemtime(st);
            }
    const SYSTEMTIME times[] = {
        {2026, 10, 0, 15, 24, 0, 0, 0}, {2026, 10, 0, 15, 0, 60, 0, 0},
        {2026, 10, 0, 15, 0, 0, 60, 0}, {2026, 10, 0, 15, 0, 0, 0, 1000},
        {1601, 1, 0, 1, 0, 0, 0, 0}, {30827, 12, 0, 31, 23, 59, 59, 999},
    };
    for (unsigned i = 0; i < sizeof times / sizeof times[0]; ++i) compare_systemtime(times[i]);
    const uint64_t ticks[] = {0, 1, 9999, 10000, 116444735999999999ull, 116444736000000000ull,
                             134000000000000000ull, INT64_MAX, 0x8000000000000000ull, UINT64_MAX};
    for (unsigned i = 0; i < sizeof ticks / sizeof ticks[0]; ++i) compare_filetime(ticks[i]);
    const SYSTEMTIME dos[] = {
        {1979, 12, 0, 31, 23, 59, 58, 0}, {1979, 12, 0, 31, 23, 59, 59, 999},
        {1980, 1, 0, 1, 0, 0, 0, 0}, {2026, 1, 0, 1, 0, 0, 0, 0},
        {2026, 1, 0, 1, 0, 0, 0, 1}, {2026, 1, 0, 1, 0, 0, 1, 999},
        {2026, 1, 0, 1, 23, 59, 59, 999}, {2000, 2, 0, 29, 12, 34, 56, 0},
        {2107, 12, 0, 31, 23, 59, 58, 0}, {2107, 12, 0, 31, 23, 59, 58, 1},
        {2108, 1, 0, 1, 0, 0, 0, 0},
    };
    for (unsigned i = 0; i < sizeof dos / sizeof dos[0]; ++i) { compare_dos(dos[i], 0); compare_dos(dos[i], 1); }
    TIME_ZONE_INFORMATION zone;
    DWORD mode = GetTimeZoneInformation(&zone); assert(mode != TIME_ZONE_ID_INVALID);
    current_offset = -(zone.Bias + (mode == TIME_ZONE_ID_DAYLIGHT ? zone.DaylightBias : zone.StandardBias)) * 60;
    for (unsigned i = 0; i < sizeof ticks / sizeof ticks[0]; ++i) {
        FILETIME input = {(DWORD)ticks[i], (DWORD)(ticks[i] >> 32)}, expected;
        assert(FileTimeToLocalFileTime(&input, &expected)); MEM64(0x2000) = ticks[i];
        assert(invoke(FileTimeToLocalFileTime_entry, 2, 0x2000, 0x3000, 0) == 1 && !memcmp(GPTR(0x3000), &expected, 8));
        assert(LocalFileTimeToFileTime(&input, &expected));
        assert(invoke(LocalFileTimeToFileTime_entry, 2, 0x2000, 0x3000, 0) == 1 && !memcmp(GPTR(0x3000), &expected, 8));
    }
    const long offsets[] = {0, 10800, 19800, -14400, -43200, 50400};
    for (unsigned o = 0; o < sizeof offsets / sizeof offsets[0]; ++o) {
        current_offset = offsets[o];
        for (unsigned i = 0; i < sizeof ticks / sizeof ticks[0]; ++i) {
            MEM64(0x2000) = ticks[i];
            assert(invoke(FileTimeToLocalFileTime_entry, 2, 0x2000, 0x3000, 0) == 1);
            assert(MEM64(0x3000) == ticks[i] + (uint64_t)((int64_t)current_offset * 10000000ll));
            assert(invoke(LocalFileTimeToFileTime_entry, 2, 0x3000, 0x3000, 0) == 1 && MEM64(0x3000) == ticks[i]);
        }
    }
    MEM64(0x3000) = 0x12345678;
    assert(!invoke(SystemTimeToFileTime_entry, 2, sizeof memory - 15, 0x3000, 0) && last_error == 87 && MEM64(0x3000) == 0x12345678);
    assert(!invoke(FileTimeToSystemTime_entry, 2, sizeof memory - 7, 0x3000, 0) && last_error == 87);
    assert(!invoke(LocalFileTimeToFileTime_entry, 2, 0x2000, sizeof memory - 7, 0) && last_error == 87);
    assert(!invoke(FileTimeToDosDateTime_entry, 3, 0x2000, sizeof memory - 1, 0x3002) && last_error == 87);
    printf("PASS timestamps: %u stdcall checks vs Win32, Gregorian/leap/range validation, pre-1970, DOS rounding, timezone bias/wrap, pointer bounds\n", checks);
    return 0;
}
'''


class TimestampTest(unittest.TestCase):
    def test_win32_oracle(self):
        text = (ROOT / "android/host/kernel32.c").read_text(encoding="utf-8")
        store = text[text.index("static void store_systemtime"):text.index("WINAPI_EXPORT(K32, GetSystemTime,")]
        conversions = text[text.index("static int filetime_tm"):text.index("/* --------------------------------------------------------------- memory */")]
        host = (ROOT / "android/host/host.h").read_text(encoding="utf-8")
        start = host.index("#define WINAPI_EXPORT(")
        macro = host[start:host.index("\n\n", start)]
        compile_probe("timestamps", HARNESS, {"timestamps.h": store + conversions, "exports.h": macro})


if __name__ == "__main__":
    unittest.main()
