/* user32: window classes, one desktop of borderless top-level windows, the
 * per-thread message queues, PE string resources and the input state the
 * Android layer feeds (cursor position, key states). */
#define _GNU_SOURCE
#include "host.h"
#include "input.h"
#include <strings.h>
#include <time.h>

#define U32 "user32.dll"

#define WM_NULL 0x0000
#define WM_CREATE 0x0001
#define WM_DESTROY 0x0002
#define WM_MOVE 0x0003
#define WM_SIZE 0x0005
#define WM_ACTIVATE 0x0006
#define WM_SETFOCUS 0x0007
#define WM_KILLFOCUS 0x0008
#define WM_PAINT 0x000F
#define WM_CLOSE 0x0010
#define WM_QUIT 0x0012
#define WM_ERASEBKGND 0x0014
#define WM_SHOWWINDOW 0x0018
#define WM_ACTIVATEAPP 0x001C
#define WM_SETCURSOR 0x0020
#define WM_GETMINMAXINFO 0x0024
#define WM_WINDOWPOSCHANGING 0x0046
#define WM_WINDOWPOSCHANGED 0x0047
#define WM_NCCREATE 0x0081
#define WM_NCDESTROY 0x0082
#define WM_NCCALCSIZE 0x0083
#define WM_NCACTIVATE 0x0086
#define WM_KEYDOWN 0x0100
#define WM_KEYUP 0x0101
#define WM_CHAR 0x0102
#define WM_SYSKEYDOWN 0x0104
#define WM_SYSKEYUP 0x0105
#define WM_SYSCHAR 0x0106
#define WM_SYSCOMMAND 0x0112

/* ------------------------------------------------------------- classes */
typedef struct {
    char name[128];
    uint32_t atom, wndproc, style, extra, instance, background;
    int unicode;
} wclass_t;
static wclass_t classes[64];
static int class_count;
static uint32_t next_atom = 0xC100;

typedef struct {
    uint32_t hwnd;
    wclass_t *cls;
    uint32_t wndproc, style, exstyle, instance, parent, id, userdata;
    int x, y, w, h;
    int visible, unicode, alive;
    uint32_t thread;
    uint8_t extra[64];
    char title[256];
} window_t;
static window_t windows[32];
static int window_count;
static uint32_t main_window, focus_window;
static pthread_mutex_t user_lock = PTHREAD_MUTEX_INITIALIZER;

static wclass_t *find_class(const char *name, uint32_t atom)
{
    for (int i = 0; i < class_count; ++i) {
        if (atom && classes[i].atom == atom) return &classes[i];
        if (name && !strcasecmp(classes[i].name, name)) return &classes[i];
    }
    return NULL;
}

static window_t *find_window(uint32_t hwnd)
{
    for (int i = 0; i < window_count; ++i) if (windows[i].alive && windows[i].hwnd == hwnd) return &windows[i];
    return NULL;
}

uint32_t void_window_main(void) { return main_window; }

uint32_t void_window_thread(uint32_t hwnd)
{
    window_t *win = find_window(hwnd);
    return win ? win->thread : 0;
}

void void_window_client_size(uint32_t hwnd, int *w, int *h)
{
    window_t *win = find_window(hwnd ? hwnd : main_window);
    *w = win ? win->w : 0;
    *h = win ? win->h : 0;
}

/* The guest string at va as UTF-8: a class atom (MAKEINTATOM) yields NULL. */
static char *class_name(uint32_t va, int wide, uint32_t *atom)
{
    *atom = 0;
    if (va < 0x10000u) { *atom = va; return NULL; }
    return wide ? void_wstr_utf8(va) : void_astr_utf8(va);
}

static uint32_t register_class(uint32_t wc, int ex, int wide)
{
    /* WNDCLASSA: style, lpfnWndProc, cbClsExtra, cbWndExtra, hInstance, hIcon,
     * hCursor, hbrBackground, lpszMenuName, lpszClassName. WNDCLASSEX has cbSize first. */
    uint32_t base = ex ? wc + 4 : wc;
    uint32_t atom;
    char *name = class_name(MEM32(base + 36), wide, &atom);
    pthread_mutex_lock(&user_lock);
    if (!name || find_class(name, 0) || class_count >= 64) {
        pthread_mutex_unlock(&user_lock);
        free(name);
        void_set_last_error(ERROR_CLASS_ALREADY_EXISTS_);
        return 0;
    }
    wclass_t *c = &classes[class_count++];
    snprintf(c->name, sizeof c->name, "%s", name);
    c->style = MEM32(base);
    c->wndproc = MEM32(base + 4);
    c->extra = MEM32(base + 12);
    c->instance = MEM32(base + 16);
    c->background = MEM32(base + 28);
    c->unicode = wide;
    c->atom = next_atom++;
    pthread_mutex_unlock(&user_lock);
    VLOG("[void] RegisterClass %s wndproc=%08X atom=%04X", name, c->wndproc, c->atom);
    free(name);
    return c->atom;
}

WINAPI_EXPORT(U32, RegisterClassA, 1) { return register_class(ARG(0), 0, 0); }
WINAPI_EXPORT(U32, RegisterClassW, 1) { return register_class(ARG(0), 0, 1); }
WINAPI_EXPORT(U32, RegisterClassExA, 1) { return register_class(ARG(0), 1, 0); }
WINAPI_EXPORT(U32, RegisterClassExW, 1) { return register_class(ARG(0), 1, 1); }

