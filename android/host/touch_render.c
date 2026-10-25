/* Change the real H5 backbuffer through its existing device/resource reset. */
#include "d3d9_internal.h"
#include "input.h"
#include "touch.h"
#include <math.h>
#include <string.h>

extern int void_android_display_size(int *w, int *h) __attribute__((weak));
extern int void_android_render_ready(void) __attribute__((weak));

static pthread_mutex_t render_lock = PTHREAD_MUTEX_INITIALIZER;
static int render_percent = 100;
static uint64_t render_request = 1;
static struct {
    uint64_t request;
    uint32_t device, width, height;
    int physical_w, physical_h, failed;
} render_attempt;

static uint32_t render_read32(uint32_t address)
{
    return void_vm_readable(address, 4) ? MEM32(address) : 0;
}

static uint32_t render_current_screen(void)
{
    uint32_t screens = render_read32(0x00FE719Cu);
    if (!screens || !void_vm_readable(screens, 12) ||
        !void_dispatch_find(0x008385A0u) || !void_dispatch_find(0x00D119FCu)) return 0;
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1);
    uint32_t table = interface ? render_read32(interface + 4) : 0;
    if (!table || !void_vm_readable(table + 4, 4)) return 0;
    uint32_t base = interface + 4 + MEM32(table + 4);
    if (!void_vm_readable(base, 4)) return 0;
    const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
    uint32_t screen = void_call_guest(0x00D119FCu, 5, args, 0);
    if (!void_vm_readable(screen, 0x150) || MEM32(screen) == 0x00E34674u) return 0;
    uint32_t pending = MEM32(screen + 0x14C);
    return pending && render_read32(pending) == pending ? screen : 0;
}

static int render_device_ready(uint32_t device, uint32_t hwnd)
{
    uint32_t table = render_read32(device);
    return device && table && void_vm_readable(table, 0xAC) &&
           void_dispatch_find(MEM32(table + 0x40)) &&
           void_dispatch_find(MEM32(table + 0xA8)) &&
           g_d3d_device && g_d3d_device->com.guest == device &&
           g_d3d_device->window == hwnd && !g_d3d_device->in_scene &&
           !g_d3d_device->recording;
}

static uint32_t render_reset(uint32_t device, uint32_t hwnd)
{
    d3d_device *owner = g_d3d_device;
    uint32_t result = void_call_guest(0x00A3FFC0u, 0, NULL, 1);
    if (!owner || g_d3d_device != owner || owner->com.guest != device ||
        owner->window != hwnd || MEM32(0x010029A8u) != device ||
        void_window_main() != hwnd || void_window_thread(hwnd) != void_thread_id())
        return result ? result : D3DERR_INVALIDCALL;
    /* Native reset ends with BeginScene. Return to this caller's closed frame boundary. */
    if (owner->in_scene) {
        uint32_t table = render_read32(device), end = render_read32(table + 0xA8);
        if (!end || !void_dispatch_find(end) || owner->recording)
            return result ? result : D3DERR_INVALIDCALL;
        uint32_t ended = void_call_guest(end, 1, &device, 1);
        if (g_d3d_device != owner || owner->in_scene)
            return result ? result : D3DERR_INVALIDCALL;
        if (!result) result = ended;
    }
    return result;
}

static void render_resize_ui(uint32_t width, uint32_t height)
{
    if (MEMF(0x00F74BF0u) == (float)width && MEMF(0x00F74BF4u) == (float)height) return;
    /* Original UI resize is fastcall(width,height), RET 0. It owns coordinate
       updates and relayout; the following scale pump restores the chosen UI size. */
    g_ecx = width; g_edx = height;
    void_call_guest(0x00B295D0u, 0, NULL, 1);
}

void void_touch_set_render_scale(float scale)
{
    if (!isfinite(scale)) return;
    int percent = (int)lroundf(fminf(1, fmaxf(0.25f, scale)) * 100);
    pthread_mutex_lock(&render_lock);
    render_percent = percent;
    if (!++render_request) ++render_request;
    pthread_mutex_unlock(&render_lock);
}

