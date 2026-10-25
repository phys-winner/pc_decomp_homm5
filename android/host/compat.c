/* Win32 desktop metrics and the small VC7.1/MFC startup surface used by Heroes. */
#include "host.h"
#include "input.h"
#include <string.h>

static uint32_t device_cap(uint32_t index, int width, int height)
{
    switch (index) {
    case 0: return 0x400;                 /* DRIVERVERSION */
    case 2: return 1;                     /* DT_RASDISPLAY */
    case 4: return (uint32_t)width * 254 / 960;   /* HORZSIZE, millimetres at 96 DPI */
    case 6: return (uint32_t)height * 254 / 960;
    case 8: case 118: return (uint32_t)width;     /* HORZRES / DESKTOPHORZRES */
    case 10: case 117: return (uint32_t)height;
    case 12: return 32;                   /* BITSPIXEL */
    case 14: return 1;                    /* PLANES */
    case 24: return 0xFFFFFFFFu;          /* NUMCOLORS: true colour */
    case 38: return 0x2A01;               /* RC_BITBLT | RC_DIBTODEV | RC_STRETCHBLT | RC_STRETCHDIB */
    case 40: case 42: return 36;          /* ASPECTX / ASPECTY */
    case 44: return 51;                   /* ASPECTXY */
    case 88: case 90: return 96;          /* LOGPIXELSX / LOGPIXELSY */
    case 108: return 24;                  /* COLORRES */
    case 116: return 60;                  /* VREFRESH */
    case 119: return 3;                   /* SB_CONST_ALPHA | SB_PIXEL_ALPHA */
    default: return 0;
    }
}

WINAPI_EXPORT("gdi32.dll", GetDeviceCaps, 2)
{
    if (!ARG(0)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    int width, height;
    void_input_screen_size(&width, &height);
    return device_cap(ARG(1), width, height);
}

static const uint32_t system_colors[] = {
    0xC8C8C8, 0x000000, 0x800000, 0x808080, 0xC0C0C0, 0xFFFFFF, 0x000000, 0x000000,
    0x000000, 0xFFFFFF, 0xC0C0C0, 0xC0C0C0, 0x808080, 0x800000, 0xFFFFFF, 0xC0C0C0,
    0x808080, 0x808080, 0x000000, 0xC0C0C0, 0xFFFFFF, 0x000000, 0xDFDFDF, 0x000000,
    0xE1FFFF, 0x000000, 0xFF0000, 0xD1B499, 0xDBCDBF, 0xF0F0F0, 0xF0F0F0,
};
WINAPI_EXPORT("user32.dll", GetSysColor, 1)
{
    return ARG(0) < sizeof system_colors / sizeof system_colors[0] ? system_colors[ARG(0)] : 0;
}
WINAPI_EXPORT("user32.dll", GetSysColorBrush, 1)
{
    return ARG(0) < sizeof system_colors / sizeof system_colors[0] ? 0x00050080u + ARG(0) : 0;
}

static uint32_t error_mode;
WINAPI_EXPORT("kernel32.dll", SetErrorMode, 1) { uint32_t old = error_mode; error_mode = ARG(0); return old; }
WINAPI_EXPORT("kernel32.dll", lstrlenA, 1) { return ARG(0) ? (uint32_t)void_gstrlen(ARG(0)) : 0; }
WINAPI_EXPORT("kernel32.dll", lstrcmpA, 2)
{
    int result = strcmp((const char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1)));
    return (uint32_t)((result > 0) - (result < 0));
}
WINAPI_EXPORT("kernel32.dll", lstrcpyA, 2) { strcpy((char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1))); return ARG(0); }
WINAPI_EXPORT("kernel32.dll", lstrcatA, 2) { strcat((char *)GPTR(ARG(0)), (const char *)GPTR(ARG(1))); return ARG(0); }
WINAPI_EXPORT("kernel32.dll", lstrcpynA, 3)
{
    if ((int32_t)ARG(2) > 0) {
        size_t length = void_gstrlen(ARG(1));
        if (length >= ARG(2)) length = ARG(2) - 1;
        memmove(GPTR(ARG(0)), GPTR(ARG(1)), length);
        MEM8(ARG(0) + (uint32_t)length) = 0;
    }
    return ARG(0);
}

static uint32_t current_directory(int wide)
{
    char path[1024];
    void_cwd_get(path, sizeof path);
    uint32_t need = wide ? void_utf8_to_gw(path, 0, 0) : void_utf8_to_ga(path, 0, 0);
    if (ARG(0) < need) return need;
    return wide ? void_utf8_to_gw(path, ARG(1), ARG(0)) : void_utf8_to_ga(path, ARG(1), ARG(0));
}
WINAPI_EXPORT("kernel32.dll", GetCurrentDirectoryA, 2) { return current_directory(0); }
WINAPI_EXPORT("kernel32.dll", GetCurrentDirectoryW, 2) { return current_directory(1); }
static uint32_t set_directory(int wide)
{
    char *path = wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0));
    int ok = path && void_cwd_set(path);
    free(path);
    if (!ok) void_set_last_error(ERROR_PATH_NOT_FOUND_);
    return (uint32_t)ok;
}
WINAPI_EXPORT("kernel32.dll", SetCurrentDirectoryA, 1) { return set_directory(0); }
WINAPI_EXPORT("kernel32.dll", SetCurrentDirectoryW, 1) { return set_directory(1); }

static uint32_t local_realloc(void)
{
    if (ARG(2) & 0x80u) return void_heap_size(void_process_heap(), ARG(0)) != 0xFFFFFFFFu ? ARG(0) : 0;
    return void_heap_realloc(void_process_heap(), ARG(0), ARG(1) ? ARG(1) : 1, (ARG(2) & 0x40u) != 0, 0);
}
WINAPI_EXPORT("kernel32.dll", GlobalReAlloc, 3) { return local_realloc(); }
WINAPI_EXPORT("kernel32.dll", LocalReAlloc, 3) { return local_realloc(); }
WINAPI_EXPORT("kernel32.dll", GlobalHandle, 1) { return void_heap_size(void_process_heap(), ARG(0)) != 0xFFFFFFFFu ? ARG(0) : 0; }
WINAPI_EXPORT("kernel32.dll", GlobalFlags, 1) { return void_heap_size(void_process_heap(), ARG(0)) != 0xFFFFFFFFu ? 0 : 0x8000u; }
