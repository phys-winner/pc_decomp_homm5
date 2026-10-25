/* Android application glue: JNI from GameActivity, the native window, the
 * game thread, touch input in DirectInput scan codes, and AAudio output for
 * the DirectSound mixer. */
#ifdef VOID_ANDROID_APP
#define _GNU_SOURCE
#include "host.h"
#include "input.h"
#include "touch.h"
#include <aaudio/AAudio.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <jni.h>
#include <math.h>
#include <time.h>
#include <unistd.h>

int void_game_main(const char *game, const char *data, const char *images, int selftest);
void void_process_exit(uint32_t code, int run_detach);

static ANativeWindow *window;
static pthread_mutex_t window_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t window_cond = PTHREAD_COND_INITIALIZER;
static int display_width, display_height;
static pthread_t game_thread;
static int game_started;
static char game_dir[512], data_dir[512], images_dir[512];
static JavaVM *jvm;
static jobject activity;
static int return_to_launcher;

void void_android_return_to_launcher(void) { return_to_launcher = 1; }

void void_android_gamepad_help(void)
{
    if (!jvm || !activity) return;
    JNIEnv *env = NULL;
    int attached = (*jvm)->GetEnv(jvm, (void **)&env, JNI_VERSION_1_6) == JNI_EDETACHED;
    if (attached && (*jvm)->AttachCurrentThread(jvm, &env, NULL) != JNI_OK) return;
    if (env) {
        jmethodID method = (*env)->GetStaticMethodID(env, (jclass)activity, "onGamepadHelp", "()V");
        if (method) (*env)->CallStaticVoidMethod(env, (jclass)activity, method);
        if ((*env)->ExceptionCheck(env)) { (*env)->ExceptionClear(env); void_log("[input] gamepad help callback failed"); }
    }
    if (attached) (*jvm)->DetachCurrentThread(jvm);
}

void void_android_process_exit(void)
{
    if (!return_to_launcher || !jvm || !activity) return;
    JNIEnv *env = NULL;
    int attached = (*jvm)->GetEnv(jvm, (void **)&env, JNI_VERSION_1_6) == JNI_EDETACHED;
    if (attached && (*jvm)->AttachCurrentThread(jvm, &env, NULL) != JNI_OK) return;
    if (!env) return;
    jmethodID callback = (*env)->GetStaticMethodID(env, (jclass)activity, "onGameExit", "()V");
    if (callback) (*env)->CallStaticVoidMethod(env, (jclass)activity, callback);
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
        void_log("[port] Java launcher callback failed");
    }
    if (attached) (*jvm)->DetachCurrentThread(jvm);
}

/* The activity's surface comes and goes (Home, the app switcher, the screen
 * turning off): window_serial counts the changes, and the renderer takes a
 * new one up at its next present (d3d9_gl.c), acknowledging the serial it
 * has switched to; a destroyed surface waits (briefly) for that. */
static uint32_t window_serial, window_acked;
static int audio_paused;
static uint64_t audio_pause_state;

uint64_t void_audio_pause_state(void)
{
    return __atomic_load_n(&audio_pause_state, __ATOMIC_ACQUIRE);
}

static void remember_display_size_locked(int w, int h)
{
    if (w > 0 && h > 0) { display_width = w; display_height = h; }
}

/* Physical dimensions are independent of the game's backbuffer/input size. */
int void_android_display_size(int *w, int *h)
{
    pthread_mutex_lock(&window_lock);
    if (window) remember_display_size_locked(ANativeWindow_getWidth(window), ANativeWindow_getHeight(window));
    *w = display_width; *h = display_height;
    int valid = *w > 0 && *h > 0;
    pthread_mutex_unlock(&window_lock);
    return valid;
}

int void_android_render_ready(void)
{
    pthread_mutex_lock(&window_lock);
    int ready = window != NULL && !(void_audio_pause_state() & 1u);
    pthread_mutex_unlock(&window_lock);
    return ready;
}

/* d3d9_gl.c asks for the window when the game creates its device; wait for
 * the surface if the activity has not delivered it yet. */
void *void_android_window(void)
{
    pthread_mutex_lock(&window_lock);
    while (!window) pthread_cond_wait(&window_cond, &window_lock);
    ANativeWindow *w = window;
    pthread_mutex_unlock(&window_lock);
    return w;
}

/* The current window (NULL while the activity has none) and its serial; with
 * wait set, block until there is one. */
