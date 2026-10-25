/* kernel32: memory, heaps, NLS, time, process environment and diagnostics.
 * Locale facts mirror the Windows PC the x86 build ran on: ANSI code page
 * 1251, system and user locale ru-RU (1049). */
#define _GNU_SOURCE
#include "host.h"
#include <ctype.h>
#include <errno.h>
#include <strings.h>
#include <time.h>
#include <unistd.h>
#include <wctype.h>

#define K32 "kernel32.dll"

/* ----------------------------------------------------------------- time */
uint64_t void_monotonic_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static uint64_t boot_ns;
uint32_t void_tick_ms(void)
{
    if (!boot_ns) boot_ns = void_monotonic_ns() - 3600000000000ull;  /* an hour of "uptime" */
    return (uint32_t)((void_monotonic_ns() - boot_ns) / 1000000ull);
}

uint64_t void_now_100ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec * 10000000ull + (uint64_t)ts.tv_nsec / 100u + 116444736000000000ull;
}

WINAPI_EXPORT(K32, GetTickCount, 0) { return void_tick_ms(); }
WINAPI_EXPORT(K32, QueryPerformanceFrequency, 1)
{
    MEM32(ARG(0)) = 10000000u;
    MEM32(ARG(0) + 4) = 0;
    return 1;
}
WINAPI_EXPORT(K32, QueryPerformanceCounter, 1)
{
    if (!boot_ns) (void)void_tick_ms();
    uint64_t ticks = (void_monotonic_ns() - boot_ns) / 100u;
    MEM32(ARG(0)) = (uint32_t)ticks;
    MEM32(ARG(0) + 4) = (uint32_t)(ticks >> 32);
    return 1;
}
WINAPI_EXPORT(K32, GetSystemTimeAsFileTime, 1)
{
    uint64_t t = void_now_100ns();
    MEM32(ARG(0)) = (uint32_t)t;
    MEM32(ARG(0) + 4) = (uint32_t)(t >> 32);
    return 0;
}

static void store_systemtime(uint32_t out, const struct tm *tm, long ms)
{
    MEM16(out + 0) = (uint16_t)(tm->tm_year + 1900);
    MEM16(out + 2) = (uint16_t)(tm->tm_mon + 1);
    MEM16(out + 4) = (uint16_t)tm->tm_wday;
    MEM16(out + 6) = (uint16_t)tm->tm_mday;
    MEM16(out + 8) = (uint16_t)tm->tm_hour;
    MEM16(out + 10) = (uint16_t)tm->tm_min;
    MEM16(out + 12) = (uint16_t)tm->tm_sec;
    MEM16(out + 14) = (uint16_t)ms;
}

WINAPI_EXPORT(K32, GetSystemTime, 1)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    gmtime_r(&ts.tv_sec, &tm);
    store_systemtime(ARG(0), &tm, ts.tv_nsec / 1000000L);
    return 0;
}

WINAPI_EXPORT(K32, GetLocalTime, 1)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);
    store_systemtime(ARG(0), &tm, ts.tv_nsec / 1000000L);
    return 0;
}

WINAPI_EXPORT(K32, GetTimeZoneInformation, 1)
{
    uint32_t out = ARG(0);
    memset(GPTR(out), 0, 172);
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    MEM32(out) = (uint32_t)(int32_t)(-(tm.tm_gmtoff / 60));   /* Bias, minutes */
    void_utf8_to_gw(tm.tm_zone ? tm.tm_zone : "UTC", out + 4, 32);
    return 0;                                                 /* TIME_ZONE_ID_UNKNOWN */
}

static int filetime_tm(uint64_t ticks, struct tm *tm)
{
    if (ticks > INT64_MAX) return 0;
    time_t seconds = (time_t)((int64_t)(ticks / 10000000ull) - 11644473600ll);
    return gmtime_r(&seconds, tm) != NULL;
}

WINAPI_EXPORT(K32, FileTimeToSystemTime, 2)
{
    if (!void_vm_readable(ARG(0), 8) || !void_vm_writable(ARG(1), 16)) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    uint64_t t = MEM32(ARG(0)) | ((uint64_t)MEM32(ARG(0) + 4) << 32);
    struct tm tm;
    if (!filetime_tm(t, &tm)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    store_systemtime(ARG(1), &tm, (long)((t / 10000u) % 1000u));
    return 1;
}

WINAPI_EXPORT(K32, SystemTimeToFileTime, 2)
{
    if (!void_vm_readable(ARG(0), 16) || !void_vm_writable(ARG(1), 8)) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    uint32_t in = ARG(0), year = MEM16(in), month = MEM16(in + 2), day = MEM16(in + 6);
    uint32_t hour = MEM16(in + 8), minute = MEM16(in + 10), second = MEM16(in + 12), ms = MEM16(in + 14);
    if (year < 1601 || year > 30827 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59 || ms > 999) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    static const uint16_t days_before_month[] = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};
    static const uint8_t month_length[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    int leap = !(year % 4) && (year % 100 || !(year % 400));
    uint32_t month_days = month_length[month - 1] + (month == 2 && leap);
    if (day < 1 || day > month_days) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    uint64_t previous = year - 1;
    uint64_t days = previous * 365 + previous / 4 - previous / 100 + previous / 400 - 584388;
    days += days_before_month[month - 1] + (month > 2 && leap) + day - 1;
    uint64_t ticks = (((days * 24 + hour) * 60 + minute) * 60 + second) * 10000000ull + ms * 10000ull;
    MEM32(ARG(1)) = (uint32_t)ticks;
    MEM32(ARG(1) + 4) = (uint32_t)(ticks >> 32);
    return 1;
}

static uint32_t local_filetime(int to_utc)
{
    if (!void_vm_readable(ARG(0), 8) || !void_vm_writable(ARG(1), 8)) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    time_t now = time(NULL);
    struct tm tm;
    if (!localtime_r(&now, &tm)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    uint64_t t = MEM32(ARG(0)) | ((uint64_t)MEM32(ARG(0) + 4) << 32);
    /* Win32 applies today's bias, including today's DST, even for old dates. */
    uint64_t offset = (uint64_t)((int64_t)tm.tm_gmtoff * 10000000ll);
    t = to_utc ? t - offset : t + offset;
    MEM32(ARG(1)) = (uint32_t)t;
    MEM32(ARG(1) + 4) = (uint32_t)(t >> 32);
    return 1;
}
WINAPI_EXPORT(K32, FileTimeToLocalFileTime, 2) { return local_filetime(0); }
WINAPI_EXPORT(K32, LocalFileTimeToFileTime, 2) { return local_filetime(1); }

WINAPI_EXPORT(K32, FileTimeToDosDateTime, 3)
{
    if (!void_vm_readable(ARG(0), 8) || !void_vm_writable(ARG(1), 2) || !void_vm_writable(ARG(2), 2)) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    uint64_t ticks = MEM32(ARG(0)) | ((uint64_t)MEM32(ARG(0) + 4) << 32);
    struct tm tm;
    /* DOS timestamps round upward to the next two-second slot, across days. */
    if (ticks > INT64_MAX || !filetime_tm(ticks + 19999999ull, &tm) || tm.tm_year < 80 || tm.tm_year > 207) {
        void_set_last_error(ERROR_INVALID_PARAMETER_); return 0;
    }
    MEM16(ARG(1)) = (uint16_t)(((tm.tm_year - 80) << 9) | ((tm.tm_mon + 1) << 5) | tm.tm_mday);
    MEM16(ARG(2)) = (uint16_t)((tm.tm_hour << 11) | (tm.tm_min << 5) | (tm.tm_sec / 2));
    return 1;
}

/* --------------------------------------------------------------- memory */
WINAPI_EXPORT(K32, VirtualAlloc, 4)
{
    uint32_t r = void_vm_alloc(ARG(0), ARG(1), ARG(2), ARG(3));
    VLOG("[void] VirtualAlloc(%08X, %08X, %X, %X) = %08X", ARG(0), ARG(1), ARG(2), ARG(3), r);
    return r;
}
WINAPI_EXPORT(K32, VirtualFree, 3) { return (uint32_t)void_vm_free(ARG(0), ARG(1), ARG(2)); }
WINAPI_EXPORT(K32, VirtualQuery, 3)
{
    if (ARG(2) < 28) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    return void_vm_query(ARG(0), ARG(1));
}
WINAPI_EXPORT(K32, VirtualProtect, 4)
{
    uint32_t old = 0;
    int ok = void_vm_protect(ARG(0), ARG(1), ARG(2), &old);
    if (ok && ARG(3)) MEM32(ARG(3)) = old;
    return (uint32_t)ok;
}

WINAPI_EXPORT(K32, GetProcessHeap, 0) { return void_process_heap(); }
WINAPI_EXPORT(K32, HeapCreate, 3) { return void_heap_create(ARG(1), ARG(2)); }
WINAPI_EXPORT(K32, HeapDestroy, 1) { return (uint32_t)void_heap_destroy(ARG(0)); }
WINAPI_EXPORT(K32, HeapAlloc, 3)
{
    uint32_t r = void_heap_alloc(ARG(0), ARG(2), (ARG(1) & 8u) != 0);
    if (!r) {
        void_log("[void] HeapAlloc(%08X, %X, %u) failed (caller %08X)", ARG(0), ARG(1), ARG(2), g_cur_func);
        void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_);
    }
    return r;
}
WINAPI_EXPORT(K32, HeapFree, 3) { return (uint32_t)void_heap_free(ARG(0), ARG(2)); }
WINAPI_EXPORT(K32, HeapReAlloc, 4)
{
    uint32_t r = void_heap_realloc(ARG(0), ARG(2), ARG(3), (ARG(1) & 8u) != 0, (ARG(1) & 0x10u) != 0);
    if (!r) void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_);
    return r;
}
WINAPI_EXPORT(K32, HeapSize, 3) { return void_heap_size(ARG(0), ARG(2)); }
WINAPI_EXPORT(K32, HeapValidate, 3) { return 1; }
WINAPI_EXPORT(K32, HeapCompact, 2) { return 0x100000u; }
WINAPI_EXPORT(K32, HeapSetInformation, 4) { return 1; }

