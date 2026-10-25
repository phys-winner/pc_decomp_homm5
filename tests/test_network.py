"""Exercise the real WinSock exports (android/host/network.c) on the device.

network.c maps WinSock onto POSIX sockets, so the probe is the actual source
with its actual stdcall entry macros, built for ARM64 Android with the NDK and
run on the selected device over adb (skipped without ANDROID_SERIAL). Everything stays on the
loopback interface: no broadcast leaves the device.
"""
import re
import os
import subprocess
import unittest
from test_static_tls import ROOT
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

SERIAL = os.environ.get("HOMM5_SERIAL") or os.environ.get("ANDROID_SERIAL")
CLANG = str(TOOLCHAIN / 'bin/clang.exe')

HARNESS = r'''
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#define GUEST_PAGE 0x1000u
static uint8_t memory[0x20000];
#define GPTR(va) ((void *)(memory + (va)))
#define MEM8(va) (*(uint8_t *)GPTR(va))
#define MEM16(va) (*(uint16_t *)GPTR(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
static __thread uint32_t g_esp, g_eax, g_edx;
#define ARG(n) MEM32(g_esp + 4u + 4u * (uint32_t)(n))
typedef void (*void_fn)(void);
typedef struct { const char *dll, *name; uint32_t ordinal; void_fn fn; } void_shim;
#define VOID_SHIM_SECTION
#include "exports.h"
static int void_verbose;
static void void_log(const char *format, ...) { (void)format; }
#define VLOG(...) do { if (void_verbose) void_log(__VA_ARGS__); } while (0)
static int void_vm_readable(uint32_t va, uint32_t size) { return va >= 0x100 && (uint64_t)va + size <= sizeof memory; }
static int void_vm_writable(uint32_t va, uint32_t size) { return void_vm_readable(va, size); }
static void void_blocking_begin(void) {}
static void void_blocking_end(void) {}
static uint32_t next_allocation = 0x18000;
static uint32_t void_galloc(uint32_t size) { uint32_t at = next_allocation; next_allocation += (size + 15u) & ~15u; return at; }
#include "network.h"

static unsigned checks;
/* A stdcall call through the export's entry: arguments on the guest stack,
   the callee pops them and leaves the result in eax, edx untouched. */
static uint32_t call(void_fn fn, unsigned count, const uint32_t *values) {
    uint32_t base = 0x1000;
    g_esp = base; g_eax = 0x87654321; g_edx = 0x12345678;
    MEM32(g_esp) = 0xDEADBEEF;
    for (unsigned i = 0; i < count; ++i) MEM32(g_esp + 4 + 4 * i) = values[i];
    fn();
    assert(g_esp == base + 4 + 4 * count && g_edx == 0x12345678 && MEM32(base) == 0xDEADBEEF);
    ++checks; return g_eax;
}
#define CALL(name, ...) call(name##_entry, sizeof((uint32_t[]){__VA_ARGS__}) / 4, (uint32_t[]){__VA_ARGS__})
#define CALL0(name) call(name##_entry, 0, NULL)
static uint32_t error(void) { return CALL0(WSAGetLastError_ws2); }

/* A sockaddr_in at a guest address: the Windows and Linux layouts agree. */
static void address(uint32_t at, uint32_t ip, uint16_t port) {
    memset(GPTR(at), 0, 16); MEM16(at) = 2; MEM16(at + 2) = htons(port); MEM32(at + 4) = ip;
}

static void *thread_error(void *unused) {
    (void)unused; assert(error() == 0);
    CALL(WSASetLastError_ws2, 10054); assert(error() == 10054);
    return NULL;
}

int main(void) {
    /* Export names and ordinals of ws2_32 and wsock32. */
    assert(WSAStartup_ws2_shim.ordinal == 115 && !strcmp(WSAStartup_ws2_shim.name, "WSAStartup"));
    assert(inet_addr_ws2_shim.ordinal == 11 && inet_addr_wsock_shim.ordinal == 10);
    assert(inet_ntoa_ws2_shim.ordinal == 12 && inet_ntoa_wsock_shim.ordinal == 11);
    assert(ioctlsocket_ws2_shim.ordinal == 10 && ioctlsocket_wsock_shim.ordinal == 12);
    assert(WSAFDIsSet_ws2_shim.ordinal == 151 && !strcmp(WSAFDIsSet_ws2_shim.name, "__WSAFDIsSet"));

    /* Startup: version 2.2 and a filled WSADATA. */
    memset(GPTR(0x2000), 0xA5, 512);
    assert(CALL(WSAStartup_ws2, 0x202, 0x2000) == 0 && MEM16(0x2000) == 0x202 && MEM16(0x2002) == 0x202);
    assert(CALL(WSAStartup_wsock, 0x101, 0x2000) == 0);

    /* Byte orders, addresses as text. */
    const uint32_t orders[] = {0, 1, 0x1234, 0xFFFF, 0x12345678, UINT32_MAX};
    for (unsigned i = 0; i < sizeof orders / sizeof orders[0]; ++i) {
        uint32_t x = orders[i];
        assert(CALL(htons_ws2, x) == (uint32_t)htons((uint16_t)x) && CALL(ntohs_wsock, x) == (uint32_t)ntohs((uint16_t)x));
        assert(CALL(htonl_wsock, x) == htonl(x) && CALL(ntohl_ws2, x) == ntohl(x));
    }
    strcpy((char *)GPTR(0x4000), "127.0.0.1"); assert(CALL(inet_addr_ws2, 0x4000) == 0x0100007F);
    strcpy((char *)GPTR(0x4000), "192.168.1.2"); assert(CALL(inet_addr_wsock, 0x4000) == 0x0201A8C0);
    strcpy((char *)GPTR(0x4000), "not an address"); assert(CALL(inet_addr_ws2, 0x4000) == UINT32_MAX);
    assert(CALL(inet_addr_ws2, 0) == UINT32_MAX && error() == 10014);
    uint32_t text = CALL(inet_ntoa_ws2, 0x0100007F);
    assert(text && !strcmp((char *)GPTR(text), "127.0.0.1"));

    /* Unknown handles. */
    assert(CALL(closesocket_ws2, 0x1234) == UINT32_MAX && error() == 10038);
    assert(CALL(send_ws2, 0x1234, 0x2000, 4, 0) == UINT32_MAX && error() == 10038);

    /* UDP on the loopback: bind, name, sendto, select, peek, receive. */
    uint32_t a = CALL(socket_ws2, 2, 2, 17), b = CALL(socket_ws2, 2, 2, 17);
    assert(a != UINT32_MAX && b != UINT32_MAX && a != b);
    address(0x3000, htonl(INADDR_LOOPBACK), 0);
    assert(CALL(bind_ws2, a, 0x3000, 16) == 0);
    MEM32(0x3020) = 16; assert(CALL(getsockname_ws2, a, 0x3010, 0x3020) == 0 && MEM32(0x3020) == 16);
    uint16_t port = ntohs(MEM16(0x3012));
    assert(MEM16(0x3010) == 2 && port && MEM32(0x3014) == htonl(INADDR_LOOPBACK));
    /* Nothing yet: a zero-timeout select finds no reader. */
    MEM32(0x3100) = 1; MEM32(0x3104) = a; MEM32(0x3200) = 0; MEM32(0x3204) = 0;
    assert(CALL(select_ws2, 0, 0x3100, 0, 0, 0x3200) == 0 && MEM32(0x3100) == 0);
    memcpy(GPTR(0x5000), "heroes of might and magic", 25);
    address(0x3030, htonl(INADDR_LOOPBACK), port);
    assert(CALL(sendto_ws2, b, 0x5000, 25, 0, 0x3030, 16) == 25);
    MEM32(0x3100) = 1; MEM32(0x3104) = a; MEM32(0x3200) = 1; MEM32(0x3204) = 0;
    assert(CALL(select_ws2, 0, 0x3100, 0, 0, 0x3200) == 1 && MEM32(0x3100) == 1 && MEM32(0x3104) == a);
    assert(CALL(WSAFDIsSet_ws2, a, 0x3100) == 1 && CALL(WSAFDIsSet_ws2, b, 0x3100) == 0);
    MEM32(0x3300) = 0; assert(CALL(ioctlsocket_ws2, a, 0x4004667Fu, 0x3300) == 0 && MEM32(0x3300) >= 25);   /* FIONREAD */
    /* A buffer too small for the datagram: WSAEMSGSIZE; peeked, it stays queued. */
    assert(CALL(recvfrom_ws2, a, 0x6000, 8, 2, 0, 0) == UINT32_MAX && error() == 10040);
    MEM32(0x3044) = 16; memset(GPTR(0x6000), 0, 64);
    assert(CALL(recvfrom_ws2, a, 0x6000, 64, 0, 0x3040, 0x3044) == 25);
    assert(!memcmp(GPTR(0x6000), "heroes of might and magic", 25) && MEM16(0x3040) == 2 && MEM32(0x3044) == 16);
    /* Non-blocking: an empty queue answers WSAEWOULDBLOCK. */
    MEM32(0x3300) = 1; assert(CALL(ioctlsocket_ws2, a, 0x8004667Eu, 0x3300) == 0);                       /* FIONBIO */
    assert(CALL(recv_ws2, a, 0x6000, 64, 0) == UINT32_MAX && error() == 10035);
    /* Options: SO_BROADCAST round trip, a socket's type. */
    MEM32(0x3400) = 1; assert(CALL(setsockopt_ws2, b, 0xFFFF, 0x20, 0x3400, 4) == 0);
    MEM32(0x3404) = 4; MEM32(0x3408) = 0; assert(CALL(getsockopt_ws2, b, 0xFFFF, 0x20, 0x3408, 0x3404) == 0 && MEM32(0x3408));
    MEM32(0x3404) = 4; assert(CALL(getsockopt_ws2, b, 0xFFFF, 0x1008, 0x3408, 0x3404) == 0 && MEM32(0x3408) == 2);   /* SO_TYPE: dgram */
    assert(CALL(closesocket_ws2, a) == 0 && CALL(closesocket_wsock, b) == 0);
    assert(CALL(closesocket_ws2, a) == UINT32_MAX && error() == 10038);

    /* TCP on the loopback: listen, connect, accept, both directions, shutdown. */
    uint32_t server = CALL(socket_ws2, 2, 1, 6), client = CALL(socket_ws2, 2, 1, 6);
    address(0x3000, htonl(INADDR_LOOPBACK), 0);
    assert(CALL(bind_ws2, server, 0x3000, 16) == 0 && CALL(listen_ws2, server, 4) == 0);
    MEM32(0x3020) = 16; assert(CALL(getsockname_ws2, server, 0x3010, 0x3020) == 0);
    address(0x3030, htonl(INADDR_LOOPBACK), ntohs(MEM16(0x3012)));
    assert(CALL(connect_ws2, client, 0x3030, 16) == 0);
    MEM32(0x3044) = 16; uint32_t peer = CALL(accept_ws2, server, 0x3040, 0x3044);
    assert(peer != UINT32_MAX && MEM16(0x3040) == 2 && MEM32(0x3044) == 16);
    assert(CALL(send_ws2, client, 0x5000, 6, 0) == 6);
    memset(GPTR(0x6000), 0, 64);
    assert(CALL(recv_ws2, peer, 0x6000, 64, 0) == 6 && !memcmp(GPTR(0x6000), "heroes", 6));
    assert(CALL(send_ws2, peer, 0x5000 + 10, 5, 0) == 5 && CALL(recv_ws2, client, 0x6000, 64, 0) == 5);
    MEM32(0x3020) = 16; assert(CALL(getpeername_ws2, client, 0x3010, 0x3020) == 0 && MEM32(0x3014) == htonl(INADDR_LOOPBACK));
    assert(CALL(shutdown_ws2, client, 1) == 0 && CALL(recv_ws2, peer, 0x6000, 64, 0) == 0);   /* orderly end */
    assert(CALL(closesocket_ws2, peer) == 0 && CALL(closesocket_ws2, client) == 0 && CALL(closesocket_ws2, server) == 0);

    /* The machine's name resolves to its own addresses. */
    assert(CALL(gethostname_ws2, 0x7000, 256) == 0 && strlen((char *)GPTR(0x7000)) > 0);
    uint32_t entry = CALL(gethostbyname_ws2, 0x7000);
    assert(entry && MEM16(entry + 8) == 2 && MEM16(entry + 10) == 4 && MEM32(MEM32(entry + 12)));

    /* Per-thread errors. */
    CALL(WSASetLastError_ws2, 10022);
    pthread_t thread; assert(!pthread_create(&thread, NULL, thread_error, NULL) && !pthread_join(thread, NULL));
    assert(error() == 10022);
    assert(CALL0(WSACleanup_ws2) == 0);
    printf("PASS WinSock on POSIX: %u stdcall checks, UDP select/peek/EMSGSIZE/nonblocking, TCP loopback, names, per-thread errors\n", checks);
    return 0;
}
'''