void *void_android_window_current(uint32_t *serial, int wait)
{
    pthread_mutex_lock(&window_lock);
    while (wait && !window) pthread_cond_wait(&window_cond, &window_lock);
    ANativeWindow *w = window;
    *serial = window_serial;
    pthread_mutex_unlock(&window_lock);
    return w;
}

void void_android_window_ack(uint32_t serial)
{
    pthread_mutex_lock(&window_lock);
    window_acked = serial;
    pthread_cond_broadcast(&window_cond);
    pthread_mutex_unlock(&window_lock);
}

static void *game_main(void *arg)
{
    (void)arg;
    int code = void_game_main(game_dir, data_dir, images_dir, 0);
    void_log("[android] game thread finished with %d", code);
    void_process_exit((uint32_t)code, 0);
    return NULL;
}

JNIEXPORT jint JNI_OnLoad(JavaVM *vm, void *reserved)
{
    (void)reserved;
    jvm = vm;
    return JNI_VERSION_1_6;
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeStart(JNIEnv *env, jobject self, jstring game,
    jstring data, jstring images, jstring overlay, jstring cache, jint screen_w, jint screen_h, jboolean verbose)
{
    if (game_started) return;
    const char *g = (*env)->GetStringUTFChars(env, game, NULL);
    const char *d = (*env)->GetStringUTFChars(env, data, NULL);
    const char *i = (*env)->GetStringUTFChars(env, images, NULL);
    const char *o = overlay ? (*env)->GetStringUTFChars(env, overlay, NULL) : NULL;
    const char *c = cache ? (*env)->GetStringUTFChars(env, cache, NULL) : NULL;
    snprintf(game_dir, sizeof game_dir, "%s", g);
    snprintf(data_dir, sizeof data_dir, "%s", d);
    snprintf(images_dir, sizeof images_dir, "%s", i);
    void_files_set_overlay(o);
    void_files_set_cache(c);
    (*env)->ReleaseStringUTFChars(env, game, g);
    (*env)->ReleaseStringUTFChars(env, data, d);
    (*env)->ReleaseStringUTFChars(env, images, i);
    if (o) (*env)->ReleaseStringUTFChars(env, overlay, o);
    if (c) (*env)->ReleaseStringUTFChars(env, cache, c);
    activity = (*env)->NewGlobalRef(env, self);
    void_verbose = verbose ? 1 : 0;
    pthread_mutex_lock(&window_lock);
    if (!display_width && screen_w > 0 && screen_h > 0 && screen_w >= screen_h)
        remember_display_size_locked(screen_w, screen_h);
    pthread_mutex_unlock(&window_lock);
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 64u << 20);
    game_started = pthread_create(&game_thread, &attr, game_main, NULL) == 0;
    pthread_attr_destroy(&attr);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeSurface(JNIEnv *env, jobject self, jobject surface)
{
    (void)self;
    pthread_mutex_lock(&window_lock);
    ANativeWindow *old = window;
    window = surface ? ANativeWindow_fromSurface(env, surface) : NULL;
    if (window) remember_display_size_locked(ANativeWindow_getWidth(window), ANativeWindow_getHeight(window));
    uint32_t serial = ++window_serial;
    pthread_cond_broadcast(&window_cond);
    if (!surface && old) {
        /* Android wants the EGL surface gone before surfaceDestroyed returns;
         * the game thread lets it go at its next present. A game busy
         * loading may not present for a while: do not hold the UI thread
         * long (EGL keeps its own reference to the window meanwhile). */
        struct timespec until;
        clock_gettime(CLOCK_REALTIME, &until);
        until.tv_sec += 1;
        while (window_acked != serial && pthread_cond_timedwait(&window_cond, &window_lock, &until) == 0) {}
    }
    pthread_mutex_unlock(&window_lock);
    if (old) ANativeWindow_release(old);
}

/* onPause/onResume: the game itself waits in its present while it has no
 * surface; the audio stream pauses with the activity. */
JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativePause(JNIEnv *env, jobject self, jboolean paused)
{
    (void)env; (void)self;
    uint64_t state = void_audio_pause_state(), next;
    /* Keep transitions even when Home and resume both fall between worker ticks. */
    do {
        if ((state & 1u) == (paused ? 1u : 0u)) break;
        next = ((state & ~UINT64_C(1)) + 2u) | (paused ? 1u : 0u);
    } while (!__atomic_compare_exchange_n(&audio_pause_state, &state, next, 0,
                                         __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE));
    __atomic_store_n(&audio_paused, (int)(void_audio_pause_state() & 1u), __ATOMIC_RELAXED);
}

/* Scan code (DIK) based input from the touch layer. */
static uint32_t dik_to_vk(uint32_t dik)
{
    for (uint32_t vk = 1; vk < 256; ++vk) if (void_vk_to_dik(vk) == dik) return vk;
    return 0;
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeKey(JNIEnv *env, jobject self, jint scan, jboolean down)
{
    (void)env; (void)self;
    uint32_t vk = dik_to_vk((uint32_t)scan);
    if (vk) void_input_key(vk, down);
}

/* A point of the view in [0,1] as game pixels, undoing the present's
 * aspect-preserving fit (d3d9_gl.c). */
static int map_touch_point(float x, float y, float dx, float dy,
                          float *gx, float *gy, float *gdx, float *gdy)
{
    int w, h;
    void_input_screen_size(&w, &h);
    pthread_mutex_lock(&window_lock);
    int present = window != NULL;
    float sw = window ? (float)ANativeWindow_getWidth(window) : (float)w;
    float sh = window ? (float)ANativeWindow_getHeight(window) : (float)h;
    pthread_mutex_unlock(&window_lock);
    if (w <= 0 || h <= 0 || sw <= 0 || sh <= 0) {
        *gx = *gy = *gdx = *gdy = 0;
        return -1;
    }
    float scale = sw / (float)w < sh / (float)h ? sw / (float)w : sh / (float)h;
    float ox = (sw - (float)w * scale) / 2.0f, oy = (sh - (float)h * scale) / 2.0f;
    *gx = (x * sw - ox) / scale;
    *gy = (y * sh - oy) / scale;
    *gdx = *gx - ((x - dx) * sw - ox) / scale;
    *gdy = *gy - ((y - dy) * sh - oy) / scale;
    if (!present) return -1;
    return x >= 0 && x <= 1 && y >= 0 && y <= 1 &&
           *gx >= 0 && *gx < w && *gy >= 0 && *gy < h;
}

static void view_to_game(float x, float y, int *gx, int *gy)
{
    float px = 0, py = 0, dx, dy;
    map_touch_point(x, y, 0, 0, &px, &py, &dx, &dy);
    *gx = (int)px; *gy = (int)py;
}

static void physical_input_mode(void)
{
    void_touch_event event = {TOUCH_POINTER, 0, 0, 0, 0, 1, 0};
    void_touch_enqueue(&event);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeHardwareKey(JNIEnv *env, jobject self,
    jint vk, jboolean down)
{
    (void)env; (void)self;
    if (vk <= 0 || vk > 255 || !void_vk_to_dik((uint32_t)vk)) return;
    if (down) physical_input_mode();
    void_input_key((uint32_t)vk, down);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativePointer(JNIEnv *env, jobject self,
    jfloat x, jfloat y, jboolean relative)
{
    (void)env; (void)self;
    static float remainder_x, remainder_y;
    if (!isfinite(x) || !isfinite(y) || fabsf(x) > 4 || fabsf(y) > 4) return;
    uint32_t old_x, old_y; void_input_cursor(&old_x, &old_y);
    int w, h; void_input_screen_size(&w, &h);
    int px, py;
    if (relative) {
        float dx = x * w + remainder_x, dy = y * h + remainder_y;
        int ix = (int)dx, iy = (int)dy;
        remainder_x = dx - ix; remainder_y = dy - iy;
        px = (int)old_x + ix; py = (int)old_y + iy;
    } else {
        float gx, gy, dx, dy;
        if (map_touch_point(x, y, 0, 0, &gx, &gy, &dx, &dy) < 0) return;
        px = (int)gx; py = (int)gy;
        remainder_x = remainder_y = 0;
    }
    px = px < 0 ? 0 : px >= w ? w - 1 : px;
    py = py < 0 ? 0 : py >= h ? h - 1 : py;
    if (px == (int)old_x && py == (int)old_y) return;
    physical_input_mode();
    void_input_mouse_move(px - (int)old_x, py - (int)old_y);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeMouseButton(JNIEnv *env, jobject self,
    jint button, jboolean down)
{
    (void)env; (void)self;
    if (button < 0 || button > 7) return;
    if (down) physical_input_mode();
    void_input_mouse_button(button, down);
    if (button == 0 && down) {
        uint32_t x, y; void_input_cursor(&x, &y);
        void_touch_event event = {TOUCH_POINTER_CLICK, (float)x, (float)y, 0, 0, 1, 0};
        void_touch_enqueue(&event);
    }
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeWheel(JNIEnv *env, jobject self, jint delta)
{
    (void)env; (void)self;
    if (!delta || delta < -12000 || delta > 12000) return;
    physical_input_mode();
    void_input_mouse_wheel(delta);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativePadCamera(JNIEnv *env, jobject self,
    jfloat rotation, jfloat tilt)
{
    (void)env; (void)self;
    if (!isfinite(rotation) || !isfinite(tilt) || fabsf(rotation) > 1 || fabsf(tilt) > 1) return;
    void_touch_event event = {TOUCH_PAD_CAMERA, 0, 0, 0, tilt, 1, rotation};
    void_touch_enqueue(&event);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeTouch(JNIEnv *env, jobject self,
    jint kind, jfloat x, jfloat y, jfloat dx, jfloat dy, jfloat scale, jfloat rotation)
{
    (void)env; (void)self;
    static int ignored;
    void_touch_event event = { kind, x, y, dx, dy, scale, rotation };
    if (kind < TOUCH_BEGIN || kind > TOUCH_KIND_LAST || !isfinite(x) || !isfinite(y) ||
        !isfinite(dx) || !isfinite(dy) || !isfinite(scale) || scale <= 0 ||
        !isfinite(rotation) || fabsf(rotation) > 3.141593f) {
        ignored = 1;
        void_touch_enqueue(&event);
        return;
    }
    if (kind == TOUCH_ABORT) {
        ignored = 0;
        void_touch_enqueue(&event);
        return;
    }
    int inside = map_touch_point(x, y, dx, dy, &event.x, &event.y, &event.dx, &event.dy);
    if (kind == TOUCH_BEGIN) ignored = inside <= 0;
    if (ignored) return;
    if (inside < 0 || (!inside && (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP))) {
        event = (void_touch_event){ TOUCH_ABORT, 0, 0, 0, 0, 1, 0 };
        ignored = 1;
    }
    void_touch_enqueue(&event);
}

/* The saved scales seed the port variables before the game registers them
 * (port_settings.c); the profile's values win once it has some. */
void void_port_set_default(int which, float value);

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeUiScale(JNIEnv *env, jobject self, jfloat scale)
{
    (void)env; (void)self;
    void_port_set_default(0, scale);
    void_touch_set_scale(scale);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeRenderScale(JNIEnv *env, jobject self, jfloat scale)
{
    (void)env; (void)self;
    void_port_set_default(1, scale);
    void_touch_set_render_scale(scale);
}

JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeCameraSensitivity(JNIEnv *env, jobject self, jfloat value)
{
    (void)env; (void)self;
    void_port_set_default(2, value);
}

JNIEXPORT jboolean JNICALL Java_org_homm5_port_GameActivity_nativeText(JNIEnv *env, jobject self,
    jint generation, jstring text)
{
    (void)self;
    if (!text) return JNI_FALSE;
    jsize count = (*env)->GetStringLength(env, text);
    if (count <= 0 || count > 256) return JNI_FALSE;
    const jchar *units = (*env)->GetStringChars(env, text, NULL);
    if (!units) return JNI_FALSE;
    int accepted = void_touch_text_enqueue((uint32_t)generation, units, (uint32_t)count);
    (*env)->ReleaseStringChars(env, text, units);
    return accepted ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jboolean JNICALL Java_org_homm5_port_GameActivity_nativeTextKey(JNIEnv *env, jobject self,
    jint generation, jint key, jint count)
{
    (void)env; (void)self;
    return void_touch_text_key((uint32_t)generation, (uint32_t)key, (uint32_t)count) ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jint JNICALL Java_org_homm5_port_GameActivity_nativeTextCancel(JNIEnv *env, jobject self)
{
    (void)env; (void)self;
    return (jint)void_touch_text_cancel();
}

void void_android_text_focus(int enabled, uint32_t generation)
{
    if (!jvm || !activity) return;
    JNIEnv *env = NULL;
    int attached = (*jvm)->GetEnv(jvm, (void **)&env, JNI_VERSION_1_6) == JNI_EDETACHED;
    if (attached && (*jvm)->AttachCurrentThread(jvm, &env, NULL) != JNI_OK) return;
    if (!env) return;
    jmethodID callback = (*env)->GetStaticMethodID(env, (jclass)activity, "onTextFocus", "(ZI)V");
    if (callback) (*env)->CallStaticVoidMethod(env, (jclass)activity, callback, enabled ? JNI_TRUE : JNI_FALSE, (jint)generation);
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
        void_log("[ime] Java focus callback failed");
    }
    if (attached) (*jvm)->DetachCurrentThread(jvm);
}

void void_android_text_state(uint32_t generation, const uint16_t *text, uint32_t count, uint32_t caret)
{
    if (!jvm || !activity || count > 4096 || caret > count || (!text && count)) return;
    JNIEnv *env = NULL;
    int attached = (*jvm)->GetEnv(jvm, (void **)&env, JNI_VERSION_1_6) == JNI_EDETACHED;
    if (attached && (*jvm)->AttachCurrentThread(jvm, &env, NULL) != JNI_OK) return;
    if (!env) return;
    static const jchar empty;
    jstring value = (*env)->NewString(env, text ? (const jchar *)text : &empty, (jsize)count);
    if (value) {
        jmethodID callback = (*env)->GetStaticMethodID(env, (jclass)activity,
            "onTextState", "(ILjava/lang/String;I)V");
        if (callback) (*env)->CallStaticVoidMethod(env, (jclass)activity, callback,
            (jint)generation, value, (jint)caret);
        (*env)->DeleteLocalRef(env, value);
    }
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
        void_log("[ime] Java text callback failed");
    }
    if (attached) (*jvm)->DetachCurrentThread(jvm);
}

/* The loading screen polls the startup: files opened so far, and readiness. */
static int load_ready;

void void_android_load_ready(void) { __atomic_store_n(&load_ready, 1, __ATOMIC_RELEASE); }

JNIEXPORT jint JNICALL Java_org_homm5_port_GameActivity_nativeLoadWork(JNIEnv *env, jclass type)
{
    (void)env; (void)type;
    return (jint)(void_perf_calls(VOID_PERF_FILE_OPEN) + void_perf_calls(VOID_PERF_FILE_MAP));
}

JNIEXPORT jboolean JNICALL Java_org_homm5_port_GameActivity_nativeLoadReady(JNIEnv *env, jclass type)
{
    (void)env; (void)type;
    return __atomic_load_n(&load_ready, __ATOMIC_ACQUIRE) ? JNI_TRUE : JNI_FALSE;
}

/* port_settings.c: a profile or the options page changed a port variable;
 * Java keeps it as the next start's default. */
void void_android_settings_changed(int which, float value)
{
    if (!jvm || !activity) return;
    JNIEnv *env = NULL;
    int attached = (*jvm)->GetEnv(jvm, (void **)&env, JNI_VERSION_1_6) == JNI_EDETACHED;
    if (attached && (*jvm)->AttachCurrentThread(jvm, &env, NULL) != JNI_OK) return;
    if (!env) return;
    jmethodID callback = (*env)->GetStaticMethodID(env, (jclass)activity, "onPortSetting", "(IF)V");
    if (callback) (*env)->CallStaticVoidMethod(env, (jclass)activity, callback, (jint)which, (jfloat)value);
    if ((*env)->ExceptionCheck(env)) {
        (*env)->ExceptionClear(env);
        void_log("[port] Java settings callback failed");
    }
    if (attached) (*jvm)->DetachCurrentThread(jvm);
}

/* ------------------------------------------------------------- audio */
static AAudioStream *stream;
static pthread_mutex_t audio_lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t stream_pause_state;
static uint64_t audio_short_writes, audio_dropped_frames, audio_errors;
static unsigned audio_zero_chunks;
/* shortcut: retry low latency only after process restart; revisit for route-aware retries. */
static int audio_normal_output;

static void audio_close_stream(void)
{
    if (stream) {
        AAudioStream_requestStop(stream);
        AAudioStream_close(stream);
    }
    stream = NULL;
    audio_zero_chunks = 0;
}

static void audio_close_failed(aaudio_result_t error)
{
    if (++audio_errors <= 4) void_log("[audio] stream error %d; reopening on next chunk", (int)error);
    audio_close_stream();
}

/* A timed-out write can accept a prefix. Never resend it or silently discard
 * the suffix; retry within a bounded budget, with no guest VM lock held. */
static uint32_t audio_write_frames(const int16_t *frames, uint32_t count)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    int64_t deadline = (int64_t)now.tv_sec * 1000000000LL + now.tv_nsec + 100000000LL;
    uint32_t written = 0;
    uint64_t pause = stream_pause_state;
    while (written < count && void_audio_pause_state() == pause) {
        clock_gettime(CLOCK_MONOTONIC, &now);
        int64_t remaining = deadline - ((int64_t)now.tv_sec * 1000000000LL + now.tv_nsec);
        if (remaining <= 0) break;
        aaudio_result_t result = AAudioStream_write(stream, frames + written * 2,
            (int32_t)(count - written), remaining < 20000000LL ? remaining : 20000000LL);
        if (result < 0) { audio_close_failed(result); break; }
        if ((uint32_t)result < count - written) ++audio_short_writes;
        written += (uint32_t)result;
        if (!result) usleep(1000);
    }
    if (written < count && void_audio_pause_state() == pause) {
        if (audio_dropped_frames < 1920)
            void_log("[audio] discarded %u unwritten frames after timeout/error", count - written);
        audio_dropped_frames += count - written;
    }
    return written;
}

void void_audio_output(const int16_t *frames, uint32_t count)
{
    pthread_mutex_lock(&audio_lock);
    uint64_t pause = void_audio_pause_state();
    /* Pause retains queued PCM; a fresh foreground epoch needs a fresh stream. */
    if (stream && pause != stream_pause_state) audio_close_stream();
    if (pause & 1u) {
        /* mixer_main already paces every chunk, including in the background. */
        pthread_mutex_unlock(&audio_lock);
        return;
    }
    if (!stream) {
        AAudioStreamBuilder *b = NULL;
        aaudio_result_t created = AAudio_createStreamBuilder(&b);
        if (created == AAUDIO_OK) {
            AAudioStreamBuilder_setFormat(b, AAUDIO_FORMAT_PCM_I16);
            AAudioStreamBuilder_setChannelCount(b, 2);
            AAudioStreamBuilder_setSampleRate(b, 48000);
            AAudioStreamBuilder_setPerformanceMode(b, audio_normal_output ?
                AAUDIO_PERFORMANCE_MODE_NONE : AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
            aaudio_result_t result = AAudioStreamBuilder_openStream(b, &stream);
            if (result == AAUDIO_OK) {
                stream_pause_state = pause;
                /* MMAP can erase pre-start PCM: prime silence, then send the whole chunk. */
                static const int16_t silence[2 * 480] = {0};
                result = AAudioStream_write(stream, silence, (int32_t)(count < 480 ? count : 480), 0);
                if (result >= 0) {
                    if (void_audio_pause_state() == pause) result = AAudioStream_requestStart(stream);
                    else audio_close_stream();
                }
                if (result < 0) audio_close_failed(result);
            } else { stream = NULL; audio_close_failed(result); }
            AAudioStreamBuilder_delete(b);
        } else audio_close_failed(created);
        if (!stream) {
            if (void_audio_pause_state() == pause) audio_dropped_frames += count;
            pthread_mutex_unlock(&audio_lock);
            return;
        }
    }
    uint32_t written = audio_write_frames(frames, count);
    if (written || void_audio_pause_state() != pause) audio_zero_chunks = 0;
    else if (stream && count && !audio_normal_output && ++audio_zero_chunks == 3) {
        audio_normal_output = 1;
        ++audio_errors;
        void_log("[audio] low latency stream stalled for 3 chunks; using normal output until process exit");
        audio_close_stream();
    }
    /* Level of what reached the device, every 10 s of audio: silence or
     * underruns show up in the log rather than only by ear. */
    static uint32_t level_frames;
    static double level_sum;
    static int level_peak;
    for (uint32_t i = 0; i < written * 2; ++i) {
        int v = frames[i] < 0 ? -frames[i] : frames[i];
        if (v > level_peak) level_peak = v;
        level_sum += (double)frames[i] * frames[i];
    }
    level_frames += written;
    if (level_frames >= 48000u * 10u) {
        void_log("[audio] last 10 s: peak %d, rms %.0f, underruns %d, short writes %llu, dropped frames %llu, errors %llu", level_peak,
                 sqrt(level_sum / (2.0 * level_frames)), stream ? (int)AAudioStream_getXRunCount(stream) : -1,
                 (unsigned long long)audio_short_writes, (unsigned long long)audio_dropped_frames,
                 (unsigned long long)audio_errors);
        level_frames = 0;
        level_sum = 0;
        level_peak = 0;
    }
    pthread_mutex_unlock(&audio_lock);
}
#endif