void void_touch_render_pump(void)
{
    if (!void_android_display_size || !void_android_render_ready ||
        !void_android_render_ready() || void_module_exe_base() != 0x00400000u ||
        !void_vm_writable(0x01002930u, 14 * 4) ||
        !void_vm_readable(0x01002991u, 1) || !MEM8(0x01002991u) ||
        !void_vm_readable(0x010029A8u, 4) ||
        !void_vm_readable(0x00F74BF0u, 8) ||
        !void_dispatch_find(0x00A3FFC0u) || !void_dispatch_find(0x00B295D0u)) return;
    uint32_t hwnd = void_window_main(), device = MEM32(0x010029A8u);
    if (!hwnd || void_window_thread(hwnd) != void_thread_id() ||
        render_read32(0x010024FCu) != hwnd || MEM32(0x0100294Cu) != hwnd ||
        !render_device_ready(device, hwnd)) return;
    d3d_device *host_device = g_d3d_device;
    int physical_w, physical_h;
    if (!void_android_display_size(&physical_w, &physical_h)) return;
    uint32_t limit = d3d_gl_limits.max_texture ? d3d_gl_limits.max_texture : 8192;
    if (physical_w <= 0 || physical_h <= 0) return;
    int input_w, input_h;
    void_input_screen_size(&input_w, &input_h);
    uint32_t width = MEM32(0x01002930u), height = MEM32(0x01002934u);
    if (!width || !height || width > limit || height > limit ||
        input_w <= 0 || input_h <= 0 || width != (uint32_t)input_w || height != (uint32_t)input_h ||
        g_d3d_device->pp[0] != width || g_d3d_device->pp[1] != height) return;
    pthread_mutex_lock(&render_lock);
    int percent = render_percent;
    uint64_t request = render_request;
    pthread_mutex_unlock(&render_lock);
    uint32_t wanted_w = (uint32_t)(((uint64_t)(unsigned)physical_w * (unsigned)percent + 50) / 100);
    uint32_t wanted_h = (uint32_t)(((uint64_t)(unsigned)physical_h * (unsigned)percent + 50) / 100);
    if (!wanted_w || !wanted_h || wanted_w > limit || wanted_h > limit) return;
    if (width == wanted_w && height == wanted_h) { render_attempt.failed = 0; return; }
    if (render_attempt.failed && render_attempt.request == request && render_attempt.device == device &&
        render_attempt.width == width && render_attempt.height == height &&
        render_attempt.physical_w == physical_w && render_attempt.physical_h == physical_h) return;
    uint32_t screen = render_current_screen();
    if (!screen) return;

    uint32_t previous[14];
    memcpy(previous, GPTR(0x01002930u), sizeof previous);
    const void_touch_event abort = {.kind = TOUCH_ABORT, .scale = 1};
    void_touch_engine_event(&abort);
    /* Cancelling a drag can invoke native UI callbacks. Do not resize a changed owner. */
    int latest_w, latest_h;
    void_input_screen_size(&input_w, &input_h);
    if (!void_android_render_ready() || render_current_screen() != screen ||
        void_window_main() != hwnd || void_window_thread(hwnd) != void_thread_id() ||
        !void_android_display_size(&latest_w, &latest_h) || latest_w != physical_w || latest_h != physical_h ||
        MEM32(0x010029A8u) != device || g_d3d_device != host_device || !render_device_ready(device, hwnd) ||
        input_w <= 0 || input_h <= 0 || (uint32_t)input_w != width || (uint32_t)input_h != height ||
        g_d3d_device->pp[0] != width || g_d3d_device->pp[1] != height ||
        memcmp(previous, GPTR(0x01002930u), sizeof previous)) return;
    render_attempt.request = request; render_attempt.device = device;
    render_attempt.width = width; render_attempt.height = height;
    render_attempt.physical_w = physical_w; render_attempt.physical_h = physical_h;
    render_attempt.failed = 1;
    MEM32(0x01002930u) = wanted_w;
    MEM32(0x01002934u) = wanted_h;
    /* Original A40E80/A41610 call this no-argument function after updating PP.
       Its zero result includes A3FDC0's resource recreation, not just IDirect3DDevice9::Reset. */
    uint32_t result = render_reset(device, hwnd);
    void_input_screen_size(&input_w, &input_h);
    if (!result && MEM32(0x010029A8u) == device &&
        MEM32(0x01002930u) == wanted_w && MEM32(0x01002934u) == wanted_h &&
        input_w > 0 && input_h > 0 && (uint32_t)input_w == wanted_w && (uint32_t)input_h == wanted_h &&
        g_d3d_device == host_device && render_device_ready(device, hwnd) &&
        g_d3d_device->pp[0] == wanted_w && g_d3d_device->pp[1] == wanted_h) {
        render_attempt.failed = 0;
        render_resize_ui(wanted_w, wanted_h);
        void_log("[touch] render-scale=%d%% backbuffer=%ux%u display=%dx%d", percent,
                 wanted_w, wanted_h, physical_w, physical_h);
        return;
    }
    /* One native rollback, then suppress this failed request until explicit retry
       or a changed display/device/backbuffer. Never spin Reset in the frame loop. */
    uint32_t rollback = 0xFFFFFFFFu;
    if (void_window_main() == hwnd && void_window_thread(hwnd) == void_thread_id() &&
        MEM32(0x010029A8u) == device && g_d3d_device == host_device && render_device_ready(device, hwnd)) {
        memcpy(GPTR(0x01002930u), previous, sizeof previous);
        rollback = render_reset(device, hwnd);
        void_input_screen_size(&input_w, &input_h);
        if (!rollback && MEM32(0x010029A8u) == device &&
            MEM32(0x01002930u) == width && MEM32(0x01002934u) == height &&
            input_w > 0 && input_h > 0 && (uint32_t)input_w == width && (uint32_t)input_h == height &&
            g_d3d_device == host_device && render_device_ready(device, hwnd) &&
            g_d3d_device->pp[0] == width && g_d3d_device->pp[1] == height)
            render_resize_ui(width, height);
    }
    void_log("[touch] render-scale=%d%% rejected HRESULT=%08X rollback=%08X previous=%ux%u observed=%dx%d",
             percent, result, rollback, width, height, input_w, input_h);
}
