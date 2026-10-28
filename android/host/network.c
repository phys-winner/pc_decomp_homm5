/* WinSock (wsock32.dll, ws2_32.dll) and GetAdaptersInfo on POSIX sockets.
 *
 * H5's network layer (0x00D816A0..0x00D82710) wraps WSOCK32: UDP sockets for
 * the LAN game and its discovery, TCP clients with non-blocking connects,
 * select, MSG_PEEK receives that grow their buffer on WSAEMSGSIZE, the
 * interface list (SIO_GET_INTERFACE_LIST) to pick its LAN address, and
 * gethostbyname(gethostname()) for its own address. Windows semantics kept
 * here: guest SOCKET handles of their own, WSA error codes per thread,
 * sockaddr_in as laid out on both, fd_set as {count, SOCKET[64]} rewritten in
 * place, a truncated datagram reported as WSAEMSGSIZE, a failed non-blocking
 * connect reported by select as an exception rather than writable, and the
 * machine's own name resolving to its LAN addresses. Calls that wait release
 * the guest machine. */
#include "host.h"
#if defined(VOID_ANDROID_APP) && !defined(HOMM5_LEGACY_UI)
#include <jni.h>
#endif
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define WSA_EINTR 10004u
#define WSA_EBADF 10009u
#define WSA_EACCES 10013u
#define WSA_EFAULT 10014u
#define WSA_EINVAL 10022u
#define WSA_EMFILE 10024u
#define WSA_EWOULDBLOCK 10035u
#define WSA_EALREADY 10037u
#define WSA_ENOTSOCK 10038u
#define WSA_EMSGSIZE 10040u
#define WSA_ENOPROTOOPT 10042u
#define WSA_EOPNOTSUPP 10045u
#define WSA_EAFNOSUPPORT 10047u
#define WSA_ENOBUFS 10055u
#define WSA_NOTINITIALISED 10093u
#define WSA_HOST_NOT_FOUND 11001u

static __thread uint32_t socket_error;
static __thread uint32_t address_text, host_entry;

/* ------------------------------------------------------------- sockets */

#define NET_SOCKETS 256
#define NET_HANDLE_BASE 0x4000u            /* guest SOCKET = base + 4 * slot */
#define NET_PEERS 8

/* A datagram socket's recent remote senders (see echo_broadcast). */
typedef struct { uint32_t address; uint16_t port; uint64_t heard_ms; } net_peer;

static struct {
    int used, fd, type, nonblocking, connecting;
    net_peer peers[NET_PEERS];
    uint64_t swept_ms;                      /* the last subnet sweep (echo_broadcast) */
} sockets[NET_SOCKETS];
static pthread_mutex_t net_lock = PTHREAD_MUTEX_INITIALIZER;
static int net_started;

static uint32_t fail(uint32_t error) { socket_error = error; return UINT32_MAX; }

static uint32_t wsa_error(int e)
{
    switch (e) {
    case EAGAIN: case EINPROGRESS: return WSA_EWOULDBLOCK;   /* a pending non-blocking connect too */
    case EALREADY: return WSA_EALREADY;
    case ENOTSOCK: return WSA_ENOTSOCK;
    case EBADF: return WSA_ENOTSOCK;
    case EDESTADDRREQ: return 10039u;
    case EMSGSIZE: return WSA_EMSGSIZE;
    case EPROTOTYPE: return 10041u;
    case ENOPROTOOPT: return WSA_ENOPROTOOPT;
    case EPROTONOSUPPORT: return 10043u;
    case EOPNOTSUPP: return WSA_EOPNOTSUPP;
    case EAFNOSUPPORT: return WSA_EAFNOSUPPORT;
    case EADDRINUSE: return 10048u;
    case EADDRNOTAVAIL: return 10049u;
    case ENETDOWN: return 10050u;
    case ENETUNREACH: return 10051u;
    case ENETRESET: return 10052u;
    case ECONNABORTED: return 10053u;
    case ECONNRESET: case EPIPE: return 10054u;
    case ENOBUFS: case ENOMEM: return WSA_ENOBUFS;
    case EISCONN: return 10056u;
    case ENOTCONN: return 10057u;
    case ESHUTDOWN: return 10058u;
    case ETIMEDOUT: return 10060u;
    case ECONNREFUSED: return 10061u;
    case EHOSTDOWN: return 10064u;
    case EHOSTUNREACH: return 10065u;
    case EACCES: case EPERM: return WSA_EACCES;
    case EFAULT: return WSA_EFAULT;
    case EINTR: return WSA_EINTR;
    case EMFILE: case ENFILE: return WSA_EMFILE;
    default: return WSA_EINVAL;
    }
}

static uint32_t fail_errno(void) { return fail(wsa_error(errno)); }

static int slot_of(uint32_t s)
{
    if (s < NET_HANDLE_BASE || (s - NET_HANDLE_BASE) % 4u || (s - NET_HANDLE_BASE) / 4u >= NET_SOCKETS) return -1;
    int slot = (int)((s - NET_HANDLE_BASE) / 4u);
    return sockets[slot].used ? slot : -1;
}

/* The socket's descriptor, or -1 with WSAENOTSOCK set. */
static int socket_fd(uint32_t s, int *slot_out)
{
    pthread_mutex_lock(&net_lock);
    int slot = slot_of(s), fd = slot >= 0 ? sockets[slot].fd : -1;
    pthread_mutex_unlock(&net_lock);
    if (fd < 0) socket_error = WSA_ENOTSOCK;
    if (slot_out) *slot_out = slot;
    return fd;
}

static uint32_t socket_new(int fd, int type)
{
    pthread_mutex_lock(&net_lock);
    for (int i = 0; i < NET_SOCKETS; ++i) {
        if (sockets[i].used) continue;
        sockets[i].used = 1;
        sockets[i].fd = fd;
        sockets[i].type = type;
        sockets[i].nonblocking = 0;
        sockets[i].connecting = 0;
        memset(sockets[i].peers, 0, sizeof sockets[i].peers);
        sockets[i].swept_ms = 0;
        pthread_mutex_unlock(&net_lock);
        return NET_HANDLE_BASE + 4u * (uint32_t)i;
    }
    pthread_mutex_unlock(&net_lock);
    close(fd);
    return fail(WSA_EMFILE);
}

static int is_blocking(int slot) { return slot >= 0 && !sockets[slot].nonblocking; }

/* ------------------------------------------------------------ addresses */

static uint32_t address_to_text(uint32_t address)
{
    if (!address_text) address_text = void_galloc(INET_ADDRSTRLEN);
    if (!address_text) { socket_error = WSA_ENOBUFS; return 0; }
    struct in_addr in;
    in.s_addr = address;
    if (inet_ntop(AF_INET, &in, GPTR(address_text), INET_ADDRSTRLEN)) return address_text;
    socket_error = WSA_EINVAL; return 0;
}

/* A NUL-terminated guest string within readable memory, or NULL. */
static const char *guest_text(uint32_t text)
{
    if (!text) return NULL;
    for (uint32_t at = text;;) {
        uint32_t size = GUEST_PAGE - (at & (GUEST_PAGE - 1));
        if (!void_vm_readable(at, size)) return NULL;
        if (memchr(GPTR(at), 0, size)) return (const char *)GPTR(text);
        if ((uint64_t)at + size > UINT32_MAX) return NULL;
        at += size;
    }
}

static uint32_t address_from_text(uint32_t text)
{
    const char *s = guest_text(text);
    if (s) return inet_addr(s);
    socket_error = WSA_EFAULT; return UINT32_MAX;
}

