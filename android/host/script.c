/* Scripted input for unattended runs.
 *
 * $VOID_INPUT names a file (default <data>/input.txt; absent = no script)
 * with one event per line, "<seconds> <action> [args]", timed from the
 * moment the script starts:
 *   key <vk>              press, hold 100 ms, release (vk in hex)
 *   down <vk> / up <vk>
 *   click <x> <y> [b]     cursor to (x, y) in game pixels, press and release button b (0 left)
 *   cursor <x> <y>        move the cursor to (x, y) in game pixels
 *   move <dx> <dy>        relative mouse motion
 *   warp <x> <y>          put the cursor at (x, y) without mouse motion
 *   bdown <b> / bup <b>   press / release mouse button b where the cursor is
 *   wheel <delta>
 *   memfind <word>        log guest addresses holding the word as UTF-16 (debugging)
 *   shot                  dump the next presented frame to <data>/frames
 *   depthtrace            CPU-only retained-depth sampler capture (120 frames)
 *   trace                 trace the next frame (see VOID_TRACE_FRAME in d3d9_gl.c)
 *   profile               write the PGO profile (instrumented builds; LLVM_PROFILE_FILE)
 *   quit                  end the process (writing the profile first)
 * '#' starts a comment.
 *
 * $VOID_INPUT_LIVE names a file that is read as it grows, for exploring a
 * running game: each new line is "<action> [args]" without a time and runs
 * at once; "sleep <seconds>" paces a batch (adb shell "echo 'down 57' >> …"). */
#include "host.h"
#include "input.h"
#include <time.h>
#include <unistd.h>

void d3d_request_frame_dump(void);
void d3d_request_trace(void);
void d3d_request_depth_trace(void);
/* Present in a build instrumented for PGO (tools/build_android.py --pgo-generate). */
extern int __llvm_profile_write_file(void) __attribute__((weak));
extern void __llvm_profile_set_filename(const char *) __attribute__((weak));

static void write_profile(void)
{
    if (!__llvm_profile_write_file || !__llvm_profile_set_filename) return;
    static char path[1024];
    /* APKs do not inherit an adb-shell environment; stop guest counters for the snapshot. */
    void_machine_enter();
    int n = snprintf(path, sizeof path, "%s/homm5-%%p.profraw", void_data_dir());
    if (n < 0 || (size_t)n >= sizeof path) {
        void_machine_leave();
        void_log("[script] profile path too long");
        return;
    }
    __llvm_profile_set_filename(path);
    int result = __llvm_profile_write_file();
    void_log("[script] profile %s (%d): %s", result ? "write failed" : "written", result, path);
    void_machine_leave();
}

typedef struct { double at; char action[16]; int a, b, c; double seconds; char text[32]; } script_event;

