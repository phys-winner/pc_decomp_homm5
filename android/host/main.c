/* Command-line entry for adb-shell bring-up on the device:
 *   void-arm64 --game DIR --data DIR --images DIR [--selftest] [-v]
 * The APK uses the same initialization through void_game_main. */
#define _GNU_SOURCE
#include "host.h"
#include "input.h"
#include "touch.h"
#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <unistd.h>

int void_modules_start(void);
void void_fmod_latency_init(void);
void void_highlight_init(void);   /* highlight.c: the map's object highlight without its per-frame rebuild */
void void_log_system_info(void);  /* core.c: the device and the engine build */

void void_files_std_init(void);
static int exiting;
static int enumerated_devices;

static void_fn original_hero_quick_combat;

static int sanctuary_ref_live(uint32_t object)
{
    if (!object || !void_vm_readable(object, 8)) return 0;
    uint32_t bases = MEM32(object + 4);
    if (!void_vm_readable(bases, 8)) return 0;
    uint32_t ref = object + 4 + MEM32(bases + 4);
    return void_vm_readable(ref, 8) && !(MEM32(ref + 4) & 0x80000000u);
}

static void hero_quick_combat(void)
{
    uint32_t hero = g_ecx;
    original_hero_quick_combat();
#if HOMM5_LEGACY_UI
    const uint32_t holder_offset = 0x1BC;
#else
    const uint32_t holder_offset = 0x1D4;
#endif
    /* The leaf is also IPlayer's getter in 1.6/2.1; only a sheltered IHero opts out. */
    if (!(g_eax & 255u) || !void_vm_readable(hero, holder_offset + 4) ||
        MEM32(hero) != 0x00E7E484u || !sanctuary_ref_live(hero)) return;
    uint32_t holder = MEM32(hero + holder_offset);
    if (void_vm_readable(holder, 8) && MEM32(holder) == 0x00E7D6D8u && sanctuary_ref_live(holder))
        g_eax &= ~255u;
}

static void sanctuary_quick_combat_init(void)
{
    if (original_hero_quick_combat) return;
    original_hero_quick_combat = void_dispatch_find(0x00B5AB50u);
    if (original_hero_quick_combat) void_dispatch_add(0x00B5AB50u, hero_quick_combat);
}

static void enumerate_test_callback(void)
{
    if (MEM32(g_esp + 4) || !void_vm_readable(MEM32(g_esp + 8), 1) || MEM32(g_esp + 16) != 0x12345678u)
        void_fatal("DirectSound enumeration callback arguments invalid");
    ++enumerated_devices;
    g_eax = 1;
    g_esp += 20;
}

static void sound_api_test(void)
{
    uint32_t module = void_module_load("dsound.dll"), out = void_galloc(4);
    uint32_t name = void_gstrdup("DirectSoundCreate");
    uint32_t create = void_module_proc(module, name), args[3] = {0, out, 0};
    void_gfree(name);
    if (!create || void_call_guest(create, 3, args, 1) || !MEM32(out)) void_fatal("DirectSoundCreate selftest failed");
    uint32_t object = MEM32(out), release = MEM32(MEM32(object) + 8);
    void_call_guest(release, 1, &object, 1);
    void_gfree(out);
    name = void_gstrdup("DirectSoundEnumerateA");
    uint32_t enumerate = void_module_proc(module, name);
    void_gfree(name);
    uint32_t enumeration[2] = {void_thunk(enumerate_test_callback, "enumerate_test_callback"), 0x12345678u};
    if (!enumerate || void_call_guest(enumerate, 2, enumeration, 1) || enumerated_devices != 1)
        void_fatal("DirectSoundEnumerateA selftest failed");
    void_log("[selftest] DirectSound legacy creation, release and stdcall enumeration PASS");
}

static void uuid_api_test(void)
{
    uint32_t module = void_module_load("rpcrt4.dll"), out = void_galloc(32);
    uint32_t name = void_gstrdup("UuidCreate"), create = void_module_proc(module, name);
    void_gfree(name);
    for (uint32_t p = out; p < out + 32; p += 16) {
        if (!create || void_call_guest(create, 1, &p, 1) || (MEM8(p + 7) & 0xF0) != 0x40 ||
            (MEM8(p + 8) & 0xC0) != 0x80) void_fatal("UuidCreate selftest failed");
    }
    if (!memcmp(GPTR(out), GPTR(out + 16), 16)) void_fatal("UuidCreate repeated its output");
    void_gfree(out);
    void_log("[selftest] UuidCreate guest ABI, GUID layout and entropy PASS");
}

void void_process_exit(uint32_t code, int run_detach)
{
    if (!exiting && run_detach) {
        exiting = 1;
        void_modules_detach_all(1);
    }
    void_log("[void] process exit %u", code);
    void_log_flush();
#ifdef VOID_ANDROID_APP
    void void_android_process_exit(void);
    void_android_process_exit();
#endif
    _exit((int)code);
}

int void_game_main(const char *game, const char *data, const char *images, int selftest)
{
    void_install_fault_handlers();
    mkdir(data, 0775);
    char log_path[1024];
    snprintf(log_path, sizeof log_path, "%s/homm5.log", data);
    void_log_open(log_path);
    void_log("[void] Heroes V ARM64 static host: game=%s data=%s images=%s", game, data, images);
#ifdef __ANDROID__
    void_log_system_info();
#endif
    if (!void_guest_reserve()) return 65;
    void_threads_init();
    void_dispatch_init();
    if (!void_files_init(game, data)) return 66;
    void_files_std_init();
    if (!void_modules_init(images)) return 67;
    void_machine_enter();
    int code;
    if (!void_modules_start()) return 68;
    uint32_t base = void_module_exe_base();
    uint32_t entry = base + MEM32(base + MEM32(base + 0x3C) + 0x28);
    if (selftest) {
        sound_api_test();
        uuid_api_test();
        d3d_device_lifecycle_selftest();
        code = void_dispatch_find(entry) ? 0 : 71;
        void_log("[selftest] imports and process TLS initialized; entry %08X, result %d", entry, code);
    } else {
        void_fmod_latency_init();
        sanctuary_quick_combat_init();
        void_touch_engine_init();
        void_highlight_init();
        void_input_script_start();
        void_log("[void] starting lifted H5_Game.exe at %08X", entry);
        code = (int)void_call_guest(entry, 0, NULL, 1);
        void_log("[void] H5_Game.exe entry returned %d", code);
    }
    void_machine_leave();
    void_log_flush();
    return code;
}

#ifndef VOID_ANDROID_APP
int main(int argc, char **argv)
{
    const char *game = "/sdcard/HeroesV/game", *data = "/sdcard/HeroesV/userdata";
    const char *images = "/sdcard/HeroesV/lifted";
    int selftest = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--game") && i + 1 < argc) game = argv[++i];
        else if (!strcmp(argv[i], "--data") && i + 1 < argc) data = argv[++i];
        else if (!strcmp(argv[i], "--images") && i + 1 < argc) images = argv[++i];
        else if (!strcmp(argv[i], "--selftest")) selftest = 1;
        else if (!strcmp(argv[i], "-v")) void_verbose = 1;
        else { fprintf(stderr, "unknown option %s\n", argv[i]); return 64; }
    }
    setvbuf(stderr, NULL, _IONBF, 0);
    int code = void_game_main(game, data, images, selftest);
    void_process_exit((uint32_t)code, 0);
    return code;
}
#endif