/* Windows and Linux lay sockaddr_in out alike: family (2 on both), port and
 * address in network order, eight zeros. */
static int sockaddr_from_guest(uint32_t name, uint32_t length, struct sockaddr_in *out)
{
    if (!name || (int32_t)length < (int32_t)sizeof *out || !void_vm_readable(name, sizeof *out)) {
        socket_error = WSA_EFAULT;
        return 0;
    }
    memcpy(out, GPTR(name), sizeof *out);
    if (out->sin_family != AF_INET) { socket_error = WSA_EAFNOSUPPORT; return 0; }
    memset(out->sin_zero, 0, sizeof out->sin_zero);
    return 1;
}

static void sockaddr_to_guest(const struct sockaddr_in *in, uint32_t name, uint32_t length)
{
    if (!name || !length || !void_vm_writable(length, 4)) return;
    uint32_t room = MEM32(length);
    if ((int32_t)room >= (int32_t)sizeof *in && void_vm_writable(name, sizeof *in)) memcpy(GPTR(name), in, sizeof *in);
    MEM32(length) = sizeof *in;
}

/* The device's IPv4 interfaces: address, netmask, flags. */
typedef struct { uint32_t address, netmask, broadcast, flags; char name[IFNAMSIZ]; } net_interface;

static int interfaces(net_interface *out, int max)
{
    struct ifaddrs *list = NULL;
    if (getifaddrs(&list)) return 0;
    int count = 0;
    for (struct ifaddrs *i = list; i && count < max; i = i->ifa_next) {
        if (!i->ifa_addr || i->ifa_addr->sa_family != AF_INET || !(i->ifa_flags & IFF_UP)) continue;
        net_interface *n = &out[count++];
        n->address = ((struct sockaddr_in *)i->ifa_addr)->sin_addr.s_addr;
        n->netmask = i->ifa_netmask ? ((struct sockaddr_in *)i->ifa_netmask)->sin_addr.s_addr : 0xFFFFFFFFu;
        n->broadcast = (i->ifa_flags & IFF_BROADCAST) && i->ifa_broadaddr
            ? ((struct sockaddr_in *)i->ifa_broadaddr)->sin_addr.s_addr : (n->address | ~n->netmask);
        n->flags = i->ifa_flags;
        snprintf(n->name, sizeof n->name, "%s", i->ifa_name ? i->ifa_name : "");
    }
    freeifaddrs(list);
    return count;
}

static uint64_t now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000u + (uint64_t)t.tv_nsec / 1000000u;
}

/* The interfaces again, read at most every two seconds: every datagram asks. */
static int interfaces_recent(net_interface *out, int max)
{
    static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
    static net_interface cache[16];
    static int count;
    static uint64_t read_ms;
    pthread_mutex_lock(&lock);
    uint64_t now = now_ms();
    if (!read_ms || now - read_ms > 2000) { count = interfaces(cache, 16); read_ms = now; }
    int n = count < max ? count : max;
    memcpy(out, cache, sizeof *out * (size_t)n);
    pthread_mutex_unlock(&lock);
    return n;
}

#ifndef HOMM5_LEGACY_UI
/* LAN over Tailscale or another VPN (option port_lan_vpn, off by default). A
 * tunnel has no broadcast and Tailscale spreads its members over 100.64.0.0/10,
 * so a small discovery broadcast also goes to the peers the player listed in
 * the launcher (names resolved on a thread of their own, every minute), and
 * the game is offered the tunnel's address first: it writes its own address
 * into its session packets. Off by default because a Wi-Fi player joining a
 * host that has it on would be handed an address only tailnet members reach. */
#define VPN_PEERS 16
static char vpn_names[VPN_PEERS][128];
static int vpn_name_count, vpn_resolver_started;
static uint32_t vpn_addresses[VPN_PEERS];
static int vpn_address_count;
static pthread_mutex_t vpn_lock = PTHREAD_MUTEX_INITIALIZER;

/* A tunnel member: point-to-point (tun) interface with a 100.64.0.0/10 address. */
static int vpn_interface(const net_interface *n)
{
    uint32_t address = ntohl(n->address);
    return (address & 0xFFC00000u) == 0x64400000u &&
           ((n->flags & IFF_POINTOPOINT) || !strncmp(n->name, "tun", 3));
}

static int vpn_resolve(uint32_t *out)
{
    char names[VPN_PEERS][128];
    pthread_mutex_lock(&vpn_lock);
    int count = vpn_name_count;
    memcpy(names, vpn_names, sizeof names);
    pthread_mutex_unlock(&vpn_lock);
    int found = 0;
    for (int i = 0; i < count && found < VPN_PEERS; ++i) {
        struct in_addr literal;
        if (inet_aton(names[i], &literal)) { out[found++] = literal.s_addr; continue; }
        struct addrinfo hints, *list = NULL;
        memset(&hints, 0, sizeof hints);
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        if (getaddrinfo(names[i], NULL, &hints, &list)) continue;
        for (struct addrinfo *a = list; a && found < VPN_PEERS; a = a->ai_next)
            if (a->ai_family == AF_INET) { out[found++] = ((struct sockaddr_in *)a->ai_addr)->sin_addr.s_addr; break; }
        freeaddrinfo(list);
    }
    return found;
}

static void *vpn_resolver(void *unused)
{
    (void)unused;
    for (;;) {
        uint32_t found[VPN_PEERS];
        int count = vpn_resolve(found);
        pthread_mutex_lock(&vpn_lock);
        memcpy(vpn_addresses, found, sizeof found);
        vpn_address_count = count;
        int listed = vpn_name_count;
        pthread_mutex_unlock(&vpn_lock);
        static int logged;
        if (logged < 3 && ++logged) void_log("[network] VPN peers: %d listed, %d resolved", listed, count);
        sleep(60);
    }
    return NULL;
}

/* The launcher's list before the game starts: addresses or names separated by
 * spaces, commas, semicolons or lines. */
void void_lan_vpn_peers(const char *list)
{
    pthread_mutex_lock(&vpn_lock);
    vpn_name_count = 0;
    for (const char *at = list ? list : ""; *at && vpn_name_count < VPN_PEERS;) {
        size_t skip = strspn(at, " ,;\t\r\n"), length;
        at += skip;
        length = strcspn(at, " ,;\t\r\n");
        if (length && length < sizeof vpn_names[0]) {
            memcpy(vpn_names[vpn_name_count], at, length);
            vpn_names[vpn_name_count++][length] = 0;
        }
        at += length;
    }
    int start = vpn_name_count && !vpn_resolver_started;
    if (start) vpn_resolver_started = 1;
    pthread_mutex_unlock(&vpn_lock);
    if (start) {
        pthread_t thread;
        pthread_attr_t attr;
        pthread_attr_init(&attr);
        pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
        if (pthread_create(&thread, &attr, vpn_resolver, NULL)) void_log("[network] VPN peer resolver failed to start");
        pthread_attr_destroy(&attr);
    }
}

/* A discovery broadcast to every resolved peer: the size sent, -1 if none took it. */
static ssize_t vpn_broadcast(int fd, const void *data, size_t size, int flags, uint16_t port)
{
    uint32_t peers[VPN_PEERS];
    pthread_mutex_lock(&vpn_lock);
    int count = vpn_address_count;
    memcpy(peers, vpn_addresses, sizeof peers);
    pthread_mutex_unlock(&vpn_lock);
    ssize_t result = -1;
    for (int i = 0; i < count; ++i) {
        struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = port, .sin_addr.s_addr = peers[i]};
        if (sendto(fd, data, size, flags | MSG_DONTWAIT, (struct sockaddr *)&to, sizeof to) >= 0) result = (ssize_t)size;
    }
    return result;
}