/* GMEM_FIXED/LMEM_FIXED blocks on the process heap; movable handles are
 * served as fixed pointers, which GlobalLock returns unchanged. */
WINAPI_EXPORT(K32, GlobalAlloc, 2) { return void_heap_alloc(void_process_heap(), ARG(1) ? ARG(1) : 1, (ARG(0) & 0x40u) != 0); }
WINAPI_EXPORT(K32, GlobalFree, 1) { return void_heap_free(void_process_heap(), ARG(0)) ? 0 : ARG(0); }
WINAPI_EXPORT(K32, GlobalLock, 1) { return ARG(0); }
WINAPI_EXPORT(K32, GlobalUnlock, 1) { return 1; }
WINAPI_EXPORT(K32, GlobalSize, 1) { return void_heap_size(void_process_heap(), ARG(0)); }
WINAPI_EXPORT(K32, LocalAlloc, 2) { return void_heap_alloc(void_process_heap(), ARG(1) ? ARG(1) : 1, (ARG(0) & 0x40u) != 0); }
WINAPI_EXPORT(K32, LocalFree, 1) { return void_heap_free(void_process_heap(), ARG(0)) ? 0 : ARG(0); }
WINAPI_EXPORT(K32, GlobalMemoryStatus, 1)
{
    uint32_t out = ARG(0);
    MEM32(out + 0) = 32;
    MEM32(out + 4) = 40;                  /* dwMemoryLoad */
    MEM32(out + 8) = 0x7FFFFFFFu;         /* dwTotalPhys */
    MEM32(out + 12) = 0x60000000u;        /* dwAvailPhys */
    MEM32(out + 16) = 0x7FFFFFFFu;
    MEM32(out + 20) = 0x60000000u;
    MEM32(out + 24) = 0x7FFE0000u;        /* dwTotalVirtual */
    MEM32(out + 28) = 0x50000000u;
    return 0;
}

WINAPI_EXPORT(K32, IsBadReadPtr, 2) { return ARG(1) && !void_vm_readable(ARG(0), ARG(1)); }
WINAPI_EXPORT(K32, IsBadWritePtr, 2) { return ARG(1) && !void_vm_writable(ARG(0), ARG(1)); }
WINAPI_EXPORT(K32, IsBadCodePtr, 1) { return !void_dispatch_find(ARG(0)); }
WINAPI_EXPORT(K32, IsBadStringPtrA, 2)
{
    uint32_t p = ARG(0), max = ARG(1);
    for (uint32_t i = 0; i < max; ++i) {
        if (!void_vm_readable(p + i, 1)) return 1;
        if (!MEM8(p + i)) return 0;
    }
    return 0;
}
WINAPI_EXPORT(K32, IsBadStringPtrW, 2)
{
    uint32_t p = ARG(0), max = ARG(1);
    for (uint32_t i = 0; i < max; ++i) {
        if (!void_vm_readable(p + 2 * i, 2)) return 1;
        if (!MEM16(p + 2 * i)) return 0;
    }
    return 0;
}

/* ------------------------------------------------------------ code pages */


static uint32_t real_cp(uint32_t cp)
{
    switch (cp) {
    case 0: case 3: return 1251;      /* CP_ACP, CP_THREAD_ACP */
    case 1: return 437;               /* CP_OEMCP */
    case 2: return 10000;             /* CP_MACCP */
    default: return cp;
    }
}

static int cp_supported(uint32_t cp)
{
    cp = real_cp(cp);
    return cp == 1252 || cp == 1251 || cp == 437 || cp == 65001 || cp == 20127 || cp == 28591;
}

static uint16_t byte_to_u16(uint32_t cp, uint8_t c)
{
    if (c < 0x80) return c;
    switch (cp) {
    case 1251: return void_ansi_to_u16(c);
    case 28591: return c;
    case 20127: return '?';
    default: return void_cp1252_to_u16(c);   /* 1252, and 437 approximated */
    }
}

static int u16_to_byte(uint32_t cp, uint16_t u, uint8_t *out)
{
    if (u < 0x80) { *out = (uint8_t)u; return 1; }
    if (cp == 1251) return void_u16_to_ansi(u, out);
    if (cp == 28591 && u < 0x100) { *out = (uint8_t)u; return 1; }
    return void_u16_to_cp1252(u, out);
}

