/* The resource loader uses raw inflateBack with a caller-owned guest window, and the
 * saves deflate (below). Keep custom allocators and all other zlib entry points in the
 * lifted DLL. A 32-bit z_stream is 56 bytes; native pointers/longs cannot be stored in it. */
#include "host.h"
#include <stdio.h>
#include <zlib.h>
#include "native_mode.h"
#include "zlib_deflate_native.h"

enum { BACK_INIT = 0x15004540u, BACK_RUN = 0x15004620u, BACK_END = 0x150054D0u,
       GUEST_ZALLOC = 0x150091C0u, GUEST_ZFREE = 0x150091E0u };
typedef struct back_stream {
    struct back_stream *next;
    uint32_t guest, token, window, window_size;
    int busy;
    z_stream native;
} back_stream;
static back_stream *streams;
static void_fn original_init, original_back, original_end;

static back_stream *back_find(uint32_t guest)
{
    for (back_stream *s = streams; s; s = s->next) if (s->guest == guest) return s;
    return NULL;
}

static void back_return(int result) { g_eax = (uint32_t)result; g_esp += 4; }

/* zlib's messages have process lifetime, including after inflateBackEnd. */
static uint32_t back_message(const char *text)
{
    static struct message { struct message *next; const char *text; uint32_t guest; } *messages;
    if (!text) return 0;
    for (struct message *m = messages; m; m = m->next)
        if (!strcmp(m->text, text)) return m->guest;
    struct message *m = malloc(sizeof *m);
    if (!m) return 0;
    m->guest = void_gstrdup(text);
    if (!m->guest) { free(m); return 0; }
    m->text = text; m->next = messages; messages = m;
    return m->guest;
}

static void native_back_init(void)
{
    uint32_t guest = MEM32(g_esp + 4), bits = MEM32(g_esp + 8), window = MEM32(g_esp + 12);
    uint32_t version = MEM32(g_esp + 16), size = MEM32(g_esp + 20);
    if (back_find(guest)) { back_return(Z_STREAM_ERROR); return; }
    /* Invalid requests and custom allocators keep the original error/callback path. */
    if (!guest || !void_vm_writable(guest, 56) || !version || !void_vm_readable(version, 1) ||
        MEM8(version) != '1' || size != 56 || bits < 8 || bits > 15 ||
        !window || !void_vm_writable(window, 1u << bits) ||
        (MEM32(guest + 32) && MEM32(guest + 32) != GUEST_ZALLOC) ||
        (MEM32(guest + 36) && MEM32(guest + 36) != GUEST_ZFREE)) {
        original_init(); return;
    }
    MEM32(guest + 24) = 0;
    if (!MEM32(guest + 32)) { MEM32(guest + 32) = GUEST_ZALLOC; MEM32(guest + 40) = 0; }
    if (!MEM32(guest + 36)) MEM32(guest + 36) = GUEST_ZFREE;
    back_stream *s = calloc(1, sizeof *s);
    if (!s) { back_return(Z_MEM_ERROR); return; }
    int result = inflateBackInit(&s->native, (int)bits, GPTR(window));
    if (result != Z_OK) { free(s); back_return(result); return; }
    s->token = void_galloc(8); /* opaque guest state and input-callback pointer cell */
    if (!s->token) { inflateBackEnd(&s->native); free(s); back_return(Z_MEM_ERROR); return; }
    s->guest = guest; s->window = window; s->window_size = 1u << bits;
    s->next = streams; streams = s;
    MEM32(guest + 28) = s->token;
    back_return(Z_OK);
}

typedef struct {
    back_stream *stream;
    uint32_t input, in_desc, output, out_desc;
} back_callbacks;

static unsigned back_input(void *opaque, z_const unsigned char **buffer)
{
    back_callbacks *c = opaque;
    uint32_t cell = c->stream->token + 4;
    MEM32(cell) = 0;
    const uint32_t args[] = {c->in_desc, cell};
    uint32_t count = void_call_guest(c->input, 2, args, 0), pointer = MEM32(cell);
    if (count && (!pointer || !void_vm_readable(pointer, count))) { *buffer = NULL; return 0; }
    *buffer = pointer ? GPTR(pointer) : NULL;
    return count;
}

static int back_output(void *opaque, unsigned char *buffer, unsigned count)
{
    back_callbacks *c = opaque;
    uintptr_t offset = (uintptr_t)buffer - (uintptr_t)GPTR(c->stream->window);
    if (offset > c->stream->window_size || count > c->stream->window_size - offset) return 1;
    const uint32_t args[] = {c->out_desc, c->stream->window + (uint32_t)offset, count};
    return (int)void_call_guest(c->output, 3, args, 0);
}

