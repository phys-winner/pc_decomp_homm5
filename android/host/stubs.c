/* Win32 imports the game links but this host only needs in their failing or
 * trivial form: clipboard, dialogs, GDI painting, profile INI files, window
 * flashing. Each reports the documented failure (or success for hints such as
 * affinity), so a rarely taken path continues instead of trapping. */
#include "host.h"
#include <string.h>

#define K32 "kernel32.dll"
#define U32 "user32.dll"
#define GDI "gdi32.dll"

/* ------------------------------------------------------------ kernel32 */

/* Network server lists (offline port): the default string, as for a missing file. */
WINAPI_EXPORT(K32, GetPrivateProfileStringA, 6)
{
    uint32_t fallback = ARG(2), out = ARG(3), size = ARG(4);
    if (!out || !size || !void_vm_writable(out, size)) return 0;
    uint32_t n = 0;
    if (fallback) {
        size_t len = void_gstrlen(fallback);
        n = (uint32_t)(len < size - 1 ? len : size - 1);
        memcpy(GPTR(out), GPTR(fallback), n);
    }
    MEM8(out + n) = 0;
    void_set_last_error(2u);              /* ERROR_FILE_NOT_FOUND */
    return n;
}

WINAPI_EXPORT(K32, GetPrivateProfileIntA, 4) { return ARG(2); }

/* OFSTRUCT-based OpenFile only feeds an entropy pool here: report no file. */
WINAPI_EXPORT(K32, OpenFile, 3)
{
    void_set_last_error(2u);
    return 0xFFFFFFFFu;                   /* HFILE_ERROR */
}

WINAPI_EXPORT(K32, SetProcessAffinityMask, 2) { return 1; }
WINAPI_EXPORT(K32, VirtualLock, 2) { return 1; }

WINAPI_EXPORT(K32, DeviceIoControl, 8)
{
    void_set_last_error(50u);             /* ERROR_NOT_SUPPORTED */
    return 0;
}

WINAPI_EXPORT(K32, FatalExit, 1)
{
    void_fatal("FatalExit(%u)", ARG(0));
}

/* ------------------------------------------------------------- user32 */
WINAPI_EXPORT(U32, OpenClipboard, 1) { void_set_last_error(5u); return 0; }
WINAPI_EXPORT(U32, CloseClipboard, 0) { return 1; }
WINAPI_EXPORT(U32, EmptyClipboard, 0) { return 0; }
WINAPI_EXPORT(U32, IsClipboardFormatAvailable, 1) { return 0; }
WINAPI_EXPORT(U32, GetClipboardData, 1) { return 0; }
WINAPI_EXPORT(U32, SetClipboardData, 2) { return 0; }

/* The splash fader's timer: without WM_TIMER its loop ends on the next quit. */
WINAPI_EXPORT(U32, SetTimer, 4) { return 0; }

WINAPI_EXPORT(U32, DialogBoxParamA, 5) { return 0xFFFFFFFFu; }
WINAPI_EXPORT(U32, EndDialog, 2) { return 1; }
WINAPI_EXPORT(U32, GetDlgItem, 2) { return 0; }
WINAPI_EXPORT(U32, SetDlgItemTextA, 3) { return 0; }
WINAPI_EXPORT(U32, CheckDlgButton, 3) { return 0; }
WINAPI_EXPORT(U32, IsDlgButtonChecked, 2) { return 0; }
WINAPI_EXPORT(U32, FlashWindowEx, 1) { return 0; }

WINAPI_EXPORT(U32, BeginPaint, 2)
{
    if (ARG(1) && void_vm_writable(ARG(1), 64)) memset(GPTR(ARG(1)), 0, 64);
    return 0;
}
WINAPI_EXPORT(U32, EndPaint, 2) { return 1; }
WINAPI_EXPORT(U32, GetUpdateRect, 3)
{
    if (ARG(1) && void_vm_writable(ARG(1), 16)) memset(GPTR(ARG(1)), 0, 16);
    return 0;
}

/* -------------------------------------------------------------- gdi32 */
WINAPI_EXPORT(GDI, BitBlt, 9) { return 0; }
WINAPI_EXPORT(GDI, RealizePalette, 1) { return 0xFFFFFFFFu; }   /* GDI_ERROR */
WINAPI_EXPORT(GDI, SelectPalette, 3) { return 0; }
WINAPI_EXPORT(GDI, CreateCompatibleDC, 1) { return 0; }
WINAPI_EXPORT(GDI, CreateHalftonePalette, 1) { return 0; }
WINAPI_EXPORT(GDI, CreatePalette, 1) { return 0; }
WINAPI_EXPORT(GDI, GetDIBColorTable, 4) { return 0; }
WINAPI_EXPORT(GDI, GetObjectA, 3) { return 0; }
WINAPI_EXPORT(GDI, DeleteDC, 1) { return 0; }

/* ------------------------------------------------------------ shell32 */
/* The account web site link: no browser hand-off from the guest. */
WINAPI_EXPORT("shell32.dll", ShellExecuteA, 6) { return 2; }   /* <= 32: failure */

/* InitCommonControls (comctl32 ordinal 17) has nothing to register here. */
WINAPI_ORDINAL("comctl32.dll", InitCommonControls, 17, 0) { return 0; }