WINAPI_EXPORT(K32, GetACP, 0) { return 1251; }
WINAPI_EXPORT(K32, GetOEMCP, 0) { return 437; }
WINAPI_EXPORT(K32, AreFileApisANSI, 0) { return 1; }
WINAPI_EXPORT(K32, IsValidCodePage, 1) { return (uint32_t)cp_supported(ARG(0)); }
WINAPI_EXPORT(K32, GetCPInfo, 2)
{
    uint32_t cp = real_cp(ARG(0)), out = ARG(1);
    if (!cp_supported(cp)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    memset(GPTR(out), 0, 18);
    MEM32(out) = cp == 65001 ? 4u : 1u;     /* MaxCharSize */
    MEM8(out + 4) = '?';                    /* DefaultChar */
    return 1;
}

WINAPI_EXPORT(K32, MultiByteToWideChar, 6)
{
    uint32_t cp = real_cp(ARG(0)), src = ARG(2), dst = ARG(4);
    int32_t src_len = (int32_t)ARG(3), dst_len = (int32_t)ARG(5);
    if (!cp_supported(cp) || !src || dst_len < 0) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    uint32_t n = src_len < 0 ? (uint32_t)void_gstrlen(src) + 1 : (uint32_t)src_len;
    uint32_t written = 0;
    if (cp == 65001) {
        uint32_t i = 0;
        while (i < n) {
            uint32_t c = MEM8(src + i++);
            if (c >= 0x80) {
                int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : -1;
                if (extra < 0) c = 0xFFFD;
                else {
                    c &= 0x3Fu >> extra;
                    for (int k = 0; k < extra && i < n; ++k) c = (c << 6) | (MEM8(src + i++) & 0x3Fu);
                }
            }
            uint32_t units = c >= 0x10000 ? 2 : 1;
            if (dst_len) {
                if (written + units > (uint32_t)dst_len) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
                if (units == 2) {
                    c -= 0x10000;
                    MEM16(dst + 2 * written) = (uint16_t)(0xD800 + (c >> 10));
                    MEM16(dst + 2 * written + 2) = (uint16_t)(0xDC00 + (c & 0x3FF));
                } else {
                    MEM16(dst + 2 * written) = (uint16_t)c;
                }
            }
            written += units;
        }
        return written;
    }
    if (dst_len && (uint32_t)dst_len < n) {
        for (uint32_t i = 0; i < (uint32_t)dst_len; ++i) MEM16(dst + 2 * i) = byte_to_u16(cp, MEM8(src + i));
        void_set_last_error(ERROR_INSUFFICIENT_BUFFER_);
        return 0;
    }
    if (dst_len) for (uint32_t i = 0; i < n; ++i) MEM16(dst + 2 * i) = byte_to_u16(cp, MEM8(src + i));
    if (void_verbose && dst_len) {
        int high = 0;
        for (uint32_t i = 0; i < n; ++i) high |= MEM8(src + i) >= 0x80;
        if (high) {
            char bytes[160];
            size_t at = 0;
            for (uint32_t i = 0; i < n && i < 32 && at + 4 < sizeof bytes; ++i)
                at += (size_t)snprintf(bytes + at, sizeof bytes - at, "%02X ", MEM8(src + i));
            void_log("[void] MultiByteToWideChar(cp %u) high bytes from %08X: %s", cp, g_cur_func, bytes);
        }
    }
    return n;
}

WINAPI_EXPORT(K32, WideCharToMultiByte, 8)
{
    uint32_t cp = real_cp(ARG(0)), src = ARG(2), dst = ARG(4), def = ARG(6), used = ARG(7);
    int32_t src_len = (int32_t)ARG(3), dst_len = (int32_t)ARG(5);
    if (!cp_supported(cp) || !src || dst_len < 0) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    uint32_t n = src_len < 0 ? (uint32_t)void_gwcslen(src) + 1 : (uint32_t)src_len;
    uint32_t written = 0;
    int defaulted = 0;
    for (uint32_t i = 0; i < n; ++i) {
        uint32_t c = MEM16(src + 2 * i);
        char buf[4];
        size_t len;
        if (cp == 65001) {
            if (c >= 0xD800 && c < 0xDC00 && i + 1 < n) {
                uint32_t low = MEM16(src + 2 * (i + 1));
                if (low >= 0xDC00 && low < 0xE000) { c = 0x10000 + ((c - 0xD800) << 10) + (low - 0xDC00); ++i; }
            }
            len = void_utf8_encode(c, buf);
        } else {
            uint8_t b;
            if (!u16_to_byte(cp, (uint16_t)c, &b)) { defaulted = 1; b = def ? MEM8(def) : (uint8_t)'?'; }
            buf[0] = (char)b;
            len = 1;
        }
        if (dst_len) {
            if (written + len > (uint32_t)dst_len) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
            for (size_t k = 0; k < len; ++k) MEM8(dst + written + (uint32_t)k) = (uint8_t)buf[k];
        }
        written += (uint32_t)len;
    }
    if (used) MEM32(used) = (uint32_t)defaulted;
    if (defaulted && void_verbose) {
        char units[200];
        size_t at = 0;
        for (uint32_t i = 0; i < n && i < 24 && at + 6 < sizeof units; ++i)
            at += (size_t)snprintf(units + at, sizeof units - at, "%04X ", MEM16(src + 2 * i));
        void_log("[void] WideCharToMultiByte(cp %u) default char from %08X: %s", cp, g_cur_func, units);
    }
    return written;
}

/* ---------------------------------------------------------------- locale */
#define LCID_EN_US 0x0409u
#define LCID_RU_RU 0x0419u

WINAPI_EXPORT(K32, GetUserDefaultLCID, 0) { return LCID_RU_RU; }
WINAPI_EXPORT(K32, GetSystemDefaultLCID, 0) { return LCID_RU_RU; }
WINAPI_EXPORT(K32, GetUserDefaultLangID, 0) { return LCID_RU_RU; }
WINAPI_EXPORT(K32, GetSystemDefaultLangID, 0) { return LCID_RU_RU; }
WINAPI_EXPORT(K32, GetThreadLocale, 0) { return LCID_RU_RU; }

static uint32_t canonical_lcid(uint32_t lcid)
{
    switch (lcid & 0xFFFFu) {
    case 0x0400: case 0x0000: return LCID_RU_RU;    /* LOCALE_USER_DEFAULT */
    case 0x0800: return LCID_RU_RU;                 /* LOCALE_SYSTEM_DEFAULT */
    default: return lcid & 0xFFFFu;
    }
}

WINAPI_EXPORT(K32, IsValidLocale, 2)
{
    uint32_t l = canonical_lcid(ARG(0));
    return l == LCID_EN_US || l == LCID_RU_RU;
}

static const char *locale_value(uint32_t lcid, uint32_t type, char *tmp)
{
    int ru = lcid == LCID_RU_RU;
    static const char *days_en[] = {"Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"};
    static const char *days_ru[] = {"понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"};
    static const char *sdays_en[] = {"Mon","Tue","Wed","Thu","Fri","Sat","Sun"};
    static const char *sdays_ru[] = {"Пн","Вт","Ср","Чт","Пт","Сб","Вс"};
    static const char *months_en[] = {"January","February","March","April","May","June","July","August","September","October","November","December"};
    static const char *months_ru[] = {"Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"};
    static const char *smonths_en[] = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"};
    static const char *smonths_ru[] = {"янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"};
    type &= ~0x80000000u;   /* LOCALE_NOUSEROVERRIDE */
    type &= ~0x40000000u;   /* LOCALE_USE_CP_ACP */
    switch (type) {
    case 0x0001: sprintf(tmp, "%04x", lcid); return tmp;                  /* LOCALE_ILANGUAGE */
    case 0x0002: return ru ? "Русский (Россия)" : "English (United States)";
    case 0x0003: return ru ? "RUS" : "ENU";                                 /* LOCALE_SABBREVLANGNAME */
    case 0x0004: return ru ? "русский" : "English";
    case 0x0005: sprintf(tmp, "%u", ru ? 7u : 1u); return tmp;              /* LOCALE_ICOUNTRY */
    case 0x0006: return ru ? "Россия" : "United States";
    case 0x0007: return ru ? "RUS" : "USA";
    case 0x0059: return ru ? "ru" : "en";                                   /* LOCALE_SISO639LANGNAME */
    case 0x005A: return ru ? "RU" : "US";                                   /* LOCALE_SISO3166CTRYNAME */
    case 0x000B: return ru ? "866" : "437";                                 /* LOCALE_IDEFAULTCODEPAGE */
    case 0x1004: return ru ? "1251" : "1252";                               /* LOCALE_IDEFAULTANSICODEPAGE */
    case 0x1011: return ru ? "10007" : "10000";                             /* LOCALE_IDEFAULTMACCODEPAGE */
    case 0x000C: return ru ? ";" : ",";                                     /* LOCALE_SLIST */
    case 0x000D: return "0";                                                /* LOCALE_IMEASURE */
    case 0x000E: return ru ? "," : ".";                                     /* LOCALE_SDECIMAL */
    case 0x000F: return ru ? "\xC2\xA0" : ",";                              /* LOCALE_STHOUSAND */
    case 0x0010: return "3;0";                                              /* LOCALE_SGROUPING */
    case 0x0011: return "2";                                                /* LOCALE_IDIGITS */
    case 0x0012: return "1";                                                /* LOCALE_ILZERO */
    case 0x0014: return ru ? "\xE2\x82\xBD" : "$";                          /* LOCALE_SCURRENCY */
    case 0x0015: return ru ? "RUB" : "USD";
    case 0x0016: return ru ? "," : ".";                                     /* LOCALE_SMONDECIMALSEP */
    case 0x0017: return ru ? "\xC2\xA0" : ",";                              /* LOCALE_SMONTHOUSANDSEP */
    case 0x0018: return "3;0";
    case 0x0019: return "2";
    case 0x001A: return "2";                                                /* LOCALE_IINTLCURRDIGITS */
    case 0x001B: return ru ? "3" : "0";                                     /* LOCALE_ICURRENCY */
    case 0x001C: return ru ? "8" : "0";                                     /* LOCALE_INEGCURR */
    case 0x001D: return ru ? "." : "/";                                     /* LOCALE_SDATE */
    case 0x001E: return ":";                                                /* LOCALE_STIME */
    case 0x001F: return ru ? "dd.MM.yyyy" : "M/d/yyyy";                     /* LOCALE_SSHORTDATE */
    case 0x0020: return ru ? "d MMMM yyyy 'г.'" : "dddd, MMMM d, yyyy";    /* LOCALE_SLONGDATE */
    case 0x1003: return ru ? "H:mm:ss" : "h:mm:ss tt";                      /* LOCALE_STIMEFORMAT */
    case 0x0021: return ru ? "1" : "0";                                     /* LOCALE_IDATE */
    case 0x0022: return ru ? "1" : "0";                                     /* LOCALE_ILDATE */
    case 0x0023: return ru ? "1" : "0";                                     /* LOCALE_ITIME */
    case 0x0025: return ru ? "0" : "0";                                     /* LOCALE_ITLZERO */
    case 0x0026: return "1";                                                /* LOCALE_ICENTURY */
    case 0x0027: return ru ? "1" : "0";                                     /* LOCALE_IDAYLZERO */
    case 0x0028: return ru ? "1" : "0";                                     /* LOCALE_IMONLZERO */
    case 0x0028 + 1: return ru ? "" : "AM";                                 /* 0x28 LOCALE_S1159 */
    case 0x002A: return ru ? "" : "PM";                                     /* LOCALE_S2359 */
    case 0x100C: return ru ? "0" : "6";                                     /* LOCALE_IFIRSTDAYOFWEEK */
    case 0x0050: return "-";                                                /* LOCALE_SNEGATIVESIGN */
    case 0x0051: return "";                                                 /* LOCALE_SPOSITIVESIGN */
    default: break;
    }
    if (type >= 0x002A + 0 && type <= 0x0030) return (ru ? days_ru : days_en)[type - 0x002A];
    if (type >= 0x0031 && type <= 0x0037) return (ru ? sdays_ru : sdays_en)[type - 0x0031];
    if (type >= 0x0038 && type <= 0x0043) return (ru ? months_ru : months_en)[type - 0x0038];
    if (type >= 0x0044 && type <= 0x004F) return (ru ? smonths_ru : smonths_en)[type - 0x0044];
    return NULL;
}

/* void_utf8_to_ga in code page cp (same contract: need + 1 when the text
 * does not fit, else the characters written before the terminator). */
static uint32_t utf8_to_cp(const char *s, uint32_t cp, uint32_t dst, uint32_t cap)
{
    uint32_t units[256], n = 0;
    for (const unsigned char *p = (const unsigned char *)s; *p && n < 256; ++n) {
        uint32_t c = *p++;
        int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
        if (extra) c &= 0x3Fu >> extra;
        while (extra-- && (*p & 0xC0) == 0x80) c = (c << 6) | (*p++ & 0x3Fu);
        units[n] = c > 0xFFFF ? 0xFFFD : c;
    }
    if (n + 1 > cap) return n + 1;
    for (uint32_t i = 0; i < n; ++i) {
        uint8_t b;
        u16_to_byte(cp, (uint16_t)units[i], &b);
        MEM8(dst + i) = b;
    }
    MEM8(dst + n) = 0;
    return n;
}

/* GetLocaleInfoA answers in the locale's ANSI code page (1251 for ru-RU)
 * unless LOCALE_USE_CP_ACP asks for the system one: the MSVC CRT reads the
 * user locale's month and day names this way for strftime. */
static uint32_t get_locale_info(int wide)
{
    uint32_t lcid = canonical_lcid(ARG(0)), type = ARG(1), out = ARG(2);
    int32_t cap = (int32_t)ARG(3);
    uint32_t ansi_cp = (type & 0x40000000u) ? 1251 : lcid == LCID_RU_RU ? 1251 : 1252;
    char tmp[32];
    const char *value = locale_value(lcid, type, tmp);
    if (!value) {
        VLOG("[void] GetLocaleInfo(%04X, %08X): unsupported", lcid, type);
        void_set_last_error(ERROR_INVALID_PARAMETER_);
        return 0;
    }
    if (type & 0x20000000u) {          /* LOCALE_RETURN_NUMBER */
        if (cap < (wide ? 2 : 4)) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
        MEM32(out) = (uint32_t)strtoul(value, NULL, 10);
        return wide ? 2 : 4;
    }
    if (!cap) {
        uint32_t need = wide ? void_utf8_to_gw(value, 0, 0) : utf8_to_cp(value, ansi_cp, 0, 0);
        return need;
    }
    uint32_t n = wide ? void_utf8_to_gw(value, out, (uint32_t)cap) : utf8_to_cp(value, ansi_cp, out, (uint32_t)cap);
    uint32_t need = (wide ? void_utf8_to_gw(value, 0, 0) : utf8_to_cp(value, ansi_cp, 0, 0));
    if (need > (uint32_t)cap) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    return n + 1;
}

WINAPI_EXPORT(K32, GetLocaleInfoA, 4) { return get_locale_info(0); }
WINAPI_EXPORT(K32, GetLocaleInfoW, 4) { return get_locale_info(1); }

WINAPI_EXPORT(K32, EnumSystemLocalesA, 2)
{
    uint32_t proc = ARG(0);
    static const char *ids[] = {"00000409", "00000419"};
    for (int i = 0; i < 2; ++i) {
        uint32_t s = void_gstrdup(ids[i]);
        uint32_t arg = s;
        uint32_t keep = void_call_guest(proc, 1, &arg, 1);
        void_gfree(s);
        if (!keep) break;
    }
    return 1;
}

/* ---------------------------------------------------------- string types */
static uint16_t ctype1(uint32_t c)
{
    uint16_t t = 0;
    if (c == 0) return 0x20;            /* C1_CNTRL */
    if (iswupper((wint_t)c)) t |= 0x001;
    if (iswlower((wint_t)c)) t |= 0x002;
    if (iswdigit((wint_t)c)) t |= 0x004;
    if (iswspace((wint_t)c)) t |= 0x008;
    if (iswpunct((wint_t)c)) t |= 0x010;
    if (iswcntrl((wint_t)c)) t |= 0x020;
    if (c == ' ' || c == '\t') t |= 0x040;
    if (iswxdigit((wint_t)c)) t |= 0x080;
    if (iswalpha((wint_t)c)) t |= 0x100;
    t |= 0x200;                          /* C1_DEFINED */
    if (c >= 0x80 && c < 0xA0) t = 0x220;
    return t;
}

static uint16_t ctype_of(uint32_t info, uint32_t c)
{
    /* The CRT asks for one character at a time (iswctype), a thousand-odd a
     * frame; ten wide-character class tests each are cached per unit. Every
     * class word has C1_DEFINED or C1_CNTRL set, so 0 means not computed. */
    static uint16_t ctype1_cache[0x10000];
    switch (info) {
    case 1:
        if (c > 0xFFFF) return ctype1(c);
        if (!ctype1_cache[c]) ctype1_cache[c] = ctype1(c);
        return ctype1_cache[c];
    case 2: return iswalpha((wint_t)c) ? 1 : iswdigit((wint_t)c) ? 3 : iswspace((wint_t)c) ? 10 : 0;  /* C2_* */
    case 4: return 0;                    /* CT_CTYPE3 */
    default: return 0;
    }
}

WINAPI_EXPORT(K32, GetStringTypeW, 4)
{
    uint32_t info = ARG(0), src = ARG(1), out = ARG(3);
    int32_t n = (int32_t)ARG(2);
    if (n < 0) n = (int32_t)void_gwcslen(src) + 1;
    for (int32_t i = 0; i < n; ++i) MEM16(out + 2 * (uint32_t)i) = ctype_of(info, MEM16(src + 2 * (uint32_t)i));
    return 1;
}

WINAPI_EXPORT(K32, GetStringTypeExW, 5)
{
    uint32_t info = ARG(1), src = ARG(2), out = ARG(4);
    int32_t n = (int32_t)ARG(3);
    if (n < 0) n = (int32_t)void_gwcslen(src) + 1;
    for (int32_t i = 0; i < n; ++i) MEM16(out + 2 * (uint32_t)i) = ctype_of(info, MEM16(src + 2 * (uint32_t)i));
    return 1;
}

WINAPI_EXPORT(K32, GetStringTypeA, 5)
{
    uint32_t lcid = canonical_lcid(ARG(0)), info = ARG(1), src = ARG(2), out = ARG(4);
    int32_t n = (int32_t)ARG(3);
    uint32_t cp = lcid == LCID_RU_RU ? 1251 : 1252;
    if (n < 0) n = (int32_t)void_gstrlen(src) + 1;
    for (int32_t i = 0; i < n; ++i) MEM16(out + 2 * (uint32_t)i) = ctype_of(info, byte_to_u16(cp, MEM8(src + (uint32_t)i)));
    return 1;
}

static uint32_t fold(uint32_t c, uint32_t flags)
{
    if (flags & 0x100u) return (uint32_t)towlower((wint_t)c);     /* LCMAP_LOWERCASE */
    if (flags & 0x200u) return (uint32_t)towupper((wint_t)c);     /* LCMAP_UPPERCASE */
    return c;
}

WINAPI_EXPORT(K32, LCMapStringW, 6)
{
    uint32_t flags = ARG(1), src = ARG(2), dst = ARG(4);
    int32_t n = (int32_t)ARG(3), cap = (int32_t)ARG(5);
    if (n < 0) n = (int32_t)void_gwcslen(src) + 1;
    if (flags & 0x400u) {               /* LCMAP_SORTKEY: bytes of the upper-cased text */
        int32_t need = n * 2 + 1;
        if (!cap) return (uint32_t)need;
        if (cap < need) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
        for (int32_t i = 0; i < n; ++i) {
            uint32_t c = (uint32_t)towupper((wint_t)MEM16(src + 2 * (uint32_t)i));
            MEM8(dst + 2 * (uint32_t)i) = (uint8_t)(c >> 8);
            MEM8(dst + 2 * (uint32_t)i + 1) = (uint8_t)c;
        }
        MEM8(dst + 2 * (uint32_t)n) = 0;
        return (uint32_t)need;
    }
    if (!cap) return (uint32_t)n;
    if (cap < n) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    for (int32_t i = 0; i < n; ++i) MEM16(dst + 2 * (uint32_t)i) = (uint16_t)fold(MEM16(src + 2 * (uint32_t)i), flags);
    return (uint32_t)n;
}

WINAPI_EXPORT(K32, LCMapStringA, 6)
{
    uint32_t lcid = canonical_lcid(ARG(0)), flags = ARG(1), src = ARG(2), dst = ARG(4);
    int32_t n = (int32_t)ARG(3), cap = (int32_t)ARG(5);
    uint32_t cp = lcid == LCID_RU_RU ? 1251 : 1252;
    if (n < 0) n = (int32_t)void_gstrlen(src) + 1;
    if (flags & 0x400u) {
        int32_t need = n + 1;
        if (!cap) return (uint32_t)need;
        if (cap < need) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
        for (int32_t i = 0; i < n; ++i) {
            uint8_t b;
            u16_to_byte(cp, (uint16_t)towupper((wint_t)byte_to_u16(cp, MEM8(src + (uint32_t)i))), &b);
            MEM8(dst + (uint32_t)i) = b;
        }
        MEM8(dst + (uint32_t)n) = 0;
        return (uint32_t)need;
    }
    if (!cap) return (uint32_t)n;
    if (cap < n) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    for (int32_t i = 0; i < n; ++i) {
        uint8_t b;
        u16_to_byte(cp, (uint16_t)fold(byte_to_u16(cp, MEM8(src + (uint32_t)i)), flags), &b);
        MEM8(dst + (uint32_t)i) = b;
    }
    return (uint32_t)n;
}

static int compare_units(uint32_t a, int wa, uint32_t b, int wb, uint32_t flags, int wide, uint32_t cp)
{
    for (int i = 0;; ++i) {
        int ea = i >= wa, eb = i >= wb;
        if (ea || eb) return ea && eb ? 2 : ea ? 1 : 3;
        uint32_t ca = wide ? MEM16(a + 2 * (uint32_t)i) : byte_to_u16(cp, MEM8(a + (uint32_t)i));
        uint32_t cb = wide ? MEM16(b + 2 * (uint32_t)i) : byte_to_u16(cp, MEM8(b + (uint32_t)i));
        if (flags & 1u) { ca = (uint32_t)towlower((wint_t)ca); cb = (uint32_t)towlower((wint_t)cb); }
        if (ca != cb) return ca < cb ? 1 : 3;
    }
}

WINAPI_EXPORT(K32, CompareStringW, 6)
{
    int32_t n1 = (int32_t)ARG(3), n2 = (int32_t)ARG(5);
    if (n1 < 0) n1 = (int32_t)void_gwcslen(ARG(2));
    if (n2 < 0) n2 = (int32_t)void_gwcslen(ARG(4));
    return (uint32_t)compare_units(ARG(2), n1, ARG(4), n2, ARG(1), 1, 0);
}

WINAPI_EXPORT(K32, CompareStringA, 6)
{
    uint32_t cp = canonical_lcid(ARG(0)) == LCID_RU_RU ? 1251 : 1252;
    int32_t n1 = (int32_t)ARG(3), n2 = (int32_t)ARG(5);
    if (n1 < 0) n1 = (int32_t)void_gstrlen(ARG(2));
    if (n2 < 0) n2 = (int32_t)void_gstrlen(ARG(4));
    return (uint32_t)compare_units(ARG(2), n1, ARG(4), n2, ARG(1), 0, cp);
}

WINAPI_EXPORT(K32, lstrcmpiA, 2)
{
    int r = compare_units(ARG(0), (int)void_gstrlen(ARG(0)), ARG(1), (int)void_gstrlen(ARG(1)), 1, 0, 1251);
    return (uint32_t)(r - 2);
}

WINAPI_EXPORT(K32, lstrcmpW, 2)
{
    int r = compare_units(ARG(0), (int)void_gwcslen(ARG(0)), ARG(1), (int)void_gwcslen(ARG(1)), 0, 1, 0);
    return (uint32_t)(r - 2);
}

WINAPI_EXPORT(K32, IsDBCSLeadByte, 1) { return 0; }

/* Date/time pictures (GetDateFormat / GetTimeFormat). */
static void format_picture(const char *pic, const uint16_t st[8], int ru, char *out, size_t cap)
{
    static const char *days_en[] = {"Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"};
    static const char *months_en[] = {"January","February","March","April","May","June","July","August","September","October","November","December"};
    size_t n = 0;
    out[0] = 0;
    for (const char *p = pic; *p && n + 16 < cap;) {
        char c = *p;
        int run = 1;
        while (p[run] == c) ++run;
        if (c == '\'') {
            const char *end = strchr(p + 1, '\'');
            size_t len = end ? (size_t)(end - p - 1) : strlen(p + 1);
            n += (size_t)snprintf(out + n, cap - n, "%.*s", (int)len, p + 1);
            p = end ? end + 1 : p + 1 + len;
            continue;
        }
        switch (c) {
        case 'd':
            if (run == 1) n += (size_t)snprintf(out + n, cap - n, "%u", st[3]);
            else if (run == 2) n += (size_t)snprintf(out + n, cap - n, "%02u", st[3]);
            else if (run == 3) n += (size_t)snprintf(out + n, cap - n, "%.3s", days_en[st[2] % 7]);
            else n += (size_t)snprintf(out + n, cap - n, "%s", days_en[st[2] % 7]);
            break;
        case 'M':
            if (run == 1) n += (size_t)snprintf(out + n, cap - n, "%u", st[1]);
            else if (run == 2) n += (size_t)snprintf(out + n, cap - n, "%02u", st[1]);
            else if (run == 3) n += (size_t)snprintf(out + n, cap - n, "%.3s", months_en[(st[1] + 11) % 12]);
            else n += (size_t)snprintf(out + n, cap - n, "%s", months_en[(st[1] + 11) % 12]);
            break;
        case 'y':
            if (run <= 2) n += (size_t)snprintf(out + n, cap - n, run == 1 ? "%u" : "%02u", st[0] % 100);
            else n += (size_t)snprintf(out + n, cap - n, "%04u", st[0]);
            break;
        case 'h': n += (size_t)snprintf(out + n, cap - n, run == 1 ? "%u" : "%02u", (st[4] % 12) ? st[4] % 12 : 12); break;
        case 'H': n += (size_t)snprintf(out + n, cap - n, run == 1 ? "%u" : "%02u", st[4]); break;
        case 'm': n += (size_t)snprintf(out + n, cap - n, run == 1 ? "%u" : "%02u", st[5]); break;
        case 's': n += (size_t)snprintf(out + n, cap - n, run == 1 ? "%u" : "%02u", st[6]); break;
        case 't':
            if (!ru) n += (size_t)snprintf(out + n, cap - n, "%.*s", run == 1 ? 1 : 2, st[4] < 12 ? "AM" : "PM");
            break;
        case 'g': break;
        default:
            n += (size_t)snprintf(out + n, cap - n, "%.*s", run, p);
            break;
        }
        p += run;
    }
}

static void current_systemtime(uint16_t st[8])
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm tm;
    localtime_r(&ts.tv_sec, &tm);
    st[0] = (uint16_t)(tm.tm_year + 1900); st[1] = (uint16_t)(tm.tm_mon + 1); st[2] = (uint16_t)tm.tm_wday;
    st[3] = (uint16_t)tm.tm_mday; st[4] = (uint16_t)tm.tm_hour; st[5] = (uint16_t)tm.tm_min;
    st[6] = (uint16_t)tm.tm_sec; st[7] = (uint16_t)(ts.tv_nsec / 1000000L);
}

