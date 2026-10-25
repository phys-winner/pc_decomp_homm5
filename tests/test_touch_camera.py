"""Exercise the native camera bridge against the engine call/coordinate ABI."""
from pathlib import Path
import unittest
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define GPTR(a) (memory + (uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEM8(a) (*GPTR(a))
static uint32_t g_eax, g_ecx, g_esp=0x70000, g_edx, g_esi, g_edi;
#define ARG(i) MEM32(g_esp+4+4*(i))
typedef void (*void_fn)(void);
static int touch_mode=1, edge_calls, set_calls, unfollow_calls, convert_calls, ray_calls;
static int bad_ray, failed_allocation, town_sets, perspective;
static int town_initializations, town_busy, town_modal, town_init_failure, missing_init;
static uint32_t current_top=0x10000;
static float town_initial_pose[10]={500,1.1f,.5f,.1f,35,0,0,33,44,5};
static float installed[10];
static void_fn registered;
#define MEMF(a) (*(float *)GPTR(a))
#define VLOG(...) ((void)0)
/* port_settings.c: the options page's camera sensitivity. */
static float option_sensitivity=1.0f;
static float void_port_camera_sensitivity(void) {return option_sensitivity;}
/* 0x0058A5E0 (ECX 1000: the current mode) -> {rod,rod,pitch,pitch,yaw,yaw} limits. */
static int limits_present, limit_calls;
static uint32_t limits_va=0x43000, set_immediate=1;
static void old_edge(void) {++edge_calls;g_eax=0x12345678;g_esp+=12;}
static void dummy(void) {}
static float projected_rod, projected_centre;
static void projection_stub(void) {projected_rod=MEMF(g_ecx+0x70);projected_centre=MEMF(g_ecx+0x60);}
static void_fn void_dispatch_find(uint32_t va) {
    if(va==0x7CD0C0) return projection_stub;
    if(va==0x835E50) return old_edge;
    if(va==0x58A5E0) return limits_present?dummy:NULL;
    if(va==0x618170) return missing_init?NULL:dummy;
    if(va==0x8385A0||va==0xD119FC||va==0x614200||va==0x6146C0||va==0x410040) return dummy;
    return va>=0x410000&&va<=0x410030?dummy:NULL;
}
static void void_dispatch_add(uint32_t va,void_fn fn) {if(va==0x7CD0C0)return;assert(va==0x835E50);registered=fn;}
static int void_touch_active_mode(void) {return touch_mode;}
static void void_input_screen_size(int *w,int *h) {*w=1280;*h=800;}
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100 && (uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n) {return void_vm_readable(a,n);}
static uint32_t void_galloc(uint32_t n) {assert(n==0x800);return failed_allocation?0:0x50000;}
static void void_lift_trap(uint32_t a,const char *why) {(void)a;fprintf(stderr,"%s",why);abort();}
static float get_float(uint32_t a) {float f;memcpy(&f,GPTR(a),4);return f;}
static void put_float(uint32_t a,float f) {memcpy(GPTR(a),&f,4);}
/* Independent perspective camera: project a fixed world point back to raw pixels. */
static void camera_axes(const float *pose,float *eye,float *right,float *up,float *forward) {
    float cp=cosf(pose[1]),sp=sinf(pose[1]),cy=cosf(pose[2]),sy=sinf(pose[2]);
    float cr=cosf(pose[3]),sr=sinf(pose[3]);
    forward[0]=-sy*cp;forward[1]=cy*cp;forward[2]=sp;
    const float r[3]={cy,sy,0},u[3]={sy*sp,-cy*sp,cp};
    for(int i=0;i<3;++i) {
        eye[i]=pose[7+i]-pose[0]*forward[i];
        right[i]=cr*r[i]+sr*u[i];up[i]=cr*u[i]-sr*r[i];
    }
}
static void perspective_ray(const float *pose,float lx,float ly,float *eye,float *ray) {
    float right[3],up[3],forward[3];camera_axes(pose,eye,right,up,forward);
    float focal=tanf(pose[4]*0.00872664626f);
    float x=(lx-327)/320-pose[5],y=(797-ly)/800-pose[6];
    for(int i=0;i<3;++i)ray[i]=forward[i]+focal*(x*right[i]+y*up[i]);
}
static void project_world(const float *pose,const float *world,float *raw) {
    float eye[3],right[3],up[3],forward[3];camera_axes(pose,eye,right,up,forward);
    float along=0,across=0,vertical=0,focal=tanf(pose[4]*0.00872664626f);
    for(int i=0;i<3;++i) {
        float v=world[i]-eye[i];along+=v*forward[i];across+=v*right[i];vertical+=v*up[i];
    }
    assert(along>0);
    raw[0]=2*((across/(along*focal)+pose[5])*320+327-7);
    raw[1]=((797-(vertical/(along*focal)+pose[6])*800)+3)*.5f;
}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int pops) {
    if(va==0x8385A0) {assert(!n&&!args&&pops==1);return current_top?0x11000:0;}
    if(va==0xD119FC) {
        assert(n==5&&args[0]==0x11024&&!args[1]&&args[2]==0xF272C0&&args[3]==0xF323A8&&!args[4]&&!pops);
        return current_top;
    }
    assert(va==0x7D46B0&&!n&&!args&&pops==1&&g_esi==0x50720&&g_edi==0x506B0);
    put_float(g_edi+0x1C,fminf(get_float(g_esi+8),fmaxf(get_float(g_esi),get_float(g_edi+0x1C))));
    put_float(g_edi+0x20,fminf(get_float(g_esi+12),fmaxf(get_float(g_esi+4),get_float(g_edi+0x20))));
    return 0;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args) {
    if(va==0x614200||va==0x6146C0) {
        assert(self==0x10000&&!n&&!args);
        return 0xA5A50000u|(va==0x614200?town_busy:town_modal);
    }
    if(va==0x618170) {
        assert(self==0x10000&&!n&&!args&&!MEM32(self+0x294));
        ++town_initializations;MEM32(self+0x294)=1;
        MEM32(self+0x374)=town_init_failure==1?0:0x22000;
        memcpy(GPTR(0x40000),town_initial_pose,40);
        if(town_init_failure==2)current_top=0;
        if(town_init_failure==3)MEM32(self+0xA0)=0xA004;
        if(town_init_failure==4)MEM32(self+0x220)=0x24004;
        return 0;
    }
    if(va==0x410000) {assert(self==0x20000&&!n);return 0x40000;}
    if(va==0x58A5E0) {assert(limits_present&&self==1000&&!n&&!args);++limit_calls;return limits_va;}
    if(va==0x410010) {
        assert(self==0x21000&&n==2&&args[1]==set_immediate);
        memcpy(installed,GPTR(args[0]),40);++set_calls;return 0;
    }
    if(va==0x410020) {assert(self==0x21000&&n==2&&!args[0]&&!args[1]);++unfollow_calls;return 0;}
    if(va==0x410030) {
        assert(self==0x22000&&n==2&&args[1]==set_immediate);
        memcpy(installed,GPTR(args[0]),40);++town_sets;return 0;
    }
    if(va==0x7D4720) {
        assert(self==0x21000&&n==3&&args[0]==0x50720&&args[1]==0x506B0&&args[2]==0x21144);
        float bounds[4]={900,1900,1100,2100};
        if(perspective) {bounds[0]=bounds[1]=-100000;bounds[2]=bounds[3]=100000;}
        memcpy(GPTR(args[0]),bounds,sizeof bounds);return 0;
    }
    if(va==0xB29220) {
        assert(!n);++convert_calls;
        put_float(0x42000,get_float(self)*0.5f+7);
        put_float(0x42004,get_float(self+4)*2-3);
        return 0x42000;
    }
    if(va==0x671310) {
        assert(self==0x10000&&n==2&&get_float(g_edx)>=0);
        assert(get_float(g_edx+4)>=0&&args[0]==0x50000);
        assert(get_float(args[0]+0x6A0)==0); /* engine overwrites the whole context */
        memcpy(GPTR(args[0]+4),GPTR(g_edx),8);
        assert(args[1]==0x40A00000);return args[0];
    }
    assert(va==0xCF6B20&&n==3&&self==0x50700&&g_edx==0x50710);
    assert(args[0]==0x50014&&args[1]==0x5000C&&args[2]==0x50004);++ray_calls;
    if(perspective) {
        float pose[10],eye[3],ray[3];memcpy(pose,GPTR(0x40000),40);
        perspective_ray(pose,get_float(args[2]),get_float(args[2]+4),eye,ray);
        memcpy(GPTR(g_edx),eye,12);memcpy(GPTR(self),ray,12);return self;
    }
    put_float(g_edx,1193);put_float(g_edx+4,1606);put_float(g_edx+8,105);
    put_float(self,get_float(args[2])-500);
    put_float(self+4,(get_float(args[2]+4)-600)*2);
    put_float(self+8,bad_ray==1?0.0f:bad_ray==2?100.0f:-100.0f);
    return self;
}
#include "touch_camera_impl.h"
static float max_pivot_error;
static void check_pivot_sequence(int kind,float pitch,float roll) {
    float pose[10]={40,pitch,3.05f,roll,63,.08f,-.06f,1000,2000,5};
    float x=850,y=320,eye[3],ray[3],world[3],pixel[2];
    perspective_ray(pose,x*.5f+7,y*2-3,eye,ray);
    float distance=(pose[9]-eye[2])/ray[2];assert(distance>0);
    for(int j=0;j<3;++j)world[j]=eye[j]+distance*ray[j];
    MEM32(0x10000)=kind?0xE1DA84:0xE230E4;
    for(int i=0;i<180;++i) {
        float dx=i<60?0:i%2?.4f:-.3f,dy=i<60?0:i%2?-.2f:.3f;
        float rotation=i>=20&&i<40?0:.19f;
        float scale=i<20?1:i%2?1.04f:1/1.04f;
        if(i==40)scale=.001f; /* Clamped dolly still keeps the world pivot. */
        if(i==41)scale=1000;
        option_sensitivity=i<60?1:1.7f;
        memcpy(GPTR(0x40000),pose,40);
        int previous_sets=set_calls;x+=dx;y+=dy;
        assert(void_touch_camera(0x10000,kind,x,y,dx,dy,scale,rotation));
        assert(set_calls==previous_sets+1&&!memcmp(GPTR(0x40000),pose,40));
        assert(installed[1]==pose[1]&&installed[3]==pose[3]&&installed[9]==pose[9]);
        if(i==40)assert(installed[0]==80);
        if(i==41)assert(installed[0]==10);
        project_world(installed,world,pixel);
        float pivot_error=fmaxf(fabsf(pixel[0]-x),fabsf(pixel[1]-y));
        if(pivot_error>max_pivot_error)max_pivot_error=pivot_error;
        /* The engine stores world coordinates as floats: accumulated rounding
           must remain below a quarter pixel, even at the closest zoom. */
        assert(pivot_error<.25f);
        memcpy(pose,installed,40);
    }
}
int main(void) {
    MEM32(0x10000)=0xE230E4;MEM32(0x100A4)=0x20000;MEM32(0x105E4)=0x21000;
    MEM32(0x20000)=0x30000;MEM32(0x21000)=0x31000;
    MEM32(0x30054)=0x410000;MEM32(0x31050)=0x410010;MEM32(0x3105C)=0x410020;
    put_float(0x21144,10);put_float(0x21148,80);
    float pos[10]={40,45,70,0,50,0,0,1000,2000,5};memcpy(GPTR(0x40000),pos,40);
    assert(void_touch_camera(0x10000,0,600,400,20,10,2,0));
    assert(set_calls==1&&unfollow_calls==1&&convert_calls==2&&ray_calls==2);
    assert(installed[0]==20&&installed[7]==990&&installed[8]==1960&&installed[9]==5);
    for(int i=1;i<7;++i) assert(installed[i]==pos[i]);
    assert(!memcmp(GPTR(0x40000),pos,40));
    MEM32(0x10000)=0xE1DA84;MEM32(0x103B8)=0x21000;
    assert(void_touch_camera(0x10000,1,600,400,0,0,0.5f,0));
    assert(installed[0]==80&&installed[7]==1000&&convert_calls==4&&set_calls==2);
    assert(void_touch_camera(0x10000,1,600,400,200,100,100,0));
    assert(installed[0]==10&&installed[7]==900&&installed[8]==1900);
    assert(!void_touch_camera(0x10000,0,600,400,1,1,1,0));
    assert(!void_touch_camera(0x10000,1,NAN,400,1,1,1,0));
    assert(!void_touch_camera(0x10000,1,600,400,1,1,0,0));
    assert(!void_touch_camera(0x10000,1,600,400,INFINITY,1,1,0));
    bad_ray=1;assert(!void_touch_camera(0x10000,1,600,400,1,1,1,0));
    assert(!void_touch_camera(0x10000,1,600,400,0,0,1,.2f));
    bad_ray=2;assert(!void_touch_camera(0x10000,1,600,400,1,1,1,0));
    assert(!void_touch_camera(0x10000,1,600,400,0,0,2,0));
    assert(set_calls==3&&unfollow_calls==3);
    bad_ray=0;
    /* Native yaw is radians. Rotation never edits the borrowed engine pose. */
    put_float(0x40008,3.1f);pos[2]=3.1f;
    assert(void_touch_camera(0x10000,1,600,400,0,0,1,-0.2f));
    assert(fabsf(installed[2]-remainderf(3.3f,6.283185307179586f))<0.00001f);
    assert(get_float(0x40008)==3.1f&&set_calls==4&&unfollow_calls==4);
    for(int i=0;i<10;++i)if(i!=2)assert(installed[i]==pos[i]);
    assert(!void_touch_camera(0x10000,1,600,400,0,0,1,NAN));
    assert(!void_touch_camera(0x10000,3,600,400,0,0,1,0.1f));
    /* Town's operator is a different native class: +144 is a camera, not bounds. */
    MEM32(0x10000)=0xE2A64C;MEM32(0x10374)=0x22000;MEM32(0x10294)=1;
    MEM32(0x100A0)=0xA000;MEM32(0x10220)=0x24000;MEM32(0x24000)=0x33000;MEM32(0x33090)=0x410040;
    MEM32(0x1014C)=0x25000;MEM32(0x25000)=0x25000;
    MEM32(0xFE719C)=0x26000;MEM32(0x26000)=0x26004;
    MEM32(0x11004)=0x32000;MEM32(0x32004)=0x20;
    MEM32(0x22000)=0xE449BC;MEM32(0xE449BC+0x50)=0x410030;
    MEM32(0x22144)=0x20000;put_float(0x22068,100);put_float(0x2206C,1000);
    float town_pos[10]={500,1.1f,.5f,.1f,35,0,0,33,44,5};
    memcpy(GPTR(0x40000),town_pos,40);
    int previous_converts=convert_calls,previous_rays=ray_calls;
    assert(void_touch_camera(0x10000,2,600,400,320,40,2,0));
    assert(town_sets==1&&installed[0]==250&&fabsf(installed[2]-(.5f-1.57079632679f))<0.00001f);
    assert(convert_calls==previous_converts&&ray_calls==previous_rays&&unfollow_calls==4);
    for(int i=1;i<10;++i)if(i!=2)assert(installed[i]==town_pos[i]);
    assert(!memcmp(GPTR(0x40000),town_pos,40));
    assert(void_touch_camera(0x10000,2,600,400,0,0,100,1.57079632679f));
    assert(town_sets==2&&installed[0]==100&&fabsf(installed[2]-(.5f-1.57079632679f))<0.00001f);
    assert(void_touch_camera(0x10000,2,600,400,0,0,.1f,0)&&installed[0]==1000);
    MEM32(0x22144)=0x23000;assert(!void_touch_camera(0x10000,2,600,400,0,0,1,.1f));MEM32(0x22144)=0x20000;
    put_float(0x22068,2000);assert(!void_touch_camera(0x10000,2,600,400,0,0,1,.1f));put_float(0x22068,100);
    MEM32(0x22000)=0xE4493C;assert(!void_touch_camera(0x10000,2,600,400,0,0,1,.1f));
    assert(town_sets==3&&set_calls==4&&unfollow_calls==4);
    MEM32(0x22000)=0xE449BC;
    /* First meaningful camera gesture interrupts the native flyup exactly once. */
    MEM32(0x10294)=0;MEM32(0x10374)=0;
    assert(!void_touch_camera(0x10000,2,600,400,0,40,1,0));
    assert(!town_initializations&&town_sets==3);
    assert(void_touch_camera(0x10000,2,600,400,320,40,2,0.25f));
    assert(town_initializations==1&&town_sets==4&&installed[0]==250);
    assert(fabsf(installed[2]-(.5f-1.57079632679f-.25f))<.00001f);
    assert(!memcmp(GPTR(0x40000),town_initial_pose,40));
    assert(void_touch_camera(0x10000,2,600,400,0,0,1,.125f));
    assert(town_initializations==1&&town_sets==5);
    /* Pending native UI, both busy predicates/bytes, stale owner and missing helper fail closed. */
    for(int guard=0;guard<7;++guard) {
        MEM32(0x10294)=0;MEM32(0x10374)=0;
        if(guard==0)MEM32(0x25000)=0x25004;
        if(guard==1)town_busy=1;
        if(guard==2)town_modal=1;
        if(guard==3)GPTR(0x1029C)[0]=1;
        if(guard==4)GPTR(0x10478)[0]=1;
        if(guard==5)current_top=0;
        if(guard==6)missing_init=1;
        assert(!void_touch_camera(0x10000,2,600,400,1,0,1,0));
        assert(town_initializations==1&&town_sets==5);
        MEM32(0x25000)=0x25000;town_busy=town_modal=missing_init=0;
        GPTR(0x1029C)[0]=GPTR(0x10478)[0]=0;current_top=0x10000;
    }
    for(town_init_failure=1;town_init_failure<=4;++town_init_failure) {
        MEM32(0x10294)=0;MEM32(0x10374)=0;current_top=0x10000;
        MEM32(0x100A0)=0xA000;MEM32(0x10220)=0x24000;
        assert(!void_touch_camera(0x10000,2,600,400,1,0,1,0));
        assert(town_initializations==1+town_init_failure&&town_sets==5);
    }
    town_init_failure=0;current_top=0x10000;
    MEM32(0x100A0)=0xA000;MEM32(0x10220)=0x24000;
    /* The options' camera sensitivity scales turning and zooming; a pan keeps the ground under the fingers. */
    float adventure[10]={40,-0.8f,0.5f,0,50,0,0,1000,2000,5};
    MEM32(0x10000)=0xE230E4;memcpy(GPTR(0x40000),adventure,40);
    int converts=convert_calls,sets=set_calls;
    assert(void_touch_camera(0x10000,0,600,400,20,10,1.25f,0));
    assert(installed[0]==32&&installed[7]==990&&installed[8]==1960&&set_calls==sets+1);
    option_sensitivity=2;
    assert(void_touch_camera(0x10000,0,600,400,20,10,1.25f,0));
    assert(fabsf(installed[0]-40/powf(1.25f,2))<.0001f&&installed[7]==990&&installed[8]==1960);
    assert(convert_calls==converts+4&&set_calls==sets+2);
    for(int i=1;i<7;++i) assert(installed[i]==adventure[i]);
    MEM32(0x10000)=0xE1DA84;
    assert(void_touch_camera(0x10000,1,600,400,0,0,1,-0.2f));
    assert(fabsf(installed[2]-(0.5f+0.4f))<.00001f&&installed[0]==40&&convert_calls==converts+6);
    option_sensitivity=4;sets=set_calls;
    assert(!void_touch_camera(0x10000,1,600,400,0,0,1e30f,0)&&set_calls==sets);
    option_sensitivity=1;
    assert(void_touch_camera(0x10000,1,600,400,0,0,1e30f,0)&&installed[0]==10&&set_calls==sets+1);
    float town_pose[10]={500,-0.6f,.5f,.1f,35,0,0,33,44,5};
    MEM32(0x10000)=0xE2A64C;memcpy(GPTR(0x40000),town_pose,40);option_sensitivity=2;
    int towns=town_sets;
    assert(void_touch_camera(0x10000,2,600,400,320,40,2,0));
    assert(town_sets==towns+1&&installed[0]==125&&fabsf(installed[2]-(.5f-3.14159265f))<.0001f);
    option_sensitivity=1;
    /* Tilt: pitch by vertical travel within the current adventure mode's own limits. */
    const float limits[6]={10,80,-1.2f,-0.3f,-3.14f,3.14f};
    memcpy(GPTR(0x43000),limits,24);limits_present=1;
    MEM32(0x10000)=0xE230E4;memcpy(GPTR(0x40000),adventure,40);
    sets=set_calls;int unfollows=unfollow_calls;
    assert(void_touch_camera_tilt(0x10000,0,100));
    assert(fabsf(installed[1]-(-0.8f-0.15f))<.00001f&&limit_calls==1&&set_calls==sets+1&&unfollow_calls==unfollows+1);
    for(int i=0;i<10;++i) if(i!=1) assert(installed[i]==adventure[i]);
    assert(!memcmp(GPTR(0x40000),adventure,40));
    assert(void_touch_camera_tilt(0x10000,0,10000)&&installed[1]==-1.2f);
    assert(void_touch_camera_tilt(0x10000,0,-10000)&&installed[1]==-0.3f);
    option_sensitivity=2;assert(void_touch_camera_tilt(0x10000,0,100)&&fabsf(installed[1]-(-0.8f-0.3f))<.00001f);
    option_sensitivity=1;
    adventure[1]=-1.2f;memcpy(GPTR(0x40000),adventure,40);sets=set_calls;
    assert(!void_touch_camera_tilt(0x10000,0,100)&&set_calls==sets);   /* already at the mode's limit */
    assert(void_touch_camera_tilt(0x10000,0,-100)&&fabsf(installed[1]-(-1.2f+0.15f))<.00001f);
    /* Implausible, inverted, unreadable or missing limits fall back to the default range. */
    const float wild[6]={10,80,-2.0f,-0.3f,0,0},inverted[6]={10,80,-0.3f,-1.2f,0,0};
    memcpy(GPTR(0x43000),wild,24);assert(void_touch_camera_tilt(0x10000,0,10000)&&installed[1]==-1.5f);
    memcpy(GPTR(0x43000),inverted,24);assert(void_touch_camera_tilt(0x10000,0,-10000)&&installed[1]==-0.05f);
    limits_va=0x10FFFF0;assert(void_touch_camera_tilt(0x10000,0,10000)&&installed[1]==-1.5f);
    limits_va=0x43000;limits_present=0;int calls=limit_calls;
    assert(void_touch_camera_tilt(0x10000,0,-10000)&&installed[1]==-0.05f&&limit_calls==calls);
    memcpy(GPTR(0x43000),limits,24);limits_present=1;
    MEM32(0x10000)=0xE1DA84;sets=set_calls;
    assert(!void_touch_camera_tilt(0x10000,1,100));   /* the battle keeps its pitch */
    MEM32(0x10000)=0xE230E4;
    assert(!void_touch_camera_tilt(0x10000,0,0)&&!void_touch_camera_tilt(0x10000,0,NAN)&&!void_touch_camera_tilt(0x10000,0,INFINITY));
    assert(set_calls==sets&&limit_calls==calls);
    /* The town keeps the default range; no adventure-mode query, no follow release. */
    MEM32(0x10000)=0xE2A64C;memcpy(GPTR(0x40000),town_pose,40);towns=town_sets;unfollows=unfollow_calls;
    assert(void_touch_camera_tilt(0x10000,2,100)&&town_sets==towns+1&&limit_calls==calls&&unfollow_calls==unfollows);
    assert(fabsf(installed[1]-(-0.6f-0.15f))<.00001f);
    for(int i=0;i<10;++i) if(i!=1) assert(installed[i]==town_pose[i]);
    assert(void_touch_camera_tilt(0x10000,2,-10000)&&installed[1]==-0.05f&&town_sets==towns+2);
    /* The battle's home pose: read it, then glide (not immediate) back to it. */
    float home[10];MEM32(0x10000)=0xE1DA84;memcpy(GPTR(0x40000),adventure,40);
    assert(void_touch_camera_pose(0x10000,1,home,0,0)&&!memcmp(home,adventure,40));
    home[7]=950;set_immediate=0;sets=set_calls;unfollows=unfollow_calls;
    assert(void_touch_camera_pose(0x10000,1,home,1,0)&&set_calls==sets+1&&unfollow_calls==unfollows+1);
    assert(installed[7]==950&&installed[8]==adventure[8]);
    set_immediate=1;home[3]=NAN;
    assert(!void_touch_camera_pose(0x10000,1,home,1,1)&&set_calls==sets+1);
    float zero_pose[10]={0};memcpy(GPTR(0x40000),zero_pose,40);
    assert(!void_touch_camera_pose(0x10000,1,home,0,0));
    memcpy(GPTR(0x40000),adventure,40);MEM32(0x10000)=0xE230E4;
    assert(!void_touch_camera_pose(0x10000,1,home,0,0));   /* not a battle screen */
    /* An off-center ground feature stays under the midpoint for repeated turns,
       pinches and simultaneous pans, including yaw wrapping and rod clamps. */
    perspective=1;
    check_pivot_sequence(0,-.8f,.17f);
    check_pivot_sequence(1,-1.1f,-.23f);
    perspective=0;option_sensitivity=1;
    printf("PASS fixed world pivot: 360 perspective gesture updates; maximum drift %.5f raw pixels\n",max_pivot_error);
    /* Enlarged combat HUD: zoom once, frame via projection, then leave manual motion alone. */
    MEM32(0x10000)=0xE1DA84;MEM32(0x102E0)=0x1000;
    MEM32(0x20000)=0xE44224;MEM32(0x21000)=0xE4493C;
    MEM32(0xE44224+0x54)=0x410000;MEM32(0xE4493C+0x50)=0x410010;MEM32(0xE4493C+0x5C)=0x410020;
    put_float(0x21148,42);put_float(0x20060,0);
    float combat_pose[10]={42,-.785f,-1.57f,0,54,1,500,92,98,0};memcpy(GPTR(0x40000),combat_pose,40);
    sets=set_calls;
    for(int i=0;i<40;++i) {
        void_touch_combat_frame(0x10000,985,439,262,340,390);
        if(set_calls>sets)memcpy(GPTR(0x40000),installed,40);
    }
    assert(set_calls==sets&&framing.ratio>1.25f&&framing.ratio<1.35f);
    assert(fabsf(framing.centre-2*(151.0f-365)/439)<.0001f);
    MEMF(0xF74BE4)=439;MEMF(0x20070)=42;g_ecx=0x20000;
    camera_projection();assert(projected_rod>52&&projected_rod<56&&projected_centre<-.9f);
    assert(MEMF(0x20070)==42&&MEMF(0x20060)==0);
    MEMF(0xF74BE4)=768;camera_projection();assert(projected_rod==42&&projected_centre==0);
    for(int i=0;i<50;++i)void_touch_combat_frame(0x10000,985,439,262,100,150);
    assert(set_calls==sets); /* Moving a creature does not move the camera again. */
    MEM32(0x102E0)=0;
    void_touch_combat_frame(0x10000,985,439,262,100,150);assert(MEMF(0x20060)==0);
    MEM32(0x10000)=0xE230E4;MEMF(0xF74BE4)=439;
    void_touch_adventure_frame(0x10000,439,45,220);
    camera_projection();
    assert(fabsf(projected_centre-(265.0f/439-1))<.0001f&&projected_rod==42);
    assert(MEMF(0x20060)==0&&MEMF(0x20070)==42&&set_calls==sets);
    void_touch_adventure_frame(0x10000,439,300,220); /* Invalid HUD cannot corrupt projection. */
    camera_projection();assert(projected_centre<-.39f&&projected_centre>-.40f);
    MEMF(0xF74BE4)=384;void_touch_adventure_frame(0x10000,384,56,144);
    camera_projection();assert(fabsf(projected_centre-(200.0f/384-1))<.0001f);
    for(int i=0;i<3;++i) { /* Hiding/reopening the army panel has no accumulated offset. */
        void_touch_adventure_frame(0x10000,384,0,384);camera_projection();assert(projected_centre==0);
        void_touch_adventure_frame(0x10000,384,56,144);camera_projection();
        assert(fabsf(projected_centre-(200.0f/384-1))<.0001f&&MEMF(0x20060)==0);
    }
    MEMF(0xF74BE4)=768;camera_projection();assert(projected_centre==0&&projected_rod==42);
    MEMF(0xF74BE4)=439;void_touch_combat_frame(0,0,0,0,0,0);
    camera_projection();assert(projected_centre==0);
    MEM32(0x20000)=0x30000;MEM32(0x21000)=0x31000;
    MEM32(0x10000)=0xE1DA84;
    camera_scratch=0;failed_allocation=1;
    assert(!void_touch_camera(0x10000,1,600,400,0,0,1,0));
    void_touch_camera_init();assert(registered);void_touch_camera_init();
    MEM32(g_esp+4)=0x60000;MEM32(g_esp+8)=0x60008;MEM32(0x60008)=0xABCDEF;
    registered();assert(g_eax==0x60000&&g_esp==0x7000C&&!MEM32(0x60000)&&!MEM32(0x60004));
    assert(MEM32(0x60008)==0xABCDEF&&!edge_calls);
    touch_mode=0;registered();assert(edge_calls==1&&g_eax==0x12345678&&g_esp==0x70018);
    puts("PASS native camera: original projection ABI/pan/pinch, radians yaw/wrap, native town operator/rod limits, stale city camera rejection, unchanged native pose and touch-only edge suppression; sensitivity scales turn/zoom/tilt but not pan, tilt within the mode's pitch limits (defaults otherwise, none in battle), pose read/glide");
    return 0;
}
'''


class TouchCameraTest(unittest.TestCase):
    def camera_source(self):
        source = (ROOT / "android/host/touch_camera.c").read_text(encoding="utf-8")
        for name in ("host.h", "input.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', '')
        return source

    def test_camera_engine_contract(self):
        source = self.camera_source()
        compile_probe("touch_camera", HARNESS, {"touch_camera_impl.h": source})

    def test_pivot_regression_rejects_old_pan_only_compensation(self):
        source = self.camera_source()
        # Disable only orbit/dolly compensation, preserving the old pan behavior.
        old = "float c = cosf(yaw), s = sinf(yaw), ax = after[0] - position[7], ay = after[1] - position[8];"
        broken = "ratio = 1 + 0 * ratio;\n        " + old.replace("cosf(yaw)", "cosf(0 * yaw)").replace("sinf(yaw)", "sinf(0 * yaw)")
        self.assertIn(old, source)
        with self.assertRaisesRegex(AssertionError, "pivot_error"):
            compile_probe("touch_camera_pivot_negative", HARNESS, {"touch_camera_impl.h": source.replace(old, broken, 1)})


if __name__ == "__main__":
    unittest.main()