static uint32_t unregister_class(uint32_t name_va, int wide)
{
    uint32_t atom;
    char *name = class_name(name_va, wide, &atom);
    pthread_mutex_lock(&user_lock);
    wclass_t *c = find_class(name, atom);
    if (c) c->name[0] = 0, c->atom = 0;
    pthread_mutex_unlock(&user_lock);
    free(name);
    return c != NULL;
}

WINAPI_EXPORT(U32, UnregisterClassA, 2) { return unregister_class(ARG(0), 0); }
WINAPI_EXPORT(U32, UnregisterClassW, 2) { return unregister_class(ARG(0), 1); }

/* ------------------------------------------------------------ messages */
typedef struct { uint32_t hwnd, msg, wparam, lparam, time, x, y; } qmsg_t;
typedef struct queue {
    uint32_t thread;
    qmsg_t items[1024];
    int head, count;
    int quit;
    uint32_t quit_code, active;
} queue_t;
static queue_t queues[32];
static int queue_count;

static queue_t *queue_for(uint32_t thread)
{
    for (int i = 0; i < queue_count; ++i) if (queues[i].thread == thread) return &queues[i];
    if (queue_count >= 32) return NULL;
    queues[queue_count].thread = thread;
    return &queues[queue_count++];
}

static void queue_push(uint32_t thread, uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam)
{
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(thread);
    if (q && q->count < 1024) {
        qmsg_t *m = &q->items[(q->head + q->count++) % 1024];
        m->hwnd = hwnd; m->msg = msg; m->wparam = wparam; m->lparam = lparam;
        m->time = void_tick_ms();
        void_input_cursor(&m->x, &m->y);
    } else if (q) {
        void_log("[void] message queue of thread %u is full; dropped %04X", thread, msg);
    }
    pthread_mutex_unlock(&user_lock);
    void_wait_broadcast();
}

/* A second press of the same button within the double-click time (500 ms)
 * and rectangle (4x4, SM_CXDOUBLECLK) becomes WM_xBUTTONDBLCLK for a window
 * whose class has CS_DBLCLKS, as Windows posts it; the press after that
 * starts a new pair. The Load game list opens a save on a double click. */
static uint32_t dblclk_translate(window_t *w, uint32_t msg, uint32_t lparam)
{
    static uint32_t last_msg, last_lparam;
    static double last_time;
    if (msg != 0x0201u && msg != 0x0204u && msg != 0x0207u) return msg;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    double now = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
    int dx = (int16_t)(lparam & 0xFFFF) - (int16_t)(last_lparam & 0xFFFF);
    int dy = (int16_t)(lparam >> 16) - (int16_t)(last_lparam >> 16);
    int pair = w->cls && (w->cls->style & 0x0008u) && last_msg == msg && now - last_time <= 0.5 &&
               dx >= -2 && dx <= 2 && dy >= -2 && dy <= 2;
    VLOG("[user32] button %04X at %d,%d: class style %08X%s", msg, (int16_t)(lparam & 0xFFFF),
         (int16_t)(lparam >> 16), w->cls ? w->cls->style : 0, pair ? " -> double click" : "");
    last_msg = pair ? 0 : msg;
    last_lparam = lparam;
    last_time = now;
    return pair ? msg + 2u : msg;
}

void void_post_message(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam)
{
    window_t *w = find_window(hwnd ? hwnd : main_window);
    if (!w) return;
    msg = dblclk_translate(w, msg, lparam);
    queue_push(w->thread, w->hwnd, msg, wparam, lparam);
}

static int matches(const qmsg_t *m, uint32_t hwnd, uint32_t lo, uint32_t hi)
{
    if (hwnd && hwnd != 0xFFFFFFFFu && m->hwnd != hwnd) return 0;
    if (hwnd == 0xFFFFFFFFu && m->hwnd) return 0;
    if (lo || hi) return m->msg >= lo && m->msg <= hi;
    return 1;
}

/* Remove the first matching message into out. Caller holds user_lock. */
static int queue_take(queue_t *q, uint32_t hwnd, uint32_t lo, uint32_t hi, int remove, qmsg_t *out)
{
    for (int i = 0; i < q->count; ++i) {
        qmsg_t *m = &q->items[(q->head + i) % 1024];
        if (!matches(m, hwnd, lo, hi)) continue;
        *out = *m;
        if (remove) {
            for (int k = i; k > 0; --k) q->items[(q->head + k) % 1024] = q->items[(q->head + k - 1) % 1024];
            q->head = (q->head + 1) % 1024;
            --q->count;
        }
        return 1;
    }
    if (q->quit && (!lo || (WM_QUIT >= lo && WM_QUIT <= hi))) {
        out->hwnd = 0; out->msg = WM_QUIT; out->wparam = q->quit_code; out->lparam = 0;
        out->time = void_tick_ms(); out->x = out->y = 0;
        if (remove) q->quit = 0;
        return 1;
    }
    return 0;
}

static void store_msg(uint32_t va, const qmsg_t *m)
{
    MEM32(va + 0) = m->hwnd; MEM32(va + 4) = m->msg; MEM32(va + 8) = m->wparam;
    MEM32(va + 12) = m->lparam; MEM32(va + 16) = m->time; MEM32(va + 20) = m->x; MEM32(va + 24) = m->y;
}

/* The Android layer's input reaches the queue through this pump. */
static void pump_host_input(void) { void_input_pump(); }

