/* The Ubisoft network layer's log (NUbi: the LAN and ubi.com matchmaking).
 *
 * Its state machines describe every step in one wide-string line logger: the
 * line is built in a global buffer and handed, with the time in front, to
 * 0x008CD870, which writes it to a log stream when one is open (never in the
 * shipped game) and clears the buffer. With verbose logging the port copies
 * each line to its own log first: "init succeeded", "connecting NetDriver at",
 * "checksums does not match, host checksum=..., client checksum=..." and so
 * on. The body is a NATIVE_OVERRIDE of tools/build_android.py. */
#include "host.h"
#include <stdio.h>
#include <string.h>
#include <unistd.h>

void sub_008CD870_lifted(void);
void sub_0081F500_lifted(void);
void sub_0081F670_lifted(void);

/* thiscall(the line buffer: wchar begin, end, ...), RET. */
void sub_008CD870(void)
{
    if (void_verbose) {
        uint32_t line = g_ecx, begin = MEM32(line), end = MEM32(line + 4);
        if (end > begin && end - begin < 8192 && void_vm_readable(begin, end - begin)) {
            char text[1024];
            size_t n = 0;
            for (uint32_t p = begin; p + 1 < end && n + 1 < sizeof text; p += 2) {
                uint16_t c = MEM16(p);
                if (c == '\r' || c == '\n') continue;
                text[n++] = c >= 32 && c < 127 ? (char)c : '?';
            }
            text[n] = 0;
            /* "Tue Oct 21 05:12:34 2026: NUbi::...": the port's log has its own time. */
            const char *from = strstr(text, "NUbi::");
            void_log("[nubi] %s", from ? from : text);
            /* With a "dump_guest" file in the user data, a checksum mismatch
               leaves the guest heaps for tools/lan_checksum_diff.py (once). */
            char trigger[512], dump[512];
            snprintf(trigger, sizeof trigger, "%s/dump_guest", void_data_dir());
            if (strstr(text, "checksums does not match") && !access(trigger, F_OK) && !unlink(trigger)) {
                snprintf(dump, sizeof dump, "%s/guest_rw.dump", void_data_dir());
                void_log("[lan] guest memory dump %s: %d MiB", dump, void_vm_dump(dump));
            }
        }
    }
    sub_008CD870_lifted();
}

/* The LAN game checksum a client must share with the host (UI 0x006F77C0):
 * adler32 over the CalcCheckSum of fourteen GameMechanics reference tables
 * (0x0081F670, one table each through 0x0081F500), xor the map's. Verbose
 * logging shows every table's value to compare with another installation. */
static void guest_text(uint32_t string, char *out, size_t size)
{
    size_t n = 0;
    out[0] = 0;
    if (!void_vm_readable(string, 8)) return;
    uint32_t begin = MEM32(string), end = MEM32(string + 4);
    if (begin && end > begin && end - begin < 512 && void_vm_readable(begin, end - begin))
        for (uint32_t p = begin; p < end && MEM8(p) && n + 1 < size; ++p) out[n++] = (char)MEM8(p);
    out[n] = 0;
}

/* fastcall(ecx: the table's xdb path, edx: its type name), RET: its checksum. */
void sub_0081F500(void)
{
    char type[96] = "", path[160] = "";
    if (void_verbose) {
        guest_text(g_ecx, path, sizeof path);
        guest_text(g_edx, type, sizeof type);
    }
    sub_0081F500_lifted();
    VLOG("[lan] checksum %08X %s (%s)", g_eax, path, type);
}

/* RET: the reference tables' checksum. */
void sub_0081F670(void)
{
    sub_0081F670_lifted();
    VLOG("[lan] game data checksum %08X (x87 control word %04X)", g_eax, g_fpu_cw);
}