static uint32_t date_time_format(int date)
{
    uint32_t lcid = canonical_lcid(ARG(0)), flags = ARG(1), time_va = ARG(2), pic_va = ARG(3), out = ARG(4);
    int32_t cap = (int32_t)ARG(5);
    uint16_t st[8];
    if (time_va) for (int i = 0; i < 8; ++i) st[i] = MEM16(time_va + 2 * (uint32_t)i);
    else current_systemtime(st);
    char *pic = pic_va ? void_astr_utf8(pic_va) : NULL;
    char tmp[32];
    const char *picture = pic ? pic : locale_value(lcid, date ? ((flags & 2u) ? 0x20u : 0x1Fu) : 0x1003u, tmp);
    char text[256];
    format_picture(picture, st, lcid == LCID_RU_RU, text, sizeof text);
    free(pic);
    uint32_t need = void_utf8_to_ga(text, 0, 0);
    if (!cap) return need;
    if (need > (uint32_t)cap) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    return void_utf8_to_ga(text, out, (uint32_t)cap) + 1;
}

WINAPI_EXPORT(K32, GetDateFormatA, 6) { return date_time_format(1); }
WINAPI_EXPORT(K32, GetTimeFormatA, 6) { return date_time_format(0); }

/* --------------------------------------------------------- environment */
static const char *const default_environment[] = {
    "ALLUSERSPROFILE=C:\\ProgramData",
    "APPDATA=C:\\Users\\Player\\AppData\\Roaming",
    "COMPUTERNAME=ANDROID",
    "LOCALAPPDATA=C:\\Users\\Player\\AppData\\Local",
    "NUMBER_OF_PROCESSORS=8",
    "OS=Windows_NT",
    "PATH=C:\\Windows\\system32;C:\\Windows",
    "PROCESSOR_ARCHITECTURE=x86",
    "ProgramData=C:\\ProgramData",
    "ProgramFiles=C:\\Program Files",
    "PUBLIC=C:\\Users\\Public",
    "SystemDrive=C:",
    "SystemRoot=C:\\Windows",
    "TEMP=C:\\Users\\Player\\AppData\\Local\\Temp",
    "TMP=C:\\Users\\Player\\AppData\\Local\\Temp",
    "USERNAME=Player",
    "USERPROFILE=C:\\Users\\Player",
    "windir=C:\\Windows",
};
static char **environment;
static int environment_count;
static pthread_mutex_t env_lock = PTHREAD_MUTEX_INITIALIZER;