/* The tunnel first, so the game advertises the address its VPN peers reach. */
static void vpn_first(net_interface *list, int n)
{
    if (!void_port_lan_vpn()) return;
    for (int i = 1; i < n; ++i)
        if (vpn_interface(&list[i]) && !vpn_interface(&list[0])) {
            net_interface tunnel = list[i];
            memmove(list + 1, list, sizeof *list * (size_t)i);
            list[0] = tunnel;
            break;
        }
}
#endif

/* LAN addresses first (wlan, then any other), loopback last; with the VPN
 * option (ToE) the tunnel comes before them. */
static int local_addresses(uint32_t *out, int max)
{
    net_interface list[16];
    int n = interfaces(list, 16), count = 0;
#ifndef HOMM5_LEGACY_UI
    vpn_first(list, n);
    int tunnel = n && void_port_lan_vpn() && vpn_interface(&list[0]);
    if (tunnel && count < max) out[count++] = list[0].address;
#else
    int tunnel = 0;
#endif
    for (int pass = 0; pass < 3; ++pass)
        for (int i = tunnel; i < n && count < max; ++i) {
            int loopback = (list[i].flags & IFF_LOOPBACK) != 0, wlan = !strncmp(list[i].name, "wlan", 4);
            if ((pass == 0 && wlan && !loopback) || (pass == 1 && !wlan && !loopback) || (pass == 2 && loopback))
                out[count++] = list[i].address;
        }
    return count;
}

/* The machine's name: the system's, unless it is "localhost" (Android's),
 * then one made from its LAN address. */
static void host_name(char *out, size_t size)
{
    char name[256] = "";
    if (gethostname(name, sizeof name) || !name[0] || !strcasecmp(name, "localhost")) {
        uint32_t address = 0;
        local_addresses(&address, 1);
        snprintf(name, sizeof name, "HEROESV-%u", (unsigned)(ntohl(address) & 0xFFu));
    }
    snprintf(out, size, "%s", name);
}

/* A hostent in this thread's guest buffer, as WinSock returns it. */
static uint32_t make_hostent(const char *name, const uint32_t *addresses, int count)
{
    enum { HOSTENT_SIZE = 1024 };
    if (!host_entry) host_entry = void_galloc(HOSTENT_SIZE);
    if (!host_entry) { socket_error = WSA_ENOBUFS; return 0; }
    if (count > 16) count = 16;
    uint32_t h = host_entry, aliases = h + 16, list = aliases + 4, data = list + 4u * (uint32_t)(count + 1);
    uint32_t text = data + 4u * (uint32_t)count;
    memset(GPTR(h), 0, HOSTENT_SIZE);
    size_t length = strlen(name);
    if (text + length + 1 > h + HOSTENT_SIZE) length = h + HOSTENT_SIZE - text - 1;
    memcpy(GPTR(text), name, length);
    MEM32(h) = text;                       /* h_name */
    MEM32(h + 4) = aliases;                /* h_aliases: none */
    MEM16(h + 8) = AF_INET;                /* h_addrtype */
    MEM16(h + 10) = 4;                     /* h_length */
    MEM32(h + 12) = list;                  /* h_addr_list */
    for (int i = 0; i < count; ++i) {
        MEM32(data + 4u * (uint32_t)i) = addresses[i];
        MEM32(list + 4u * (uint32_t)i) = data + 4u * (uint32_t)i;
    }
    return h;
}

static uint32_t resolve(const char *name)
{
    if (!name) { socket_error = WSA_EFAULT; return 0; }
    char own[256];
    host_name(own, sizeof own);
    uint32_t addresses[16];
    int count = 0;
    struct in_addr literal;
    if (!name[0] || !strcasecmp(name, own)) {
        count = local_addresses(addresses, 16);
    } else if (!strcasecmp(name, "localhost")) {
        addresses[0] = htonl(INADDR_LOOPBACK);
        count = 1;
    } else if (inet_aton(name, &literal)) {
        addresses[0] = literal.s_addr;
        count = 1;
    } else {
        struct addrinfo hints, *found = NULL;
        memset(&hints, 0, sizeof hints);
        hints.ai_family = AF_INET;
        void_blocking_begin();
        int result = getaddrinfo(name, NULL, &hints, &found);
        void_blocking_end();
        for (struct addrinfo *a = found; a && count < 16; a = a->ai_next)
            if (a->ai_family == AF_INET) addresses[count++] = ((struct sockaddr_in *)a->ai_addr)->sin_addr.s_addr;
        if (found) freeaddrinfo(found);
        if (result) VLOG("[network] gethostbyname(%s): %s", name, gai_strerror(result));
    }
    if (!count) { socket_error = WSA_HOST_NOT_FOUND; return 0; }
    return make_hostent(name[0] ? name : own, addresses, count);
}

/* --------------------------------------------------------------- select */

static int fd_is_set(uint32_t socket, uint32_t set)
{
    if (!void_vm_readable(set, 4)) return 0;
    uint32_t count = MEM32(set);
    if (count > 64 || !void_vm_readable(set, 4 + 4 * count)) return 0;
    for (uint32_t i = 0; i < count; ++i) if (MEM32(set + 4 + 4 * i) == socket) return 1;
    return 0;
}

static uint32_t do_select(uint32_t sets_in[3], uint32_t timeout)
{
    struct pollfd fds[192];
    uint32_t handles[192];
    int slots[192], nfds = 0;
    for (int k = 0; k < 3; ++k) {
        uint32_t set = sets_in[k];
        if (!set) continue;
        if (!void_vm_writable(set, 4) || MEM32(set) > 64 || !void_vm_writable(set, 4 + 4 * MEM32(set))) return fail(WSA_EFAULT);
        for (uint32_t i = 0; i < MEM32(set); ++i) {
            uint32_t s = MEM32(set + 4 + 4 * i);
            int at = 0;
            while (at < nfds && handles[at] != s) ++at;
            if (at == nfds) {
                int slot, fd = socket_fd(s, &slot);
                if (fd < 0) return fail(WSA_ENOTSOCK);
                handles[nfds] = s;
                slots[nfds] = slot;
                fds[nfds].fd = fd;
                fds[nfds].events = 0;
                fds[nfds].revents = 0;
                ++nfds;
            }
            fds[at].events |= k == 0 ? POLLIN : k == 1 ? POLLOUT : POLLPRI;
        }
    }
    int ms = -1;
    if (timeout) {
        if (!void_vm_readable(timeout, 8)) return fail(WSA_EFAULT);
        int32_t sec = (int32_t)MEM32(timeout), usec = (int32_t)MEM32(timeout + 4);
        int64_t total = (int64_t)(sec < 0 ? 0 : sec) * 1000 + (usec < 0 ? 0 : usec) / 1000;
        ms = total > 0x7FFFFFFF ? 0x7FFFFFFF : (int)total;
        if (!ms && usec > 0) ms = 1;
    }
    if (!nfds) return fail(WSA_EINVAL);              /* WinSock refuses an empty select */
    int ready;
    if (ms) void_blocking_begin();
    do ready = poll(fds, (nfds_t)nfds, ms);
    while (ready < 0 && errno == EINTR);
    if (ms) void_blocking_end();
    if (ready < 0) return fail_errno();
    /* A pending connect ends writable on success, as an exception on failure.
       Reading SO_ERROR clears it: the slot keeps it for the caller's getsockopt. */
    int failed[192];
    for (int i = 0; i < nfds; ++i) {
        failed[i] = 0;
        int slot = slots[i];
        if (slot >= 0 && sockets[slot].connecting == 1 && (fds[i].revents & (POLLOUT | POLLERR | POLLHUP))) {
            int error = 0;
            socklen_t length = sizeof error;
            getsockopt(fds[i].fd, SOL_SOCKET, SO_ERROR, &error, &length);
            failed[i] = error;
            sockets[slot].connecting = error ? -error : 0;
        }
    }
    uint32_t total = 0;
    for (int k = 0; k < 3; ++k) {
        uint32_t set = sets_in[k];
        if (!set) continue;
        uint32_t count = MEM32(set), kept = 0;
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t s = MEM32(set + 4 + 4 * i);
            int at = 0;
            while (at < nfds && handles[at] != s) ++at;
            short r = fds[at].revents;
            int yes = k == 0 ? (r & (POLLIN | POLLHUP | POLLERR)) != 0
                    : k == 1 ? (r & POLLOUT) != 0 && !failed[at]
                    : (r & POLLPRI) != 0 || failed[at] != 0;
            if (yes) MEM32(set + 4 + 4 * kept++) = s;
        }
        MEM32(set) = kept;
        total += kept;
    }
    socket_error = 0;
    return total;
}