static double now_seconds(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static void sleep_until(double t)
{
    for (;;) {
        double left = t - now_seconds();
        if (left <= 0) return;
        struct timespec ts = { (time_t)left, (long)((left - (double)(time_t)left) * 1e9) };
        nanosleep(&ts, NULL);
    }
}

static void hold(double seconds)
{
    sleep_until(now_seconds() + seconds);
}

static void run_event(const script_event *e)
{
    if (!strcmp(e->action, "key")) {
        void_input_key((uint32_t)e->a, 1);
        hold(0.1);
        void_input_key((uint32_t)e->a, 0);
    } else if (!strcmp(e->action, "down")) {
        void_input_key((uint32_t)e->a, 1);
    } else if (!strcmp(e->action, "up")) {
        void_input_key((uint32_t)e->a, 0);
    } else if (!strcmp(e->action, "click")) {
        uint32_t x, y;
        void_input_cursor(&x, &y);
        void_input_mouse_move(e->a - (int)x, e->b - (int)y);
        hold(0.05);
        void_input_mouse_button(e->c, 1);
        hold(0.1);
        void_input_mouse_button(e->c, 0);
    } else if (!strcmp(e->action, "cursor")) {
        uint32_t x, y;
        void_input_cursor(&x, &y);
        void_input_mouse_move(e->a - (int)x, e->b - (int)y);
    } else if (!strcmp(e->action, "move")) {
        void_input_mouse_move(e->a, e->b);
    } else if (!strcmp(e->action, "warp")) {
        void_input_mouse_warp(e->a, e->b);
    } else if (!strcmp(e->action, "bdown")) {
        void_input_mouse_button(e->a, 1);
    } else if (!strcmp(e->action, "bup")) {
        void_input_mouse_button(e->a, 0);
    } else if (!strcmp(e->action, "wheel")) {
        void_input_mouse_wheel(e->a);
    } else if (!strcmp(e->action, "shot")) {
        d3d_request_frame_dump();
    } else if (!strcmp(e->action, "depthtrace")) {
        d3d_request_depth_trace();
    } else if (!strcmp(e->action, "trace")) {
        d3d_request_trace();
    } else if (!strcmp(e->action, "sleep")) {
        hold(e->seconds);
    } else if (!strcmp(e->action, "memfind")) {
        /* Debugging: where guest memory holds the UTF-16 text (ASCII word),
         * with the 40 code units before it. */
        uint8_t pattern[64];
        uint32_t n = 0, hits[16];
        for (const unsigned char *c = (const unsigned char *)e->text; *c && n + 2 <= sizeof pattern;) {
            uint32_t u = *c++;                                     /* UTF-8 -> UTF-16 (BMP) */
            int extra = u >= 0xE0 ? 2 : u >= 0xC0 ? 1 : 0;
            if (extra) u &= 0x3Fu >> extra;
            while (extra-- && (*c & 0xC0) == 0x80) u = (u << 6) | (*c++ & 0x3Fu);
            pattern[n++] = (uint8_t)u;
            pattern[n++] = (uint8_t)(u >> 8);
        }
        void_machine_enter();   /* nothing unmaps guest pages under the scan */
        int found = void_vm_find(pattern, n, hits, 16);
        void_log("[script] memfind %s: %d hits", e->text, found);
        for (int h = 0; h < found; ++h) {
            char line[512];
            size_t at = 0;
            uint32_t from = hits[h] >= 80 ? hits[h] - 80 : 0;
            for (uint32_t va = from; va < hits[h] + n + 8 && at + 8 < sizeof line; va += 2) {
                if (!void_vm_readable(va, 2)) break;
                at += (size_t)snprintf(line + at, sizeof line - at, "%04X ", MEM16(va));
            }
            void_log("[script]   %08X: %s", hits[h], line);
        }
        void_machine_leave();
    } else if (!strcmp(e->action, "profile")) {
        write_profile();
    } else if (!strcmp(e->action, "quit")) {
        void_log("[script] quit");
        write_profile();
        _exit(0);
    } else {
        void_log("[script] unknown action '%s'", e->action);
    }
}

/* One line into an event; `timed` lines start with their time in seconds. */
static int parse_line(char *line, script_event *e, int timed)
{
    char *hash = strchr(line, '#');
    if (hash) *hash = 0;
    memset(e, 0, sizeof *e);
    char a[32] = "", b[32] = "", c[32] = "";
    if (timed) {
        if (sscanf(line, "%lf %15s %31s %31s %31s", &e->at, e->action, a, b, c) < 2) return 0;
    } else if (sscanf(line, "%15s %31s %31s %31s", e->action, a, b, c) < 1) {
        return 0;
    }
    int hex = !strcmp(e->action, "key") || !strcmp(e->action, "down") || !strcmp(e->action, "up");
    e->a = (int)strtol(a, NULL, hex ? 16 : 10);
    e->b = (int)strtol(b, NULL, 10);
    e->c = (int)strtol(c, NULL, 10);
    e->seconds = strtod(a, NULL);
    snprintf(e->text, sizeof e->text, "%s", a);
    return 1;
}

static void *script_thread(void *arg)
{
    script_event *events = (script_event *)arg;
    double start = now_seconds();
    for (script_event *e = events; e->action[0]; ++e) {
        sleep_until(start + e->at);
        void_log("[script] %.1fs %s %d %d %d", e->at, e->action, e->a, e->b, e->c);
        run_event(e);
    }
    free(events);
    return NULL;
}

static void *live_thread(void *arg)
{
    char *path = (char *)arg;
    long offset = 0;
    char pending[512];
    size_t used = 0;
    for (;;) {
        FILE *f = fopen(path, "r");
        if (f) {
            if (fseek(f, offset, SEEK_SET) == 0) {
                int ch;
                while ((ch = fgetc(f)) != EOF) {
                    ++offset;
                    if (ch != '\n') {
                        if (used + 1 < sizeof pending) pending[used++] = (char)ch;
                        continue;
                    }
                    pending[used] = 0;
                    used = 0;
                    script_event e;
                    if (!parse_line(pending, &e, 0)) continue;
                    void_log("[live] %s %d %d %d", e.action, e.a, e.b, e.c);
                    run_event(&e);
                }
            }
            fclose(f);
        }
        hold(0.05);
    }
    return NULL;
}

static void start_detached(void *(*fn)(void *), void *arg)
{
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&thread, &attr, fn, arg)) void_log("[script] thread start failed");
    pthread_attr_destroy(&attr);
}

void void_input_script_start(void)
{
    const char *live = getenv("VOID_INPUT_LIVE");
    if (live && *live) {
        void_log("[live] reading commands from %s", live);
        start_detached(live_thread, strdup(live));
    }
    char path[1024];
    const char *env = getenv("VOID_INPUT");
    if (env && *env) snprintf(path, sizeof path, "%s", env);
    else snprintf(path, sizeof path, "%s/input.txt", void_data_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    script_event *events = (script_event *)calloc(1025, sizeof *events);
    int count = 0;
    char line[256];
    while (count < 1024 && fgets(line, sizeof line, f))
        if (parse_line(line, &events[count], 1)) ++count;
    fclose(f);
    void_log("[script] %d events from %s", count, path);
    start_detached(script_thread, events);
}
