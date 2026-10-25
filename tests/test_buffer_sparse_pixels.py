"""Render the actual sparse helpers and draw routing through local ANGLE.

Each case renders with the per-draw stores (VOID_NO_RING) and with the
streaming ring. Where ANGLE lacks GL_EXT_buffer_storage the ring's coherent
persistent mapping is emulated: a CPU copy of the mapping uploaded to the
ring's GL store before each draw (routing and offsets are real; GPU/CPU
hazards that the segment fences prevent cannot be observed this way).
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_legacy_shaders import Angle
from test_static_tls import ROOT
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

OUT = ROOT / "build/tests/buffer_sparse_pixels"
V, U, I, P = None, C.c_uint, C.c_int, C.c_void_p
APIS = [
    ("glGenBuffers", "void", "GLsizei,GLuint*", V, [I, C.POINTER(U)]),
    ("glDeleteBuffers", "void", "GLsizei,const GLuint*", V, [I, C.POINTER(U)]),
    ("glBindBuffer", "void", "GLenum,GLuint", V, [U, U]),
    ("glBufferData", "void", "GLenum,GLsizeiptr,const void*,GLenum", V, [U, C.c_ssize_t, P, U]),
    ("glVertexAttribPointer", "void", "GLuint,GLint,GLenum,GLboolean,GLsizei,const void*", V, [U,I,U,C.c_ubyte,I,P]),
    ("glEnableVertexAttribArray", "void", "GLuint", V, [U]),
    ("glDisableVertexAttribArray", "void", "GLuint", V, [U]),
    ("glVertexAttribDivisor", "void", "GLuint,GLuint", V, [U,U]),
    ("glVertexAttrib4f", "void", "GLuint,GLfloat,GLfloat,GLfloat,GLfloat", V, [U]+[C.c_float]*4),
    ("glDrawArrays", "void", "GLenum,GLint,GLsizei", V, [U,I,I]),
    ("glDrawArraysInstanced", "void", "GLenum,GLint,GLsizei,GLsizei", V, [U,I,I,I]),
    ("glDrawElements", "void", "GLenum,GLsizei,GLenum,const void*", V, [U,I,U,P]),
    ("glDrawElementsBaseVertex", "void", "GLenum,GLsizei,GLenum,const void*,GLint", V, [U,I,U,P,I]),
    ("glDrawRangeElementsBaseVertex", "void", "GLenum,GLuint,GLuint,GLsizei,GLenum,const void*,GLint", V, [U,U,U,I,U,P,I]),
    ("glDrawElementsInstancedBaseVertex", "void", "GLenum,GLsizei,GLenum,const void*,GLsizei,GLint", V, [U,I,U,P,I,I]),
    ("glGetError", "GLenum", "void", U, []),
    ("glBufferSubData", "void", "GLenum,GLintptr,GLsizeiptr,const void*", V, [U, C.c_ssize_t, C.c_ssize_t, P]),
    ("glGetString", "const GLubyte*", "GLenum", C.c_char_p, [U]),
    ("glMapBufferRange", "void*", "GLenum,GLintptr,GLsizeiptr,GLbitfield", P, [U, C.c_ssize_t, C.c_ssize_t, U]),
    ("glUnmapBuffer", "GLboolean", "GLenum", C.c_ubyte, [U]),
    ("glFenceSync", "GLsync", "GLenum,GLbitfield", P, [U, U]),
    ("glClientWaitSync", "GLenum", "GLsync,GLbitfield,GLuint64", U, [P, U, C.c_uint64]),
    ("glDeleteSync", "void", "GLsync", V, [P]),
]
# Production calls these through the probe: the ring's extension query/mapping and flushed draws.
WRAPPED = {"glGetString", "glMapBufferRange", "glUnmapBuffer", "glDrawArrays", "glDrawArraysInstanced",
           "glDrawElements", "glDrawElementsBaseVertex", "glDrawRangeElementsBaseVertex", "glDrawElementsInstancedBaseVertex"}

PRE = r'''
#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <limits.h>
typedef unsigned GLenum,GLuint,GLbitfield;typedef int GLint,GLsizei;typedef unsigned char GLboolean,GLubyte;
typedef float GLfloat;typedef intptr_t GLsizeiptr,GLintptr;typedef uint64_t GLuint64;typedef struct __GLsync *GLsync;
typedef void (*PFNGLBUFFERSTORAGEEXTPROC)(GLenum,GLsizeiptr,const void*,GLbitfield);
typedef void (*egl_proc)(void);
#define GL_FALSE 0
#define GL_TRUE 1
#define GL_FLOAT 0x1406u
#define GL_UNSIGNED_BYTE 0x1401u
#define GL_SHORT 0x1402u
#define GL_UNSIGNED_SHORT 0x1403u
#define GL_UNSIGNED_INT 0x1405u
#define GL_UNSIGNED_INT_2_10_10_10_REV 0x8368u
#define GL_INT_2_10_10_10_REV 0x8D9Fu
#define GL_HALF_FLOAT 0x140Bu
#define GL_ARRAY_BUFFER 0x8892u
#define GL_ELEMENT_ARRAY_BUFFER 0x8893u
#define GL_COPY_WRITE_BUFFER 0x8F37u
#define GL_STREAM_DRAW 0x88E0u
#define GL_POINTS 0
#define GL_LINES 1
#define GL_LINE_STRIP 3
#define GL_TRIANGLES 4
#define GL_TRIANGLE_STRIP 5
#define GL_TRIANGLE_FAN 6
#define GL_NO_ERROR 0u
#define GL_EXTENSIONS 0x1F03u
#define GL_MAP_WRITE_BIT 0x0002u
#define GL_MAP_PERSISTENT_BIT_EXT 0x0040u
#define GL_MAP_COHERENT_BIT_EXT 0x0080u
#define GL_SYNC_GPU_COMMANDS_COMPLETE 0x9117u
#define GL_SYNC_FLUSH_COMMANDS_BIT 0x00000001u
#define GL_ALREADY_SIGNALED 0x911Au
#define GL_CONDITION_SATISFIED 0x911Cu
#define GL_WAIT_FAILED 0x911Du
#define FB_UNKNOWN UINT32_MAX
typedef struct {uint32_t size,shadow,format;GLuint gl;uint8_t *dirty_pages;int locks;} d3d_buffer;
typedef struct {uint16_t stream,offset;uint8_t type,method,usage,usage_index;} d3d_vertex_element;
typedef struct {int count;d3d_vertex_element elements[8];} d3d_decl;
typedef struct {int unused;} d3d_shader;
typedef struct {struct {void *vs,*ps,*decl,*indices,*streams[16];uint32_t stream_stride[16],stream_offset[16],stream_freq[16],rs[256],viewport[4];} st;} d3d_device;
static unsigned char memory[80u*1024u*1024u];
#define GPTR(a) (memory+(uint32_t)(a))
static int void_vm_readable(uint32_t a,uint32_t n){return a>0&&(uint64_t)a+n<=sizeof memory;}
static uint64_t draw_calls,vb_upload_calls,vb_upload_bytes,vb_upload_frame_bytes,vb_sparse_calls,vb_sparse_saved;
static GLuint up_vbo,up_ibo,stream_vbos[16],elem_buffer=FB_UNKNOWN;
static uint32_t enabled_attribs;static int attr_cache_ready;
typedef struct {GLuint buffer;GLint size;GLenum type;GLboolean norm;GLsizei stride;uintptr_t offset;GLuint divisor;} attr_state;
static attr_state attr_cache[16];
static int enable_sparse,draw_errors,shader_fail,ring_mode=-1,emulate_ring,ring_logs;
static d3d_device fixture_device;
static d3d_decl fixture_decl;
static d3d_buffer fixture_buffers[4];
static void void_log(const char *format,...){if(!strncmp(format,"[gl] streaming ring: %u",23))++ring_logs;else ++draw_errors;}
static unsigned ui_quad_depth;
static void ui_promote(d3d_device *d){(void)d;}
static void d3d_gl_bind_targets(d3d_device *d){(void)d;}
static void d3d_gl_apply_state(d3d_device *d){(void)d;}
static void bind_texture(d3d_device *d,int s,GLuint u){(void)d;(void)s;(void)u;}
static int d3d_ff_bind(d3d_device*d,int *count,int *usage,int *index,uint32_t *samplers){
 (void)d;*count=fixture_decl.count;*samplers=0;
 for(int i=0;i<*count;i++){usage[i]=fixture_decl.elements[i].usage;index[i]=0;}
 return !shader_fail;
}
static int d3d_shader_bind2(d3d_device*d,d3d_shader*v,d3d_shader*p,int(*bg)(d3d_device*,int,int),int*c,const int**u,const int**i,uint32_t*ps,uint32_t*vs,const int**pt,const int**vt){(void)d;(void)v;(void)p;(void)bg;(void)c;(void)u;(void)i;(void)ps;(void)vs;(void)pt;(void)vt;return 0;}
static void d3d_shader_upload(d3d_device*d,float x,float y,int f,float r){(void)d;(void)x;(void)y;(void)f;(void)r;}
/* GL_PROCEDURES */
static egl_proc (*p_eglGetProcAddress)(const char*);
static uint8_t *emulated_map;
static int native_storage(void){const char*e=(const char*)p_glGetString(GL_EXTENSIONS);return e&&strstr(e,"GL_EXT_buffer_storage")!=NULL;}
static const GLubyte *probe_glGetString(GLenum name){
 static char extensions[1<<16];
 const GLubyte *s=p_glGetString(name);
 if(name!=GL_EXTENSIONS||!emulate_ring)return s;
 snprintf(extensions,sizeof extensions,"%s GL_EXT_buffer_storage",s?(const char*)s:"");return (const GLubyte*)extensions;
}
/* The ring's GL store; the emulated mapping is a CPU copy uploaded before each draw. */
static void emulated_storage(GLenum target,GLsizeiptr size,const void*data,GLbitfield flags){
 assert(!data&&flags==(GL_MAP_WRITE_BIT|GL_MAP_PERSISTENT_BIT_EXT|GL_MAP_COHERENT_BIT_EXT));p_glBufferData(target,size,NULL,GL_STREAM_DRAW);
}
static egl_proc eglGetProcAddress(const char*name){return emulate_ring&&!strcmp(name,"glBufferStorageEXT")?(egl_proc)emulated_storage:p_eglGetProcAddress(name);}
static void *probe_glMapBufferRange(GLenum target,GLintptr offset,GLsizeiptr length,GLbitfield access){
 if(!emulate_ring)return p_glMapBufferRange(target,offset,length,access);
 assert(!offset&&(access&GL_MAP_PERSISTENT_BIT_EXT)&&!emulated_map);emulated_map=calloc(1,(size_t)length);return emulated_map;
}
static GLboolean probe_glUnmapBuffer(GLenum target){
 if(!emulated_map)return p_glUnmapBuffer(target);
 free(emulated_map);emulated_map=NULL;return GL_TRUE;
}
static void d3d_buffer_flush(d3d_buffer*b){(void)b;}
static void d3d_buffer_flush_range(d3d_buffer*b,uint32_t lo,uint32_t hi){assert(hi<=b->size&&lo<hi);}
/* ACTUAL_HELPERS */
static void flush_emulated_ring(void){
 if(!emulated_map||ring_map!=emulated_map||!ring_used)return;
 uint32_t base=ring_segment*RING_SEGMENT_BYTES;
 p_glBindBuffer(GL_COPY_WRITE_BUFFER,ring_buffer);p_glBufferSubData(GL_COPY_WRITE_BUFFER,base,ring_used,emulated_map+base);
}
static void probe_glDrawArrays(GLenum m,GLint f,GLsizei n){flush_emulated_ring();p_glDrawArrays(m,f,n);}
static void probe_glDrawArraysInstanced(GLenum m,GLint f,GLsizei n,GLsizei i){flush_emulated_ring();p_glDrawArraysInstanced(m,f,n,i);}
static void probe_glDrawElements(GLenum m,GLsizei n,GLenum t,const void*p){flush_emulated_ring();p_glDrawElements(m,n,t,p);}
static void probe_glDrawElementsBaseVertex(GLenum m,GLsizei n,GLenum t,const void*p,GLint b){flush_emulated_ring();p_glDrawElementsBaseVertex(m,n,t,p,b);}
static void probe_glDrawRangeElementsBaseVertex(GLenum m,GLuint lo,GLuint hi,GLsizei n,GLenum t,const void*p,GLint b){flush_emulated_ring();p_glDrawRangeElementsBaseVertex(m,lo,hi,n,t,p,b);}
static void probe_glDrawElementsInstancedBaseVertex(GLenum m,GLsizei n,GLenum t,const void*p,GLsizei i,GLint b){flush_emulated_ring();p_glDrawElementsInstancedBaseVertex(m,n,t,p,i,b);}
#define draw_sparse_prepare(...) (enable_sparse ? draw_sparse_prepare(__VA_ARGS__) : 0u)
/* ACTUAL_DRAW */
#undef draw_sparse_prepare

__declspec(dllexport) void probe_egl(egl_proc (*get)(const char*)){p_eglGetProcAddress=get;}
__declspec(dllexport) void probe_begin(int ring){
 if(ring!=ring_mode){
  ring_release();ring_mode=ring;
  _putenv(ring?"VOID_NO_RING=":"VOID_NO_RING=1");   /* production switch for the per-draw stores */
  emulate_ring=ring&&!native_storage();
 } else ring_frame_end();                            /* as at Present: the next segment, after its fence */
 for(unsigned i=0;i<16;i++)if(stream_vbos[i])glDeleteBuffers(1,&stream_vbos[i]);
 if(up_vbo)glDeleteBuffers(1,&up_vbo);if(up_ibo)glDeleteBuffers(1,&up_ibo);
 for(unsigned i=0;i<4;i++)if(fixture_buffers[i].gl)glDeleteBuffers(1,&fixture_buffers[i].gl);
 memset(stream_vbos,0,sizeof stream_vbos);up_vbo=up_ibo=0;
 memset(attr_cache,0,sizeof attr_cache);attr_cache_ready=0;elem_buffer=FB_UNKNOWN;
 for(unsigned i=0;i<16;i++){glDisableVertexAttribArray(i);glVertexAttribDivisor(i,0);}
 enabled_attribs=0;glVertexAttrib4f(2,0,0,0,1);
 memset(&fixture_device,0,sizeof fixture_device);memset(&fixture_decl,0,sizeof fixture_decl);
 memset(fixture_buffers,0,sizeof fixture_buffers);fixture_device.st.decl=&fixture_decl;
 draw_errors=shader_fail=0;vb_sparse_calls=vb_sparse_saved=0;
}
__declspec(dllexport) void probe_stream(unsigned slot,const void *bytes,uint32_t size,uint32_t stride,uint32_t offset,int dirty){
 assert(slot<4&&size>0&&size<20u*1024u*1024u);d3d_buffer*b=&fixture_buffers[slot];
 b->size=size;b->shadow=4096u+slot*20u*1024u*1024u;assert(void_vm_readable(b->shadow,size));
 b->dirty_pages=dirty?(uint8_t*)1:NULL;memcpy(GPTR(b->shadow),bytes,size);
 if(!b->gl)glGenBuffers(1,&b->gl);glBindBuffer(GL_COPY_WRITE_BUFFER,b->gl);
 glBufferData(GL_COPY_WRITE_BUFFER,size,bytes,GL_STREAM_DRAW);
 if(slot<3){fixture_device.st.streams[slot]=b;fixture_device.st.stream_stride[slot]=stride;fixture_device.st.stream_offset[slot]=offset;}
 else{fixture_device.st.indices=b;b->format=stride;}
}
__declspec(dllexport) void probe_layout(int instances,int interleaved){
 fixture_decl.count=instances?3:2;
 fixture_decl.elements[0]=(d3d_vertex_element){0,interleaved?0:4,1,0,0,0};
 fixture_decl.elements[1]=(d3d_vertex_element){interleaved?0:1,interleaved?8:4,3,0,10,0};
 fixture_decl.elements[2]=(d3d_vertex_element){2,4,1,0,5,0};
 fixture_device.st.stream_freq[0]=instances?(0x40000000u|(unsigned)instances):1;
 fixture_device.st.stream_freq[1]=1;fixture_device.st.stream_freq[2]=instances?0x80000001u:1;
}
__declspec(dllexport) int probe_draw(int sparse,unsigned primitive,int indexed,uint32_t base,uint32_t start_index,uint32_t start_vertex,uint32_t count,int up){
 enable_sparse=sparse;
 const void *vertices=up?GPTR(fixture_buffers[0].shadow)+fixture_device.st.stream_offset[0]:NULL;
 const void *indices=up&&indexed?GPTR(fixture_buffers[3].shadow)+(size_t)start_index*(fixture_buffers[3].format==102?4:2):NULL;
 return d3d_gl_draw(&fixture_device,primitive,start_vertex,count,count/3,indexed,base,start_index,0,vertices,fixture_device.st.stream_stride[0],indices,fixture_buffers[3].format==102);
}
__declspec(dllexport) uint64_t probe_sparse_calls(void){return vb_sparse_calls;}
__declspec(dllexport) int probe_ring_state(void){return ring_state;}
__declspec(dllexport) unsigned probe_ring_used(void){return ring_used;}
__declspec(dllexport) int probe_ring_emulated(void){return !native_storage();}
__declspec(dllexport) unsigned probe_errors(void){return (unsigned)draw_errors;}
__declspec(dllexport) unsigned probe_dense_max(unsigned count){unsigned n=0;for(unsigned i=0;i<count;i++)if(sparse_indices[i]>n)n=sparse_indices[i];return n;}
'''


def without_diagnostic_blocks(source):
    """Omit only disabled observational trace branches; keep every draw decision."""
    for anchor in ("    if (tracing(d)) {", "    if (trace_query) {"):
        while anchor in source:
            start = source.index(anchor)
            opening = source.index("{", start)
            depth, pos = 1, opening + 1
            while depth:
                depth += (source[pos] == "{") - (source[pos] == "}")
                pos += 1
            source = source[:start] + source[pos:]
    line = "    if (depth_trace_remaining) depth_trace_draw(d, ps_samplers, vs_samplers, shader_tag(vs), shader_tag(ps));\n"
    assert source.count(line) == 1
    return source.replace(line, "")


def fixture(mutant=False):
    source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
    a = source.index("typedef struct { GLint size; GLenum type; GLboolean norm; } attr_format;")
    z = source.index("void d3d_buffer_flush(", a)
    attributes = source[a:z]
    a = source.index("/* Sparse pooled meshes")
    z = source.index("static GLenum gl_mode(", a)
    sparse = source[a:z]
    ring = source[source.index("/* Per-draw uploads go to one persistently mapped buffer"):source.index("static uint32_t enabled_attribs;")]
    helpers = attributes + "\n".join(function(source, name) for name in (
        "static int draw_vertex_bounds(", "static void buffer_flush_vertices(",
        "static int draw_stream_range(", "static int draw_rebase(", "static GLenum gl_mode(")) + ring + sparse
    draw = without_diagnostic_blocks(function(source, "int d3d_gl_draw("))
    if mutant:
        good = "(b->dirty_pages || (sparse_count && !instanced))"
        assert draw.count(good) == 1
        draw = draw.replace(good, "b->dirty_pages")
    declarations, assignments = [], []
    for index, (name, ret, args, _, _) in enumerate(APIS):
        declarations += [f"static {ret} (*p_{name})({args});", f"#define {name} {'probe' if name in WRAPPED else 'p'}_{name}"]
        if name in WRAPPED:
            declarations.append(f"static {ret} probe_{name}({args});")
        assignments.append(f"p_{name}=({ret} (*)({args}))procedures[{index}];")
    declarations += ["__declspec(dllexport) void probe_api(void **procedures){", *assignments, "}"]
    return PRE.replace("/* GL_PROCEDURES */", "\n".join(declarations)).replace("/* ACTUAL_HELPERS */", helpers).replace("/* ACTUAL_DRAW */", draw), hashlib.sha256(source.encode()).hexdigest()


def build(mutant=False):
    out = OUT / ("bad_static_route" if mutant else "actual")
    out.mkdir(parents=True, exist_ok=True)
    code, source_hash = fixture(mutant)
    (out / "probe.c").write_text(code, encoding="utf8")
    install = Path(subprocess.check_output([r"C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe", "-latest", "-products", "*", "-property", "installationPath"], text=True).strip())
    msvc = sorted((install / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:/Program Files (x86)/Windows Kits/10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    env = os.environ.copy()
    env["PATH"] = str(msvc / "bin/Hostx64/x64") + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk/f"Include/{version}/ucrt", sdk/f"Include/{version}/shared", sdk/f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk/f"Lib/{version}/ucrt/x64", sdk/f"Lib/{version}/um/x64"]))
    compiler = (TOOLCHAIN / 'bin/clang-cl.exe')
    result = subprocess.run([str(compiler), "/nologo", "/O2", "/std:c11", "/W4", "/WX", "/clang:-Wno-unused-function", "/clang:-Wno-unused-variable", "/c", "probe.c", "/Foprobe.obj"], cwd=out, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(msvc/"bin/Hostx64/x64/link.exe"), "/nologo", "/DLL", "/OUT:probe.dll", "probe.obj"], cwd=out, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    dll = C.CDLL(str(out / "probe.dll"))
    dll.probe_api.argtypes = [C.POINTER(P)]
    dll.probe_egl.argtypes = [P]
    dll.probe_begin.argtypes = [I]
    dll.probe_ring_state.restype = I
    dll.probe_ring_used.restype = U
    dll.probe_ring_emulated.restype = I
    dll.probe_stream.argtypes = [U,P,U,U,U,I]
    dll.probe_layout.argtypes = [I,I]
    dll.probe_draw.argtypes = [I,U,I,U,U,U,U,I]
    dll.probe_draw.restype = I
    dll.probe_sparse_calls.restype = C.c_uint64
    dll.probe_dense_max.argtypes = [U]
    dll.probe_dense_max.restype = U
    dll.source_hash = source_hash
    return dll


class SparsePixelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.angle = Angle()
        a = cls.angle
        a.api(a.egl, "eglGetProcAddress", P, C.c_char_p)
        cls.pointers = []
        for name, _, _, result, args in APIS:
            if "BaseVertex" in name:
                pointer = next((a.egl.eglGetProcAddress((name+suffix).encode()) for suffix in ("OES", "EXT", "") if a.egl.eglGetProcAddress((name+suffix).encode())), None)
                if not pointer:
                    raise unittest.SkipTest("ANGLE base-vertex draw extension required")
                cls.pointers.append(pointer)
            else:
                a.api(a.gl, name, result, *args)
                cls.pointers.append(C.cast(getattr(a.gl, name), P).value)
        for name, result, args in [("glDisable", V, [U]), ("glClear", V, [U]), ("glClearColor", V, [C.c_float]*4)]:
            a.api(a.gl, name, result, *args)
        cls.actual, cls.bad = build(), build(True)
        procedures = (P*len(APIS))(*cls.pointers)
        egl = C.cast(a.egl.eglGetProcAddress, P).value
        for lib in (cls.actual, cls.bad):
            lib.probe_api(procedures)
            lib.probe_egl(egl)
        vs = a.compile(b"#version 300 es\nprecision highp float;layout(location=0)in vec2 p;layout(location=1)in vec4 c;layout(location=2)in vec2 instance_offset;out vec4 color;void main(){gl_Position=vec4(p+instance_offset,0,1);color=c;}", 0x8B31)
        ps = a.compile(b"#version 300 es\nprecision highp float;in vec4 color;out vec4 output_color;void main(){output_color=color;}")
        cls.program = a.gl.glCreateProgram()
        for shader in (vs, ps):
            a.gl.glAttachShader(cls.program, shader)
        a.gl.glLinkProgram(cls.program)
        ok = I()
        a.gl.glGetProgramiv(cls.program, 0x8B82, C.byref(ok))
        assert ok.value
        a.gl.glUseProgram(cls.program)
        for shader in (vs, ps):
            a.gl.glDeleteShader(shader)
        cls.results = []

    def render(self, case, sparse, lib=None, ring=False):
        lib = lib or self.actual
        gl = self.angle.gl
        lib.probe_begin(int(ring))
        gl.glUseProgram(self.program)
        for flag in (0xB71, 0xBE2, 0xB90, 0xB44, 0xC11):
            gl.glDisable(flag)
        gl.glClearColor(0,0,0,1)
        gl.glViewport(0,0,8,8)
        gl.glClear(0x4000)
        base = case.get("base", 0)
        effective = case.get("vertices", [7, 2048, 4090])
        raw = case.get("raw", [v-base for v in effective])
        wide = case.get("wide", True)
        instances = case.get("instances", 0)
        indexed = case.get("indexed", True)
        up = case.get("up", False)
        start_index = 5
        repeat = case.get("repeat", 1)
        if "many" in case:
            effective = [8*i for i in range(case["many"])]
            raw = effective
        refs = raw*repeat
        count = len(refs) if indexed else len(effective)
        for queued in range(2 if case.get("queued") else 1):
            draw_up = up or bool(queued and case.get("after_up"))
            draw_refs = [0,1,2] if draw_up else refs
            max_vertex = max(effective)
            pos_stride, color_stride = 20, 24
            pos_offset, color_offset = 12, 28
            positions = bytearray(pos_offset+(max_vertex+1)*pos_stride)
            colors = bytearray(color_offset+(max_vertex+1)*color_stride)
            triangle = ((-.5,-1),(.5,-1),(-.5,1)) if instances else ((-1,-1),(3,-1),(-1,3))
            palette = ((1,0,0,1),(0,1,0,1),(0,0,1,1)) if not queued else ((0,1,1,1),(1,0,1,1),(1,1,0,1))
            for i, vertex in enumerate(effective):
                struct.pack_into("<2f", positions, pos_offset+vertex*pos_stride+4, *triangle[i%3])
                struct.pack_into("<4f", colors, color_offset+vertex*color_stride+4, *palette[i%3])
            if draw_up:
                positions = bytearray(b"".join(struct.pack("<6f", *triangle[i%3], *palette[i%3]) for i in range(3)))
                pos_stride, pos_offset = 24, 0
            lib.probe_stream(0,bytes(positions),len(positions),pos_stride,pos_offset,int(case.get("dirty",True)))
            lib.probe_stream(1,bytes(colors),len(colors),color_stride,color_offset,int(case.get("color_dirty",False)))
            if instances:
                instance = bytearray(28+instances*16)
                for i in range(instances):
                    struct.pack_into("<2f", instance, 28+i*16+4, -.5+i,0)
                lib.probe_stream(2,bytes(instance),len(instance),16,28,int(case.get("instance_dirty",False)))
            if indexed:
                indices = bytes(start_index*(4 if wide else 2))+struct.pack("<"+("I" if wide else "H")*len(draw_refs), *draw_refs)
                lib.probe_stream(3,indices,len(indices),102 if wide else 101,0,int(case.get("index_dirty",True)))
            lib.probe_layout(instances,draw_up)
            gl.glViewport(queued*4,0,4,8) if case.get("queued") else gl.glViewport(0,0,8,8)
            self.assertEqual(lib.probe_draw(int(sparse),case.get("primitive",4),int(indexed),0 if draw_up else base&0xffffffff,start_index,0 if draw_up else effective[0],len(draw_refs) if draw_up else count,int(draw_up)),1)
            self.assertEqual(lib.probe_errors(),0)
        # The ring holds this frame's uploads; client (UP) data never consults it.
        state, used = lib.probe_ring_state(), lib.probe_ring_used()
        if up:
            self.assertIn(state, (0, 1 if ring else -1))
            self.assertEqual(used, 0)
        else:
            self.assertEqual(state, 1 if ring else -1)
            self.assertEqual(used > 0, ring)
        pixels = (C.c_ubyte*256)()
        gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels)
        self.assertEqual(gl.glGetError(),0)
        return bytes(pixels),lib.probe_sparse_calls()

    def check_case(self, case, expected_sparse=True):
        expected, old_calls = self.render(case,False)
        self.assertEqual(old_calls,0)
        expected_calls = (2 if case.get("queued") and not case.get("after_up") else 1) if expected_sparse else 0
        self.assertGreater(sum(bool(expected[i] or expected[i+1] or expected[i+2]) for i in range(0,256,4)),16)
        for ring, sparse in ((False, True), (True, False), (True, True)):
            with self.subTest(ring=ring, sparse=sparse):
                actual, new_calls = self.render(case,sparse,ring=ring)
                self.assertEqual(new_calls,expected_calls if sparse else 0)
                self.assertEqual(actual,expected)
        self.results.append({"name":case["name"],"pixel_sha256":hashlib.sha256(expected).hexdigest(),"sparse_calls":expected_calls,
                             "paths":["stores", "stores+sparse", "ring", "ring+sparse"]})

    def test_sparse_actual_draw_pixels(self):
        cases = [
            dict(name="wide-mixed-static"),
            dict(name="negative-base32",base=-65531),
            dict(name="negative-base16",base=-5,wide=False),
            dict(name="positive-base16",base=3,wide=False),
            dict(name="raw65535-is-a-vertex",base=-60000,wide=False,vertices=[7,2048,5535]),
            dict(name="repeated-primitive-order",repeat=5),
            dict(name="triangle-strip-order",primitive=5,vertices=[7,4090,2048,12],raw=[7,4090,2048,12]),
            dict(name="two-dirty-streams",color_dirty=True),
            dict(name="static-position-dirty-color",dirty=False,color_dirty=True),
            dict(name="instance-static-offset",instances=2),
            dict(name="instance-dirty-offset",instances=2,instance_dirty=True),
            dict(name="queued-orphans-mixed",queued=True),
            dict(name="queued-orphans-instanced",queued=True,instances=2,instance_dirty=True),
            dict(name="queued-sparse-then-UP-indexed",queued=True,after_up=True),
        ]
        for case in cases:
            with self.subTest(name=case["name"]):
                self.check_case(case)

    def test_dense_remap_exceeds_16_bits(self):
        self.check_case(dict(name="dense-index-above65535",many=65538))
        self.assertGreater(self.actual.probe_dense_max(65538),65535)

    def test_unchanged_arrays_up_and_compact_fallback(self):
        for case in [dict(name="arrays",indexed=False,vertices=[7,8,9]),
                     dict(name="dense-indexed-fallback",vertices=[7,8,9]),
                     dict(name="static-only-fallback",dirty=False),
                     dict(name="UP-arrays",indexed=False,vertices=[0,1,2],up=True),
                     dict(name="UP-indexed",vertices=[0,1,2],up=True)]:
            with self.subTest(name=case["name"]):
                self.check_case(case,False)

    def test_missing_static_stream_gather_is_visible(self):
        case=dict(name="negative-static-route",queued=True)
        expected,_=self.render(case,False)
        for ring in (False, True):
            with self.subTest(ring=ring):
                wrong,calls=self.render(case,True,self.bad,ring)
                self.assertGreater(calls,0)
                self.assertNotEqual(wrong,expected)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,"results"):
            ring = "emulated coherent mapping (ANGLE without GL_EXT_buffer_storage)" if cls.actual.probe_ring_emulated() else "native GL_EXT_buffer_storage"
            (OUT/"pixel-receipt.json").write_text(json.dumps({"source_sha256":cls.actual.source_hash,"ring":ring,"cases":cls.results,"comparisons":len(cls.results),"negative_control":"static stream routing omission must change pixels","scope":"Current production sparse helpers+draw body; disabled diagnostic trace branches omitted; ANGLE uses real uploads/attributes/draws/readback; no Mali performance claim"},indent=2),encoding="utf8")


if __name__ == "__main__":
    unittest.main()