WINAPI_EXPORT(U32, PeekMessageA, 5)
{
    pump_host_input();
    uint32_t out = ARG(0), hwnd = ARG(1), lo = ARG(2), hi = ARG(3), flags = ARG(4);
    qmsg_t m;
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(void_thread_id());
    int got = q && queue_take(q, hwnd, lo, hi, (flags & 1u) != 0, &m);
    pthread_mutex_unlock(&user_lock);
    if (got) store_msg(out, &m);
    return (uint32_t)got;
}
WINAPI_EXPORT(U32, PeekMessageW, 5)
{
    pump_host_input();
    uint32_t out = ARG(0), hwnd = ARG(1), lo = ARG(2), hi = ARG(3), flags = ARG(4);
    qmsg_t m;
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(void_thread_id());
    int got = q && queue_take(q, hwnd, lo, hi, (flags & 1u) != 0, &m);
    pthread_mutex_unlock(&user_lock);
    if (got) store_msg(out, &m);
    return (uint32_t)got;
}

static int queue_nonempty(void *arg)
{
    queue_t *q = (queue_t *)arg;
    return q->count > 0 || q->quit;
}

WINAPI_EXPORT(U32, GetMessageA, 4)
{
    uint32_t out = ARG(0), hwnd = ARG(1), lo = ARG(2), hi = ARG(3);
    for (;;) {
        pump_host_input();
        qmsg_t m;
        pthread_mutex_lock(&user_lock);
        queue_t *q = queue_for(void_thread_id());
        int got = q && queue_take(q, hwnd, lo, hi, 1, &m);
        pthread_mutex_unlock(&user_lock);
        if (got) { store_msg(out, &m); return m.msg != WM_QUIT; }
        void_wait_extra_cond(0, NULL, 50, queue_nonempty, q);
    }
}

WINAPI_EXPORT(U32, GetQueueStatus, 1)
{
    pump_host_input();
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(void_thread_id());
    uint32_t bits = 0;
    if (q) for (int i = 0; i < q->count; ++i) {
        uint32_t msg = q->items[(q->head + i) % 1024].msg;
        if (msg >= 0x100 && msg <= 0x109) bits |= 0x0001;          /* QS_KEY */
        else if (msg >= 0x200 && msg <= 0x20E) bits |= 0x0006;     /* QS_MOUSE */
        else bits |= 0x0008;                                        /* QS_POSTMESSAGE */
    }
    pthread_mutex_unlock(&user_lock);
    return (bits << 16) | bits;
}

WINAPI_EXPORT(U32, MsgWaitForMultipleObjects, 5)
{
    uint32_t count = ARG(0), list = ARG(1), timeout = ARG(3);
    uint32_t handles[64];
    for (uint32_t i = 0; i < count && i < 63; ++i) handles[i] = MEM32(list + 4 * i);
    pump_host_input();
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(void_thread_id());
    pthread_mutex_unlock(&user_lock);
    return void_wait_extra_cond((int)count, handles, timeout, queue_nonempty, q);
}

WINAPI_EXPORT(U32, PostThreadMessageA, 4)
{
    queue_push(ARG(0), 0, ARG(1), ARG(2), ARG(3));
    return 1;
}

WINAPI_EXPORT(U32, PostMessageA, 4)
{
    window_t *w = find_window(ARG(0));
    if (!w && ARG(0)) { void_set_last_error(1400u); return 0; }
    queue_push(w ? w->thread : void_thread_id(), ARG(0), ARG(1), ARG(2), ARG(3));
    return 1;
}

WINAPI_EXPORT(U32, PostQuitMessage, 1)
{
    pthread_mutex_lock(&user_lock);
    queue_t *q = queue_for(void_thread_id());
    if (q) { q->quit = 1; q->quit_code = ARG(0); }
    pthread_mutex_unlock(&user_lock);
    void_log("[void] PostQuitMessage(%u) from %08X", ARG(0), g_cur_func);
    return 0;
}

static uint32_t send_message(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam)
{
    window_t *w = find_window(hwnd);
    if (!w || !w->wndproc) return 0;
    uint32_t args[4] = { hwnd, msg, wparam, lparam };
    return void_call_guest(w->wndproc, 4, args, 1);
}

uint32_t void_send_message(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam)
{
    return send_message(hwnd ? hwnd : main_window, msg, wparam, lparam);
}

WINAPI_EXPORT(U32, SendMessageA, 4) { return send_message(ARG(0), ARG(1), ARG(2), ARG(3)); }
WINAPI_EXPORT(U32, SendMessageW, 4) { return send_message(ARG(0), ARG(1), ARG(2), ARG(3)); }

WINAPI_EXPORT(U32, DispatchMessageA, 1)
{
    uint32_t m = ARG(0);
    if (!MEM32(m)) return 0;
    return send_message(MEM32(m), MEM32(m + 4), MEM32(m + 8), MEM32(m + 12));
}
WINAPI_EXPORT(U32, DispatchMessageW, 1)
{
    uint32_t m = ARG(0);
    if (!MEM32(m)) return 0;
    return send_message(MEM32(m), MEM32(m + 4), MEM32(m + 8), MEM32(m + 12));
}

