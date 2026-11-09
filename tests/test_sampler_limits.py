"""Execute production sampler creation and caps with optional anisotropy."""
import re
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


class SamplerLimitsTest(unittest.TestCase):
    def test_extension_query_driver_limit_and_caps(self):
        gl = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        device = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf8")
        internal = (ROOT / "android/host/d3d9_internal.h").read_text(encoding="utf8")
        limits = re.search(r"^typedef struct .* d3d_gl_limits_t;$", internal, re.M)[0]
        init = gl[gl.index("    const char *extensions ="):gl.index("    gpu_profile_init(extensions);")]
        samplers = gl[gl.index("typedef struct { uint32_t key[9];"):gl.index("/* What each texture unit")]
        caps = re.search(r"static const char pc_caps_hex\[\] =.*?;", device, re.S)[0]
        caps += "\n" + re.search(r"static int hex_digit.*?\n", device)[0]
        caps += "\n" + function(device, "static void fill_caps(")
        production = (limits + "\nstatic d3d_gl_limits_t d3d_gl_limits;\n"
                      "static void init_limits(void) {\n" + init + "}\n" + samplers + "\n" + caps)
        compile_probe("sampler-limits", r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned GLuint, GLenum;
typedef int GLint;
typedef float GLfloat;
enum { GL_REPEAT=0x2901, GL_MIRRORED_REPEAT=0x8370, GL_CLAMP_TO_EDGE=0x812F,
 GL_CLAMP_TO_BORDER_EXT=0x812D, GL_TEXTURE_WRAP_S=0x2802, GL_TEXTURE_WRAP_T=0x2803,
 GL_TEXTURE_WRAP_R=0x8072, GL_TEXTURE_BORDER_COLOR_EXT=0x1004, GL_TEXTURE_MAG_FILTER=0x2800,
 GL_TEXTURE_MIN_FILTER=0x2801, GL_NEAREST=0x2600, GL_LINEAR=0x2601,
 GL_NEAREST_MIPMAP_NEAREST=0x2700, GL_LINEAR_MIPMAP_NEAREST=0x2701,
 GL_NEAREST_MIPMAP_LINEAR=0x2702, GL_LINEAR_MIPMAP_LINEAR=0x2703,
 GL_TEXTURE_MAX_ANISOTROPY_EXT=0x84FE, GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT=0x84FF,
 GL_TEXTURE_MIN_LOD=0x813A, GL_NUM_EXTENSIONS=0x821D, GL_EXTENSIONS=0x1F03 };
static uint32_t caps[76];
#define MEM8(a) (((uint8_t *)caps)[a])
#define MEM32(a) (caps[(a)/4])
static int supported, queries, parameters;
static GLuint unit_sampler[32];
static unsigned char sampler_live[10000];
static unsigned sampler_alive, sampler_created;
static float driver_max, parameter;
static const unsigned char *glGetStringi(GLenum name, GLuint i) {
    assert(name==GL_EXTENSIONS && i<2);
    return (const unsigned char *)(i ? "GL_EXT_texture_border_clamp" : supported
        ? "GL_EXT_texture_filter_anisotropic" : "GL_EXT_texture_filter_anisotropic2");
}
static const unsigned char *glGetString(GLenum name) { return glGetStringi(name,0); }
static void glGetIntegerv(GLenum name, GLint *value) { assert(name==GL_NUM_EXTENSIONS); *value=2; }
static void glGetFloatv(GLenum name, GLfloat *value) {
    assert(supported && name==GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT); ++queries; *value=driver_max;
}
static void glGenSamplers(GLint n, GLuint *sampler) {
    assert(n==1 && sampler_created+1<sizeof sampler_live);
    *sampler=++sampler_created;sampler_live[*sampler]=1;++sampler_alive;
}
static void glDeleteSamplers(GLint n, const GLuint *sampler) {
    assert(n==1 && *sampler && sampler_live[*sampler]);
    for(unsigned i=0;i<32;++i)assert(unit_sampler[i]!=*sampler);
    sampler_live[*sampler]=0;--sampler_alive;
}
static void glSamplerParameteri(GLuint sampler, GLenum name, GLint value) { assert(sampler && name && value); }
static void glSamplerParameterfv(GLuint sampler, GLenum name, const GLfloat *value) {
    assert(sampler && name==GL_TEXTURE_BORDER_COLOR_EXT && value);
}
static void glSamplerParameterf(GLuint sampler, GLenum name, GLfloat value) {
    assert(sampler);
    if (name==GL_TEXTURE_MAX_ANISOTROPY_EXT) {
        assert(supported && value>=1 && value<=driver_max); ++parameters; parameter=value;
    } else assert(name==GL_TEXTURE_MIN_LOD);
}
#include "production.h"
static void reset_driver(int support, float maximum) {
    memset(unit_sampler,0,sizeof unit_sampler);
    for(int i=0;i<sampler_count;++i)glDeleteSamplers(1,&sampler_cache[i].sampler);
    supported=support; driver_max=maximum; queries=parameters=sampler_count=0;
    sampler_next=0;
    memset(&d3d_gl_limits,0,sizeof d3d_gl_limits); init_limits(); fill_caps(0);
}
static void sample(uint32_t min, uint32_t mag, uint32_t requested, int no_filter) {
    uint32_t ss[14]={0}; ss[1]=ss[2]=ss[3]=1; ss[5]=mag; ss[6]=min; ss[10]=requested;
    assert(sampler_for(ss,no_filter,1,0));
}
int main(void) {
    (void)glGetIntegerv; (void)glGetFloatv;
    fill_caps(0); assert(MEM32(108)==16);
    reset_driver(0,4); sample(3,3,16,0); sample(2,2,4,0);
    assert(!queries && !parameters && MEM32(108)==1);
    reset_driver(1,4); assert(queries==1 && MEM32(108)==4);
    sample(3,3,16,0); assert(parameters==1 && parameter==4);
    sample(3,3,2,0); assert(parameter==2);
    sample(2,3,4,0); assert(parameter==4);
    sample(2,2,16,0); assert(parameter==1);
    sample(3,3,0,0); assert(parameter==1);
    sample(3,3,16,1); assert(parameters==6 && parameter==1);
    sample(3,3,16,1); assert(parameters==6);
    reset_driver(1,32); sample(3,3,32,0); assert(parameter==32 && MEM32(108)==16);
    reset_driver(1,4);
    uint32_t ss[14]={0};ss[1]=ss[2]=ss[3]=ss[5]=ss[6]=1;
    for(unsigned i=0;i<4096;++i) {
        ss[4]=i;GLuint id=sampler_for(ss,0,1,0);
        if(i<32)unit_sampler[i]=id;
        for(unsigned unit=0;unit<32 && unit<=i;++unit)assert(sampler_live[unit_sampler[unit]]);
        assert(sampler_alive<=512 && sampler_count<=512);
        unsigned before=sampler_created;
        assert(sampler_for(ss,0,1,0)==id && sampler_created==before);
    }
    assert(sampler_alive==512);
    reset_driver(0,1);assert(!sampler_alive);
    puts("PASS samplers: optional anisotropy/caps; 4096 states stay within 512 live objects, bound units survive eviction, overflow reuse and complete cleanup");
    return 0;
}
''', {"production.h": production}, extra_flags=("/O2",))


if __name__ == "__main__":
    unittest.main()
