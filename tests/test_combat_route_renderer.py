"""Execute the bounded game-renderer route submission and quad drawing helpers."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "touch.h"
typedef unsigned GLuint, GLenum;
typedef int GLint, GLsizei;
typedef struct { unsigned width, height; } d3d_surface;
typedef struct { d3d_surface *backbuffer, *rt[4]; } d3d_device;
enum {GL_DRAW_FRAMEBUFFER,GL_DEPTH_TEST,GL_STENCIL_TEST,GL_SCISSOR_TEST,
 GL_CULL_FACE,GL_POLYGON_OFFSET_FILL,GL_BLEND,GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA,GL_ONE,
 GL_FUNC_ADD,GL_TRUE,GL_TRIANGLES};
static GLuint combat_route_program=7;
static int combat_route_failed,invalidated,deleted,drawn;
static GLint combat_route_corners=1,combat_route_target=2,combat_route_style=3,combat_route_tint=4,combat_route_metrics=5;
enum {COMBAT_ROUTE_BATCH=32};
static uint64_t draw_calls,now_ns;
static float target[2],current_corners[256],current_metrics[64],style[4],tint[4];
static int corner_count,metric_count;
typedef struct {float corners[256],metrics[64],style[4],tint[4];int quads;} Draw;
static Draw draws[32];
static unsigned disabled,enabled;
static GLuint combat_route_link(void){return combat_route_program;}
static void glBindFramebuffer(GLenum t,GLuint f){assert(t==GL_DRAW_FRAMEBUFFER&&!f);}
static void glDisable(GLenum p){disabled|=1u<<p;}
static void glEnable(GLenum p){enabled|=1u<<p;}
static void glBlendFuncSeparate(GLenum a,GLenum b,GLenum c,GLenum d){assert(a==GL_SRC_ALPHA&&b==GL_ONE_MINUS_SRC_ALPHA&&c==GL_ONE&&d==b);}
static void glBlendEquationSeparate(GLenum a,GLenum b){assert(a==GL_FUNC_ADD&&b==a);}
static void glColorMask(int a,int b,int c,int d){assert(a&&b&&c&&d);}
static void glViewport(int x,int y,GLsizei w,GLsizei h){assert(x==30&&y==40&&w>0&&h>0);}
static void glUseProgram(GLuint p){assert(p==7);}
static void glUniform2f(GLint p,float x,float y){assert(p==2);target[0]=x;target[1]=y;}
static void glUniform2fv(GLint p,int n,const float *v){
 if(p==1){assert(n>0&&n<=128&&n%4==0);corner_count=n;memcpy(current_corners,v,2*(size_t)n*sizeof(float));}
 else{assert(p==5&&n>0&&n<=32);metric_count=n;memcpy(current_metrics,v,2*(size_t)n*sizeof(float));}}
static void glUniform4f(GLint p,float a,float b,float c,float d){float *v=p==3?style:tint;assert(p==3||p==4);v[0]=a;v[1]=b;v[2]=c;v[3]=d;}
static void glDrawArrays(GLenum p,int first,int n){assert(p==GL_TRIANGLES&&!first&&n>0&&n%6==0&&drawn<32);
 assert(n/6==metric_count&&corner_count==4*metric_count);draws[drawn].quads=n/6;
 memcpy(draws[drawn].corners,current_corners,sizeof current_corners);memcpy(draws[drawn].metrics,current_metrics,sizeof current_metrics);
 memcpy(draws[drawn].style,style,sizeof style);memcpy(draws[drawn++].tint,tint,sizeof tint);}
static void d3d_gl_filter_done(d3d_device *d){assert(d);++invalidated;}
static uint64_t void_perf_now_ns(void){return now_ns;}
static void glDeleteProgram(GLuint p){assert(p==7);++deleted;}
#include "route_helpers.h"
static int near(float a,float b){return fabsf(a-b)<.001f;}
static void frame(d3d_device *d,const combat_route_snapshot *route){drawn=0;disabled=enabled=0;combat_route_draw(d,route,30,40,(int)d->backbuffer->width,(int)d->backbuffer->height);}
static unsigned packet(float *p,int mode,unsigned path,const float *xy,unsigned count){
 memset(p,0,COMBAT_ROUTE_FLOATS*sizeof(float));p[0]=(float)mode;p[1]=(float)path;p[2]=(float)((count-path)/4);
 /* World XY maps to the supplied normalized XY; nonzero Z is retained independently. */
 p[4]=2;p[7]=-1;p[9]=-2;p[11]=1;p[19]=1;
 for(unsigned i=0;i<count;++i){p[20+3*i]=xy[2*i];p[21+3*i]=xy[2*i+1];p[22+3*i]=.25f*(float)i;}
 return 20+3*count;
}
int main(void){
 float p[COMBAT_ROUTE_FLOATS];const float xy[]={.1f,.2f,.7f,.2f,.65f,.15f,.75f,.15f,.75f,.25f,.65f,.25f};
 assert(packet(p,2,2,xy,6)==38);
 d3d_gl_combat_route(p,38);assert(combat_route_game.count==38);
 combat_route_snapshot queued=combat_route_game;
 p[23]=.8f;assert(near(queued.points[23],.7f));
 d3d_gl_combat_route(NULL,0);assert(!combat_route_game.count&&queued.count==38);
 for(unsigned count=0;count<=COMBAT_ROUTE_FLOATS+2;++count){d3d_gl_combat_route(p,count);assert((combat_route_game.count!=0)==(count==38));}
 float invalid[]={NAN,INFINITY,-INFINITY};
 for(unsigned i=0;i<3;++i){p[23]=invalid[i];d3d_gl_combat_route(p,38);assert(!combat_route_game.count);}
 p[23]=.7f;
 for(unsigned i=4;i<20;++i){float saved=p[i];p[i]=NAN;d3d_gl_combat_route(p,38);assert(!combat_route_game.count);p[i]=saved;}
 p[0]=3;d3d_gl_combat_route(p,38);assert(!combat_route_game.count);
 p[0]=2;float bad_counts[]={NAN,INFINITY,0,1.5f,257};
 for(unsigned i=0;i<5;++i){p[1]=bad_counts[i];d3d_gl_combat_route(p,38);assert(!combat_route_game.count);}p[1]=2;
 p[0]=2;d3d_surface bb={1920,1080};d3d_device d={&bb,{&bb,0,0,0}};
 frame(&d,&queued);assert(drawn==3&&draw_calls==3&&invalidated==1);
 assert(near(target[0],1920)&&near(target[1],1080));
 assert(near(draws[0].corners[0],1248)&&near(draws[0].corners[1],162)&&draws[0].style[0]<0);
 assert(near(draws[1].corners[0],192)&&near(draws[1].corners[2],1344));
 assert(near(draws[2].corners[0],1344)&&near(draws[2].corners[2],192));
 float outward=(draws[1].corners[1]+draws[1].corners[7])/2;
 float returning=(draws[2].corners[1]+draws[2].corners[7])/2;
 assert(near(outward,225)&&near(returning,207));
 assert(near(draws[1].tint[0],244/255.0f)&&near(draws[2].tint[0],153/255.0f));
 assert((disabled&(1u<<GL_DEPTH_TEST))&&(disabled&(1u<<GL_STENCIL_TEST))&&(disabled&(1u<<GL_SCISSOR_TEST)));
 assert(enabled==(1u<<GL_BLEND));
 now_ns=375000000;frame(&d,&queued);assert(near(draws[1].style[1],22.5f)&&near(draws[2].style[1],22.5f));
 queued.points[0]=1;frame(&d,&queued);assert(drawn==2&&near((draws[1].corners[1]+draws[1].corners[7])/2,216));
 queued.points[23]=queued.points[20];queued.points[24]=queued.points[21];frame(&d,&queued);assert(drawn==1);
 queued.count=0;int old=invalidated;frame(&d,&queued);assert(!drawn&&invalidated==old);
 queued.count=74;queued.points[2]=4;queued.points[23]=.7f;queued.points[0]=2;frame(&d,&queued);assert(drawn==6);
 d.rt[0]=NULL;frame(&d,&queued);assert(drawn==6);
 float bend[COMBAT_ROUTE_FLOATS];const float bends[]={.1f,.2f,.3f,.2f,.3f,.4f,.5f,.4f};
 assert(packet(bend,1,4,bends,4)==32);
 d3d_gl_combat_route(bend,32);frame(&d,&combat_route_game);assert(drawn==1&&draws[0].quads==3);
 assert(near(draws[0].metrics[1],0)&&near(draws[0].metrics[3],384)&&near(draws[0].metrics[5],600));
 for(int j=0;j<2;++j){assert(near(draws[0].corners[2+j],draws[0].corners[8+j]));assert(near(draws[0].corners[4+j],draws[0].corners[14+j]));}
 bend[0]=2;d3d_gl_combat_route(bend,32);frame(&d,&combat_route_game);assert(drawn==2);
 for(int line=0;line<2;++line)for(int j=1;j<3;++j)assert(near(draws[line].metrics[2*j+1],draws[line].metrics[2*j-1]+draws[line].metrics[2*j-2]));
 p[1]=COMBAT_ROUTE_MAX_POINTS;p[2]=4;
 for(unsigned i=0;i<COMBAT_ROUTE_MAX_POINTS;++i){p[20+3*i]=.1f+.002f*(float)i;p[21+3*i]=.2f+.01f*(float)(i&1);p[22+3*i]=0;}
 d3d_gl_combat_route(p,20+3*(256+16));assert(combat_route_game.count==20+3*(256+16));
 frame(&d,&combat_route_game);assert(drawn==20&&draws[4].quads==32&&draws[11].quads==31&&draws[12].quads==32&&draws[19].quads==31);
 assert(draws[5].metrics[1]>draws[4].metrics[63]);
 /* Melee fan: three solid arrows, then the full bounded fan, independent of movement dashes. */
 packet(p,0,0,xy,2);p[2]=0;p[3]=3;
 for(unsigned i=0;i<=COMBAT_ROUTE_MAX_TARGETS;++i){p[20+3*i]=.1f+.02f*i;p[21+3*i]=.2f+.01f*i;p[22+3*i]=0;}
 d3d_gl_combat_route(p,32);frame(&d,&combat_route_game);
 assert(drawn==1&&draws[0].quads==3&&draws[0].style[0]==1);
 for(unsigned i=0;i<3;++i){assert(draws[0].metrics[2*i]>0&&draws[0].metrics[2*i+1]>0);
  /* The outlined shader uses physical width, including short-arrow clamping. */
  float *c=draws[0].corners+8*i;
  assert(near(hypotf(c[6]-c[0],c[7]-c[1]),2*draws[0].metrics[2*i+1]));}
 p[3]=1;d3d_gl_combat_route(p,26);frame(&d,&combat_route_game);assert(drawn==1&&draws[0].quads==1&&draws[0].style[0]==1);
 p[3]=COMBAT_ROUTE_MAX_TARGETS;d3d_gl_combat_route(p,20+3*(COMBAT_ROUTE_MAX_TARGETS+1));frame(&d,&combat_route_game);
 assert(drawn==1&&draws[0].quads==COMBAT_ROUTE_MAX_TARGETS);
 p[3]=COMBAT_ROUTE_MAX_TARGETS+1;d3d_gl_combat_route(p,20+3*(COMBAT_ROUTE_MAX_TARGETS+1));assert(!combat_route_game.count);
 /* Actual worker projection: nontrivial XYZ and perspective, independently calculated in double precision. */
 packet(p,1,2,xy,2);
 float m[16]={.025f,.01f,.03f,-.2f,-.01f,.04f,.02f,.3f,0,0,1,0,.002f,.003f,.004f,1};
 memcpy(p+4,m,sizeof m);p[20]=7;p[21]=10;p[22]=1.4f;p[23]=15;p[24]=12;p[25]=2;
 d3d_gl_combat_route(p,26);combat_route_snapshot projected_packet=combat_route_game;
 float projected[COMBAT_ROUTE_WORLD_POINTS][2];assert(combat_route_project(&projected_packet,projected));
 for(unsigned i=0;i<2;++i){double clip[4]={0},world[4]={p[20+3*i],p[21+3*i],p[22+3*i],1};
  for(unsigned row=0;row<4;++row)for(unsigned col=0;col<4;++col)clip[row]+=(double)m[4*row+col]*world[col];
  assert(near(projected[i][0],(float)((clip[0]/clip[3]+1)/2))&&near(projected[i][1],(float)((1-clip[1]/clip[3])/2)));}
 p[7]+=.25f;p[20]=999;assert(near(projected_packet.points[7],m[3])&&near(projected_packet.points[20],7));
 for(int bad=0;bad<5;++bad){combat_route_snapshot hidden=projected_packet;
  if(bad==0){hidden.points[16]=hidden.points[17]=hidden.points[18]=0;hidden.points[19]=-1;}
  if(bad==1){hidden.points[16]=hidden.points[17]=hidden.points[18]=hidden.points[19]=0;}
  if(bad==2)hidden.points[4]=INFINITY;
  if(bad==3)hidden.points[20]=NAN;
  if(bad==4)hidden.points[7]=100;
  old=invalidated;frame(&d,&hidden);assert(!drawn&&invalidated==old);}
 float cusp[3][2]={{0,0},{100,0},{.01f,.01f}},miter[3][2];combat_route_miters(cusp,3,miter);
 for(int i=0;i<3;++i)assert(isfinite(miter[i][0]+miter[i][1])&&hypotf(miter[i][0],miter[i][1])<=2.501f);
 bb.width=0;frame(&d,&queued);assert(!drawn);bb.width=1920;
 combat_route_reset();combat_route_reset();assert(deleted==1&&!combat_route_program&&!combat_route_failed);
 frame(&d,&queued);assert(!drawn);
 puts("PASS native route renderer: worker XYZ/perspective projection, immutable camera/path snapshot, clipped invalid points, native bends/cells, continuous phase/return joins, 256-point draw bound, GL invalidation/reset");
 return 0;
}
'''


class CombatRouteRendererTest(unittest.TestCase):
    def test_bounded_geometry_and_render_state(self):
        source = (ROOT / "android/host/d3d9_combat_route.inc").read_text(encoding="utf-8")
        definitions = source[source.index("typedef struct"):source.index("static GLuint combat_route_program;")]
        helpers = definitions + "\n".join(function(source, name) for name in (
            "void d3d_gl_combat_route(", "static void combat_route_miters(", "static void combat_route_batch_draw(",
            "static int combat_route_project(", "static void combat_route_draw(", "static void combat_route_reset("))
        compile_probe("combat_route_renderer", HARNESS, {"route_helpers.h": helpers,
                      "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf-8")})

    def test_present_snapshot_and_teardown_wiring(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
        present = function(source, "void d3d_gl_present(")
        self.assertIn(".route = combat_route_game", present)
        self.assertIn("d3d_rt_call(run_present, &a, sizeof a)", present)
        self.assertIn("gl_present(RDEV, &a->route)", function(source, "static void run_present("))
        render = function(source, "static void gl_present(")
        self.assertLess(render.index("glBlitFramebuffer("), render.index("combat_route_draw(dev, route, dx, dy, dw, dh)"))
        self.assertLess(render.index("combat_route_draw(dev, route, dx, dy, dw, dh)"), render.index("eglSwapBuffers("))
        self.assertIn("combat_route_reset()", function(source, "static void gl_device_destroy("))
        destroy = function(source, "void d3d_gl_device_destroy(")
        self.assertLess(destroy.index("d3d_gl_combat_route(NULL, 0)"), destroy.index("d3d_rt_sync("))


if __name__ == "__main__":
    unittest.main()