WINAPI_EXPORT(U32, TranslateMessage, 1)
{
    uint32_t m = ARG(0), msg = MEM32(m + 4), vk = MEM32(m + 8);
    if (msg != WM_KEYDOWN && msg != WM_SYSKEYDOWN) return 0;
    uint32_t ch = void_input_vk_char(vk);
    if (!ch) return 0;
    window_t *w = find_window(MEM32(m));
    queue_push(w ? w->thread : void_thread_id(), MEM32(m), msg == WM_KEYDOWN ? WM_CHAR : WM_SYSCHAR, ch, MEM32(m + 12));
    return 1;
}

WINAPI_EXPORT(U32, RegisterWindowMessageA, 1)
{
    static char names[64][128];
    static int count;
    char *name = void_astr_utf8(ARG(0));
    uint32_t id = 0;
    pthread_mutex_lock(&user_lock);
    for (int i = 0; i < count; ++i) if (!strcasecmp(names[i], name)) id = 0xC000u + (uint32_t)i;
    if (!id && count < 64) { snprintf(names[count], 128, "%s", name); id = 0xC000u + (uint32_t)count++; }
    pthread_mutex_unlock(&user_lock);
    free(name);
    return id;
}

/* ------------------------------------------------------------- windows */
static uint32_t def_window_proc(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam)
{
    (void)wparam; (void)lparam;
    switch (msg) {
    case WM_NCCREATE: return 1;
    case WM_CLOSE: {
        uint32_t arg = hwnd;
        (void)arg;
        window_t *w = find_window(hwnd);
        if (w) {
            send_message(hwnd, WM_DESTROY, 0, 0);
            send_message(hwnd, WM_NCDESTROY, 0, 0);
            w->alive = 0;
            queue_t *q = queue_for(w->thread);
            if (q && q->active == hwnd) q->active = 0;
            if (focus_window == hwnd) focus_window = 0;
            if (main_window == hwnd) main_window = 0;
        }
        return 0;
    }
    case WM_ERASEBKGND: return 1;
    case WM_SETCURSOR: return 1;
    case WM_NCACTIVATE: return 1;
    case WM_SYSCOMMAND: return 0;
    default: return 0;
    }
}

WINAPI_EXPORT(U32, DefWindowProcA, 4) { return def_window_proc(ARG(0), ARG(1), ARG(2), ARG(3)); }
WINAPI_EXPORT(U32, DefWindowProcW, 4) { return def_window_proc(ARG(0), ARG(1), ARG(2), ARG(3)); }

static void notify_geometry(window_t *w)
{
    uint32_t pos = void_galloc(28);
    MEM32(pos) = w->hwnd; MEM32(pos + 8) = (uint32_t)w->x; MEM32(pos + 12) = (uint32_t)w->y;
    MEM32(pos + 16) = (uint32_t)w->w; MEM32(pos + 20) = (uint32_t)w->h;
    send_message(w->hwnd, WM_WINDOWPOSCHANGED, 0, pos);
    void_gfree(pos);
    send_message(w->hwnd, WM_SIZE, 0, ((uint32_t)(w->h & 0xFFFF) << 16) | (uint32_t)(w->w & 0xFFFF));
    send_message(w->hwnd, WM_MOVE, 0, ((uint32_t)(w->y & 0xFFFF) << 16) | (uint32_t)(w->x & 0xFFFF));
}

static void activate(window_t *w)
{
    queue_t *q = queue_for(w->thread);
    if (q) q->active = w->hwnd;
    if (focus_window == w->hwnd) return;
    focus_window = w->hwnd;
    send_message(w->hwnd, WM_ACTIVATEAPP, 1, 0);
    send_message(w->hwnd, WM_NCACTIVATE, 1, 0);
    send_message(w->hwnd, WM_ACTIVATE, 1, 0);       /* WA_ACTIVE */
    send_message(w->hwnd, WM_SETFOCUS, 0, 0);
}