static void env_init(void)
{
    if (environment) return;
    environment_count = (int)(sizeof default_environment / sizeof default_environment[0]);
    environment = (char **)calloc(256, sizeof(char *));
    for (int i = 0; i < environment_count; ++i) environment[i] = strdup(default_environment[i]);
}

static int env_find(const char *name)
{
    size_t n = strlen(name);
    for (int i = 0; i < environment_count; ++i)
        if (!strncasecmp(environment[i], name, n) && environment[i][n] == '=') return i;
    return -1;
}

static uint32_t env_block(int wide)
{
    pthread_mutex_lock(&env_lock);
    env_init();
    size_t units = 1;
    for (int i = 0; i < environment_count; ++i) units += strlen(environment[i]) + 1;
    uint32_t block = void_galloc((uint32_t)(units * (wide ? 2 : 1)));
    uint32_t at = 0;
    for (int i = 0; i < environment_count; ++i) {
        for (const char *p = environment[i]; *p; ++p) {
            if (wide) MEM16(block + 2 * at) = (uint8_t)*p; else MEM8(block + at) = (uint8_t)*p;
            ++at;
        }
        if (wide) MEM16(block + 2 * at) = 0; else MEM8(block + at) = 0;
        ++at;
    }
    if (wide) MEM16(block + 2 * at) = 0; else MEM8(block + at) = 0;
    pthread_mutex_unlock(&env_lock);
    return block;
}

