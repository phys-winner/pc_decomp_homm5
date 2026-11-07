/* EASU/RCAS and bicubic reconstruction before the full-resolution UI is drawn. */
#include "d3d9_internal.h"
#include "d3d9_thread.inc"
#include "touch.h"
#include "d3d9_filter.h"
#include <math.h>

static GLuint filter_program[3], filter_fbo, filter_sampler;
static int filter_failed[3];
static d3d_surface *filter_intermediate;

static GLuint filter_shader(GLenum type, const char *const *source, int count)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, count, source, NULL);
    glCompileShader(shader);
    GLint ok = 0; glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[2048]; glGetShaderInfoLog(shader, sizeof log, NULL, log);
        void_log("[filter] shader failed: %s", log);
        glDeleteShader(shader); return 0;
    }
    return shader;
}

static GLuint filter_link(int kind)
{
    if (filter_program[kind] || filter_failed[kind]) return filter_program[kind];
    const char *vertex = "#version 310 es\nvoid main(){vec2 p=vec2(gl_VertexID&1,gl_VertexID>>1);gl_Position=vec4(p*2.0-1.0,0.0,1.0);}";
    const char *common = "#version 310 es\nprecision highp float;precision highp int;\n"
        "uniform sampler2D image;uniform vec2 target;uniform float sharp;layout(location=0)out vec4 color;\n"
        "#define FSR_ALPHA 0\n#define VP_FILTER_OPAQUE 1\n"
        "#define FSR_EASU_BASE(fp) ivec2 vpBase=ivec2(fp);\n"
        "#define T(x,y) texelFetch(image,clamp(vpBase+ivec2(x,y),ivec2(0),textureSize(image,0)-1),0)\n"
        "#define FSR_RCAS_BASE ivec2 vpBase=ivec2(gl_FragCoord.xy);\n"
        "#define L(x,y) texelFetch(image,clamp(vpBase+ivec2(x,y),ivec2(0),textureSize(image,0)-1),0)\n";
    const char *body[] = {
        "void main(){color=vpCubicSample(image,gl_FragCoord.xy/target);}",
        "void main(){color=FsrEasuH(gl_FragCoord.xy*vec2(textureSize(image,0))/target);color.a=1.0;}",
        "void main(){color=FsrRcasH(sharp);}"
    };
    const char *fragment[] = {common, kind == 0 ? d3d_cubic_glsl : kind == 1 ? fsr1_easu_glsl : fsr1_rcas_glsl, body[kind]};
    GLuint vs = filter_shader(GL_VERTEX_SHADER, &vertex, 1), fs = filter_shader(GL_FRAGMENT_SHADER, fragment, 3);
    GLuint program = vs && fs ? glCreateProgram() : 0;
    if (program) {
        glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
        GLint ok = 0; glGetProgramiv(program, GL_LINK_STATUS, &ok);
        if (!ok) {
            char log[2048]; glGetProgramInfoLog(program, sizeof log, NULL, log);
            void_log("[filter] link failed: %s", log); glDeleteProgram(program); program = 0;
        }
    }
    if (vs) glDeleteShader(vs);
    if (fs) glDeleteShader(fs);
    filter_failed[kind] = !program;
    return filter_program[kind] = program;
}

static int filter_draw(d3d_surface *source, d3d_surface *target, GLuint program, float sharpness)
{
    if (!filter_fbo) glGenFramebuffers(1, &filter_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, filter_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, target->gl, 0);
    const GLenum color = GL_COLOR_ATTACHMENT0; glDrawBuffers(1, &color);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) return 0;
    if (!filter_sampler) {
        glGenSamplers(1, &filter_sampler);
        glSamplerParameteri(filter_sampler, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glSamplerParameteri(filter_sampler, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glSamplerParameteri(filter_sampler, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glSamplerParameteri(filter_sampler, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }
    glActiveTexture(GL_TEXTURE31); glBindTexture(GL_TEXTURE_2D, source->gl); glBindSampler(31, filter_sampler);
    glDisable(GL_DEPTH_TEST); glDisable(GL_STENCIL_TEST); glDisable(GL_SCISSOR_TEST);
    glDisable(GL_BLEND); glDisable(GL_CULL_FACE); glDisable(GL_POLYGON_OFFSET_FILL);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glViewport(0, 0, target->width, target->height);
    glUseProgram(program);
    glUniform1i(glGetUniformLocation(program, "image"), 31);
    glUniform2f(glGetUniformLocation(program, "target"), (float)target->width, (float)target->height);
    glUniform1f(glGetUniformLocation(program, "sharp"), fsr1_rcas_con(2.0f * (1.0f - sharpness)));
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    return 1;
}

int d3d_filter_blit(d3d_surface *source, d3d_surface *target, int mode, float sharpness)
{
    if (mode < 1 || mode > 2 || !source || !target || !source->gl || !target->gl || source->gl == target->gl) return 0;
    GLuint program = filter_link(mode - 1);
    if (!program) return 0;
    int rcas = mode == 2 && sharpness > 0 && filter_link(2);
    if (filter_intermediate && (filter_intermediate->dev != target->dev || filter_intermediate->width != target->width ||
        filter_intermediate->height != target->height || filter_intermediate->format != target->format)) {
        d3d_gl_scratch_free(filter_intermediate); filter_intermediate = NULL;
    }
    if (rcas && !filter_intermediate)
        filter_intermediate = d3d_gl_scratch_new(target->dev, target->width, target->height, target->format, target->usage);
    rcas = rcas && filter_intermediate && filter_intermediate->gl;
    int ok = filter_draw(source, rcas ? filter_intermediate : target, program, sharpness);
    if (ok && rcas) ok = filter_draw(filter_intermediate, target, filter_program[2], sharpness);
    d3d_gl_filter_done(target->dev);
    return ok;
}

void d3d_filter_reset(void)
{
    if (filter_intermediate) d3d_gl_scratch_free(filter_intermediate);
    filter_intermediate = NULL;
    for (unsigned i = 0; i < 3; ++i) if (filter_program[i]) glDeleteProgram(filter_program[i]);
    if (filter_fbo) glDeleteFramebuffers(1, &filter_fbo);
    if (filter_sampler) glDeleteSamplers(1, &filter_sampler);
    memset(filter_program, 0, sizeof filter_program); memset(filter_failed, 0, sizeof filter_failed);
    filter_fbo = filter_sampler = 0;
}