static uint32_t create_window(uint32_t exstyle, uint32_t class_va, uint32_t title_va, uint32_t style,
    int x, int y, int cx, int cy, uint32_t parent, uint32_t menu, uint32_t instance, uint32_t param, int wide)
{
    uint32_t atom;
    char *name = class_name(class_va, wide, &atom);
    char *title = wide ? void_wstr_utf8(title_va) : void_astr_utf8(title_va);
    pthread_mutex_lock(&user_lock);
    wclass_t *c = find_class(name, atom);
    if (!c || window_count >= 32) {
        pthread_mutex_unlock(&user_lock);
        void_log("[void] CreateWindowEx: unknown class %s", name ? name : "(atom)");
        free(name); free(title);
        void_set_last_error(1407u);    /* ERROR_CANNOT_FIND_WND_CLASS */
        return 0;
    }
    window_t *w = &windows[window_count];
    memset(w, 0, sizeof *w);
    w->hwnd = 0x00010010u + 0x10u * (uint32_t)window_count++;
    w->cls = c;
    w->wndproc = c->wndproc;
    w->style = style;
    w->exstyle = exstyle;
    w->instance = instance;
    w->parent = parent;
    w->id = menu;
    int sw, sh;
    void_input_screen_size(&sw, &sh);
    w->x = x == (int)0x80000000 ? 0 : x;
    w->y = y == (int)0x80000000 ? 0 : y;
    w->w = cx == (int)0x80000000 ? sw : cx;
    w->h = cy == (int)0x80000000 ? sh : cy;
    w->unicode = wide;
    w->alive = 1;
    w->thread = void_thread_id();
    snprintf(w->title, sizeof w->title, "%s", title ? title : "");
    if (!parent && !main_window) main_window = w->hwnd;
    pthread_mutex_unlock(&user_lock);
    void_log("[void] CreateWindowEx class=%s title=\"%s\" style=%08X ex=%08X %dx%d at %d,%d -> %08X",
        c->name, w->title, style, exstyle, w->w, w->h, w->x, w->y, w->hwnd);
    free(name); free(title);
    /* CREATESTRUCT for WM_NCCREATE/WM_CREATE. */
    uint32_t cs = void_galloc(48);
    MEM32(cs + 0) = param; MEM32(cs + 4) = instance; MEM32(cs + 8) = menu; MEM32(cs + 12) = parent;
    MEM32(cs + 16) = (uint32_t)w->h; MEM32(cs + 20) = (uint32_t)w->w;
    MEM32(cs + 24) = (uint32_t)w->y; MEM32(cs + 28) = (uint32_t)w->x;
    MEM32(cs + 32) = style; MEM32(cs + 36) = title_va; MEM32(cs + 40) = class_va; MEM32(cs + 44) = exstyle;
    uint32_t hwnd = w->hwnd;
    uint32_t minmax = void_galloc(40);
    send_message(hwnd, WM_GETMINMAXINFO, 0, minmax);
    void_gfree(minmax);
    if (!send_message(hwnd, WM_NCCREATE, 0, cs)) {
        void_log("[void] WM_NCCREATE rejected window %08X", hwnd);
        void_gfree(cs);
        w->alive = 0;
        return 0;
    }
    send_message(hwnd, WM_NCCALCSIZE, 0, 0);
    if (send_message(hwnd, WM_CREATE, 0, cs) == 0xFFFFFFFFu) {
        void_log("[void] WM_CREATE rejected window %08X", hwnd);
        void_gfree(cs);
        w->alive = 0;
        return 0;
    }
    void_gfree(cs);
    notify_geometry(w);
    if (style & 0x10000000u) {           /* WS_VISIBLE */
        w->visible = 1;
        send_message(hwnd, WM_SHOWWINDOW, 1, 0);
        activate(w);
    }
    return hwnd;
}

WINAPI_EXPORT(U32, CreateWindowExA, 12)
{
    return create_window(ARG(0), ARG(1), ARG(2), ARG(3), (int)ARG(4), (int)ARG(5), (int)ARG(6), (int)ARG(7),
        ARG(8), ARG(9), ARG(10), ARG(11), 0);
}

WINAPI_EXPORT(U32, CreateWindowExW, 12)
{
    return create_window(ARG(0), ARG(1), ARG(2), ARG(3), (int)ARG(4), (int)ARG(5), (int)ARG(6), (int)ARG(7),
        ARG(8), ARG(9), ARG(10), ARG(11), 1);
}

WINAPI_EXPORT(U32, DestroyWindow, 1)
{
    window_t *w = find_window(ARG(0));
    if (!w) { void_set_last_error(1400u); return 0; }
    send_message(w->hwnd, WM_DESTROY, 0, 0);
    send_message(w->hwnd, WM_NCDESTROY, 0, 0);
    w->alive = 0;
    queue_t *q = queue_for(w->thread);
    if (q && q->active == w->hwnd) q->active = 0;
    if (focus_window == w->hwnd) focus_window = 0;
    if (main_window == w->hwnd) main_window = 0;
    return 1;
}

WINAPI_EXPORT(U32, ShowWindow, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    int was = w->visible;
    uint32_t cmd = ARG(1);
    int show = cmd != 0;                 /* SW_HIDE */
    VLOG("[void] ShowWindow(%08X, %u)", w->hwnd, cmd);
    if (show && !was) {
        w->visible = 1;
        send_message(w->hwnd, WM_SHOWWINDOW, 1, 0);
        notify_geometry(w);
        activate(w);
    } else if (!show && was) {
        w->visible = 0;
        send_message(w->hwnd, WM_SHOWWINDOW, 0, 0);
    }
    return (uint32_t)was;
}

WINAPI_EXPORT(U32, UpdateWindow, 1)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    send_message(w->hwnd, WM_PAINT, 0, 0);
    return 1;
}

WINAPI_EXPORT(U32, SetWindowPos, 7)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    uint32_t flags = ARG(6);
    if (!(flags & 0x0002u)) { w->x = (int)ARG(2); w->y = (int)ARG(3); }   /* SWP_NOMOVE */
    if (!(flags & 0x0001u)) { w->w = (int)ARG(4); w->h = (int)ARG(5); }   /* SWP_NOSIZE */
    if (flags & 0x0040u) w->visible = 1;                                  /* SWP_SHOWWINDOW */
    if (flags & 0x0080u) w->visible = 0;                                  /* SWP_HIDEWINDOW */
    VLOG("[void] SetWindowPos(%08X) -> %dx%d at %d,%d flags %X", w->hwnd, w->w, w->h, w->x, w->y, flags);
    notify_geometry(w);
    return 1;
}

WINAPI_EXPORT(U32, MoveWindow, 6)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    w->x = (int)ARG(1); w->y = (int)ARG(2); w->w = (int)ARG(3); w->h = (int)ARG(4);
    notify_geometry(w);
    return 1;
}

WINAPI_EXPORT(U32, AdjustWindowRectEx, 4)
{
    /* Windows here are borderless: the client rectangle is the window. */
    return 1;
}
WINAPI_EXPORT(U32, AdjustWindowRect, 3) { return 1; }