WINAPI_EXPORT(K32, GetEnvironmentStrings, 0) { return env_block(0); }
WINAPI_EXPORT(K32, GetEnvironmentStringsA, 0) { return env_block(0); }
WINAPI_EXPORT(K32, GetEnvironmentStringsW, 0) { return env_block(1); }
WINAPI_EXPORT(K32, FreeEnvironmentStringsA, 1) { void_gfree(ARG(0)); return 1; }
WINAPI_EXPORT(K32, FreeEnvironmentStringsW, 1) { void_gfree(ARG(0)); return 1; }

WINAPI_EXPORT(K32, GetEnvironmentVariableA, 3)
{
    char *name = void_astr_utf8(ARG(0));
    pthread_mutex_lock(&env_lock);
    env_init();
    int i = name ? env_find(name) : -1;
    uint32_t r = 0;
    if (i < 0) {
        void_set_last_error(ERROR_ENVVAR_NOT_FOUND_);
    } else {
        const char *value = strchr(environment[i], '=') + 1;
        uint32_t need = (uint32_t)strlen(value) + 1;
        if (need > ARG(2)) r = need;
        else r = void_utf8_to_ga(value, ARG(1), ARG(2));
    }
    pthread_mutex_unlock(&env_lock);
    VLOG("[void] GetEnvironmentVariableA(%s) = %u", name ? name : "", r);
    free(name);
    return r;
}

