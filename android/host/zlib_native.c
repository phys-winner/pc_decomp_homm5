/* The resource loader uses raw inflateBack with a caller-owned guest window.
 * Keep custom allocators and all other zlib entry points in the lifted DLL.
 * A 32-bit z_stream is 56 bytes; native pointers/longs cannot be stored in it. */
#include "host.h"
#include <zlib.h>

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

void void_zlib_init(void)
{
    if (original_init) return;
    void_fn init = void_dispatch_find(BACK_INIT), run = void_dispatch_find(BACK_RUN), end = void_dispatch_find(BACK_END);
    if (!init || !run || !end) return;
    original_init = init; original_back = run; original_end = end;
    void_dispatch_add(BACK_INIT, native_back_init);
    void_dispatch_add(BACK_RUN, native_back);
    void_dispatch_add(BACK_END, native_back_end);
    void_log("[zlib] native inflateBack for default allocators; lifted fallback retained");
}
