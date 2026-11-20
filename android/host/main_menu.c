/* Resolve arena references between menu frames, then publish the complete
 * actor collection through the original render-world update. */
#include "d3d9_internal.h"
#include <stdlib.h>
#include <string.h>

#ifdef VOID_ANDROID_APP
int void_android_menu_ready(void);
#else
static int void_android_menu_ready(void) { return 1; }
#endif

enum { MENU_STOCK, MENU_STATIC, MENU_LOADING };
#define ARENA_OBJECTS 0x54u   /* {begin, end} of 8-byte resource references */
#define MENU_COLOR 0xFF5E4A47u

static struct {
    uint32_t screen, thread, world, scene, view, actors, next, count, first_frame, last_frame;
    uint32_t attach_method, attach_owner, attach_collection;
    int mode, initializing;
} menu;
static uint32_t vector_proxy, backbuffer_out;

void void_menu_scene_begin(uint32_t screen, uint32_t existing, uint32_t world)
{
    if (existing) return;
    memset(&menu, 0, sizeof menu);
    menu.screen = screen;
    menu.thread = void_thread_id();
    menu.world = world;
    menu.initializing = 1;
    const char *show = getenv("PORT_OPTION_MAIN_MENU_3D");
    const char *fast = getenv("PORT_OPTION_FAST_MAIN_MENU");
    if (show && !strcmp(show, "0")) menu.mode = MENU_STATIC;
    else if (world && fast && !strcmp(fast, "1")) menu.mode = MENU_LOADING;
}

void void_menu_scene_end(void)
{
    if (menu.initializing && menu.thread == void_thread_id()) menu.initializing = 0;
}

uint32_t void_menu_scene_slice(uint32_t scene, uint32_t arena, uint32_t view)
{
    if (!menu.initializing) return arena;
    if (menu.thread != void_thread_id() || (menu.scene && scene != menu.scene)) return arena;
    if (!void_vm_readable(arena, ARENA_OBJECTS + 8)) return arena;
    uint32_t begin = MEM32(arena + ARENA_OBJECTS), end = MEM32(arena + ARENA_OBJECTS + 4);
    if (end < begin || (end - begin) % 8) return arena;
    menu.scene = scene;
    menu.view = view;
    menu.actors = begin;
    menu.count = (end - begin) / 8;
    if (!menu.count) menu.mode = MENU_STATIC;  /* Also covers static-menu mods. */
    if (menu.mode == MENU_STOCK || !menu.count) return arena;
    if (!vector_proxy) vector_proxy = void_galloc(ARENA_OBJECTS + 8);
    if (!vector_proxy) { menu.mode = MENU_STOCK; return arena; }
    MEM32(vector_proxy + ARENA_OBJECTS) = 0;
    MEM32(vector_proxy + ARENA_OBJECTS + 4) = 0;
    return vector_proxy;
}

/* The world view registers the collection after its actor list has been built. */
void void_menu_scene_attach(void)
{
    uint32_t owner = g_ecx, method = MEM32(MEM32(owner)), collection = MEM32(g_esp + 4);
    if (menu.initializing && menu.mode == MENU_LOADING && menu.scene && menu.thread == void_thread_id()) {
        menu.attach_method = method;
        menu.attach_owner = owner;
        menu.attach_collection = collection;
        g_esp += 8;  /* thiscall, RET 4 */
        return;
    }
    void_resolve(method)();
}

void void_menu_scene_tick(uint32_t screen)
{
    if (menu.screen != screen || menu.mode != MENU_LOADING || !menu.scene || !g_d3d_device) return;
    if (!void_android_menu_ready()) return;
    uint32_t frame = g_d3d_device->frame;
    if (!menu.first_frame) {
        menu.first_frame = menu.last_frame = frame + 1;
        void_log("[menu] showing interface while %u scene actors are pending", menu.count);
    }
    if (frame <= menu.first_frame || frame == menu.last_frame) return;
    menu.last_frame = frame;
    void_regs saved;
    void_regs_save(&saved);
    if (menu.next < menu.count) {
        uint32_t actor = menu.actors + 8 * menu.next++;
        if (void_vm_readable(actor, 8)) void_call_guest_this(0x00933DB0u, actor, 0, NULL);
    } else {
        void_call_guest_this(0x00A867C0u, menu.scene, 1, &menu.view);
        if (menu.attach_method)
            void_call_guest_this(menu.attach_method, menu.attach_owner, 1, &menu.attach_collection);
        void_call_guest_this(MEM32(MEM32(menu.world)), menu.world, 0, NULL);
        menu.mode = MENU_STOCK;
        void_log("[menu] 3D scene ready after %u menu frames", frame - menu.first_frame + 1);
    }
    void_regs_load(&saved);
}

void void_menu_clear(uint32_t screen)
{
    if (menu.screen != screen || menu.mode == MENU_STOCK || !g_d3d_device) return;
    d3d_device *device = g_d3d_device;
    if (device->backbuffer) {
        const uint32_t rect[] = {0, 0, device->backbuffer->width, device->backbuffer->height};
        d3d_gl_fill(device->backbuffer, rect, MENU_COLOR);
        return;
    }
    /* DXVK owns its backbuffer. A full-surface ColorFill ignores the UI viewport. */
    if (!backbuffer_out) backbuffer_out = void_galloc(4);
    if (!backbuffer_out) return;
    uint32_t guest = device->com.guest, methods = MEM32(guest);
    const uint32_t get[] = {guest, 0, 0, 0, backbuffer_out};
    MEM32(backbuffer_out) = 0;
    void_regs saved;
    void_regs_save(&saved);
    if (!void_call_guest(MEM32(methods + 18 * 4), 5, get, 1) && MEM32(backbuffer_out)) {
        uint32_t surface = MEM32(backbuffer_out);
        const uint32_t fill[] = {guest, surface, 0, MENU_COLOR};
        void_call_guest(MEM32(methods + 35 * 4), 4, fill, 1);
        void_call_guest(MEM32(MEM32(surface) + 2 * 4), 1, &surface, 1);
    }
    void_regs_load(&saved);
}
