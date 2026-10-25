"""Differential oracle for the production GLES raster-state cache."""
import re
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned GLenum, GLuint, GLbitfield;
typedef int GLint, GLsizei;
typedef unsigned char GLboolean;
typedef float GLfloat;
enum { GL_FALSE=0, GL_TRUE=1, GL_ZERO=0, GL_ONE=1,
 GL_NEVER=0x200, GL_LESS, GL_EQUAL, GL_LEQUAL, GL_GREATER, GL_NOTEQUAL, GL_GEQUAL, GL_ALWAYS,
 GL_SRC_COLOR=0x300, GL_ONE_MINUS_SRC_COLOR, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
 GL_DST_ALPHA, GL_ONE_MINUS_DST_ALPHA, GL_DST_COLOR, GL_ONE_MINUS_DST_COLOR, GL_SRC_ALPHA_SATURATE,
 GL_CONSTANT_COLOR=0x8001, GL_ONE_MINUS_CONSTANT_COLOR, GL_CONSTANT_ALPHA, GL_ONE_MINUS_CONSTANT_ALPHA,
 GL_FUNC_ADD=0x8006, GL_MIN, GL_MAX, GL_FUNC_SUBTRACT=0x800A, GL_FUNC_REVERSE_SUBTRACT,
 GL_FRONT=0x404, GL_BACK=0x405, GL_CCW=0x901,
 GL_KEEP=0x1E00, GL_REPLACE, GL_INCR, GL_DECR, GL_INVERT=0x150A, GL_INCR_WRAP=0x8507, GL_DECR_WRAP,
 GL_DEPTH_TEST=0xB71, GL_BLEND=0xBE2, GL_CULL_FACE=0xB44, GL_STENCIL_TEST=0xB90,
 GL_SCISSOR_TEST=0xC11, GL_POLYGON_OFFSET_FILL=0x8037,
 GL_COLOR_BUFFER_BIT=0x4000, GL_DEPTH_BUFFER_BIT=0x100, GL_STENCIL_BUFFER_BIT=0x400,
 GL_NONE=0, GL_FRAMEBUFFER=0x8D40, GL_READ_FRAMEBUFFER=0x8CA8, GL_DRAW_FRAMEBUFFER=0x8CA9,
 GL_COLOR_ATTACHMENT0=0x8CE0, GL_DEPTH_ATTACHMENT=0x8D00, GL_DEPTH_STENCIL_ATTACHMENT=0x821A,
 GL_FRAMEBUFFER_COMPLETE=0x8CD5, GL_COLOR_WRITEMASK=0xC23, GL_READ_BUFFER=0xC02, GL_DRAW_BUFFER0=0x8825,
 GL_LINEAR=0x2601, GL_NEAREST=0x2600 };
