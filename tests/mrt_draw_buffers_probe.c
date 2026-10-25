#include <stdint.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLuint,GLenum,GLbitfield;typedef int GLint,GLsizei;typedef unsigned char GLboolean;
enum {GL_NONE=0,GL_TRUE=1,GL_TEXTURE_2D=0xDE1,GL_TEXTURE_3D=0x806F,GL_FRAMEBUFFER=0x8D40,
 GL_READ_FRAMEBUFFER=0x8CA8,GL_DRAW_FRAMEBUFFER=0x8CA9,GL_COLOR_ATTACHMENT0=0x8CE0,
 GL_DEPTH_ATTACHMENT=0x8D00,GL_DEPTH_STENCIL_ATTACHMENT=0x821A,GL_FRAMEBUFFER_COMPLETE=0x8CD5,
 GL_SCISSOR_TEST=0xC11,GL_COLOR_BUFFER_BIT=0x4000,GL_DEPTH_BUFFER_BIT=0x100,GL_STENCIL_BUFFER_BIT=0x400,
 GL_COLOR_WRITEMASK=0xC23,GL_READ_BUFFER=0xC02,GL_DRAW_BUFFER0=0x8825,GL_LINEAR=0x2601,GL_NEAREST=0x2600};
#define FB_UNKNOWN 0xFFFFFFFFu
typedef struct {int internal,depth,stencil;} d3d_format;
typedef struct {const d3d_format *fmt;uint32_t width,height,format;GLuint gl;} d3d_surface;
typedef struct {d3d_surface *rt[4],*ds,*backbuffer;int fbo_dirty;uint32_t frame;} d3d_device;
static GLuint fbo,read_fbo,draw_fbo;
static d3d_device *g_d3d_device;
static int raster_state_valid;
static d3d_surface *trace_rt;
static int tracing(d3d_device *d) {(void)d;return 0;}
static void trace_dump(d3d_device *d,d3d_surface *s,const char *r) {(void)d;(void)s;(void)r;}
static void void_log(const char *f,...) {(void)f;}
static GLuint d3d_surface_gl_texture(d3d_surface *s,GLenum *target,GLint *level,GLint *layer) {
 *target=GL_TEXTURE_2D;*level=*layer=0;return s->gl;
}
/* ACTUAL_GL_PROCEDURES */
static void ui_prepare_depth(d3d_device *d) {(void)d;}
static d3d_surface *ui_surface(d3d_device *d,d3d_surface *s) {(void)d;return s;}
/* ACTUAL_FUNCTIONS */
__declspec(dllexport) unsigned probe_case(unsigned color0,unsigned color1,unsigned input,int destination,int mrt) {
 const d3d_format rgba={0x8058,0,0};
 d3d_surface colors[2]={{&rgba,8,8,21,color0},{&rgba,8,8,21,color1}},source={&rgba,8,8,21,input};
 d3d_device dev={0};dev.rt[0]=&colors[0];if(mrt)dev.rt[1]=&colors[1];dev.backbuffer=&colors[0];
 dev.fbo_dirty=1;g_d3d_device=&dev;
 if(fbo)glDeleteFramebuffers(1,&fbo);if(read_fbo)glDeleteFramebuffers(1,&read_fbo);if(draw_fbo)glDeleteFramebuffers(1,&draw_fbo);
 fbo=read_fbo=draw_fbo=0;
 for(unsigned i=0;i<4;++i)fb_color[i]=(fb_attachment){FB_UNKNOWN,0,0,0};
 fb_depth=(fb_attachment){FB_UNKNOWN,0,0,0};fb_depth_point=FB_UNKNOWN;fb_buf_count=-1;
 memset(fb_bufs,0,sizeof fb_bufs);fb_depth_w=fb_depth_h=0;
 d3d_gl_bind_targets(&dev);
 uint32_t rect[4]={0,0,8,8};
 d3d_gl_blit(&source,rect,&colors[destination],rect,0);
 d3d_gl_bind_targets(&dev);
 g_d3d_device=NULL;
 return glGetError();
}

__declspec(dllexport) unsigned probe_scratch(unsigned color,unsigned depth) {
 const d3d_format rgba={0x8058,0,0},z={0x88F0,1,1};
 d3d_surface large={&rgba,8,8,21,color},small={&z,2,2,75,depth};
 if(!draw_fbo)glGenFramebuffers(1,&draw_fbo);
 glBindFramebuffer(GL_FRAMEBUFFER,draw_fbo);
 attach(GL_FRAMEBUFFER,GL_DEPTH_STENCIL_ATTACHMENT,&small);
 attach(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,&large);
 return glGetError();
}