WINAPI_EXPORT(K32, SetEnvironmentVariableA, 2)
{
    char *name = void_astr_utf8(ARG(0)), *value = void_astr_utf8(ARG(1));
    pthread_mutex_lock(&env_lock);
    env_init();
    int i = env_find(name);
    if (value) {
        size_t len = strlen(name) + strlen(value) + 2;
        char *entry = (char *)malloc(len);
        snprintf(entry, len, "%s=%s", name, value);
        if (i >= 0) { free(environment[i]); environment[i] = entry; }
        else if (environment_count < 255) environment[environment_count++] = entry;
        else free(entry);
    } else if (i >= 0) {
        free(environment[i]);
        environment[i] = environment[--environment_count];
    }
    pthread_mutex_unlock(&env_lock);
    free(name); free(value);
    return 1;
}

WINAPI_EXPORT(K32, ExpandEnvironmentStringsA, 3)
{
    char *in = void_astr_utf8(ARG(0));
    char out[2048];
    size_t n = 0;
    pthread_mutex_lock(&env_lock);
    env_init();
    for (const char *p = in; p && *p && n < sizeof out - 1;) {
        const char *end = *p == '%' ? strchr(p + 1, '%') : NULL;
        if (end) {
            char name[256];
            snprintf(name, sizeof name, "%.*s", (int)(end - p - 1), p + 1);
            int i = env_find(name);
            if (i >= 0) { n += (size_t)snprintf(out + n, sizeof out - n, "%s", strchr(environment[i], '=') + 1); p = end + 1; continue; }
        }
        out[n++] = *p++;
    }
    out[n] = 0;
    pthread_mutex_unlock(&env_lock);
    free(in);
    uint32_t need = void_utf8_to_ga(out, 0, 0);
    if (need > ARG(2)) return need;
    return void_utf8_to_ga(out, ARG(1), ARG(2)) + 1;
}

static uint32_t command_line_a, command_line_w;
WINAPI_EXPORT(K32, GetCommandLineA, 0)
{
    if (!command_line_a) command_line_a = void_gstrdup("\"C:\\Games\\HeroesV\\bin\\H5_Game.exe\"");
    return command_line_a;
}
WINAPI_EXPORT(K32, GetCommandLineW, 0)
{
    if (!command_line_w) {
        const char *s = "\"C:\\Games\\HeroesV\\bin\\H5_Game.exe\"";
        command_line_w = void_galloc((uint32_t)(2 * strlen(s) + 2));
        void_utf8_to_gw(s, command_line_w, (uint32_t)strlen(s) + 1);
    }
    return command_line_w;
}

static void startup_info(uint32_t out)
{
    memset(GPTR(out), 0, 68);
    MEM32(out) = 68;
    MEM32(out + 44) = 1;                 /* dwFlags: STARTF_USESHOWWINDOW */
    MEM16(out + 48) = 10;                /* wShowWindow: SW_SHOWDEFAULT */
}

WINAPI_EXPORT(K32, GetStartupInfoA, 1) { startup_info(ARG(0)); return 0; }
WINAPI_EXPORT(K32, GetStartupInfoW, 1) { startup_info(ARG(0)); return 0; }
WINAPI_EXPORT(K32, SetHandleCount, 1) { return ARG(0); }

/* ---------------------------------------------------------- system info */
WINAPI_EXPORT(K32, GetVersion, 0) { return 0x23F00206u; }   /* 6.2 build 9200 */
WINAPI_EXPORT(K32, GetVersionExA, 1)
{
    uint32_t out = ARG(0), size = MEM32(out);
    if (size != 148 && size != 156) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    memset(GPTR(out + 4), 0, size - 4);
    MEM32(out + 4) = 6;          /* Windows reports 6.2 to unmanifested applications */
    MEM32(out + 8) = 2;
    MEM32(out + 12) = 9200;
    MEM32(out + 16) = 2;         /* VER_PLATFORM_WIN32_NT */
    if (size == 156) MEM8(out + 154) = 1;   /* wProductType: VER_NT_WORKSTATION */
    return 1;
}

WINAPI_EXPORT(K32, GetSystemInfo, 1)
{
    uint32_t out = ARG(0);
    long cpus = sysconf(_SC_NPROCESSORS_CONF);
    if (cpus < 1) cpus = 1;
    if (cpus > 32) cpus = 32;
    memset(GPTR(out), 0, 36);
    MEM16(out + 0) = 0;                       /* PROCESSOR_ARCHITECTURE_INTEL */
    MEM32(out + 4) = 0x1000;                  /* dwPageSize */
    MEM32(out + 8) = 0x10000;                 /* lpMinimumApplicationAddress */
    MEM32(out + 12) = 0x7FFEFFFF;             /* lpMaximumApplicationAddress */
    MEM32(out + 16) = (uint32_t)((1ull << cpus) - 1);
    MEM32(out + 20) = (uint32_t)cpus;
    MEM32(out + 24) = 586;                    /* PROCESSOR_INTEL_PENTIUM */
    MEM32(out + 28) = 0x10000;                /* dwAllocationGranularity */
    MEM16(out + 32) = 6;                      /* wProcessorLevel */
    MEM16(out + 34) = 0x0F12;
    return 0;
}

WINAPI_EXPORT(K32, IsProcessorFeaturePresent, 1)
{
    switch (ARG(0)) {
    case 0: return 0;     /* PF_FLOATING_POINT_PRECISION_ERRATA */
    case 1: return 0;     /* PF_FLOATING_POINT_EMULATED */
    case 2: case 3: case 6: case 8: case 10: case 12: case 13: case 17: return 1;
    case 7: return 0;     /* PF_3DNOW_INSTRUCTIONS_AVAILABLE */
    default: return 0;
    }
}

