/* Production D3D9 resources (d3d9_resource.c) with the render thread on and a
 * real GLES context on it: a DISCARD lock while records not yet run read the
 * buffer gets a fresh guest copy at once, a plain lock waits for them, the GL
 * buffer ends with what the game wrote; a destroyed buffer outlives the records
 * before its release; texture data is copied at Unlock; occlusion results are
 * the GPU's and arrive before the game asks.
 * Build: tools/build_host_test.py tests/test_render_resources.c --objects build/<task>/obj */
#include "host.h"
#include <assert.h>
#include <unistd.h>
#include "../android/host/d3d9_resource.c"

void *void_android_window_current(uint32_t *serial, int wait) { (void)wait; *serial = 0; return NULL; }
void void_android_window_ack(uint32_t serial) { (void)serial; }

void void_process_exit(uint32_t code, int detach) { (void)detach; _exit((int)code); }

static uint32_t call(uint32_t object, unsigned slot, unsigned count, uint32_t *args)
{
    args[0] = object;
    return void_call_guest(MEM32(MEM32(object) + slot * 4), count, args, 1);
}

static uint64_t now_ns(void) { return void_monotonic_ns(); }

/* ---------------------------------------------- render-thread helpers */
static void run_sleep(void *ms) { struct timespec t = { 0, *(int *)ms * 1000000L }; nanosleep(&t, NULL); }
static void hold(int ms) { d3d_rt_call(run_sleep, &ms, sizeof ms); d3d_rt_flush(); }

typedef struct { d3d_buffer *b; uint32_t size; uint8_t *out; } read_buffer_args;
static void run_read_buffer(void *p)
{
    read_buffer_args *a = (read_buffer_args *)p;
    glBindBuffer(GL_COPY_READ_BUFFER, a->b->gl);
    const void *m = glMapBufferRange(GL_COPY_READ_BUFFER, 0, a->size, GL_MAP_READ_BIT);
    assert(m);
    memcpy(a->out, m, a->size);
    glUnmapBuffer(GL_COPY_READ_BUFFER);
}

typedef struct { d3d_buffer *b; int ms; GLuint gl; int alive; uint32_t size; } late_args;
static void run_late_use(void *p)
{
    late_args *a = (late_args *)p;
    struct timespec t = { 0, a->ms * 1000000L };
    nanosleep(&t, NULL);
    a->alive = glIsBuffer(a->gl) == GL_TRUE;   /* not deleted before this record ran */
    a->size = a->b->size;
}