def device_ready():
    if not SERIAL:
        return False
    try:
        state = subprocess.run(["adb", "-s", SERIAL, "get-state"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return state.returncode == 0 and state.stdout.strip() == "device"


class NetworkTest(unittest.TestCase):
    @unittest.skipUnless(device_ready(), "set ANDROID_SERIAL to a connected Android device")
    def test_winsock_on_posix_device(self):
        out = ROOT / "build/tests/network"
        out.mkdir(parents=True, exist_ok=True)
        source = (ROOT / "android/host/network.c").read_text(encoding="utf-8")
        source = re.sub(r"^#include[^\n]*\n", "", source, flags=re.M)
        host = (ROOT / "android/host/host.h").read_text(encoding="utf-8")
        macros = []
        for name in ("WINAPI_EXPORT(", "WINAPI_EXPORT_AS("):
            start = host.index("#define " + name)
            macros.append(host[start:host.index("\n\n", start)])
        (out / "network.h").write_text(source, encoding="utf-8")
        (out / "exports.h").write_text("\n".join(macros), encoding="utf-8")
        (out / "probe.c").write_text(HARNESS, encoding="utf-8")
        built = subprocess.run([CLANG, "--target=aarch64-linux-android30", "-O2", "-Wall", "-Werror",
                                "-Wno-unused-function", "-Wno-unused-variable", "-static", "-o", "probe", "probe.c"],
                               cwd=out, capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        remote = "/data/local/tmp/homm5-network-probe"
        pushed = subprocess.run(["adb", "-s", SERIAL, "push", str(out / "probe"), remote], capture_output=True, text=True)
        self.assertEqual(pushed.returncode, 0, pushed.stdout + pushed.stderr)
        ran = subprocess.run(["adb", "-s", SERIAL, "shell", f"chmod 755 {remote} && {remote}; echo exit=$?; rm -f {remote}"],
                             capture_output=True, text=True, timeout=60)
        self.assertIn("exit=0", ran.stdout, ran.stdout + ran.stderr)
        self.assertIn("PASS WinSock on POSIX", ran.stdout)
        print(ran.stdout.strip().splitlines()[0])


if __name__ == "__main__":
    unittest.main()