WINAPI_EXPORT(K32, GetSystemDirectoryA, 2) { return void_utf8_to_ga("C:\\Windows\\system32", ARG(0), ARG(1)); }
WINAPI_EXPORT(K32, GetSystemDirectoryW, 2) { return void_utf8_to_gw("C:\\Windows\\system32", ARG(0), ARG(1)); }
WINAPI_EXPORT(K32, GetWindowsDirectoryA, 2) { return void_utf8_to_ga("C:\\Windows", ARG(0), ARG(1)); }
WINAPI_EXPORT(K32, GetComputerNameA, 2) { void_utf8_to_ga("ANDROID", ARG(0), MEM32(ARG(1))); MEM32(ARG(1)) = 7; return 1; }

WINAPI_EXPORT(K32, MulDiv, 3)
{
    int32_t a = (int32_t)ARG(0), b = (int32_t)ARG(1), c = (int32_t)ARG(2);
    if (!c) return 0xFFFFFFFFu;
    int64_t p = (int64_t)a * b;
    int64_t q = (p + (((p < 0) != (c < 0)) ? -(int64_t)(llabs(c) / 2) : (int64_t)(llabs(c) / 2))) / c;
    if (q > INT32_MAX || q < INT32_MIN) return 0xFFFFFFFFu;
    return (uint32_t)(int32_t)q;
}

WINAPI_EXPORT(K32, EncodePointer, 1) { return ARG(0); }
WINAPI_EXPORT(K32, DecodePointer, 1) { return ARG(0); }

/* ---------------------------------------------------------- diagnostics */
WINAPI_EXPORT(K32, IsDebuggerPresent, 0) { return 0; }

WINAPI_EXPORT(K32, OutputDebugStringA, 1)
{
    char *s = void_astr_utf8(ARG(0));
    if (s) {
        size_t n = strlen(s);
        while (n && (s[n - 1] == '\n' || s[n - 1] == '\r')) s[--n] = 0;
        void_log("[guest-debug] %s", s);
    }
    free(s);
    return 0;
}

WINAPI_EXPORT(K32, OutputDebugStringW, 1)
{
    char *s = void_wstr_utf8(ARG(0));
    if (s) void_log("[guest-debug] %s", s);
    free(s);
    return 0;
}

static uint32_t unhandled_filter;
WINAPI_EXPORT(K32, SetUnhandledExceptionFilter, 1)
{
    uint32_t previous = unhandled_filter;
    unhandled_filter = ARG(0);
    return previous;
}

WINAPI_EXPORT(K32, UnhandledExceptionFilter, 1)
{
    uint32_t pointers = ARG(0), record = pointers ? MEM32(pointers) : 0;
    void_log("[void] UnhandledExceptionFilter: code %08X at %08X (caller %08X)",
        record ? MEM32(record) : 0, record ? MEM32(record + 12) : 0, g_cur_func);
    void_dump_state("UnhandledExceptionFilter");
    return 1;   /* EXCEPTION_EXECUTE_HANDLER: the caller terminates */
}

WINAPI_EXPORT(K32, GetConsoleCP, 0) { return 437; }
WINAPI_EXPORT(K32, GetConsoleOutputCP, 0) { return 437; }
WINAPI_EXPORT(K32, GetConsoleMode, 2) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
WINAPI_EXPORT(K32, WriteConsoleA, 5)
{
    char *s = (char *)malloc(ARG(2) + 1);
    memcpy(s, GPTR(ARG(1)), ARG(2));
    s[ARG(2)] = 0;
    void_log("[guest-console] %s", s);
    free(s);
    if (ARG(3)) MEM32(ARG(3)) = ARG(2);
    return 1;
}
WINAPI_EXPORT(K32, WriteConsoleW, 5)
{
    uint32_t n = ARG(2);
    char *s = (char *)malloc(n * 3 + 1), *w = s;
    for (uint32_t i = 0; i < n; ++i) w += void_utf8_encode(MEM16(ARG(1) + 2 * i), w);
    *w = 0;
    void_log("[guest-console] %s", s);
    free(s);
    if (ARG(3)) MEM32(ARG(3)) = n;
    return 1;
}

WINAPI_EXPORT(K32, FormatMessageA, 7)
{
    uint32_t flags = ARG(0), id = ARG(2), out = ARG(4), size = ARG(5);
    char text[128];
    snprintf(text, sizeof text, "Error %u.\r\n", id);
    uint32_t need = (uint32_t)strlen(text) + 1;
    if (flags & 0x100u) {                      /* FORMAT_MESSAGE_ALLOCATE_BUFFER */
        uint32_t block = void_heap_alloc(void_process_heap(), need > size ? need : size, 1);
        void_utf8_to_ga(text, block, need);
        MEM32(out) = block;
        return need - 1;
    }
    if (size < need) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    return void_utf8_to_ga(text, out, size);
}

/* ------------------------------------------------------------- process */
void void_process_exit(uint32_t code, int run_detach);

WINAPI_EXPORT(K32, ExitProcess, 1)
{
    void_log("[void] ExitProcess(%u) from %08X", ARG(0), g_cur_func);
    void_process_exit(ARG(0), 1);
    return 0;
}

WINAPI_EXPORT(K32, TerminateProcess, 2)
{
    void_log("[void] TerminateProcess(%08X, %u) from %08X", ARG(0), ARG(1), g_cur_func);
    if (ARG(0) == 0xFFFFFFFFu) void_process_exit(ARG(1), 0);
    return 0;
}

WINAPI_EXPORT(K32, GetExitCodeProcess, 2)
{
    if (ARG(1)) MEM32(ARG(1)) = 259u;
    return 1;
}

static uint32_t create_process_failed(const char *app, const char *cmd)
{
    void_log("[void] CreateProcess(%s, %s) refused: no child processes on Android",
        app ? app : "(null)", cmd ? cmd : "(null)");
    void_set_last_error(ERROR_FILE_NOT_FOUND_);
    return 0;
}

WINAPI_EXPORT(K32, CreateProcessA, 10)
{
    char *a = void_astr_utf8(ARG(0)), *c = void_astr_utf8(ARG(1));
    uint32_t r = create_process_failed(a, c);
    free(a); free(c);
    return r;
}

WINAPI_EXPORT(K32, CreateProcessW, 10)
{
    char *a = void_wstr_utf8(ARG(0)), *c = void_wstr_utf8(ARG(1));
    uint32_t r = create_process_failed(a, c);
    free(a); free(c);
    return r;
}

WINAPI_EXPORT(K32, CreatePipe, 4)
{
    void_log("[void] CreatePipe refused (caller %08X)", g_cur_func);
    void_set_last_error(ERROR_NOT_SUPPORTED_);
    return 0;
}

/* RtlUnwind(TargetFrame, TargetIp, ExceptionRecord, ReturnValue): C++ frames
 * are unwound by the host dispatcher; this only drops SEH records above the
 * target, which is what the CRT's local/global unwind helpers ask for. */
WINAPI_EXPORT(K32, RtlUnwind, 4)
{
    uint32_t target = ARG(0);
    uint32_t rec = MEM32(g_fs_base);
    while (rec && rec != 0xFFFFFFFFu && rec != target) rec = MEM32(rec);
    VLOG("[void] RtlUnwind to %08X from %08X", target, g_cur_func);
    MEM32(g_fs_base) = target ? target : 0xFFFFFFFFu;
    g_eax = ARG(3);
    return ARG(3);
}