/* ------------------------------------------------------------ options */

/* WinSock SOL_SOCKET options and their Linux names; 0: accepted, ignored. */
static int socket_option(uint32_t name)
{
    switch (name) {
    case 0x0001: return SO_DEBUG;
    case 0x0004: return SO_REUSEADDR;
    case 0x0008: return SO_KEEPALIVE;
    case 0x0010: return SO_DONTROUTE;
    case 0x0020: return SO_BROADCAST;
    case 0x0080: return SO_LINGER;
    case 0x0100: return SO_OOBINLINE;
    case 0x1001: return SO_SNDBUF;
    case 0x1002: return SO_RCVBUF;
    case 0x1003: return SO_SNDLOWAT;
    case 0x1004: return SO_RCVLOWAT;
    case 0x1005: return SO_SNDTIMEO;
    case 0x1006: return SO_RCVTIMEO;
    case 0x1007: return SO_ERROR;
    case 0x1008: return SO_TYPE;
    default: return 0;
    }
}

static uint32_t do_setsockopt(uint32_t s, uint32_t level, uint32_t name, uint32_t value, uint32_t length)
{
    int fd = socket_fd(s, NULL);
    if (fd < 0) return UINT32_MAX;
    if (!value || (int32_t)length < 1 || !void_vm_readable(value, length)) return fail(WSA_EFAULT);
    int32_t v = length >= 4 ? (int32_t)MEM32(value) : MEM8(value);
    int result = 0;
    if (level == 0xFFFFu) {
        int option = socket_option(name);
        if (name == 0x0080u && length >= 4) {            /* struct linger {u_short onoff, linger} */
            struct linger l = { MEM16(value) != 0, MEM16(value + 2) };
            result = setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof l);
        } else if (name == 0xFFFFFF7Fu) {                /* SO_DONTLINGER */
            struct linger l = { v == 0, 0 };
            result = setsockopt(fd, SOL_SOCKET, SO_LINGER, &l, sizeof l);
        } else if (option == SO_SNDTIMEO || option == SO_RCVTIMEO) {   /* DWORD milliseconds */
            struct timeval t = { (time_t)((uint32_t)v / 1000u), (suseconds_t)((uint32_t)v % 1000u) * 1000 };
            result = setsockopt(fd, SOL_SOCKET, option, &t, sizeof t);
        } else if (option && option != SO_ERROR && option != SO_TYPE) {
            int x = v;
            result = setsockopt(fd, SOL_SOCKET, option, &x, sizeof x);
        } else {
            VLOG("[network] setsockopt(SOL_SOCKET, %X) ignored", name);
        }
    } else if (level == IPPROTO_TCP && name == 1) {      /* TCP_NODELAY */
        int x = v != 0;
        result = setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &x, sizeof x);
    } else {
        VLOG("[network] setsockopt(%u, %u) ignored", level, name);
    }
    if (result) return fail_errno();
    socket_error = 0;
    return 0;
}

static uint32_t do_getsockopt(uint32_t s, uint32_t level, uint32_t name, uint32_t value, uint32_t length)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    if (!value || !length || !void_vm_writable(length, 4) || (int32_t)MEM32(length) < 1 ||
        !void_vm_writable(value, MEM32(length))) return fail(WSA_EFAULT);
    uint32_t room = MEM32(length);
    int32_t answer = 0;
    if (level == 0xFFFFu && name == 0x1007u) {           /* SO_ERROR, as a WSA code */
        int error = 0;
        socklen_t size = sizeof error;
        getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size);
        if (!error && slot >= 0 && sockets[slot].connecting < 0) error = -sockets[slot].connecting;
        if (slot >= 0 && sockets[slot].connecting < 0) sockets[slot].connecting = 0;
        answer = error ? (int32_t)wsa_error(error) : 0;
    } else if (level == 0xFFFFu && name == 0x1008u) {    /* SO_TYPE: 1 stream, 2 datagram */
        answer = slot >= 0 ? sockets[slot].type : 0;
    } else if (level == 0xFFFFu && name == 0x0080u) {
        struct linger l = {0, 0};
        socklen_t size = sizeof l;
        if (getsockopt(fd, SOL_SOCKET, SO_LINGER, &l, &size)) return fail_errno();
        if (room >= 4) { MEM16(value) = (uint16_t)l.l_onoff; MEM16(value + 2) = (uint16_t)l.l_linger; MEM32(length) = 4; }
        socket_error = 0;
        return 0;
    } else if (level == 0xFFFFu && socket_option(name)) {
        int option = socket_option(name);
        if (option == SO_SNDTIMEO || option == SO_RCVTIMEO) {
            struct timeval t = {0, 0};
            socklen_t size = sizeof t;
            if (getsockopt(fd, SOL_SOCKET, option, &t, &size)) return fail_errno();
            answer = (int32_t)(t.tv_sec * 1000 + t.tv_usec / 1000);
        } else {
            int x = 0;
            socklen_t size = sizeof x;
            if (getsockopt(fd, SOL_SOCKET, option, &x, &size)) return fail_errno();
            answer = option == SO_SNDBUF || option == SO_RCVBUF ? x / 2 : x;   /* Linux reports doubled */
        }
    } else if (level == IPPROTO_TCP && name == 1) {
        int x = 0;
        socklen_t size = sizeof x;
        if (getsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &x, &size)) return fail_errno();
        answer = x;
    } else {
        VLOG("[network] getsockopt(%u, %X) unsupported", level, name);
        return fail(WSA_ENOPROTOOPT);
    }
    /* BOOL options may be read as a single byte (H5's connect check does). */
    if (room >= 4) { MEM32(value) = (uint32_t)answer; MEM32(length) = 4; }
    else { MEM8(value) = (uint8_t)answer; MEM32(length) = 1; }
    socket_error = 0;
    return 0;
}

/* ------------------------------------------------------------ the calls */

