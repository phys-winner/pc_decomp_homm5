#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
typedef unsigned GLuint,GLenum;typedef int GLint,GLsizei;
enum {GL_TEXTURE_2D=0xDE1,GL_TEXTURE_3D=0x806F,GL_FRAMEBUFFER=0x8D40,GL_COLOR_ATTACHMENT0=0x8CE0,
 GL_DEPTH_ATTACHMENT=0x8D00,GL_DEPTH_STENCIL_ATTACHMENT=0x821A,GL_FRAMEBUFFER_COMPLETE=0x8CD5,GL_NONE=0};
#define FB_UNKNOWN 0xFFFFFFFFu
typedef struct {int internal,stencil;} d3d_format;
typedef struct d3d_texture {GLuint gl;GLenum target;uint32_t levels,lod;} d3d_texture;
typedef struct {const d3d_format *fmt;uint32_t width,height,format;GLuint gl;d3d_texture *container;uint32_t level,face;} d3d_surface;
typedef struct {void *textures[20];uint32_t ss[20][14];} d3d_state;
typedef struct {d3d_state st;d3d_surface *ds,*rt[4],*backbuffer;int fbo_dirty;uint32_t frame;} d3d_device;
static GLuint fbo,unit_tex[32];static GLenum unit_target[32];static uint64_t draw_calls;
static d3d_surface *trace_rt;
static unsigned api_calls,queries,logs,alias_logs,sample_logs,end_logs;
static GLuint attached_depth,attached_stencil;
static char last_log[2048];
static int tracing(d3d_device *d) {(void)d;return 0;}
static void trace_dump(d3d_device *d,d3d_surface *s,const char *message) {(void)d;(void)s;(void)message;}
static void void_log(const char *format,...) {
    va_list args;va_start(args,format);vsnprintf(last_log,sizeof last_log,format,args);va_end(args);++logs;
    if(strstr(last_log,"[depth-trace] alias "))++alias_logs;
    if(strstr(last_log,"[depth-trace] sample "))++sample_logs;
    if(strstr(last_log,"[depth-trace] end "))++end_logs;
}
static GLuint d3d_surface_gl_texture(d3d_surface *s,GLenum *target,GLint *level,GLint *layer) {
    *target=GL_TEXTURE_2D;*level=(GLint)s->level;*layer=(GLint)s->face;return s->container?s->container->gl:s->gl;
}
static void glGenFramebuffers(GLsizei n,GLuint *name) {assert(n==1);*name=1;++api_calls;}
static void glBindFramebuffer(GLenum target,GLuint name) {assert(target==GL_FRAMEBUFFER&&name==1);++api_calls;}
static void glFramebufferTexture2D(GLenum target,GLenum point,GLenum texture_target,GLuint name,GLint level) {
    assert(target==GL_FRAMEBUFFER&&texture_target==GL_TEXTURE_2D&&level==0);++api_calls;
    if(point==GL_DEPTH_ATTACHMENT)attached_depth=name;
    if(point==GL_DEPTH_STENCIL_ATTACHMENT)attached_depth=attached_stencil=name;
}
static void glFramebufferTextureLayer(GLenum target,GLenum point,GLuint name,GLint level,GLint layer) {
    (void)target;(void)point;(void)name;(void)level;(void)layer;assert(!"unexpected layered attachment");
}
static void glDrawBuffers(GLsizei n,const GLenum *points) {assert(n>=1&&points);++api_calls;}
static GLenum glCheckFramebufferStatus(GLenum target) {assert(target==GL_FRAMEBUFFER);++queries;return GL_FRAMEBUFFER_COMPLETE;}
/* ACTUAL_ATTACHMENTS */
/* ACTUAL_DEPTH_POINT */
/* ACTUAL_FORGET */
/* ACTUAL_TARGETS */
/* ACTUAL_HELPERS */
static void retain(d3d_device *d,d3d_surface *depth) {
    d->ds=depth;d->fbo_dirty=1;d3d_gl_bind_targets(d);assert(attached_depth==depth->gl);
    d->ds=NULL;d->fbo_dirty=1;d3d_gl_bind_targets(d);assert(attached_depth==depth->gl&&!d->fbo_dirty);
}
int main(void) {
    const d3d_format plain={1,0},stencil={1,1};
    d3d_surface color={&plain,64,64,21,11,NULL,0,0},depth={&plain,128,128,80,7,NULL,0,0};
    d3d_texture texture={7,GL_TEXTURE_2D,1,0},different={8,GL_TEXTURE_2D,1,0},alias={7,GL_TEXTURE_2D,1,0};
    d3d_device d={0};d.rt[0]=&color;
    retain(&d,&depth);d.st.textures[0]=&texture;
    assert(!retained_depth_sampler_mask(&d,0,0));
    assert(retained_depth_sampler_mask(&d,1,0)==1);
    d.st.textures[15]=&alias;d.st.textures[19]=&texture;
    assert(retained_depth_sampler_mask(&d,1u<<15,8)==((1u<<15)|(1u<<19)));
    d.st.textures[0]=&different;assert(!retained_depth_sampler_mask(&d,1,0));
    d.st.textures[0]=&texture;d.ds=&depth;assert(!retained_depth_sampler_mask(&d,1,0));d.ds=NULL;
    fb_depth_point=FB_UNKNOWN;assert(!retained_depth_sampler_mask(&d,1,0));
    fb_depth_point=GL_DEPTH_ATTACHMENT;fb_depth.tex=FB_UNKNOWN;assert(!retained_depth_sampler_mask(&d,1,0));
    fb_depth.tex=0;assert(!retained_depth_sampler_mask(&d,1,0));
    fb_depth.tex=7;d3d_gl_forget_texture(7);attached_depth=attached_stencil=0;
    assert(!retained_depth_sampler_mask(&d,1,0));
    /* A view resolves to its owning GL storage, including depth/stencil. */
    depth.container=&alias;depth.fmt=&stencil;d.fbo_dirty=1;retain(&d,&depth);
    assert(retained_depth_sampler_mask(&d,1,0)==1&&attached_stencil==7);
    for(unsigned i=0;i<20;++i) {d.st.textures[i]=&texture;unit_tex[i]=7;unit_target[i]=GL_TEXTURE_2D;}
    unsigned before=api_calls,q=queries;
    depth_trace_draw(&d,0xFFFF,15,0,0);assert(!logs&&!depth_trace_draws);
    d3d_request_depth_trace();assert(!depth_trace_remaining&&!logs);
    depth_trace_present(&d);assert(depth_trace_remaining==120&&logs==1);
    for(unsigned i=0;i<1000;++i){++draw_calls;depth_trace_draw(&d,0xFFFF,15,123,456);}
    assert(strstr(last_log,"hit=FFFFF")&&strstr(last_log,"shaders=0000007B/000001C8"));
    d.st.textures[0]=&different;
    for(unsigned i=0;i<8;++i)depth_trace_draw(&d,1,0,123,456);
    assert(depth_trace_aliases==1000&&alias_logs==12&&sample_logs==4&&logs==17);
    assert(depth_trace_draws==1008&&depth_trace_null==1008&&depth_trace_retained==1008);
    assert(api_calls==before&&queries==q&&attached_depth==7&&attached_stencil==7);
    for(unsigned i=0;i<120;++i){++d.frame;depth_trace_present(&d);}
    assert(!depth_trace_remaining&&end_logs==1&&logs==18&&strstr(last_log,"aliasDraws=1000"));
    depth_trace_draw(&d,0xFFFF,15,0,0);assert(logs==18);
    d3d_request_depth_trace();d3d_request_depth_trace();depth_trace_present(&d);
    assert(depth_trace_remaining==120&&logs==19); /* requests coalesce */
    for(unsigned i=0;i<120;++i){depth_trace_draw(&d,1,0,0,0);++d.frame;depth_trace_present(&d);}
    assert(depth_trace_aliases==0&&strstr(last_log,"aliasDraws=0")&&depth_trace_retained==120);
    assert(api_calls==before&&queries==q&&attached_depth==7&&attached_stencil==7);
    d3d_request_depth_trace();depth_trace_present(&d);
    d.ds=&depth;depth_trace_draw(&d,0xFFFF,15,0,0);
    assert(depth_trace_draws==1&&!depth_trace_null&&!depth_trace_retained&&!depth_trace_aliases);
    d.ds=NULL;fb_depth.tex=0;depth_trace_draw(&d,0xFFFF,15,0,0);
    assert(depth_trace_draws==2&&depth_trace_null==1&&!depth_trace_retained);
    /* A later request resets the bounded window without a render operation. */
    d3d_request_depth_trace();depth_trace_present(&d);
    assert(depth_trace_remaining==120&&!depth_trace_draws&&!depth_trace_aliases);
    assert(api_calls==before&&queries==q);
    puts("PASS actual depth diagnostic: active PS/VS and storage identity, logical DS/unknown/deleted exclusions; 120 frames/16 records, zero-hit coverage, coalesced requests; no GL calls or attachment mutations");
    return 0;
}