static void native_back(void)
{
    uint32_t guest = MEM32(g_esp + 4);
    back_stream *s = back_find(guest);
    if (!s) { original_back(); return; }
    back_callbacks c = {s, MEM32(g_esp + 8), MEM32(g_esp + 12), MEM32(g_esp + 16), MEM32(g_esp + 20)};
    if (s->busy || !void_vm_writable(guest, 56) || MEM32(guest + 28) != s->token ||
        !void_dispatch_find(c.input) || !void_dispatch_find(c.output) ||
        !void_vm_writable(s->window, s->window_size)) { back_return(Z_STREAM_ERROR); return; }
    uint32_t input = MEM32(guest), count = MEM32(guest + 4);
    if (input && count && !void_vm_readable(input, count)) { back_return(Z_STREAM_ERROR); return; }
    s->native.next_in = input ? GPTR(input) : NULL;
    s->native.avail_in = input ? count : 0;
    s->busy = 1;
    int result = inflateBack(&s->native, back_input, &c, back_output, &c);
    s->busy = 0;
    /* Only these fields are part of inflateBack's public output contract. */
    MEM32(guest) = s->native.next_in ? (uint32_t)((uintptr_t)s->native.next_in - (uintptr_t)GPTR(0)) : 0;
    MEM32(guest + 4) = s->native.avail_in;
    MEM32(guest + 24) = back_message(s->native.msg);
    back_return(result);
}

static void native_back_end(void)
{
    uint32_t guest = MEM32(g_esp + 4);
    back_stream *s = back_find(guest);
    if (!s) { original_end(); return; }
    if (s->busy || !void_vm_writable(guest, 56) || MEM32(guest + 28) != s->token ||
        !MEM32(guest + 36)) { back_return(Z_STREAM_ERROR); return; }
    int result = inflateBackEnd(&s->native);
    if (result == Z_OK) {
        back_stream **link = &streams;
        while (*link != s) link = &(*link)->next;
        *link = s->next;
        MEM32(guest + 28) = 0;
        void_gfree(s->token); free(s);
    }
    back_return(result);
}

/* ------------------------------------------------------------ deflate */
/* The game's deflate streams (saves: deflateInit_ at the default level in 32 KiB chunks;
 * deflateInit2_ level 9 raw -15 for one-shot buffers) run on zlib 1.3.1's deflate kept to
 * 1.2.3's per-call behaviour (zlib_deflate_native.c): every return code and every z_stream
 * field the guest sees is what zlib1.dll 1.2.3 leaves, call by call, and the bytes are the
 * same (tests/test_deflate_native.py against the DLL itself). Requests outside that tested
 * set (level 0, other window, memory or strategy values, custom allocators, versions or
 * sizes zlib1.dll refuses) keep the lifted DLL, as does <data>/native-deflate-original = 1;
 * <data>/native-deflate-live switches new streams live. The deflate state lives in native
 * memory, so the guest heap no longer holds it (as with inflateBack above) and strm->state is
 * a small guest token; the registers a cdecl callee may clobber are not reproduced. Every
 * stream logs its parameters, sizes and time when it ends, in both modes. zlib1.dll is the
 * same code in all three editions (1.2.3, one export table). */
enum { DEFLATE_INIT = 0x15001660u, DEFLATE_INIT2 = 0x15001690u, DEFLATE_RUN = 0x15001C70u,
       DEFLATE_END = 0x150024B0u, GUEST_ERRMSG = 0x1500EDD8u };
typedef struct deflate_stream {
    struct deflate_stream *next;
    uint32_t guest, token, serial;
    h5z_stream *native;                 /* NULL: the lifted zlib1.dll runs it (timed only) */
    int is_native, level, bits, calls;
    uint64_t in, out, ns;
} deflate_stream;
static deflate_stream *deflates;
static uint32_t deflate_serial;
static void_fn original_deflate_init, original_deflate_init2, original_deflate_run, original_deflate_end;

static int deflate_live_read(char *first)
{
    char path[1024];
    const char *directory = void_data_dir();
    int length = directory ? snprintf(path, sizeof path, "%s/native-deflate-live", directory) : -1;
    if (length < 0 || (size_t)length >= sizeof path) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    int c = fgetc(file);
    fclose(file);
    *first = c == EOF ? 0 : (char)c;
    return 1;
}

/* As vertex_native.c: a live file present at the first stream is read again at most once a
 * second ('1' the lifted DLL, anything else native); it decides for streams started later. */