static uint32_t do_startup(uint32_t version, uint32_t data)
{
    if (data && void_vm_writable(data, 400)) {
        memset(GPTR(data), 0, 400);
        uint32_t major = version & 0xFFu, minor = (version >> 8) & 0xFFu;
        uint32_t use = (major > 2 || (major == 2 && minor > 2)) ? 0x0202u : (version & 0xFFFFu);
        MEM16(data) = (uint16_t)use;                     /* wVersion */
        MEM16(data + 2) = 0x0202;                        /* wHighVersion */
        strcpy((char *)GPTR(data + 4), "WinSock 2.0");   /* szDescription[257] */
        strcpy((char *)GPTR(data + 261), "Running");     /* szSystemStatus[129] */
        MEM16(data + 390) = 0;                           /* iMaxSockets (unused since 2.0) */
        MEM16(data + 392) = 0;                           /* iMaxUdpDg */
    }
    if (!net_started++) {
        uint32_t addresses[4];
        int n = local_addresses(addresses, 4);
        char text[INET_ADDRSTRLEN] = "none";
        if (n) inet_ntop(AF_INET, &addresses[0], text, sizeof text);
        char name[64];
        host_name(name, sizeof name);
        void_log("[network] WinSock up: %s, %d address(es), first %s", name, n, text);
    }
    socket_error = 0;
    return 0;
}

static uint32_t do_socket(uint32_t af, uint32_t type, uint32_t protocol)
{
    if (af != AF_INET) return fail(WSA_EAFNOSUPPORT);
    if (type != 1 && type != 2) return fail(10044u);    /* WSAESOCKTNOSUPPORT */
    int fd = socket(AF_INET, (type == 1 ? SOCK_STREAM : SOCK_DGRAM) | SOCK_CLOEXEC, (int)protocol);
    if (fd < 0) return fail_errno();
    uint32_t s = socket_new(fd, (int)type);
    if (s != UINT32_MAX) { socket_error = 0; VLOG("[network] socket(%s) = %X", type == 1 ? "tcp" : "udp", s); }
    return s;
}

static uint32_t do_close(uint32_t s)
{
    pthread_mutex_lock(&net_lock);
    int slot = slot_of(s), fd = slot >= 0 ? sockets[slot].fd : -1;
    if (slot >= 0) sockets[slot].used = 0;
    pthread_mutex_unlock(&net_lock);
    if (fd < 0) return fail(WSA_ENOTSOCK);
    close(fd);
    socket_error = 0;
    return 0;
}

static uint32_t do_bind(uint32_t s, uint32_t name, uint32_t length)
{
    int fd = socket_fd(s, NULL);
    if (fd < 0) return UINT32_MAX;
    struct sockaddr_in in;
    if (!sockaddr_from_guest(name, length, &in)) return UINT32_MAX;
    if (bind(fd, (struct sockaddr *)&in, sizeof in)) return fail_errno();
    void_log("[network] bind %X to %s:%u", s, inet_ntoa(in.sin_addr), ntohs(in.sin_port));
    socket_error = 0;
    return 0;
}

static uint32_t do_connect(uint32_t s, uint32_t name, uint32_t length)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    struct sockaddr_in in;
    if (!sockaddr_from_guest(name, length, &in)) return UINT32_MAX;
    int blocking = is_blocking(slot), result;
    if (blocking) void_blocking_begin();
    do result = connect(fd, (struct sockaddr *)&in, sizeof in);
    while (result && errno == EINTR && blocking);
    if (blocking) void_blocking_end();
    VLOG("[network] connect %X to %s:%u = %d (%d)", s, inet_ntoa(in.sin_addr), ntohs(in.sin_port), result, result ? errno : 0);
    if (result) {
        if (errno == EINPROGRESS && slot >= 0) sockets[slot].connecting = 1;
        return fail_errno();
    }
    socket_error = 0;
    return 0;
}

static uint32_t do_listen(uint32_t s, uint32_t backlog)
{
    int fd = socket_fd(s, NULL);
    if (fd < 0) return UINT32_MAX;
    if (listen(fd, (int)(backlog > 128 ? 128 : backlog))) return fail_errno();
    socket_error = 0;
    return 0;
}

static uint32_t do_accept(uint32_t s, uint32_t name, uint32_t length)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    struct sockaddr_in in;
    socklen_t size = sizeof in;
    int blocking = is_blocking(slot), client;
    if (blocking) void_blocking_begin();
    do client = accept4(fd, (struct sockaddr *)&in, &size, SOCK_CLOEXEC);
    while (client < 0 && errno == EINTR && blocking);
    if (blocking) void_blocking_end();
    if (client < 0) return fail_errno();
    uint32_t handle = socket_new(client, 1);
    if (handle != UINT32_MAX) { sockaddr_to_guest(&in, name, length); socket_error = 0; }
    return handle;
}

/* The limited broadcast leaves by the default route, which a VPN (or a phone
 * whose Wi-Fi is not its default network) turns away from the LAN: send it as
 * the directed broadcast of every LAN interface instead. */
static ssize_t send_broadcast(int fd, const void *data, size_t size, int flags, struct sockaddr_in *to)
{
    net_interface list[16];
    int n = interfaces_recent(list, 16), sent_any = 0;
    ssize_t result = -1;
    int error = ENETUNREACH;
    for (int i = 0; i < n; ++i) {
        if ((list[i].flags & (IFF_LOOPBACK | IFF_POINTOPOINT)) || !(list[i].flags & IFF_BROADCAST)) continue;
        struct sockaddr_in each = *to;
        each.sin_addr.s_addr = list[i].broadcast;
        ssize_t r = sendto(fd, data, size, flags, (struct sockaddr *)&each, sizeof each);
        if (r >= 0) { result = r; sent_any = 1; }
        else error = errno;
    }
    if (!sent_any) {
        result = sendto(fd, data, size, flags, (struct sockaddr *)to, sizeof *to);
        if (result < 0) error = errno;
    }
    if (result < 0) errno = error;
    return result;
}

/* H5's LAN discovery: a client in the lobby broadcasts a 5-byte ping every
 * second and every host answers it by unicast with its game. Some Wi-Fi
 * access points pass no broadcasts between their own clients (two phones on
 * one router both see a wired PC's games, never each other's), so a small
 * broadcast also goes, at most every three seconds, to every address of each
 * local subnet of up to 254 hosts, and each broadcast straight to the senders
 * heard on the socket in the last three seconds: the hosts found keep
 * answering every second. */
static void note_peer(int slot, const struct sockaddr_in *from)
{
    if (slot < 0 || sockets[slot].type != 2) return;
    net_interface list[16];
    int n = interfaces_recent(list, 16);
    for (int i = 0; i < n; ++i)
        if (list[i].address == from->sin_addr.s_addr) return;          /* our own broadcast, echoed */
    pthread_mutex_lock(&net_lock);
    net_peer *peers = sockets[slot].peers, *slot_for = &peers[0];
    for (int i = 0; i < NET_PEERS; ++i) {
        if (peers[i].address == from->sin_addr.s_addr && peers[i].port == from->sin_port) { slot_for = &peers[i]; break; }
        if (peers[i].heard_ms < slot_for->heard_ms) slot_for = &peers[i];
    }
    *slot_for = (net_peer){from->sin_addr.s_addr, from->sin_port, now_ms()};
    pthread_mutex_unlock(&net_lock);
}

static int is_broadcast(uint32_t address)
{
    if (address == INADDR_BROADCAST) return 1;
    net_interface list[16];
    int n = interfaces_recent(list, 16);
    for (int i = 0; i < n; ++i)
        if ((list[i].flags & IFF_BROADCAST) && list[i].broadcast == address) return 1;
    return 0;
}