static uint32_t store_rect(uint32_t out, int l, int t, int r, int b)
{
    MEM32(out) = (uint32_t)l; MEM32(out + 4) = (uint32_t)t; MEM32(out + 8) = (uint32_t)r; MEM32(out + 12) = (uint32_t)b;
    return 1;
}

WINAPI_EXPORT(U32, GetClientRect, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) { void_set_last_error(1400u); return 0; }
    return store_rect(ARG(1), 0, 0, w->w, w->h);
}

WINAPI_EXPORT(U32, GetWindowRect, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) { void_set_last_error(1400u); return 0; }
    return store_rect(ARG(1), w->x, w->y, w->x + w->w, w->y + w->h);
}

WINAPI_EXPORT(U32, ClientToScreen, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    MEM32(ARG(1)) += (uint32_t)w->x;
    MEM32(ARG(1) + 4) += (uint32_t)w->y;
    return 1;
}

WINAPI_EXPORT(U32, ScreenToClient, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) return 0;
    MEM32(ARG(1)) -= (uint32_t)w->x;
    MEM32(ARG(1) + 4) -= (uint32_t)w->y;
    return 1;
}

WINAPI_EXPORT(U32, GetWindowLongA, 2)
{
    window_t *w = find_window(ARG(0));
    if (!w) { void_set_last_error(1400u); return 0; }
    int32_t index = (int32_t)ARG(1);
    switch (index) {
    case -4: return w->wndproc;
    case -6: return w->instance;
    case -8: return w->parent;
    case -12: return w->id;
    case -16: return w->style | (w->visible ? 0x10000000u : 0);
    case -20: return w->exstyle;
    case -21: return w->userdata;
    default:
        if (index >= 0 && index + 4 <= 64) { uint32_t v; memcpy(&v, w->extra + index, 4); return v; }
        return 0;
    }
}

static uint32_t set_window_long(void)
{
    window_t *w = find_window(ARG(0));
    if (!w) { void_set_last_error(1400u); return 0; }
    int32_t index = (int32_t)ARG(1);
    uint32_t value = ARG(2), old = 0;
    switch (index) {
    case -4: old = w->wndproc; w->wndproc = value; break;
    case -16: old = w->style; w->style = value; break;
    case -20: old = w->exstyle; w->exstyle = value; break;
    case -21: old = w->userdata; w->userdata = value; break;
    case -12: old = w->id; w->id = value; break;
    default:
        if (index >= 0 && index + 4 <= 64) { memcpy(&old, w->extra + index, 4); memcpy(w->extra + index, &value, 4); }
        break;
    }
    return old;
}

WINAPI_EXPORT(U32, SetWindowLongA, 3) { return set_window_long(); }
WINAPI_EXPORT(U32, SetWindowLongW, 3) { return set_window_long(); }

WINAPI_EXPORT(U32, SetWindowTextW, 2)
{
    window_t *w = find_window(ARG(0));
    char *t = void_wstr_utf8(ARG(1));
    if (w && t) snprintf(w->title, sizeof w->title, "%s", t);
    VLOG("[void] SetWindowTextW: %s", t ? t : "");
    free(t);
    return w != NULL;
}

WINAPI_EXPORT(U32, SetWindowTextA, 2)
{
    window_t *w = find_window(ARG(0));
    char *t = void_astr_utf8(ARG(1));
    if (w && t) snprintf(w->title, sizeof w->title, "%s", t);
    free(t);
    return w != NULL;
}

WINAPI_EXPORT(U32, GetForegroundWindow, 0) { return focus_window ? focus_window : main_window; }
WINAPI_EXPORT(U32, GetActiveWindow, 0) { queue_t *q = queue_for(void_thread_id()); return q ? q->active : 0; }
WINAPI_EXPORT(U32, SetActiveWindow, 1)
{
    window_t *w = ARG(0) ? find_window(ARG(0)) : NULL;
    if (ARG(0) && !w) { void_set_last_error(1400u); return 0; }
    queue_t *q = queue_for(void_thread_id());
    uint32_t old = q ? q->active : 0;
    if (w && w->thread == void_thread_id()) {
        if (w->style & 0x40000000u) return 0;   /* WS_CHILD cannot be active. */
        activate(w);
        return old;
    }
    if (q) q->active = 0;
    if (old && focus_window == old) {
        focus_window = 0;
        send_message(old, WM_NCACTIVATE, 0, 0);
        send_message(old, WM_ACTIVATE, 0, 0);
        send_message(old, WM_KILLFOCUS, 0, 0);
    }
    return w ? 0 : old;   /* A foreign thread's window cannot become this queue's active window. */
}
WINAPI_EXPORT(U32, GetFocus, 0) { return focus_window; }
WINAPI_EXPORT(U32, SetForegroundWindow, 1) { return 1; }
WINAPI_EXPORT(U32, SetFocus, 1) { uint32_t old = focus_window; focus_window = ARG(0); return old; }
WINAPI_EXPORT(U32, GetMenu, 1) { return 0; }
WINAPI_EXPORT(U32, IsWindow, 1) { return find_window(ARG(0)) != NULL; }
WINAPI_EXPORT(U32, IsWindowVisible, 1) { window_t *w = find_window(ARG(0)); return w && w->visible; }
WINAPI_EXPORT(U32, IsIconic, 1) { return 0; }
WINAPI_EXPORT(U32, GetDesktopWindow, 0) { return 0x00010000u; }