static GLuint program;
static void run_program(void *unused)
{
    (void)unused;
    const char *vs = "#version 300 es\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0.,1.);}";
    const char *fs = "#version 300 es\nprecision mediump float;out vec4 c;void main(){c=vec4(1.);}";
    GLuint s[2] = { glCreateShader(GL_VERTEX_SHADER), glCreateShader(GL_FRAGMENT_SHADER) };
    glShaderSource(s[0], 1, &vs, NULL); glShaderSource(s[1], 1, &fs, NULL);
    glCompileShader(s[0]); glCompileShader(s[1]);
    program = glCreateProgram(); glAttachShader(program, s[0]); glAttachShader(program, s[1]); glLinkProgram(program);
    GLint ok = 0; glGetProgramiv(program, GL_LINK_STATUS, &ok); assert(ok);
}
void d3d_shader_forget_current(void);
static GLuint target_fbo, target_tex;
static void run_draw(void *hidden)
{
    if (!target_fbo) {
        glGenTextures(1, &target_tex); glBindTexture(GL_TEXTURE_2D, target_tex);
        glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA8, 32, 32);
        glGenFramebuffers(1, &target_fbo);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, target_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, target_tex, 0);
    glUseProgram(program); glViewport(0, 0, 32, 32);
    glDisable(GL_DEPTH_TEST); glDisable(GL_BLEND); glDisable(GL_STENCIL_TEST); glDisable(GL_SCISSOR_TEST);
    glDisable(GL_CULL_FACE);
    glColorMask(*(int *)hidden ? GL_FALSE : GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    /* Hidden: the scissor rejects every fragment. */
    if (*(int *)hidden) { glEnable(GL_SCISSOR_TEST); glScissor(0, 0, 0, 0); }
    glDrawArrays(GL_TRIANGLES, 0, 3);
    glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glUseProgram(0);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    d3d_shader_forget_current();
    d3d_rt_device()->fbo_dirty = 1;
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    assert(void_guest_reserve());
    void_threads_init(); void_dispatch_init(); void_machine_enter();
    setenv("VOID_RENDER_THREAD", "1", 1);
    assert(d3d_gl_init() && d3d_rt_threaded());
    static d3d_device device;
    device.st.viewport[2] = device.st.viewport[3] = 32;
    uint32_t args[6], out = void_galloc(16);

    /* ------------------------------------------------ buffer renaming */
    enum { SIZE = 65536 };
    uint32_t vb = d3d_buffer_create(&device, 0, SIZE, D3DUSAGE_DYNAMIC, 0, D3DPOOL_DEFAULT);
    assert(vb);
    d3d_buffer *b = (d3d_buffer *)void_com_host(vb);
    args[1] = 0; args[2] = 0; args[3] = out; args[4] = 0;
    assert(call(vb, 11, 5, args) == D3D_OK);
    uint32_t first = MEM32(out);
    memset(GPTR(first), 0x11, SIZE);
    assert(call(vb, 12, 1, args) == D3D_OK);
    /* A draw not run yet reads the copy. */
    hold(300);
    d3d_buffer_read_by(b, d3d_rt_position());
    uint64_t t0 = now_ns();
    args[1] = 0; args[2] = 0; args[3] = out; args[4] = D3DLOCK_DISCARD;
    assert(call(vb, 11, 5, args) == D3D_OK);
    uint32_t second = MEM32(out);
    assert(second != first && now_ns() - t0 < 100000000ull);
    assert(*(uint8_t *)GPTR(first) == 0x11);           /* the old copy is untouched for the render thread */
    memset(GPTR(second), 0x22, SIZE);
    assert(call(vb, 12, 1, args) == D3D_OK);
    puts("PASS DISCARD under pending reads: a fresh guest copy at once, the old one left as recorded");
    /* NOOVERWRITE: no wait, same copy. */
    hold(300);
    d3d_buffer_read_by(b, d3d_rt_position());
    t0 = now_ns();
    args[1] = 0; args[2] = 256; args[3] = out; args[4] = D3DLOCK_NOOVERWRITE;
    assert(call(vb, 11, 5, args) == D3D_OK && MEM32(out) == second && now_ns() - t0 < 100000000ull);
    assert(call(vb, 12, 1, args) == D3D_OK);
    /* A plain lock waits until the records reading the copy have run. */
    t0 = now_ns();
    args[1] = 0; args[2] = 0; args[3] = out; args[4] = 0;
    assert(call(vb, 11, 5, args) == D3D_OK && MEM32(out) == second);
    assert(now_ns() - t0 > 150000000ull);
    memset(GPTR(second), 0x33, SIZE);
    assert(call(vb, 12, 1, args) == D3D_OK);
    static uint8_t seen[SIZE];
    read_buffer_args r = { b, SIZE, seen };
    d3d_rt_sync(run_read_buffer, &r);
    for (uint32_t i = 0; i < SIZE; ++i) assert(seen[i] == 0x33);
    shadow_collect(0);
    assert(!retired_count);
    puts("PASS NOOVERWRITE never waits; a plain lock waits for the pending reads; GL holds the last write; old copies freed");

    /* ------------------------------------- destruction after pending records */
    late_args late = { b, 200, b->gl, 0, 0 };
    late_args *handed = (late_args *)d3d_rt_begin(run_late_use, sizeof late);
    *handed = late;
    d3d_rt_commit();
    args[1] = 0;
    assert(call(vb, 2, 1, args) == 0);                  /* Release: the last reference */
    d3d_rt_finish();
    /* The record ran before the buffer's release record: read its own copy of the arguments. */
    assert(handed->alive && handed->size == SIZE);
    puts("PASS a buffer released while a record still uses it is deleted after that record (glIsBuffer there)");

    /* ------------------------------------------- texture copied at Unlock */
    d3d_texture *t = d3d_texture_new(&device, D3DRTYPE_TEXTURE, 4, 4, 1, 1, D3DUSAGE_RENDERTARGET, 21, D3DPOOL_DEFAULT);
    assert(t);
    uint32_t tex = d3d_wrap_texture(t), rect = void_galloc(8);
    hold(300);
    args[1] = 0; args[2] = rect; args[3] = 0; args[4] = D3DLOCK_DISCARD;
    assert(call(tex, 19, 5, args) == D3D_OK);
    uint32_t bits = MEM32(rect + 4), pitch = MEM32(rect);
    for (uint32_t y = 0; y < 4; ++y) for (uint32_t x = 0; x < 4; ++x) MEM32(bits + y * pitch + 4 * x) = 0xFF00FF00u;   /* green */
    args[1] = 0;
    assert(call(tex, 20, 2, args) == D3D_OK);
    /* The lock's memory is gone or reused now; the render thread has not uploaded yet. */
    d3d_surface *level = (d3d_surface *)void_com_host(d3d_texture_surface(t, 0, 0));
    uint32_t whole[4] = { 0, 0, 4, 4 };
    float rgba[64];
    assert(d3d_gl_read_rgba(level, whole, rgba));
    for (int i = 0; i < 16; ++i) assert(rgba[4 * i] == 0.0f && rgba[4 * i + 1] == 1.0f && rgba[4 * i + 2] == 0.0f);
    puts("PASS texture rows copied at Unlock while the render thread was behind; read back green");

    /* ------------------------------------------- asynchronous occlusion */
    d3d_rt_sync(run_program, NULL);
    for (int hidden = 0; hidden < 2; ++hidden) {
        uint32_t query = d3d_query_create(&device, 9);
        d3d_query *q = (d3d_query *)void_com_host(query);
        args[1] = 2; assert(call(query, 6, 2, args) == D3D_OK);          /* BEGIN */
        d3d_rt_call(run_draw, &hidden, sizeof hidden);
        args[1] = 1; assert(call(query, 6, 2, args) == D3D_OK);          /* END */
        d3d_rt_flush();
        /* Nobody asks: the render thread's queue publishes the GPU's result. */
        for (int wait = 0; wait < 2000 && !(atomic_load_explicit(&QRY_RT(q)->answer, memory_order_acquire) & 3u); ++wait) usleep(1000);
        assert(atomic_load_explicit(&QRY_RT(q)->answer, memory_order_acquire) & 3u);
        uint64_t polls_before = poll_recorded;
        args[1] = out; args[2] = 4; args[3] = 1;
        assert(call(query, 7, 4, args) == D3D_OK);
        assert(poll_recorded == polls_before);                         /* answered on the first poll */
        assert(MEM32(out) == (hidden ? 0u : 1024u));
        args[1] = 0; call(query, 2, 1, args);
    }
    d3d_rt_finish();
    puts("PASS occlusion: visible and hidden results of the GPU published unasked, first GetData answers");
    return 0;
}