static void echo_broadcast(int slot, int fd, const void *data, size_t size, int flags, uint16_t port)
{
    if (slot < 0 || sockets[slot].type != 2) return;
    net_peer recent[NET_PEERS];
    int count = 0, sweep = 0;
    uint64_t now = now_ms();
    pthread_mutex_lock(&net_lock);
    for (int i = 0; i < NET_PEERS; ++i)
        if (sockets[slot].peers[i].address && now - sockets[slot].peers[i].heard_ms < 3000) recent[count++] = sockets[slot].peers[i];
    if (size <= 64 && (!sockets[slot].swept_ms || now - sockets[slot].swept_ms >= 3000)) {
        sockets[slot].swept_ms = now;
        sweep = 1;
    }
    pthread_mutex_unlock(&net_lock);
    for (int i = 0; i < count; ++i) {
        struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = recent[i].port, .sin_addr.s_addr = recent[i].address};
        if (sendto(fd, data, size, flags, (struct sockaddr *)&to, sizeof to) < 0)
            VLOG("[network] broadcast echo to %s:%u failed: %s", inet_ntoa(to.sin_addr), ntohs(to.sin_port), strerror(errno));
    }
    if (!sweep) return;
    net_interface list[16];
    int n = interfaces_recent(list, 16), sent = 0;
    for (int i = 0; i < n; ++i) {
        uint32_t mask = ntohl(list[i].netmask), self = ntohl(list[i].address);
        if ((list[i].flags & (IFF_LOOPBACK | IFF_POINTOPOINT)) || !(list[i].flags & IFF_BROADCAST) || ~mask > 255u) continue;
        for (uint32_t host = 1; host < ~mask; ++host) {
            uint32_t address = (self & mask) | host;
            if (address == self) continue;
            struct sockaddr_in to = {.sin_family = AF_INET, .sin_port = port, .sin_addr.s_addr = htonl(address)};
            if (sendto(fd, data, size, flags | MSG_DONTWAIT, (struct sockaddr *)&to, sizeof to) >= 0) ++sent;
        }
    }
    static int sweeps_logged;
    if (sweeps_logged < 3 && ++sweeps_logged) VLOG("[network] broadcast swept to %d LAN addresses", sent);
}

/* Verbose traffic trace by kind (socket, direction, peer, first byte): the
 * first of a kind in full, the next few by their head, then one in 500. */
static struct {
    uint32_t s, peer;
    uint16_t port;
    uint8_t send, type;
    unsigned count;
} trace_kinds[256];
static int trace_kind_count;
static pthread_mutex_t trace_lock = PTHREAD_MUTEX_INITIALIZER;

static void trace_packet(int slot, uint32_t s, const char *what, const struct sockaddr_in *at, const uint8_t *data,
                         ssize_t size)
{
    if (!void_verbose || slot < 0 || size < 0) return;
    uint8_t send = what[0] == 's', type = size ? data[0] : 0;
    uint32_t peer = at ? at->sin_addr.s_addr : 0;
    uint16_t port = at ? at->sin_port : 0;
    pthread_mutex_lock(&trace_lock);
    int k = 0;
    while (k < trace_kind_count && !(trace_kinds[k].s == s && trace_kinds[k].peer == peer && trace_kinds[k].port == port &&
                                     trace_kinds[k].send == send && trace_kinds[k].type == type)) ++k;
    if (k == trace_kind_count && k < (int)(sizeof trace_kinds / sizeof *trace_kinds))
        trace_kinds[trace_kind_count++] = (typeof(trace_kinds[0])){s, peer, port, send, type, 0};
    unsigned n = k < trace_kind_count ? trace_kinds[k].count++ : 5;   /* table full: kinds past it unlogged */
    pthread_mutex_unlock(&trace_lock);
    if (n >= 4 && n % 500) return;
    ssize_t shown = n ? (size < 16 ? size : 16) : (size < 1024 ? size : 1024);
    void_log("[network] %s %X %s %s:%u %zd bytes (#%u)%s", what, s, send ? "->" : "<-",
             at ? inet_ntoa(at->sin_addr) : "peer", at ? ntohs(at->sin_port) : 0, size, n + 1, shown > 16 ? ":" : "");
    for (ssize_t row = 0; row < shown; row += 32) {
        char hex[3 * 32 + 1] = "";
        for (ssize_t i = row; i < shown && i < row + 32; ++i) snprintf(hex + 3 * (i - row), 4, "%02X ", data[i]);
        void_log("[network]   %04zX %s", row, hex);
    }
}

static uint32_t do_send(uint32_t s, uint32_t buffer, uint32_t size, uint32_t flags, uint32_t to, uint32_t tolen)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    if (size && !void_vm_readable(buffer, size)) return fail(WSA_EFAULT);
    struct sockaddr_in in;
    if (to && !sockaddr_from_guest(to, tolen, &in)) return UINT32_MAX;
    int blocking = is_blocking(slot);
    ssize_t sent;
    if (blocking) void_blocking_begin();
    int host_flags = (int)(flags & 7u) | MSG_NOSIGNAL;
    do sent = !to ? send(fd, GPTR(buffer), size, host_flags)
            : in.sin_addr.s_addr == INADDR_BROADCAST ? send_broadcast(fd, GPTR(buffer), size, host_flags, &in)
            : sendto(fd, GPTR(buffer), size, host_flags, (struct sockaddr *)&in, sizeof in);
    while (sent < 0 && errno == EINTR && blocking);
    if (blocking) void_blocking_end();
    trace_packet(slot, s, "sendto", to ? &in : NULL, (const uint8_t *)GPTR(buffer), sent);
    if (sent >= 0 && to && is_broadcast(in.sin_addr.s_addr)) echo_broadcast(slot, fd, GPTR(buffer), size, host_flags, in.sin_port);
#ifndef HOMM5_LEGACY_UI
    if (to && size <= 64 && void_port_lan_vpn() && is_broadcast(in.sin_addr.s_addr)) {
        ssize_t peers = vpn_broadcast(fd, GPTR(buffer), size, host_flags, in.sin_port);
        if (sent < 0 && peers >= 0) sent = peers;
    }
#endif
    if (sent < 0) {
        uint32_t e = fail_errno();
        if (socket_error != WSA_EWOULDBLOCK)
            VLOG("[network] send %X (%u bytes%s%s) failed: %s", s, size, to ? " to " : "", to ? inet_ntoa(in.sin_addr) : "",
                 strerror(errno));
        return e;
    }
    socket_error = 0;
    return (uint32_t)sent;
}

static uint32_t do_recv(uint32_t s, uint32_t buffer, uint32_t size, uint32_t flags, uint32_t from, uint32_t fromlen)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    if (size && !void_vm_writable(buffer, size)) return fail(WSA_EFAULT);
    int datagram = slot >= 0 && sockets[slot].type == 2;
    struct sockaddr_in in;
    memset(&in, 0, sizeof in);
    socklen_t length = sizeof in;
    int blocking = is_blocking(slot);
    /* MSG_TRUNC: a datagram's whole length, to answer WSAEMSGSIZE as Windows. */
    int host_flags = (int)(flags & 7u) | (datagram ? MSG_TRUNC : 0);
    ssize_t got;
    if (blocking) void_blocking_begin();
    do got = recvfrom(fd, GPTR(buffer), size, host_flags, (struct sockaddr *)&in, &length);
    while (got < 0 && errno == EINTR && blocking);
    if (blocking) void_blocking_end();
    if (got < 0) return fail_errno();
    if (!(flags & 2u)) {
        trace_packet(slot, s, "recvfrom", &in, (const uint8_t *)GPTR(buffer), got < (ssize_t)size ? got : (ssize_t)size);
        if (datagram && length >= sizeof in) note_peer(slot, &in);
    }
    if (from && length >= sizeof in) sockaddr_to_guest(&in, from, fromlen);
    if (datagram && (uint32_t)got > size) return fail(WSA_EMSGSIZE);   /* the datagram is consumed unless peeked */
    socket_error = 0;
    return (uint32_t)got;
}