static int deflate_original_choice(int cached)
{
    static int live = -2;               /* -2 not looked at, -1 no live file, 0/1 the live choice */
    static uint64_t next_read;
    char first = 0;
    if (live == -1) return cached;
    if (live == -2) {
        if (!deflate_live_read(&first)) { live = -1; return cached; }
    } else {
        const uint64_t now = void_perf_now_ns();
        if (now < next_read) return live;
        if (!deflate_live_read(&first)) first = live ? '1' : '0';
    }
    const int next = first == '1';
    next_read = void_perf_now_ns() + 1000000000ull;
    if (next != live) void_log("[deflate-native] live original=%d", next);
    live = next;
    return next;
}

static int deflate_native_enabled(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    const int cached = void_native_mode_get(&cache, "native-deflate-original", "[deflate-native] original=%d (cached for this process)");
    return !deflate_original_choice(cached);
}

static deflate_stream *deflate_find(uint32_t guest)
{
    for (deflate_stream *s = deflates; s; s = s->next) if (s->guest == guest) return s;
    return NULL;
}

static void deflate_forget(deflate_stream *s, int result)
{
    void_log("[deflate-native] stream %u %s: level %d bits %d, %llu -> %llu bytes in %d calls, %.2f ms, end %d",
             s->serial, s->is_native ? "native" : "original", s->level, s->bits, (unsigned long long)s->in,
             (unsigned long long)s->out, s->calls, (double)s->ns / 1e6, result);
    deflate_stream **link = &deflates;
    while (*link != s) link = &(*link)->next;
    *link = s->next;
    if (s->token) void_gfree(s->token);
    free(s);
}

/* deflateInit_ and deflateInit2_ (cdecl). */
static void deflate_start(void_fn original, uint32_t guest, int level, int method, int bits, int memory,
                          int strategy, uint32_t version, uint32_t size)
{
    deflate_stream *old = deflate_find(guest);
    if (old) {                          /* a re-init: zlib1.dll would drop the old state */
        if (old->native) h5z_deflate_end(old->native);
        old->native = NULL;
        deflate_forget(old, 1);   /* (logged as ended by a re-init) */
    }
    const int proven = method == 8 && memory == 8 && strategy == 0 && (bits == 15 || bits == -15) &&
                       (level == -1 || (level >= 1 && level <= 9)) && size == 56 && guest &&
                       void_vm_writable(guest, 56) && version && void_vm_readable(version, 1) && MEM8(version) == '1' &&
                       (!MEM32(guest + 32) || MEM32(guest + 32) == GUEST_ZALLOC) &&
                       (!MEM32(guest + 36) || MEM32(guest + 36) == GUEST_ZFREE);
    h5z_stream *native = NULL;
    uint32_t token = 0;
    if (!proven || !deflate_native_enabled() || h5z_deflate_init(&native, level, 8, bits, 8, 0) != 0 ||
        !(token = void_galloc(8))) {
        if (native) h5z_deflate_end(native);
        original();
        if (g_eax == 0 && guest) {      /* Z_OK: time the lifted stream too */
            deflate_stream *s = calloc(1, sizeof *s);
            if (s) {
                s->guest = guest; s->serial = ++deflate_serial; s->level = level; s->bits = bits;
                s->next = deflates; deflates = s;
            }
        }
        return;
    }
    deflate_stream *s = calloc(1, sizeof *s);
    if (!s) { h5z_deflate_end(native); void_gfree(token); original(); return; }
    s->guest = guest; s->token = token; s->serial = ++deflate_serial; s->native = native; s->is_native = 1;
    s->level = level; s->bits = bits;
    s->next = deflates; deflates = s;
    /* zlib 1.2.3 deflateInit2_ and deflateReset: msg, allocators, state, totals, type, adler. */
    MEM32(guest + 24) = 0;
    if (!MEM32(guest + 32)) { MEM32(guest + 32) = GUEST_ZALLOC; MEM32(guest + 40) = 0; }
    if (!MEM32(guest + 36)) MEM32(guest + 36) = GUEST_ZFREE;
    MEM32(guest + 28) = token;
    MEM32(guest + 8) = 0; MEM32(guest + 20) = 0;
    MEM32(guest + 44) = 2;              /* Z_UNKNOWN */
    MEM32(guest + 48) = 1;              /* adler32 of nothing */
    g_eax = 0; g_esp += 4;
}

static void native_deflate_init(void)
{
    const uint32_t e = g_esp;
    deflate_start(original_deflate_init, MEM32(e + 4), (int32_t)MEM32(e + 8), 8, 15, 8, 0, MEM32(e + 12), MEM32(e + 16));
}

static void native_deflate_init2(void)
{
    const uint32_t e = g_esp;
    deflate_start(original_deflate_init2, MEM32(e + 4), (int32_t)MEM32(e + 8), (int32_t)MEM32(e + 12),
                  (int32_t)MEM32(e + 16), (int32_t)MEM32(e + 20), (int32_t)MEM32(e + 24), MEM32(e + 28), MEM32(e + 32));
}

