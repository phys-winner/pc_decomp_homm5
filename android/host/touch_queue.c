/* UI threads only record intent; engine callbacks run on the window's guest thread. */
#include "host.h"
#include "touch.h"
#include <math.h>

#define TOUCH_QUEUE_CAPACITY 256
static pthread_mutex_t touch_lock = PTHREAD_MUTEX_INITIALIZER;
static void_touch_event touch_queue[TOUCH_QUEUE_CAPACITY];
static uint64_t touch_sequence[TOUCH_QUEUE_CAPACITY], touch_next;
static unsigned touch_head, touch_count;
static int touch_dropping, touch_pumping;
static int pointer_mode_requested;

static void touch_abort_locked(void)
{
    pointer_mode_requested = 0;
    touch_queue[0] = (void_touch_event){ TOUCH_ABORT, 0, 0, 0, 0, 1, 0 };
    touch_sequence[0] = ++touch_next;
    touch_head = 0;
    touch_count = 1;
    touch_dropping = 1;
}

void void_touch_enqueue(const void_touch_event *event)
{
    pthread_mutex_lock(&touch_lock);
    if (!event || event->kind < TOUCH_BEGIN || event->kind > TOUCH_KIND_LAST ||
        !isfinite(event->x) || !isfinite(event->y) || !isfinite(event->dx) ||
        !isfinite(event->dy) || !isfinite(event->scale) || event->scale <= 0 ||
        !isfinite(event->rotation) || fabsf(event->rotation) > 3.141593f) {
        touch_abort_locked();
    } else if (event->kind == TOUCH_ABORT || event->kind == TOUCH_POINTER) {
        if (event->kind != TOUCH_POINTER || !pointer_mode_requested) {
            touch_abort_locked();
            touch_queue[0].kind = event->kind;
        }
        if (event->kind == TOUCH_POINTER) pointer_mode_requested = 1;
    } else {
        if (event->kind == TOUCH_BEGIN) { touch_dropping = 0; pointer_mode_requested = 0; }
        if (!touch_dropping || event->kind == TOUCH_PAD_CAMERA || event->kind == TOUCH_POINTER_CLICK) {
            if (touch_count == TOUCH_QUEUE_CAPACITY) touch_abort_locked();
            else {
                unsigned index = (touch_head + touch_count++) % TOUCH_QUEUE_CAPACITY;
                touch_queue[index] = *event;
                touch_sequence[index] = ++touch_next;
            }
        }
    }
    pthread_mutex_unlock(&touch_lock);
}

void void_touch_pump(void)
{
    uint32_t hwnd = void_window_main();
    if (!hwnd || void_window_thread(hwnd) != void_thread_id() || touch_pumping) return;
    pthread_mutex_lock(&touch_lock);
    unsigned count = touch_count;
    uint64_t cutoff = touch_next;
    pthread_mutex_unlock(&touch_lock);
    void_regs saved;
    void_regs_save(&saved);
    touch_pumping = 1;
    for (unsigned i = 0; i < count; ++i) {
        pthread_mutex_lock(&touch_lock);
        if (!touch_count || touch_sequence[touch_head] > cutoff ||
            !void_touch_engine_ready(touch_queue[touch_head].kind)) {
            pthread_mutex_unlock(&touch_lock);
            break;
        }
        void_touch_event event = touch_queue[touch_head];
        touch_head = (touch_head + 1) % TOUCH_QUEUE_CAPACITY;
        --touch_count;
        pthread_mutex_unlock(&touch_lock);
        /* Native callbacks need the full x87 stack; the interrupted temporaries are saved. */
        g_fp_top = 0;
        void_touch_engine_event(&event);
        void_regs_load(&saved);
    }
    g_fp_top = 0;
    void_port_settings_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_render_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_scale_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_ui_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_text_pump();
    void_regs_load(&saved);
    touch_pumping = 0;
}

void void_touch_render_frame_pump(void)
{
    uint32_t hwnd = void_window_main();
    if (!hwnd || void_window_thread(hwnd) != void_thread_id() || touch_pumping) return;
    void_regs saved;
    void_regs_save(&saved);
    touch_pumping = 1;
    g_fp_top = 0;
    void_port_settings_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_render_pump();
    void_regs_load(&saved);
    g_fp_top = 0;
    void_touch_scale_pump();
    void_regs_load(&saved);
    touch_pumping = 0;
}
