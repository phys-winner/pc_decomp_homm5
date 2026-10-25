"""Exercise production UI promotion, surface ownership and raster coordinates."""
import json
from pathlib import Path
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
typedef int GLint,EGLint,GLsizei;
typedef unsigned GLuint;
enum {D3DPOOL_DEFAULT,GL_TEXTURE_2D,GL_TEXTURE_WIDTH,EGL_WIDTH,EGL_HEIGHT};
#define EGL_NO_SURFACE 0
typedef struct {int depth;} format_t;
typedef struct {int unused;} com_t;
typedef struct d3d_device d3d_device;
typedef struct d3d_surface {
    com_t com;d3d_device *dev;uint32_t width,height,format,usage;GLuint gl;format_t *fmt;
} d3d_surface;
struct d3d_device {d3d_surface *backbuffer,*rt[4],*ds;int fbo_dirty;};
static int window_mode=1,egl_surface=1,egl_display=1,raster_state_valid=1;
static struct {uint32_t max_texture;} d3d_gl_limits={8192};
static int display_w=2400,display_h=1080,allocations,releases,copies,fail_allocate;
static int scissor[4],native_calls;
static d3d_surface *last_allocated;
static format_t color_format={0},depth_format={1};
static void void_log(const char *fmt,...) {(void)fmt;}
static int eglQuerySurface(int display,int surface,int key,EGLint *out) {
    assert(display==1&&surface==1);*out=key==EGL_WIDTH?display_w:display_h;return 1;
}
static d3d_surface *d3d_surface_new(d3d_device *d,uint32_t w,uint32_t h,uint32_t fmt,uint32_t usage,int pool,int samples) {
    assert(pool==D3DPOOL_DEFAULT&&!samples);d3d_surface *s=calloc(1,sizeof *s);assert(s);
    s->dev=d;s->width=w;s->height=h;s->format=fmt;s->usage=usage;s->gl=++allocations;
    s->fmt=fmt==2?&depth_format:&color_format;last_allocated=s;return s;
}
static void glGetTexLevelParameteriv(int target,int level,int key,GLint *out) {
    assert(target==GL_TEXTURE_2D&&!level&&key==GL_TEXTURE_WIDTH);
    *out=fail_allocate?0:(GLint)last_allocated->width;
}
static void void_com_release(com_t *s) {++releases;free(s);}
static void glScissor(GLint x,GLint y,GLsizei w,GLsizei h) {scissor[0]=x;scissor[1]=y;scissor[2]=w;scissor[3]=h;}
static void d3d_gl_blit(d3d_surface *src,const uint32_t *sr,d3d_surface *dst,const uint32_t *dr,uint32_t filter);
/* ACTUAL */
static void d3d_gl_blit(d3d_surface *src,const uint32_t *sr,d3d_surface *dst,const uint32_t *dr,uint32_t filter) {
    assert(!ui_active&&src->dev->fbo_dirty&&src!=dst);
    assert(!sr[0]&&!sr[1]&&sr[2]==src->width&&sr[3]==src->height);
    assert(!dr[0]&&!dr[1]&&dr[2]==dst->width&&dr[3]==dst->height);
    assert(filter==(src->fmt->depth?1u:2u));++copies;
}
static d3d_device *native_device;
void sub_00A46BC0_lifted(void) {assert(ui_quad_depth);++native_calls;ui_promote(native_device);}
static void end_frame(d3d_device *d) {ui_active=0;ui_depth_source=NULL;d->fbo_dirty=1;raster_state_valid=0;}
int main(void) {
    d3d_device d={0},other={0};
    d3d_surface bb={0},depth={0},off={0};bb.dev=&d;bb.width=600;bb.height=270;bb.format=1;bb.fmt=&color_format;
    depth=bb;depth.format=2;depth.fmt=&depth_format;off=bb;off.width=128;off.height=128;
    d.backbuffer=d.rt[0]=&bb;d.ds=&depth;native_device=&d;
    uint32_t rect[]={11,7,40,21},out[4];ui_rect(&d,rect,out);assert(!memcmp(rect,out,sizeof out));
    window_mode=0;ui_promote(&d);assert(!ui_active&&!allocations);window_mode=1;
    d.rt[1]=&off;ui_promote(&d);assert(!allocations);d.rt[1]=NULL;
    d.rt[0]=&off;ui_promote(&d);assert(!allocations);d.rt[0]=&bb;
    display_w=600;display_h=270;ui_promote(&d);assert(!allocations);
    display_w=2400;display_h=1080;d3d_gl_limits.max_texture=1024;ui_promote(&d);assert(!allocations);d3d_gl_limits.max_texture=8192;
    fail_allocate=1;ui_promote(&d);assert(!ui_active&&!ui_color&&releases==1);fail_allocate=0;
    sub_00A46BC0();assert(native_calls==1&&!ui_quad_depth&&ui_active&&copies==1);
    assert(ui_color->width==2400&&ui_color->height==1080&&d.backbuffer==&bb&&bb.width==600);
    assert(ui_surface(&d,&bb)==ui_color&&ui_surface(&d,&off)==&off&&ui_surface(&other,&bb)==&bb);
    ui_rect(&d,rect,out);assert(out[0]==44&&out[1]==28&&out[2]==160&&out[3]==84);
    ui_scissor(&d,-2,3,5,7);assert(scissor[0]==-8&&scissor[1]==12&&scissor[2]==20&&scissor[3]==28);
    ui_prepare_depth(&d);assert(ui_surface(&d,&depth)==ui_depth&&copies==2);
    assert(ui_depth->width==2400&&ui_depth->height==1080&&ui_depth->format==2);
    ui_prepare_depth(&d);assert(copies==2);
    d.rt[0]=&off;ui_prepare_depth(&d);ui_rect(&d,rect,out);assert(!memcmp(rect,out,sizeof out));
    assert(ui_surface(&d,&depth)==&depth);d.rt[0]=&bb;ui_prepare_depth(&d);assert(copies==3);
    int before=allocations;end_frame(&d);sub_00A46BC0();assert(allocations==before&&copies==4);
    // Fractional and negative edges must agree across adjacent scissor rectangles.
    end_frame(&d);bb.width=1319;bb.height=588;sub_00A46BC0();
    uint32_t a[]={11,7,40,21},b[]={51,7,29,21},oa[4],ob[4];ui_rect(&d,a,oa);ui_rect(&d,b,ob);
    assert(oa[0]+oa[2]==ob[0]&&oa[1]==ob[1]&&oa[3]==ob[3]);
    // Emit production coordinates for a real GLES sharp-edge pixel oracle.
    end_frame(&d);bb.width=2;bb.height=2;display_w=display_h=8;sub_00A46BC0();
    uint32_t clips[3][4]={{0,0,2,2},{0,0,1,2},{1,0,1,2}};
    FILE *f=fopen("coords.json","w");assert(f);fputs("[",f);
    for(int i=0;i<3;++i) {ui_rect(&d,clips[i],out);fprintf(f,"%s[%u,%u,%u,%u]",i?",":"",out[0],out[1],out[2],out[3]);}
    fputs("]",f);assert(!fclose(f));
    end_frame(&d);ui_release(&ui_color);ui_release(&ui_depth);assert(allocations==releases);
    puts("PASS actual UI: native quad scope, low-resolution world, native-resolution UI/depth, clips, fractional edges, allocation failure and resource reuse");
    return 0;
}
'''


class UiResolutionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        helpers = source[source.index("/* The native quad renderer"):source.index("void d3d_gl_bind_targets(")]
        compile_probe("ui_resolution", HARNESS.replace("/* ACTUAL */", helpers).replace('"coords.json"', json.dumps(str(ROOT / "build/tests/ui_resolution/coords.json"))), {})
        cls.coords = json.loads((ROOT / "build/tests/ui_resolution/coords.json").read_text())

    def test_native_routing_and_lifetime(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        draw = function(source, "int d3d_gl_draw(")
        self.assertLess(draw.index("if (ui_quad_depth) ui_promote(d);"), draw.index("d3d_gl_apply_state(d);"))
        present = function(source, "void d3d_gl_present(")
        self.assertIn("d3d_surface *bb = ui_surface(dev, dev->backbuffer);", present)
        self.assertLess(present.index("eglSwapBuffers("), present.index("ui_active = 0;"))
        self.assertIn("ui_release(&ui_color); ui_release(&ui_depth);", function(source, "void d3d_gl_device_destroy("))

    def test_quad_override_preserves_original_guest_register_summary(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "tools"))
        import build_android
        with patch.object(build_android, "_protocol", None), patch.object(build_android, "Protocol") as protocol:
            build_android.call_protocol()
            full = protocol.call_args.kwargs["full"]
            self.assertIn("sub_00A46BC0", build_android.NATIVE_OVERRIDES)
            self.assertNotIn("sub_00A46BC0", full)
            self.assertEqual(set(full), set(build_android.NATIVE_OVERRIDES) - {"sub_00A46BC0"})

    def test_native_resolution_ui_edges_with_gles(self):
        import ctypes as C
        from test_legacy_shaders import Angle
        a = Angle()
        a.api(a.gl, "glScissor", None, *([C.c_int] * 4))
        a.api(a.gl, "glEnable", None, C.c_uint)
        a.api(a.gl, "glClearColor", None, *([C.c_float] * 4))
        a.api(a.gl, "glClear", None, C.c_uint)
        a.api(a.gl, "glReadPixels", None, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_void_p)
        a.api(a.gl, "glDisable", None, C.c_uint)
        a.api(a.gl, "glGenFramebuffers", None, C.c_int, C.POINTER(C.c_uint))
        a.api(a.gl, "glBindFramebuffer", None, C.c_uint, C.c_uint)
        a.api(a.gl, "glFramebufferTexture2D", None, C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_int)
        a.api(a.gl, "glCheckFramebufferStatus", C.c_uint, C.c_uint)
        a.api(a.gl, "glBlitFramebuffer", None, *([C.c_int]*8), C.c_uint, C.c_uint)
        a.api(a.gl, "glDeleteFramebuffers", None, C.c_int, C.POINTER(C.c_uint))
        a.api(a.gl, "glDeleteTextures", None, C.c_int, C.POINTER(C.c_uint))
        targets, textures = (C.c_uint*2)(), (C.c_uint*4)()
        a.gl.glGenFramebuffers(2, targets); a.gl.glGenTextures(4, textures)
        for i,size in enumerate((2,8)):
            a.gl.glBindFramebuffer(0x8D40, targets[i])
            for j,internal,fmt,typ,point in ((0,0x8058,0x1908,0x1401,0x8CE0),(1,0x88F0,0x84F9,0x84FA,0x821A)):
                texture=textures[2*i+j]
                a.gl.glBindTexture(0x0DE1,texture)
                a.gl.glTexImage2D(0x0DE1,0,internal,size,size,0,fmt,typ,None)
                a.gl.glFramebufferTexture2D(0x8D40,point,0x0DE1,texture,0)
            self.assertEqual(a.gl.glCheckFramebufferStatus(0x8D40),0x8CD5)
        a.gl.glBindFramebuffer(0x8D40,targets[0]); a.gl.glDisable(0x0C11)
        a.gl.glClearColor(0,0,1,1); a.gl.glClear(0x4000|0x100|0x400)
        a.gl.glBindFramebuffer(0x8CA8,targets[0]); a.gl.glBindFramebuffer(0x8CA9,targets[1])
        a.gl.glBlitFramebuffer(0,0,2,2,0,0,8,8,0x4000,0x2601)
        a.gl.glBlitFramebuffer(0,0,2,2,0,0,8,8,0x100|0x400,0x2600)
        self.assertEqual(a.gl.glGetError(),0)
        a.gl.glBindFramebuffer(0x8D40,targets[1])
        a.gl.glEnable(0x0C11)
        for clip,color in zip(self.coords, ((0,0,0,1),(1,0,0,1),(0,1,0,1))):
            a.gl.glScissor(*clip); a.gl.glClearColor(*color); a.gl.glClear(0x4000)
        pixels = (C.c_ubyte * (8 * 8 * 4))()
        a.gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels)
        for y in range(8):
            for x in range(8):
                self.assertEqual(tuple(pixels[(y*8+x)*4:(y*8+x)*4+4]), (255,0,0,255) if x<4 else (0,255,0,255))
        # A one-pixel glyph-like pattern must stay at display resolution after scene promotion.
        vs=a.compile(b"#version 300 es\nvoid main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}",0x8B31)
        ps=a.compile(b"#version 300 es\nprecision highp float;out vec4 color;void main(){float v=mod(floor(gl_FragCoord.x),2.);color=vec4(v,v,0,1);}")
        program=a.gl.glCreateProgram()
        for shader in (vs,ps): a.gl.glAttachShader(program,shader)
        a.gl.glLinkProgram(program); a.gl.glUseProgram(program)
        a.gl.glDisable(0x0C11); a.gl.glViewport(*self.coords[0]); a.gl.glDrawArrays(4,0,3)
        a.gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels)
        for y in range(8):
            for x in range(8):
                self.assertEqual(tuple(pixels[(y*8+x)*4:(y*8+x)*4+4]),(255,255,0,255) if x%2 else (0,0,0,255))
        for shader in (vs,ps): a.gl.glDeleteShader(shader)
        a.gl.glDeleteProgram(program); a.gl.glDeleteFramebuffers(2,targets); a.gl.glDeleteTextures(4,textures)
        self.assertEqual(a.gl.glGetError(),0)


if __name__ == "__main__":
    unittest.main()