static uint32_t do_shutdown(uint32_t s, uint32_t how)
{
    int fd = socket_fd(s, NULL);
    if (fd < 0) return UINT32_MAX;
    if (shutdown(fd, how == 0 ? SHUT_RD : how == 1 ? SHUT_WR : SHUT_RDWR)) return fail_errno();
    socket_error = 0;
    return 0;
}

static uint32_t do_name(uint32_t s, uint32_t name, uint32_t length, int peer)
{
    int fd = socket_fd(s, NULL);
    if (fd < 0) return UINT32_MAX;
    if (!name || !length || !void_vm_writable(length, 4) || (int32_t)MEM32(length) < 16) return fail(WSA_EFAULT);
    struct sockaddr_in in;
    socklen_t size = sizeof in;
    if ((peer ? getpeername : getsockname)(fd, (struct sockaddr *)&in, &size)) return fail_errno();
    sockaddr_to_guest(&in, name, length);
    socket_error = 0;
    return 0;
}

static uint32_t do_ioctl(uint32_t s, uint32_t command, uint32_t argument)
{
    int slot, fd = socket_fd(s, &slot);
    if (fd < 0) return UINT32_MAX;
    if (!argument || !void_vm_writable(argument, 4)) return fail(WSA_EFAULT);
    if (command == 0x8004667Eu) {                        /* FIONBIO */
        int flags = fcntl(fd, F_GETFL), on = MEM32(argument) != 0;
        if (flags < 0 || fcntl(fd, F_SETFL, on ? flags | O_NONBLOCK : flags & ~O_NONBLOCK)) return fail_errno();
        if (slot >= 0) sockets[slot].nonblocking = on;
    } else if (command == 0x4004667Fu) {                 /* FIONREAD */
        int pending = 0;
        if (ioctl(fd, FIONREAD, &pending)) return fail_errno();
        MEM32(argument) = (uint32_t)pending;
    } else if (command == 0x40047307u) {                 /* SIOCATMARK: no urgent data */
        MEM32(argument) = 1;
    } else {
        return fail(WSA_EINVAL);
    }
    socket_error = 0;
    return 0;
}

/* WSAIoctl(s, code, in, in_size, out, out_size, &returned, overlapped, routine) */
static uint32_t do_wsaioctl(uint32_t s, uint32_t code, uint32_t out, uint32_t out_size, uint32_t returned)
{
    if (socket_fd(s, NULL) < 0) return UINT32_MAX;
    if (returned && void_vm_writable(returned, 4)) MEM32(returned) = 0;
    if (code == 0x4004747Fu) {                           /* SIO_GET_INTERFACE_LIST: INTERFACE_INFO[] */
        net_interface list[16];
        int n = interfaces(list, 16);
#ifndef HOMM5_LEGACY_UI
        vpn_first(list, n);
#endif
        uint32_t need = 76u * (uint32_t)n;
        if (!out || out_size < need || !void_vm_writable(out, need)) return fail(WSA_EFAULT);
        memset(GPTR(out), 0, need);
        for (int i = 0; i < n; ++i) {
            uint32_t at = out + 76u * (uint32_t)i, flags = 0;
            if (list[i].flags & IFF_UP) flags |= 1u;
            if (list[i].flags & IFF_BROADCAST) flags |= 2u;
            if (list[i].flags & IFF_LOOPBACK) flags |= 4u;
            if (list[i].flags & IFF_POINTOPOINT) flags |= 8u;
            if (list[i].flags & IFF_MULTICAST) flags |= 16u;
            MEM32(at) = flags;
            uint32_t addresses[3] = { list[i].address, list[i].broadcast, list[i].netmask };
            for (int k = 0; k < 3; ++k) {                /* sockaddr_gen: a sockaddr_in in 24 bytes */
                uint32_t sa = at + 4u + 24u * (uint32_t)k;
                MEM16(sa) = AF_INET;
                MEM32(sa + 4) = addresses[k];
            }
        }
        if (returned && void_vm_writable(returned, 4)) MEM32(returned) = need;
        VLOG("[network] SIO_GET_INTERFACE_LIST: %d interface(s)", n);
        socket_error = 0;
        return 0;
    }
    if (code == 0x48000005u) {                           /* SIO_GET_BROADCAST_ADDRESS */
        if (!out || out_size < 16 || !void_vm_writable(out, 16)) return fail(WSA_EFAULT);
        memset(GPTR(out), 0, 16);
        MEM16(out) = AF_INET;
        MEM32(out + 4) = INADDR_BROADCAST;
        if (returned && void_vm_writable(returned, 4)) MEM32(returned) = 16;
        socket_error = 0;
        return 0;
    }
    VLOG("[network] WSAIoctl %X unsupported", code);
    return fail(WSA_EOPNOTSUPP);
}

static uint32_t do_gethostname(uint32_t name, uint32_t length)
{
    char own[256];
    host_name(own, sizeof own);
    size_t n = strlen(own);
    if (!name || (int32_t)length <= (int32_t)n || !void_vm_writable(name, length)) return fail(WSA_EFAULT);
    memcpy(GPTR(name), own, n + 1);
    socket_error = 0;
    return 0;
}

static uint32_t do_gethostbyaddr(uint32_t address, uint32_t length, uint32_t type)
{
    if (!address || length < 4 || type != AF_INET || !void_vm_readable(address, 4)) { socket_error = WSA_EFAULT; return 0; }
    uint32_t a = MEM32(address);
    char text[INET_ADDRSTRLEN];
    inet_ntop(AF_INET, &a, text, sizeof text);
    return make_hostent(text, &a, 1);
}