static void native_deflate_run(void)
{
    const uint32_t guest = MEM32(g_esp + 4);
    const int flush = (int32_t)MEM32(g_esp + 8);
    deflate_stream *s = deflate_find(guest);
    if (!s) { original_deflate_run(); return; }
    const uint64_t start = void_perf_now_ns();
    const uint32_t in0 = MEM32(guest + 8), out0 = MEM32(guest + 20);
    if (!s->native) {
        original_deflate_run();
    } else {
        int result = Z_STREAM_ERROR;    /* zlib1.dll: flush outside Z_NO_FLUSH..Z_FINISH */
        const uint32_t next_in = MEM32(guest), avail_in = MEM32(guest + 4);
        const uint32_t next_out = MEM32(guest + 12), avail_out = MEM32(guest + 16);
        if (MEM32(guest + 28) == s->token && flush >= 0 && flush <= 4 &&
            (!next_in || !avail_in || void_vm_readable(next_in, avail_in)) &&
            (!next_out || !avail_out || void_vm_writable(next_out, avail_out))) {
            h5z_io io = {next_in ? (const uint8_t *)GPTR(next_in) : NULL, avail_in, in0,
                         next_out ? (uint8_t *)GPTR(next_out) : NULL, avail_out, out0,
                         MEM32(guest + 48), (int32_t)MEM32(guest + 44), -1};
            result = h5z_deflate(s->native, &io, flush);
            MEM32(guest) = io.next_in ? GVA(io.next_in) : 0;
            MEM32(guest + 4) = io.avail_in;
            MEM32(guest + 8) = io.total_in;
            MEM32(guest + 12) = io.next_out ? GVA(io.next_out) : 0;
            MEM32(guest + 16) = io.avail_out;
            MEM32(guest + 20) = io.total_out;
            MEM32(guest + 44) = (uint32_t)io.data_type;
            MEM32(guest + 48) = io.adler;
            if (io.message >= 0) MEM32(guest + 24) = MEM32(GUEST_ERRMSG + 4u * (uint32_t)io.message);
        }
        g_eax = (uint32_t)result; g_esp += 4;
    }
    s->calls++;
    s->in += (uint32_t)(MEM32(guest + 8) - in0);
    s->out += (uint32_t)(MEM32(guest + 20) - out0);
    s->ns += void_perf_now_ns() - start;
}

static void native_deflate_end(void)
{
    const uint32_t guest = MEM32(g_esp + 4);
    deflate_stream *s = deflate_find(guest);
    if (!s) { original_deflate_end(); return; }
    if (!s->native) {
        original_deflate_end();
        deflate_forget(s, (int32_t)g_eax);
        return;
    }
    if (MEM32(guest + 28) != s->token) { g_eax = (uint32_t)Z_STREAM_ERROR; g_esp += 4; return; }
    const int result = h5z_deflate_end(s->native);
    s->native = NULL;
    MEM32(guest + 28) = 0;              /* strm->state = Z_NULL */
    deflate_forget(s, result);
    g_eax = (uint32_t)result; g_esp += 4;
}

void void_zlib_init(void)
{
    if (original_init || original_deflate_run) return;
    void_fn init = void_dispatch_find(BACK_INIT), run = void_dispatch_find(BACK_RUN), end = void_dispatch_find(BACK_END);
    if (init && run && end) {
        original_init = init; original_back = run; original_end = end;
        void_dispatch_add(BACK_INIT, native_back_init);
        void_dispatch_add(BACK_RUN, native_back);
        void_dispatch_add(BACK_END, native_back_end);
        void_log("[zlib] native inflateBack for default allocators; lifted fallback retained");
    }
    void_fn dinit = void_dispatch_find(DEFLATE_INIT), dinit2 = void_dispatch_find(DEFLATE_INIT2);
    void_fn drun = void_dispatch_find(DEFLATE_RUN), dend = void_dispatch_find(DEFLATE_END);
    if (dinit && dinit2 && drun && dend) {
        original_deflate_init = dinit; original_deflate_init2 = dinit2;
        original_deflate_run = drun; original_deflate_end = dend;
        void_dispatch_add(DEFLATE_INIT, native_deflate_init);
        void_dispatch_add(DEFLATE_INIT2, native_deflate_init2);
        void_dispatch_add(DEFLATE_RUN, native_deflate_run);
        void_dispatch_add(DEFLATE_END, native_deflate_end);
        void_log("[zlib] native deflate (zlib 1.3.1 kept to 1.2.3 call by call); lifted fallback retained");
    }
}
