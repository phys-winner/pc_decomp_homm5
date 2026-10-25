"""Run CURRENT actual target/blit bodies through local ANGLE, with no fake pixels."""
from pathlib import Path
import ctypes as C
import json
import os
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "build/tests/mrt_draw_buffers"
sys.path.insert(0, str(ROOT / "tests"))
from test_d3d_lifecycle import function
from test_legacy_shaders import Angle
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

ANCHOR = "            glDrawBuffers(slot + 1, bufs);\n"
LINE = "            fb_buf_count = -1;\n"
NDK = (TOOLCHAIN / 'bin')
V,P,I,U,B = None,C.c_void_p,C.c_int,C.c_uint,C.c_ubyte
APIS = [
 ("glGenFramebuffers","void","GLsizei,GLuint *",V,[I,C.POINTER(U)]),
 ("glDeleteFramebuffers","void","GLsizei,const GLuint *",V,[I,C.POINTER(U)]),
 ("glBindFramebuffer","void","GLenum,GLuint",V,[U,U]),
 ("glFramebufferTexture2D","void","GLenum,GLenum,GLenum,GLuint,GLint",V,[U,U,U,U,I]),
 ("glFramebufferTextureLayer","void","GLenum,GLenum,GLuint,GLint,GLint",V,[U,U,U,I,I]),
 ("glReadBuffer","void","GLenum",V,[U]),
 ("glDrawBuffers","void","GLsizei,const GLenum *",V,[I,C.POINTER(U)]),
 ("glCheckFramebufferStatus","GLenum","GLenum",U,[U]),
 ("glGetBooleanv","void","GLenum,GLboolean *",V,[U,C.POINTER(B)]),
 ("glDisable","void","GLenum",V,[U]),
 ("glColorMask","void","GLboolean,GLboolean,GLboolean,GLboolean",V,[B,B,B,B]),
 ("glDepthMask","void","GLboolean",V,[B]),
 ("glStencilMask","void","GLuint",V,[U]),
 ("glBlitFramebuffer","void","GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLbitfield,GLenum",V,[I]*8+[U,U]),
 ("glGetError","GLenum","void",U,[]),
 ("glGetIntegerv","void","GLenum,GLint *",V,[U,C.POINTER(I)]),
]


def fixture(candidate):
    source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
    if source.count(ANCHOR + LINE) != 1:
        raise ValueError("production temporary draw-buffer invalidation changed")
    if not candidate:
        # Exact pre-fix production body, used as the meaningful negative control.
        source = source.replace(ANCHOR + LINE, ANCHOR, 1)
        source = source.replace("    glFramebufferTexture2D(fb_target, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, 0, 0);\n", "", 1)
    start = source.index("typedef struct { GLuint tex; GLenum target; GLint level, layer; } fb_attachment;")
    stop = source.index("void d3d_gl_forget_texture(", start)
    functions = source[start:stop] + "\n" + "\n".join(function(source, signature) for signature in (
        "static void attach(", "static GLenum depth_attachment(", "void d3d_gl_bind_targets(", "void d3d_gl_blit("))
    declarations, assignments = [], []
    for index,(name,ret,args,_,_) in enumerate(APIS):
        declarations += [f"static {ret} (*p_{name})({args});",f"#define {name} p_{name}"]
        assignments.append(f"p_{name}=({ret} (*)({args}))procedures[{index}];")
    declarations += ["__declspec(dllexport) void probe_api(void **procedures) {",*assignments,"}"]
    return (HERE / "mrt_draw_buffers_probe.c").read_text(encoding="utf-8").replace("/* ACTUAL_GL_PROCEDURES */", "\n".join(declarations)).replace("/* ACTUAL_FUNCTIONS */",functions)


def build(candidate):
    out = OUT / ("candidate" if candidate else "original")
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.c").write_text(fixture(candidate),encoding="utf-8")
    installation=Path(subprocess.check_output([r"C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe",
        "-latest","-products","*","-property","installationPath"],text=True).strip())
    msvc=sorted((installation/"VC/Tools/MSVC").iterdir())[-1]
    sdk=Path(r"C:/Program Files (x86)/Windows Kits/10");version=sorted((sdk/"Lib").iterdir())[-1].name
    env=os.environ.copy();env["PATH"]=str(msvc/"bin/Hostx64/x64")+os.pathsep+env["PATH"]
    env["INCLUDE"]=";".join(map(str,[msvc/"include",sdk/f"Include/{version}/ucrt",sdk/f"Include/{version}/shared",sdk/f"Include/{version}/um"]))
    env["LIB"]=";".join(map(str,[msvc/"lib/x64",sdk/f"Lib/{version}/ucrt/x64",sdk/f"Lib/{version}/um/x64"]))
    compile=subprocess.run([str(NDK/"clang-cl.exe"),"/nologo","/W4","/WX","/O2","/std:c11","/c","probe.c","/Foprobe.obj"],cwd=out,env=env,capture_output=True,text=True)
    assert compile.returncode==0,compile.stdout+compile.stderr
    link=subprocess.run([str(msvc/"bin/Hostx64/x64/link.exe"),"/nologo","/DLL","/OUT:probe.dll","probe.obj"],cwd=out,env=env,capture_output=True,text=True)
    assert link.returncode==0,link.stdout+link.stderr
    lib=C.CDLL(str(out/"probe.dll"));lib.probe_api.argtypes=[C.POINTER(P)]
    lib.probe_case.argtypes=[U,U,U,I,I];lib.probe_case.restype=U
    lib.probe_scratch.argtypes=[U,U];lib.probe_scratch.restype=U
    return lib


class MrtDrawBuffersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.angle=Angle();a=cls.angle
        for name,_,_,ret,args in APIS:
            a.api(a.gl,name,ret,*args)
        a.api(a.gl,"glReadBuffer",V,U)
        a.api(a.gl,"glDeleteTextures",V,I,C.POINTER(U))
        a.api(a.gl,"glGetString",C.c_char_p,U)
        cls.original,cls.candidate=build(False),build(True)
        pointers=(P*len(APIS))(*(C.cast(getattr(a.gl,row[0]),P).value for row in APIS))
        cls.original.probe_api(pointers);cls.candidate.probe_api(pointers)
        vs=a.compile(b"#version 300 es\nvoid main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}",0x8B31)
        ps=a.compile(b"#version 300 es\nprecision highp float;layout(location=0)out vec4 c0;layout(location=1)out vec4 c1;void main(){c0=vec4(1,0,0,1);c1=vec4(1,1,0,1);}")
        program=a.gl.glCreateProgram()
        for shader in (vs,ps):a.gl.glAttachShader(program,shader)
        a.gl.glLinkProgram(program);ok=I();a.gl.glGetProgramiv(program,0x8B82,C.byref(ok));assert ok.value
        a.gl.glUseProgram(program)
        for shader in (vs,ps):a.gl.glDeleteShader(shader)
        cls.results={"renderer":a.gl.glGetString(0x1F01).decode(),"cases":[]}

    def render(self,lib,slot,mrt):
        gl=self.angle.gl;names=(U*3)();gl.glGenTextures(3,names)
        for i,name in enumerate(names):
            gl.glBindTexture(0xDE1,name);gl.glTexParameteri(0xDE1,0x2801,0x2600);gl.glTexParameteri(0xDE1,0x2800,0x2600)
            color=(0,0,255,255) if i==2 else (0,0,0,255)
            pixels=(B*256)(*(color*64));gl.glTexImage2D(0xDE1,0,0x8058,8,8,0,0x1908,0x1401,pixels)
        self.assertEqual(lib.probe_case(*names,slot,int(mrt)),0)
        gl.glViewport(0,0,8,8)
        for cap in (0xB71,0xBE2,0xB90,0xB44,0xC11):gl.glDisable(cap)
        # No readback/synchronization between the actual blit and following MRT draw.
        gl.glDrawArrays(4,0,3)
        output=[]
        for attachment in range(2 if mrt else 1):
            gl.glReadBuffer(0x8CE0+attachment);pixels=(B*256)();gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels);output.append(bytes(pixels))
        self.assertEqual(gl.glGetError(),0);gl.glDeleteTextures(3,names)
        return output

    def test_actual_blit_then_two_output_draw_red_to_green(self):
        for slot in (0,1):
            with self.subTest(slot=slot):
                original=self.render(self.original,slot,True);fixed=self.render(self.candidate,slot,True)
                expected=[bytes((255,0,0,255))*64,bytes((255,255,0,255))*64]
                self.assertNotEqual(original,expected)
                self.assertEqual(fixed,expected)
                self.assertEqual(original[slot],expected[slot])
                self.assertEqual(original[1-slot],bytes((0,0,0,255))*64)
                self.results["cases"].append({"mrt":True,"slot":slot,"original_non_destination":"black (wrong)","candidate":"both complete expected colors","gl_error":0})

    def test_single_render_target_control_is_unchanged(self):
        original=self.render(self.original,0,False);fixed=self.render(self.candidate,0,False)
        self.assertEqual(original,fixed);self.assertEqual(fixed,[bytes((255,0,0,255))*64])
        self.results["cases"].append({"mrt":False,"slot":0,"original_equals_candidate":True,"gl_error":0})

    def test_scratch_fbo_cannot_clip_large_color_to_old_small_depth(self):
        gl=self.angle.gl
        names=(U*2)();gl.glGenTextures(2,names)
        try:
            gl.glBindTexture(0xDE1,names[1]);gl.glTexImage2D(0xDE1,0,0x88F0,2,2,0,0x84F9,0x84FA,None)
            outputs=[]
            for lib in (self.original,self.candidate):
                gl.glBindTexture(0xDE1,names[0]);pixels=(B*256)(*(0,0,0,255)*64)
                gl.glTexImage2D(0xDE1,0,0x8058,8,8,0,0x1908,0x1401,pixels)
                self.assertEqual(lib.probe_scratch(*names),0)
                gl.glViewport(0,0,8,8)
                for cap in (0xB71,0xBE2,0xB90,0xB44,0xC11):gl.glDisable(cap)
                gl.glDrawArrays(4,0,3);gl.glReadBuffer(0x8CE0)
                gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels);outputs.append(bytes(pixels))
                error=gl.glGetError()
                if lib is self.original: self.assertIn(error,(0,0x506))
                else: self.assertEqual(error,0)
            self.assertNotEqual(outputs[0],bytes((255,0,0,255))*64)
            self.assertEqual(outputs[1],bytes((255,0,0,255))*64)
            self.results["cases"].append({"scratch_8x8_color_after_2x2_depth":"full 8x8 red; old path clipped", "gl_error":0})
        finally:
            gl.glDeleteTextures(2,names)

    def test_cache_invalidation_follows_temporary_main_fbo_mask(self):
        source=(ROOT/"android/host/d3d9_gl.c").read_text(encoding="utf-8")
        blit=function(source,"void d3d_gl_blit(")
        self.assertEqual(blit.count(ANCHOR+LINE),1)
        self.assertLess(blit.index(ANCHOR+LINE),blit.index("    } else {"))

    @classmethod
    def tearDownClass(cls):
        (OUT/"pixel-results.json").write_text(json.dumps(cls.results,indent=2)+"\n")


if __name__=="__main__":
    unittest.main()