/* Ordinals verified against the installed Windows SysWOW64 DLL exports. */
#define NETWORK_EXPORTS(dll, sfx, inet_ordinal, text_ordinal, ioctl_ordinal) \
    WINAPI_EXPORT_AS(dll, WSAStartup##sfx, "WSAStartup", 115, 2) { return do_startup(ARG(0), ARG(1)); } \
    WINAPI_EXPORT_AS(dll, WSAGetLastError##sfx, "WSAGetLastError", 111, 0) { return socket_error; } \
    WINAPI_EXPORT_AS(dll, WSASetLastError##sfx, "WSASetLastError", 112, 1) { socket_error = ARG(0); return 0; } \
    WINAPI_EXPORT_AS(dll, WSACleanup##sfx, "WSACleanup", 116, 0) { socket_error = 0; return 0; } \
    WINAPI_EXPORT_AS(dll, socket##sfx, "socket", 23, 3) { return do_socket(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, bind##sfx, "bind", 2, 3) { return do_bind(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, connect##sfx, "connect", 4, 3) { return do_connect(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, listen##sfx, "listen", 13, 2) { return do_listen(ARG(0), ARG(1)); } \
    WINAPI_EXPORT_AS(dll, accept##sfx, "accept", 1, 3) { return do_accept(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, shutdown##sfx, "shutdown", 22, 2) { return do_shutdown(ARG(0), ARG(1)); } \
    WINAPI_EXPORT_AS(dll, closesocket##sfx, "closesocket", 3, 1) { return do_close(ARG(0)); } \
    WINAPI_EXPORT_AS(dll, send##sfx, "send", 19, 4) { return do_send(ARG(0), ARG(1), ARG(2), ARG(3), 0, 0); } \
    WINAPI_EXPORT_AS(dll, recv##sfx, "recv", 16, 4) { return do_recv(ARG(0), ARG(1), ARG(2), ARG(3), 0, 0); } \
    WINAPI_EXPORT_AS(dll, sendto##sfx, "sendto", 20, 6) { return do_send(ARG(0), ARG(1), ARG(2), ARG(3), ARG(4), ARG(5)); } \
    WINAPI_EXPORT_AS(dll, recvfrom##sfx, "recvfrom", 17, 6) { return do_recv(ARG(0), ARG(1), ARG(2), ARG(3), ARG(4), ARG(5)); } \
    WINAPI_EXPORT_AS(dll, select##sfx, "select", 18, 5) { uint32_t sets[3] = {ARG(1), ARG(2), ARG(3)}; return do_select(sets, ARG(4)); } \
    WINAPI_EXPORT_AS(dll, setsockopt##sfx, "setsockopt", 21, 5) { return do_setsockopt(ARG(0), ARG(1), ARG(2), ARG(3), ARG(4)); } \
    WINAPI_EXPORT_AS(dll, getsockopt##sfx, "getsockopt", 7, 5) { return do_getsockopt(ARG(0), ARG(1), ARG(2), ARG(3), ARG(4)); } \
    WINAPI_EXPORT_AS(dll, getsockname##sfx, "getsockname", 6, 3) { return do_name(ARG(0), ARG(1), ARG(2), 0); } \
    WINAPI_EXPORT_AS(dll, getpeername##sfx, "getpeername", 5, 3) { return do_name(ARG(0), ARG(1), ARG(2), 1); } \
    WINAPI_EXPORT_AS(dll, gethostname##sfx, "gethostname", 57, 2) { return do_gethostname(ARG(0), ARG(1)); } \
    WINAPI_EXPORT_AS(dll, gethostbyname##sfx, "gethostbyname", 52, 1) { return resolve(guest_text(ARG(0))); } \
    WINAPI_EXPORT_AS(dll, gethostbyaddr##sfx, "gethostbyaddr", 51, 3) { return do_gethostbyaddr(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, ioctlsocket##sfx, "ioctlsocket", ioctl_ordinal, 3) { return do_ioctl(ARG(0), ARG(1), ARG(2)); } \
    WINAPI_EXPORT_AS(dll, htons##sfx, "htons", 9, 1) { return htons((uint16_t)ARG(0)); } \
    WINAPI_EXPORT_AS(dll, ntohs##sfx, "ntohs", 15, 1) { return ntohs((uint16_t)ARG(0)); } \
    WINAPI_EXPORT_AS(dll, htonl##sfx, "htonl", 8, 1) { return htonl(ARG(0)); } \
    WINAPI_EXPORT_AS(dll, ntohl##sfx, "ntohl", 14, 1) { return ntohl(ARG(0)); } \
    WINAPI_EXPORT_AS(dll, inet_addr##sfx, "inet_addr", inet_ordinal, 1) { return address_from_text(ARG(0)); } \
    WINAPI_EXPORT_AS(dll, inet_ntoa##sfx, "inet_ntoa", text_ordinal, 1) { return address_to_text(ARG(0)); } \
    WINAPI_EXPORT_AS(dll, WSAFDIsSet##sfx, "__WSAFDIsSet", 151, 2) { return fd_is_set(ARG(0), ARG(1)); } \
    /* Asynchronous lookups are refused; callers fall back or report no network. */ \
    WINAPI_EXPORT_AS(dll, WSAAsyncGetHostByName##sfx, "WSAAsyncGetHostByName", 103, 5) \
        { VLOG("[network] WSAAsyncGetHostByName refused"); socket_error = WSA_ENOBUFS; return 0; } \
    WINAPI_EXPORT_AS(dll, WSACancelAsyncRequest##sfx, "WSACancelAsyncRequest", 108, 1) { socket_error = WSA_EINVAL; return UINT32_MAX; }

NETWORK_EXPORTS("ws2_32.dll", _ws2, 11, 12, 10)
NETWORK_EXPORTS("wsock32.dll", _wsock, 10, 11, 12)
WINAPI_EXPORT("ws2_32.dll", WSAIoctl, 9) { return do_wsaioctl(ARG(0), ARG(1), ARG(4), ARG(5), ARG(6)); }

/* ------------------------------------------------------------- iphlpapi */

/* GetAdaptersInfo(IP_ADAPTER_INFO *, ULONG *size): one 640-byte record per
 * IPv4 LAN interface (32-bit layout, 32-bit time_t of the VC7.1 modules). */
WINAPI_EXPORT("iphlpapi.dll", GetAdaptersInfo, 2)
{
    uint32_t info = ARG(0), size = ARG(1);
    if (!size || !void_vm_writable(size, 4)) return 87u;          /* ERROR_INVALID_PARAMETER */
    net_interface list[16], lan[16];
    int n = interfaces(list, 16), count = 0;
    for (int i = 0; i < n; ++i) if (!(list[i].flags & IFF_LOOPBACK)) lan[count++] = list[i];
    if (!count) return 232u;                                       /* ERROR_NO_DATA */
    uint32_t need = 640u * (uint32_t)count;
    if (!info || MEM32(size) < need || !void_vm_writable(info, need)) { MEM32(size) = need; return 111u; }   /* ERROR_BUFFER_OVERFLOW */
    memset(GPTR(info), 0, need);
    for (int i = 0; i < count; ++i) {
        uint32_t at = info + 640u * (uint32_t)i;
        MEM32(at) = i + 1 < count ? at + 640u : 0;                 /* Next */
        MEM32(at + 4) = (uint32_t)i + 1;                           /* ComboIndex */
        snprintf((char *)GPTR(at + 8), 260, "{00000000-0000-0000-0000-%012X}", (unsigned)i + 1);
        snprintf((char *)GPTR(at + 268), 132, "Android %s", lan[i].name);
        MEM32(at + 400) = 6;                                       /* AddressLength */
        uint32_t host = ntohl(lan[i].address);                     /* a stable, locally administered MAC */
        uint8_t mac[6] = {0x02, 0x48, 0x35, (uint8_t)(host >> 16), (uint8_t)(host >> 8), (uint8_t)host};
        memcpy(GPTR(at + 404), mac, 6);
        MEM32(at + 412) = (uint32_t)i + 1;                         /* Index */
        MEM32(at + 416) = !strncmp(lan[i].name, "wlan", 4) ? 71u : 6u;   /* IEEE 802.11 / Ethernet */
        MEM32(at + 420) = 1;                                       /* DhcpEnabled */
        MEM32(at + 424) = at + 428;                                /* CurrentIpAddress */
        char text[INET_ADDRSTRLEN];
        inet_ntop(AF_INET, &lan[i].address, text, sizeof text);
        snprintf((char *)GPTR(at + 428 + 4), 16, "%s", text);       /* IpAddressList.IpAddress */
        inet_ntop(AF_INET, &lan[i].netmask, text, sizeof text);
        snprintf((char *)GPTR(at + 428 + 20), 16, "%s", text);      /* IpAddressList.IpMask */
        for (uint32_t list_at = 468; list_at <= 592; list_at += 40) {
            if (list_at == 548) list_at = 552;                     /* HaveWins sits between the lists */
            snprintf((char *)GPTR(at + list_at + 4), 16, "0.0.0.0");
            snprintf((char *)GPTR(at + list_at + 20), 16, "0.0.0.0");
        }
    }
    return 0;
}

#if defined(VOID_ANDROID_APP) && !defined(HOMM5_LEGACY_UI)
JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeLanPeers(JNIEnv *env, jobject self, jstring peers)
{
    (void)self;
    const char *text = peers ? (*env)->GetStringUTFChars(env, peers, NULL) : NULL;
    void_lan_vpn_peers(text);
    if (text) (*env)->ReleaseStringUTFChars(env, peers, text);
}
#endif