/* ------------------------------------------------------------- metrics */
WINAPI_EXPORT(U32, GetSystemMetrics, 1)
{
    int sw, sh;
    void_input_screen_size(&sw, &sh);
    switch (ARG(0)) {
    case 0: case 16: case 78: return (uint32_t)sw;    /* SM_CXSCREEN, SM_CXFULLSCREEN, SM_CXVIRTUALSCREEN */
    case 1: case 17: case 79: return (uint32_t)sh;
    case 2: case 3: return 17;                        /* scroll bars */
    case 4: return 23;                                /* SM_CYCAPTION */
    case 5: case 6: return 1;                         /* borders */
    case 7: case 8: return 3;                         /* dialog frame */
    case 11: case 12: return 32;                      /* icon */
    case 13: case 14: return 32;                      /* cursor */
    case 19: return 1;                                /* SM_MOUSEPRESENT */
    case 23: return 0;                                /* SM_SWAPBUTTON */
    case 32: case 33: return 4;                       /* frame */
    case 36: case 37: return 4;                       /* double click */
    case 43: return 3;                                /* SM_CMOUSEBUTTONS */
    case 75: return 1;                                /* SM_MOUSEWHEELPRESENT */
    case 76: case 77: return 0;                       /* virtual screen origin */
    case 80: return 1;                                /* SM_CMONITORS */
    case 0x1000: return 0;                            /* SM_REMOTESESSION */
    default: return 0;
    }
}

/* -------------------------------------------------------- cursor & keys */
WINAPI_EXPORT(U32, GetCursorPos, 1)
{
    uint32_t x, y;
    void_input_cursor(&x, &y);
    MEM32(ARG(0)) = x;
    MEM32(ARG(0) + 4) = y;
    return 1;
}

WINAPI_EXPORT(U32, SetCursorPos, 2) { void_input_set_cursor((int)ARG(0), (int)ARG(1)); return 1; }

static int cursor_count;
static uint32_t current_cursor = 0x00020001u;
static uint8_t shared_cursors[256] = {1};
WINAPI_EXPORT(U32, ShowCursor, 1)
{
    cursor_count += ARG(0) ? 1 : -1;
    return (uint32_t)cursor_count;
}

WINAPI_EXPORT(U32, ClipCursor, 1) { return 1; }
static int shared_cursor(uint32_t handle)
{
    return handle >= 0x00020001u && handle <= 0x00020100u && shared_cursors[handle - 0x00020001u];
}
WINAPI_EXPORT(U32, SetCursor, 1)
{
    if (ARG(0) && !shared_cursor(ARG(0))) { void_set_last_error(1402u); return 0; }
    uint32_t old = current_cursor;
    current_cursor = ARG(0);
    return old;
}
WINAPI_EXPORT(U32, GetCursor, 0) { return current_cursor; }
WINAPI_EXPORT(U32, GetKeyState, 1) { return (uint32_t)(int32_t)void_input_key_state(ARG(0) & 0xFF); }
WINAPI_EXPORT(U32, GetAsyncKeyState, 1) { return (uint32_t)(int32_t)void_input_key_state(ARG(0) & 0xFF); }
static uint32_t load_shared_cursor(uint32_t instance, uint32_t name)
{
    if (instance || name >= 0x10000u) { void_set_last_error(ERROR_NOT_SUPPORTED_); return 0; }
    switch (name) {
    case 32512: case 32513: case 32514: case 32515: case 32516:
    case 32640: case 32641: case 32642: case 32643: case 32644: case 32645:
    case 32646: case 32648: case 32649: case 32650: case 32651: case 32671: case 32672:
        shared_cursors[name & 0xFFu] = 1;
        return 0x00020001u + (name & 0xFFu);
    default: void_set_last_error(1814u); return 0;
    }
}
WINAPI_EXPORT(U32, LoadCursorA, 2) { return load_shared_cursor(ARG(0), ARG(1)); }
WINAPI_EXPORT(U32, LoadCursorW, 2) { return load_shared_cursor(ARG(0), ARG(1)); }
WINAPI_EXPORT(U32, LoadCursorFromFileA, 1) { void_set_last_error(ERROR_NOT_SUPPORTED_); return 0; }
WINAPI_EXPORT(U32, DestroyCursor, 1)
{
    if (!shared_cursor(ARG(0))) { void_set_last_error(1402u); return 0; }
    if (current_cursor == ARG(0)) { void_set_last_error(170u); return 0; }   /* ERROR_BUSY */
    return 1;   /* Shared system cursors remain valid for the module lifetime. */
}
WINAPI_EXPORT(U32, LoadIconW, 2) { return 0x00030001u + (ARG(1) & 0xFFu); }
WINAPI_EXPORT(U32, LoadIconA, 2) { return 0x00030001u + (ARG(1) & 0xFFu); }

WINAPI_EXPORT(U32, CharLowerA, 1)
{
    uint32_t address = ARG(0);
    if (address < 0x10000u) return (address & 0xFF00u) | void_ansi_lower((uint8_t)address);
    uint32_t end = address;
    for (;;) {
        if (!void_vm_readable(end, 1)) { void_set_last_error(ERROR_INVALID_ADDRESS_); return 0; }
        if (!MEM8(end)) break;
        if (end == UINT32_MAX) { void_set_last_error(ERROR_INVALID_ADDRESS_); return 0; }
        ++end;
    }
    if (!void_vm_writable(address, end - address + 1)) { void_set_last_error(ERROR_INVALID_ADDRESS_); return 0; }
    for (uint32_t p = address; p < end; ++p) MEM8(p) = void_ansi_lower(MEM8(p));
    return address;
}