typedef struct { int stencil, bits, depth; } d3d_format;
typedef struct { const d3d_format *fmt; uint32_t width,height,format; } d3d_surface;
typedef struct { uint32_t rs[256], viewport[4], scissor[4]; float viewport_z[2]; } d3d_state;
typedef struct { d3d_state st; d3d_surface *ds, *rt[4]; int fbo_dirty; } d3d_device;
typedef struct {
    uint32_t enable[6], depth_func, depth_mask, blend[4], equation[2], front, cull;
    uint32_t stencil_func[2][3], stencil_op[2][3], stencil_mask, color[4][4];
    int32_t scissor[4], viewport[4];
    float blend_color[4], polygon[2], range[2];
} gl_state;
static gl_state state;
static unsigned calls;
static int cap_index(GLenum cap) {
    switch(cap) {
    case GL_DEPTH_TEST:return 0; case GL_BLEND:return 1; case GL_CULL_FACE:return 2;
    case GL_STENCIL_TEST:return 3; case GL_SCISSOR_TEST:return 4; case GL_POLYGON_OFFSET_FILL:return 5;
    default:assert(!"unknown raster cap");return 0;
    }
}
static void glEnable(GLenum cap) { ++calls; state.enable[cap_index(cap)]=1; }
static void glDisable(GLenum cap) { ++calls; state.enable[cap_index(cap)]=0; }
static void glDepthFunc(GLenum value) { ++calls;state.depth_func=value; }
static void glDepthMask(GLboolean value) { ++calls;state.depth_mask=value; }
static void glBlendFuncSeparate(GLenum a,GLenum b,GLenum c,GLenum d) { ++calls;state.blend[0]=a;state.blend[1]=b;state.blend[2]=c;state.blend[3]=d; }
static void glBlendEquationSeparate(GLenum a,GLenum b) { ++calls;state.equation[0]=a;state.equation[1]=b; }
static void glBlendColor(float a,float b,float c,float d) { ++calls;state.blend_color[0]=a;state.blend_color[1]=b;state.blend_color[2]=c;state.blend_color[3]=d; }
static void glFrontFace(GLenum value) { ++calls;state.front=value; }
static void glCullFace(GLenum value) { ++calls;state.cull=value; }
static unsigned face(GLenum value) { assert(value==GL_FRONT||value==GL_BACK);return value==GL_BACK; }
static void glStencilFuncSeparate(GLenum f,GLenum a,GLint b,GLuint c) { ++calls;uint32_t *s=state.stencil_func[face(f)];s[0]=a;s[1]=(uint32_t)b;s[2]=c; }
static void glStencilOpSeparate(GLenum f,GLenum a,GLenum b,GLenum c) { ++calls;uint32_t *s=state.stencil_op[face(f)];s[0]=a;s[1]=b;s[2]=c; }
static void glStencilMask(GLuint value) { ++calls;state.stencil_mask=value; }
static void glColorMaski(GLuint i,GLboolean a,GLboolean b,GLboolean c,GLboolean d) { assert(i<4);++calls;state.color[i][0]=a;state.color[i][1]=b;state.color[i][2]=c;state.color[i][3]=d; }
static void glColorMask(GLboolean a,GLboolean b,GLboolean c,GLboolean d) { for(unsigned i=0;i<4;++i)glColorMaski(i,a,b,c,d); }
static void glScissor(GLint a,GLint b,GLsizei c,GLsizei d) { ++calls;state.scissor[0]=a;state.scissor[1]=b;state.scissor[2]=c;state.scissor[3]=d; }
static void glPolygonOffset(float a,float b) { ++calls;state.polygon[0]=a;state.polygon[1]=b; }
static void glViewport(GLint a,GLint b,GLsizei c,GLsizei d) { ++calls;state.viewport[0]=a;state.viewport[1]=b;state.viewport[2]=c;state.viewport[3]=d; }
static void glDepthRangef(float a,float b) { ++calls;state.range[0]=a;state.range[1]=b; }
static unsigned clears,blits;
static d3d_device *g_d3d_device;
static GLuint read_fbo,draw_fbo,fbo;
static GLsizei fb_buf_count;
static uint32_t memory[16];
#define MEM32(va) memory[(va)/4u]
static void d3d_gl_bind_targets(d3d_device *d) { (void)d; }
static int tracing(d3d_device *d) { (void)d;return 0; }
static void trace_dump(d3d_device *d,d3d_surface *s,const char *name) { (void)d;(void)s;(void)name; }
static void void_log(const char *format,...) { (void)format; }
static void glClearColor(float a,float b,float c,float d) { (void)a;(void)b;(void)c;(void)d; }
static void glClearDepthf(float value) { (void)value; }
static void glClearStencil(GLint value) { (void)value; }
static void glClear(GLbitfield value) { assert(value);++clears; }
static void glGenFramebuffers(int count,GLuint *out) { static GLuint next=1;assert(count==1);*out=next++; }
static void glBindFramebuffer(GLenum target,GLuint id) { (void)target;(void)id; }
static void glDrawBuffers(int count,const GLenum *buffers) { (void)count;(void)buffers; }
static void attach(GLenum target,GLenum attachment,d3d_surface *s) { (void)target;(void)attachment;assert(s); }
static GLenum depth_attachment(const d3d_surface *s) { return s->fmt->stencil?GL_DEPTH_STENCIL_ATTACHMENT:GL_DEPTH_ATTACHMENT; }
static GLenum glGetError(void) { return 0; }
static void glGetBooleanv(GLenum key,GLboolean *out) { (void)key;memset(out,0,4); }
static void glGetIntegerv(GLenum key,GLint *out) { (void)key;*out=0; }
static GLenum glCheckFramebufferStatus(GLenum target) { (void)target;return GL_FRAMEBUFFER_COMPLETE; }
static void glBlitFramebuffer(GLint a,GLint b,GLint c,GLint d,GLint e,GLint f,GLint g,GLint h,GLbitfield mask,GLenum filter) {
    (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;
    assert(mask&&(filter==GL_LINEAR||filter==GL_NEAREST));++blits;
}
static void ui_rect(d3d_device *d,const uint32_t in[4],uint32_t out[4]) { (void)d;memcpy(out,in,16); }
static void ui_scissor(d3d_device *d,int x,int y,int w,int h) { (void)d;glScissor(x,y,w,h); }
static d3d_surface *ui_surface(d3d_device *d,d3d_surface *s) { (void)d;return s; }
#include "state.h"
#include "uncached.h"
#include "clear.h"
#include "blit.h"
#include "fill.h"
static unsigned comparisons, omitted;
static void verify(d3d_device *d) {
    gl_state before=state; unsigned start=calls;
    d3d_gl_apply_state(d); gl_state cached=state; unsigned emitted=calls-start;
    state=before; start=calls; uncached_apply(d);
    assert(!memcmp(&state,&cached,sizeof state));
    unsigned reference_calls=calls-start;
    assert(emitted<=reference_calls);omitted+=reference_calls-emitted;state=cached;
    start=calls; d3d_gl_apply_state(d);
    assert(calls==start && "identical raster state must emit no GL calls");
    omitted+=reference_calls;
    ++comparisons;
}
static void damage_state(void) {
    glDisable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);glDepthMask(GL_TRUE);glStencilMask(0xFF);
}
int main(void) {
    d3d_format fmt={1,24,1};d3d_surface ds={&fmt,640,480,75}, same={&fmt,640,480,75};d3d_device d={0};
    d.ds=&ds;d.rt[0]=&ds;
    for(unsigned i=0;i<256;++i)d.st.rs[i]=1;
    d.st.rs[19]=5;d.st.rs[20]=6;d.st.rs[22]=2;d.st.rs[23]=4;d.st.rs[171]=2;
    d.st.rs[207]=7;d.st.rs[208]=8;d.st.rs[209]=3;d.st.rs[193]=0xA1325476u;
    d.st.rs[53]=3;d.st.rs[54]=4;d.st.rs[55]=5;d.st.rs[56]=3;d.st.rs[57]=7;d.st.rs[58]=0xEF;d.st.rs[59]=0x5A;
    d.st.rs[186]=6;d.st.rs[187]=7;d.st.rs[188]=8;d.st.rs[189]=5;
    d.st.rs[168]=3;d.st.rs[190]=5;d.st.rs[191]=9;d.st.rs[192]=6;
    d.st.rs[195]=0x38800000u;d.st.rs[175]=0x3FA00000u;
    uint32_t viewport[4]={2,3,640,480},scissor[4]={4,5,300,200};
    memcpy(d.st.viewport,viewport,sizeof viewport);memcpy(d.st.scissor,scissor,sizeof scissor);
    d.st.viewport_z[0]=0.125f;d.st.viewport_z[1]=0.875f;
    verify(&d);
    /* Enumerated from the unchanged GL body, independently of the cache key. */
    unsigned consumed[]={CONSUMED};
    for(unsigned i=0;i<sizeof consumed/sizeof consumed[0];++i) {
        unsigned index=consumed[i];uint32_t old=d.st.rs[index];
        d.st.rs[index]^=1;verify(&d);d.st.rs[index]=old;verify(&d);
    }
    for(unsigned i=0;i<4;++i) { ++d.st.viewport[i];verify(&d);++d.st.scissor[i];verify(&d); }
    for(unsigned i=0;i<2;++i) { d.st.viewport_z[i]+=0.0625f;verify(&d); }
    d.ds=&same;unsigned start=calls;d3d_gl_apply_state(&d);assert(calls==start);
    fmt.bits=16;verify(&d);fmt.stencil=0;verify(&d);ds.fmt=NULL;d.ds=&ds;verify(&d);
    d.ds=NULL;verify(&d);ds.fmt=&fmt;d.ds=&ds;verify(&d);fmt.stencil=1;fmt.bits=24;verify(&d);
    d.st.rs[185]=0;verify(&d);d.st.rs[19]=12;verify(&d);d.st.rs[19]=13;verify(&d);
    d.st.rs[207]=12;verify(&d);d.st.rs[207]=13;verify(&d);d.st.rs[206]=0;verify(&d);
    d.st.rs[195]=0;d.st.rs[175]=0;verify(&d);
    d.st.rs[195]=0x38800000u;verify(&d);
    uint32_t negative_zero=0x80000000u;d.st.viewport_z[0]=0;verify(&d);
    memcpy(&d.st.viewport_z[0],&negative_zero,4);verify(&d);
    d3d_device other=d;start=calls;d3d_gl_apply_state(&other);assert(calls==start);
    ++d.st.rs[15];++d.st.rs[24];++d.st.rs[25];++d.st.rs[100];
    start=calls;d3d_gl_apply_state(&d);assert(calls==start);

    /* Live production Clear mutates masks/scissor behind the cache. */
    start=clears;d3d_gl_clear(&d,0,0,7,0xFF123456u,0.5f,3);assert(clears==start+1);verify(&d);
    memory[4]=10;memory[5]=12;memory[6]=20;memory[7]=24;
    d3d_gl_clear(&d,1,16,1,0,1,0);verify(&d);
    d3d_gl_clear(&d,0,0,0,0,1,0);verify(&d);
    d.ds=NULL;d3d_gl_clear(&d,0,0,6,0,1,0);verify(&d);d.ds=&ds;verify(&d);

    /* Live blit paths: separate FBO, main color slot, and depth/stencil. */
    uint32_t rect[4]={0,0,32,24};d3d_format color_fmt={0,32,0};
    d3d_surface src={&color_fmt,64,64,21},dst={&color_fmt,64,64,21};
    start=blits;d3d_gl_blit(&src,rect,&dst,rect,2);assert(blits==start+1);verify(&d);
    g_d3d_device=&d;d.rt[0]=&dst;d.fbo_dirty=0;
    d3d_gl_blit(&src,rect,&dst,rect,0);assert(d.fbo_dirty);verify(&d);
    d.fbo_dirty=0;d3d_gl_blit(&ds,rect,&ds,rect,2);assert(d.fbo_dirty);verify(&d);
    start=clears;d.fbo_dirty=0;d3d_gl_fill(&dst,rect,0x12345678u);
    assert(d.fbo_dirty&&clears==start+1);verify(&d);

    /* Non-draw mutations must invalidate the complete context snapshot. */
    damage_state();INVALIDATE();verify(&d);
    memset(&state,0,sizeof state);INVALIDATE();verify(&d);
    printf("PASS raster cache: %u differential states, identical draws emit 0 GL calls, %u redundant calls skipped\n",comparisons,omitted);
    return 0;
}
'''


def sources():
    source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
    apply = function(source, "void d3d_gl_apply_state(")
    gl_body = apply[apply.index("    /* Depth */"):]
    # Both routes use the unchanged translation; only the production cache is bypassed.
    reference = "static void uncached_apply(d3d_device *d) {\nconst uint32_t *rs=d->st.rs;\n" + gl_body
    helpers = source[source.index("static GLenum compare("):source.index("/* ------------------------------------------------------------- samplers */")]
    valid = "static int raster_state_valid;\n" if "static int raster_state_valid;" in source else ""
    invalidate = "#define INVALIDATE() (raster_state_valid=0)\n" if valid else "#define INVALIDATE() ((void)0)\n"
    indices = {int(i) for i in re.findall(r"\brs\[(\d+)\]", gl_body)}
    indices.update(map(int, re.search(r"mask_state\[4\] = \{([^}]+)\}", gl_body)[1].split(",")))
    harness = HARNESS.replace("CONSUMED", ",".join(map(str, sorted(indices))))
    return source, harness, {"state.h": valid + invalidate + helpers, "uncached.h": reference,
                             "clear.h": function(source, "void d3d_gl_clear("),
                             "blit.h": function(source, "void d3d_gl_blit("),
                             "fill.h": function(source, "void d3d_gl_fill(")}


class RasterStateCacheTest(unittest.TestCase):
    def test_actual_state_and_clear(self):
        _, harness, headers = sources()
        compile_probe("raster_state_cache", harness, headers)

    def test_context_present_and_debug_invalidation(self):
        source, _, _ = sources()
        for name, first_mutation in (
            ("int d3d_gl_init(", "eglCreateContext("),
            ("static void follow_window(", "eglMakeCurrent("),
            ("void d3d_gl_device_destroy(", "glUseProgram("),
            ("void d3d_gl_present(", "glDisable(GL_SCISSOR_TEST)"),
        ):
            with self.subTest(function=name):
                body = function(source, name)
                self.assertIn("raster_state_valid = 0;", body[:body.index(first_mutation)])
        draw = function(source, "int d3d_gl_draw(")
        debug = draw[draw.index('getenv("VOID_DEBUG_NOALPHA")'):draw.index('getenv("VOID_TRACE_DIFF")')]
        self.assertLess(debug.index("raster_state_valid = 0;"), debug.index("glDisable(GL_DEPTH_TEST)"))
        self.assertLess(debug.index("raster_state_valid = 0;"), debug.index("glDisable(GL_CULL_FACE)"))


if __name__ == "__main__":
    unittest.main()
