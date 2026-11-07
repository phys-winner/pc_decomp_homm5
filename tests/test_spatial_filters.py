"""Execute the production spatial shaders on GLES, including transparent UI edges."""
import ctypes as C
import json
import unittest
from test_d3d_lifecycle import function
from test_legacy_shaders import Angle
from test_static_tls import ROOT, compile_probe


class SpatialFiltersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / "build/tests/spatial_filters"
        cls.out.mkdir(parents=True, exist_ok=True)
        source = (ROOT / "android/host/d3d9_filter.c").read_text()
        harness = r'''
#include <assert.h>
#include "d3d9_filter.h"
typedef unsigned GLuint,GLenum;typedef int GLint;
#define GL_VERTEX_SHADER 1
#define GL_FRAGMENT_SHADER 2
#define GL_LINK_STATUS 3
#define void_log(...) ((void)0)
static GLuint filter_program[3];static int filter_failed[3],capture_kind;
static GLuint filter_shader(GLenum type,const char *const *parts,int count){
 char name[1024];snprintf(name,sizeof name,"%s/%d.%s",OUT,capture_kind,type==1?"vert":"frag");
 FILE *f=fopen(name,"wb");assert(f);for(int i=0;i<count;++i)fputs(parts[i],f);fclose(f);return type;
}
static GLuint glCreateProgram(void){return 10;}
static void glAttachShader(GLuint p,GLuint s){assert(p==10&&s);}
static void glLinkProgram(GLuint p){assert(p==10);}
static void glGetProgramiv(GLuint p,GLenum q,GLint *v){assert(p==10&&q==3);*v=1;}
static void glGetProgramInfoLog(GLuint p,int n,void *len,char *text){(void)p;(void)n;(void)len;*text=0;}
static void glDeleteProgram(GLuint p){assert(p==10);}
static void glDeleteShader(GLuint s){assert(s);}
/* ACTUAL_LINK */
int main(void){
 for(capture_kind=0;capture_kind<3;++capture_kind)assert(filter_link(capture_kind)&&!filter_failed[capture_kind]);
 const char *pixel="#version 310 es\nprecision highp float;uniform sampler2D image;layout(location=0)out vec4 color;void main(){color=texture(image,gl_FragCoord.xy/vec2(8.0));}";
 char *ui=d3d_ui_filter_source(pixel);assert(ui&&strstr(ui,"vpTexture(image,"));
 FILE *f=fopen(OUT "/ui.frag","wb");assert(f);fputs(ui,f);fclose(f);free(ui);
 const char *mojo="#version 310 es\n#define texture2D texture\n#define texture2DLod textureLod\n"
 "precision highp float;uniform sampler2D image;layout(location=0)out vec4 color;"
 "void main(){color=texture2D(image,gl_FragCoord.xy/vec2(8.0));}";
 ui=d3d_ui_filter_source(mojo);assert(ui&&strstr(ui,"color=vpTexture(image,"));
 assert(strstr(ui,"#define texture2DLod textureLod"));
 f=fopen(OUT "/ui-mojo.frag","wb");assert(f);fputs(ui,f);fclose(f);free(ui);return 0;
}
'''.replace('/* ACTUAL_LINK */', function(source, 'static GLuint filter_link('))
        harness = '#define OUT ' + json.dumps(cls.out.as_posix()) + '\n' + harness
        compile_probe("spatial_filter_sources", harness, {name: (ROOT / "android/host" / name).read_text()
                                                          for name in ("d3d9_filter.h", "fsr1.h")})

    def render(self, angle, fragment, pixels, ui=-1):
        gl = angle.gl
        vs = angle.compile((self.out / "0.vert").read_bytes(), 0x8B31)
        ps = angle.compile(fragment)
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs); gl.glAttachShader(program, ps); gl.glLinkProgram(program)
        status = C.c_int(); gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        gl.glUseProgram(program)
        angle.api(gl, "glUniform2f", None, C.c_int, C.c_float, C.c_float)
        angle.api(gl, "glUniform1f", None, C.c_int, C.c_float)
        angle.api(gl, "glDeleteTextures", None, C.c_int, C.POINTER(C.c_uint))
        gl.glUniform1i(gl.glGetUniformLocation(program, b"image"), 0)
        gl.glUniform1i(gl.glGetUniformLocation(program, b"vpUiFilter"), ui)
        gl.glUniform2f(gl.glGetUniformLocation(program, b"target"), 8, 8)
        gl.glUniform1f(gl.glGetUniformLocation(program, b"sharp"), 0.5)
        tex = C.c_uint(); gl.glGenTextures(1, C.byref(tex)); gl.glActiveTexture(0x84C0); gl.glBindTexture(0x0DE1, tex)
        for parameter in (0x2800, 0x2801): gl.glTexParameteri(0x0DE1, parameter, 0x2601)
        for parameter in (0x2802, 0x2803): gl.glTexParameteri(0x0DE1, parameter, 0x812F)
        data = (C.c_ubyte * 16)(*pixels)
        gl.glTexImage2D(0x0DE1, 0, 0x8058, 2, 2, 0, 0x1908, 0x1401, data)
        gl.glViewport(0, 0, 8, 8); gl.glDrawArrays(5, 0, 4)
        output = (C.c_ubyte * 256)(); gl.glReadPixels(0, 0, 8, 8, 0x1908, 0x1401, output)
        self.assertEqual(gl.glGetError(), 0)
        gl.glDeleteProgram(program); gl.glDeleteShader(vs); gl.glDeleteShader(ps); gl.glDeleteTextures(1, C.byref(tex))
        return [tuple(output[i:i + 4]) for i in range(0, 256, 4)]

    def test_scene_kernels_keep_flat_color_even_when_backbuffer_alpha_is_zero(self):
        angle = Angle()
        for kind in range(3):
            with self.subTest(kind=kind):
                pixels = self.render(angle, (self.out / f"{kind}.frag").read_bytes(), [64, 128, 192, 0] * 4)
                self.assertTrue(all(all(abs(a - b) <= 1 for a, b in zip(p, (64, 128, 192, 255))) for p in pixels))

    def test_ui_filters_preserve_alpha_without_blue_halos(self):
        angle = Angle()
        shader = (self.out / "ui.frag").read_bytes()
        for mode in (2, 3):
            with self.subTest(mode=mode):
                flat = self.render(angle, shader, [64, 128, 192, 128] * 4, mode)
                self.assertTrue(all(all(abs(a - b) <= 1 for a, b in zip(p, (64, 128, 192, 128))) for p in flat))
                edges = self.render(angle, shader, [255, 0, 0, 255, 0, 0, 255, 0] * 2, mode)
                self.assertTrue(any(0 < p[3] < 255 for p in edges))
                self.assertTrue(all(p[1] <= 1 and p[2] <= 1 for p in edges if p[3] > 5))


    def test_game_texture2d_alias_uses_each_ui_filter(self):
        angle = Angle()
        pixels = [255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 255, 255]
        fragment = (self.out / "ui-mojo.frag").read_bytes()
        images = [self.render(angle, fragment, pixels, mode) for mode in range(4)]
        for left in range(4):
            for right in range(left + 1, 4):
                self.assertNotEqual(images[left], images[right], (left, right))


if __name__ == "__main__":
    unittest.main()