/* ---------------------------------------------------------- resources */
/* Find a resource data entry: type / name (ids only) / first language. */
uint32_t void_resource_find(uint32_t module, uint32_t type, uint32_t name, uint32_t *size)
{
    if (!module) module = void_module_exe_base();
    uint32_t nt = module + MEM32(module + 0x3C);
    uint32_t rva = MEM32(nt + 0x78 + 8 * 2);
    if (!rva) return 0;
    uint32_t root = module + rva;
    uint32_t ids[2] = { type, name };
    uint32_t dir = root;
    for (int level = 0; level < 3; ++level) {
        uint32_t named = MEM16(dir + 12), idcount = MEM16(dir + 14);
        uint32_t entry = dir + 16, found = 0;
        for (uint32_t i = 0; i < named + idcount; ++i, entry += 8) {
            uint32_t id = MEM32(entry), offset = MEM32(entry + 4);
            if (level == 2 || (!(id & 0x80000000u) && id == ids[level])) { found = offset; break; }
        }
        if (!found) return 0;
        if (found & 0x80000000u) dir = root + (found & 0x7FFFFFFFu);
        else {
            uint32_t data = root + found;
            if (size) *size = MEM32(data + 4);
            return module + MEM32(data);
        }
    }
    return 0;
}

WINAPI_EXPORT(U32, LoadStringW, 4)
{
    uint32_t module = ARG(0), id = ARG(1), buffer = ARG(2), cap = ARG(3);
    uint32_t size = 0;
    uint32_t block = void_resource_find(module, 6u, id / 16u + 1u, &size);
    if (!block) { if (cap) MEM16(buffer) = 0; return 0; }
    uint32_t p = block;
    for (uint32_t i = 0; i < (id & 15u); ++i) p += 2u + 2u * MEM16(p);
    uint32_t len = MEM16(p);
    if (!cap) { MEM32(buffer) = p + 2; return len; }   /* read-only pointer form */
    uint32_t n = len < cap - 1 ? len : cap - 1;
    memcpy(GPTR(buffer), GPTR(p + 2), 2 * n);
    MEM16(buffer + 2 * n) = 0;
    return n;
}

WINAPI_EXPORT(U32, LoadStringA, 4)
{
    uint32_t module = ARG(0), id = ARG(1), buffer = ARG(2), cap = ARG(3);
    uint32_t size = 0;
    uint32_t block = void_resource_find(module, 6u, id / 16u + 1u, &size);
    if (!block || !cap) { if (cap) MEM8(buffer) = 0; return 0; }
    uint32_t p = block;
    for (uint32_t i = 0; i < (id & 15u); ++i) p += 2u + 2u * MEM16(p);
    uint32_t len = MEM16(p), n = len < cap - 1 ? len : cap - 1;
    for (uint32_t i = 0; i < n; ++i) {
        uint8_t b;
        void_u16_to_ansi(MEM16(p + 2 + 2 * i), &b);
        MEM8(buffer + i) = b;
    }
    MEM8(buffer + n) = 0;
    return n;
}

/* --------------------------------------------------------- message boxes */
static uint32_t message_box(uint32_t text_va, uint32_t caption_va, uint32_t type, int wide)
{
    char *text = wide ? void_wstr_utf8(text_va) : void_astr_utf8(text_va);
    char *caption = wide ? void_wstr_utf8(caption_va) : void_astr_utf8(caption_va);
    void_log("[void] MessageBox(\"%s\", \"%s\", %08X) from %08X", caption ? caption : "", text ? text : "", type, g_cur_func);
    free(text); free(caption);
    /* No interactive dialogs: the affirmative default the guest offers. */
    switch (type & 0xFu) {
    case 1: return 1;      /* MB_OKCANCEL -> IDOK */
    case 2: return 3;      /* MB_ABORTRETRYIGNORE -> IDABORT */
    case 3: case 4: return 6;   /* YESNO(CANCEL) -> IDYES */
    case 5: return 2;      /* MB_RETRYCANCEL -> IDCANCEL */
    default: return 1;
    }
}

WINAPI_EXPORT(U32, MessageBoxA, 4) { return message_box(ARG(1), ARG(2), ARG(3), 0); }
WINAPI_EXPORT(U32, MessageBoxW, 4) { return message_box(ARG(1), ARG(2), ARG(3), 1); }

WINAPI_EXPORT(U32, DrawTextA, 5)
{
    char *text = void_astr_utf8(ARG(1));
    VLOG("[void] DrawTextA(%08X, \"%s\")", ARG(0), text ? text : "");
    free(text);
    return 16;
}

WINAPI_EXPORT(U32, GetDC, 1) { return 0x00040001u; }
WINAPI_EXPORT(U32, ReleaseDC, 2) { return 1; }
/* shortcut: GDI splash bitmaps are unavailable; add bitmap surfaces if game rendering requires them. */
WINAPI_EXPORT(U32, LoadImageA, 6)
{
    void_log("[user32] LoadImageA type %u unavailable (caller %08X)", ARG(2), g_cur_func);
    void_set_last_error(ERROR_NOT_SUPPORTED_);
    return 0;
}
WINAPI_EXPORT(U32, InvalidateRect, 3) { return 1; }
WINAPI_EXPORT(U32, ValidateRect, 2) { return 1; }
