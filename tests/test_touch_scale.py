"""Run native UI scaling against the original viewport and relayout ABI."""
from pathlib import Path
import unittest
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define MEMF(a) (*(float *)(memory+(uint32_t)(a)))
#define MEM8(a) (*(uint8_t *)(memory+(uint32_t)(a)))
#define GPTR(a) (memory+(uint32_t)(a))
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int locked;
static void pthread_mutex_lock(pthread_mutex_t *m) {(void)m;assert(!locked);locked=1;}
static void pthread_mutex_unlock(pthread_mutex_t *m) {(void)m;assert(locked);locked=0;}
enum { TOUCH_ABORT=10 };
typedef struct {int kind;float x,y,dx,dy,scale;} void_touch_event;
typedef void (*void_fn)(void);
#define VLOG(...) ((void)0)
static int mapped=1, writable=1, dispatch=1, has_screen=1;
static void void_touch_adventure_frame(uint32_t s,float h,float t,float b) {(void)s;(void)h;(void)t;(void)b;}
static void void_touch_combat_frame(uint32_t s,float w,float h,float hud,float t,float b) {
    (void)w;(void)h;(void)hud;(void)t;(void)b;assert(!s);
}
static int backbuffer_w=1920,backbuffer_h=1080,aborts,relayouts,queries,gesture_active;
static int text_refreshes[3], bad_cast, cycle_screens;
static int alternate_top, viewport_calls, viewport_stage, allocation_fail, flip_on_query, pump_layouts;
/* CWindow elements of the top root: primary vtable 0x71000 (placement getter +8, layout +0x24). */
static const uint32_t elements[]={0x61000,0x61400,0x61800,0x61C00,0x62000};
static float native_axis(uint32_t mode,float origin,float span,float pos,float low,float size) {
    return mode==1?origin+truncf((span-truncf(size))*.5f)+pos:mode==2?origin+span-size+pos:mode==3?origin+low:origin+pos;
}
static void native_layout(uint32_t e,const float *r) {
    uint32_t p=MEM32(e+0x140);
    MEMF(e+0x64)=native_axis(MEM32(p+0x9C),r[0],r[2]-r[0],MEMF(p+0x88),MEMF(p+0xB0),MEMF(p+0xA4));
    MEMF(e+0x68)=native_axis(MEM32(p+0x94),r[1],r[3]-r[1],MEMF(p+0x8C),MEMF(p+0xB4),MEMF(p+0xA8));
}
/* The original CWindow::Layout: thiscall, parent rectangle at [esp+4], RET 4. */
static uint32_t g_ecx, g_esp;
typedef struct {uint32_t ecx,esp;} void_regs;
static void void_regs_save(void_regs *r){r->ecx=g_ecx;r->esp=g_esp;}
static void void_regs_load(const void_regs *r){g_ecx=r->ecx;g_esp=r->esp;}
static int lifted_layouts;
static void sub_00A50560(void) {
    native_layout(g_ecx,(const float *)GPTR(MEM32(g_esp+4)));g_esp+=8;++lifted_layouts;
}
/* Its dispatch entry, as virtual calls resolve it. */
static void_fn layout_entry;
static void void_dispatch_add(uint32_t va,void_fn fn) {assert(va==0xA50560&&!layout_entry&&fn);layout_entry=fn;}
static void layout_through_entry(uint32_t window,uint32_t rect) {
    g_esp=0x7F000;MEM32(g_esp)=0xDEADu;MEM32(g_esp+4)=rect;g_ecx=window;
    (layout_entry?layout_entry:sub_00A50560)();assert(g_esp==0x7F008);
}
static void layout_through_override(uint32_t window,const float *parent) {
    memcpy(GPTR(0x7E000),parent,16);layout_through_entry(window,0x7E000);
}
static void native_children(uint32_t complete) {
    /* A50560 -> A4F710: children against the root's own rectangle, each through slot +0x24. */
    uint32_t p=MEM32(complete+0x140);float r[4]={MEMF(complete+0x64),MEMF(complete+0x68),0,0};
    r[2]=r[0]+MEMF(p+0xA4);r[3]=r[1]+MEMF(p+0xA8);
    for(uint32_t i=MEM32(complete+0xA4);i<MEM32(complete+0xA8);i+=4)layout_through_override(MEM32(i),r);
}
static uint32_t module=0x400000;
static float old_w,old_h;
static int native_w=2399,native_h=1501;
static int native_size(int*w,int*h){*w=native_w;*h=native_h;return 1;}
static int (*void_android_display_size)(int*,int*);
static uint32_t void_module_exe_base(void) {return module;}
static int void_vm_readable(uint32_t a,uint32_t n) {return mapped&&a>0&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n) {return writable&&void_vm_readable(a,n);}
static void dummy(void) {}
static uint32_t void_galloc(uint32_t size) {assert(size==16||size==128);return allocation_fail?0:size==16?0x80000:0x80100;}
static void sub_00A50560(void);
static void_fn void_dispatch_find(uint32_t a) {
    if(a==0x8885D0)return NULL; /* Scrollable rows have their own native-layout fixture. */
    if(a==0xA50560)return dispatch?(void_fn)sub_00A50560:NULL;
    assert(a==0x66A4D0||a==0x8385A0||a==0x8384D0||a==0xD119FC||
           a==0xA4E570||a==0xB95AC0||a==0xABE980||a==0x487990||a==0xA504B0||a==0x488220||a==0xA50560);return dispatch?dummy:NULL;
}
static void void_input_screen_size(int *w,int *h) {*w=backbuffer_w;*h=backbuffer_h;}
static void void_touch_engine_event(const void_touch_event *e) {
    assert(!locked&&e->kind==TOUCH_ABORT&&e->scale==1);
    assert(MEMF(0xF74BE0)==old_w&&MEMF(0xF74BE4)==old_h);
    gesture_active=0;++aborts;
}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int pops) {
    assert(!locked);
    if(va==0xD119FC) {
        assert(n==5&&args&&!pops&&!args[1]&&!args[4]);
        if(bad_cast)return 0;
        if(args[2]==0xF272C0) {
            assert(args[3]==0xF323A8);
            if(args[0]==0x20024)return 0x22000;
            assert(args[0]==0x21024);return 0x23000;
        }
        assert(args[2]==0xF2DAF4&&args[3]==0xF2DA88);
        if(args[0]==0x24044)return 0x30000;
        assert(args[0]==0x25044);return 0x31000;
    }
    assert(pops==1);
    if(va==0x8385A0) {assert(!n&&!args);++queries;if(queries==flip_on_query)alternate_top=1;return has_screen?(alternate_top?0x21000:0x20000):0;}
    assert(va==0x66A4D0&&n==1&&args&&!args[0]&&!gesture_active);
    assert(MEMF(0xF74BF0)==backbuffer_w&&MEMF(0xF74BF4)==backbuffer_h);
    assert(MEMF(0xF74BE0)>0&&MEMF(0xF74BE4)>0);
    /* Original relayout restores canonical parent rectangles, never resource positions. */
    MEMF(0x24000-0xF8+0x64)=MEMF(0x24000-0xF8+0x68)=0;
    MEMF(0x25000-0xF8+0x64)=MEMF(0x25000-0xF8+0x68)=0;
    MEMF(0x72000+0xA4)=MEMF(0xF74BE0);MEMF(0x72000+0xA8)=MEMF(0xF74BE4);
    native_children(0x24000-0xF8);
    ++relayouts;return 0;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args) {
    assert(!locked);
    if(va==0x487990) {
        assert(n==1&&args&&args[0]==0x80000&&!viewport_stage);
        assert(self==(alternate_top?0x25000u:0x24000u));
        assert(MEM32(0xD0FC)==3&&MEM32(0xD100)==3);
        float *rect=(float *)GPTR(args[0]);
        assert(rect[2]-rect[0]>=1024&&rect[3]-rect[1]>=768);
        MEMF(self-0xF8+0x64)=rect[0]+7;
        MEMF(self-0xF8+0x68)=rect[1]+9;
        /* A stretched root takes the rectangle's size; the native setter lays out descendants. */
        uint32_t placement=MEM32(self-0xF8+0x140);
        MEMF(placement+0xA4)=rect[2]-rect[0];MEMF(placement+0xA8)=rect[3]-rect[1];
        native_children(self-0xF8);
        viewport_stage=1;return 0;
    }
    if(va==0xA50560) {
        /* The frame pump moving an element through its layout slot. */
        assert(n==1&&args&&args[0]==0x80000&&!viewport_stage);
        layout_through_entry(self,args[0]);++pump_layouts;return 0;
    }
    assert(!n&&!args);
    if(va==0xA504B0) {assert(viewport_stage==1&&self==(alternate_top?0x25014u:0x24014u));viewport_stage=2;return 0;}
    if(va==0x488220) {assert(viewport_stage==2&&self==(alternate_top?0x25000u-0xF8u:0x24000u-0xF8u));viewport_stage=0;++viewport_calls;return 0;}
    if(va==0x8384D0) {
        assert(self==0x20000||self==0x21000);
        return cycle_screens?0x20000:self==0x20000?0x21000:0;
    }
    assert(relayouts&&!gesture_active);
    if(va==0xA4E570) {assert(self==0x32000||self==0x37000);++text_refreshes[0];}
    else if(va==0xB95AC0) {assert(self==0x33000);++text_refreshes[1];}
    else {assert(va==0xABE980&&self==0x34000);++text_refreshes[2];}
    return 0;
}
#include "touch_scale_impl.h"
static void near_at(double a,double b,int line) {
    if(fabs(a-b)>=0.0002)fprintf(stderr,"line %d: %.4f != %.4f\n",line,a,b);
    assert(fabs(a-b)<0.0002);
}
#define near(a,b) near_at((a),(b),__LINE__)
static void dimensions(float pw,float ph,float vw,float vh) {
    MEMF(0xF74BF0)=pw;MEMF(0xF74BF4)=ph;
    MEMF(0xF74BE0)=vw;MEMF(0xF74BE4)=vh;
}
static void pump(void) {old_w=MEMF(0xF74BE0);old_h=MEMF(0xF74BE4);void_touch_scale_pump();}
int main(void) {
    MEM32(0x900)=0xE1DA84;viewport.screen=0x900;
    memcpy(GPTR(0x1000),"WindowFadedText",15);MEM32(0x2058)=0x1000;MEM32(0x205C)=0x100F;
    MEMF(0x208C)=150;MEMF(0x20A4)=512;MEMF(0x20A8)=128;MEM32(0x209C)=1;
    float fr[4]={0,0,1024,768},position[2],size[2],shift[2];
    scale_place(0x2000,fr,fr,985,439,position,size,shift);near(position[1]+shift[1],44);
    viewport.screen=0;
    near(scale_anchor_shift(2,774,256,0,1024,985),-39);
    near(scale_anchor_shift(2,528,256,0,768,439),-329);
    /* HoF ChangeProfile: its -220 bottom inset must not push a fitting dialog above the screen. */
    near(768-464-220+scale_anchor_shift(2,768-464-220,464,0,768,76800.0f/165),0);
    near(768-464-220+scale_anchor_shift(2,768-464-220,464,0,768,384),0);
    near((528+scale_anchor_shift(2,528,256,0,768,439))+33,
         561+scale_anchor_shift(2,561,57,0,768,439));
    MEMF(0xF74BE8)=1024;MEMF(0xF74BEC)=768;
    MEMF(0x10268C4)=7.5f;MEMF(0x10268C8)=-3.25f;
    MEM32(0xFE719C)=0x10000;
    /* Two original CBaseScreen roots with borrowed CWindow trees. */
    MEM32(0x20004)=MEM32(0x21004)=0x8000;MEM32(0x8004)=0x20;
    MEM32(0x220A0)=0x24000;MEM32(0x230A0)=0x25000;
    MEM32(0x24004)=MEM32(0x25004)=0x8100;MEM32(0x8108)=0x40;
    MEM32(0x30000)=MEM32(0x31000)=0x9000;MEM32(0x9004)=0xA4E570;
    MEM32(0x300A4)=0xA000;MEM32(0x300A8)=0xA014;
    for(int i=0;i<5;i++)MEM32(0xA000+4*i)=0x32000+0x1000*i;
    MEM32(0x310A4)=0xA100;MEM32(0x310A8)=0xA104;MEM32(0xA100)=0x37000;
    MEM32(0x32000)=MEM32(0x37000)=0x9000;MEM32(0x32070)=0x40000;MEM32(0x37070)=0x43000;
    MEM32(0x40004)=MEM32(0x43004)=0x50000;MEM32(0x40008)=MEM32(0x43008)=0x50002;
    MEM32(0x33000)=0x9200;MEM32(0x9204)=0xB95AC0;MEM32(0x33100)=0x41000;
    MEM32(0x3310C)=0x50010;MEM32(0x33110)=0x50012;
    MEM32(0x34000)=0x9300;MEM32(0x9304)=0xABE980;MEM32(0x34104)=0x42000;MEM32(0x42000)=0x9400;
    MEM32(0x35000)=0x9500;MEM32(0x9504)=0x123456;MEM32(0x35070)=0x40000; /* Nontext VM object is rejected. */
    MEM32(0x36000)=0x9000;MEM32(0x360A4)=0xA200;MEM32(0x360A8)=0xA1FF; /* Invalid child vector. */
    dimensions(1920,1080,1366,768);
    pump();assert(!aborts&&!relayouts&&!queries); /* Existing 100% is untouched. */

    void_touch_set_scale(.75f);
    assert(!aborts&&!relayouts); /* UI thread only records the request. */
    module=0;pump();module=0x400000;assert(!aborts);
    mapped=0;pump();mapped=1;assert(!aborts);
    writable=0;pump();writable=1;assert(!aborts);
    dispatch=0;pump();dispatch=1;assert(!aborts);
    backbuffer_w=1600;pump();backbuffer_w=1920;assert(!aborts); /* D3D/UI resize race. */
    MEMF(0xF74BE8)=800;pump();MEMF(0xF74BE8)=1024;assert(!aborts);
    MEM32(0xFE719C)=0;pump();MEM32(0xFE719C)=0x10000;assert(!aborts);
    has_screen=0;pump();has_screen=1;assert(!aborts);
    gesture_active=1;pump();assert(aborts==1&&relayouts==1&&!gesture_active);
    assert(text_refreshes[0]==2&&text_refreshes[1]==1&&text_refreshes[2]==1);
    near(MEMF(0xF74BE0),1366.0/.75);near(MEMF(0xF74BE4),1024);
    assert(MEMF(0xF74BF0)==1920&&MEMF(0xF74BF4)==1080);
    assert(MEMF(0xF74BE8)==1024&&MEMF(0xF74BEC)==768);
    assert(MEMF(0x10268C4)==7.5f&&MEMF(0x10268C8)==-3.25f);
    /* Original conversion/inverse and camera aspect remain coherent. */
    double vx=MEMF(0xF74BE0),vy=MEMF(0xF74BE4);
    double lx=700.0/1920*vx+7.5,ly=500.0/1080*vy-3.25;
    near((lx-7.5)/vx*1920,700);near((ly+3.25)/vy*1080,500);
    near((lx-7.5)/vx,700.0/1920);near((ly+3.25)/vy,500.0/1080);
    near(vy/vx,768.0/1366); /* CF7D90's projection input is height/width. */
    int seen_queries=queries;
    for(int i=0;i<20;i++)pump();
    assert(aborts==1&&relayouts==1&&queries==seen_queries);
    assert(text_refreshes[0]==2&&text_refreshes[1]==1&&text_refreshes[2]==1);
    void_touch_set_scale(.75f);pump();assert(relayouts==1);

    dimensions(1920,1080,1366,768);pump(); /* Engine resets virtual UI after resize. */
    assert(aborts==2&&relayouts==2);pump();assert(relayouts==2);
    backbuffer_w=2560;backbuffer_h=1600;dimensions(2560,1600,1229,768);pump();
    near(MEMF(0xF74BE0),1229.0/.75);near(MEMF(0xF74BE4),1024);
    assert(aborts==3&&relayouts==3);pump();assert(relayouts==3);
    backbuffer_w=800;backbuffer_h=1200;dimensions(800,1200,1024,1536);pump();
    near(MEMF(0xF74BE0),1024.0/.75);near(MEMF(0xF74BE4),2048);
    assert(relayouts==4);

    void_touch_set_scale(-10);
    void_touch_set_scale(NAN);void_touch_set_scale(INFINITY);
    pump();near(MEMF(0xF74BE0),2048);near(MEMF(0xF74BE4),3072);assert(relayouts==5);
    void_touch_set_scale(1);pump();
    near(MEMF(0xF74BE0),1024);near(MEMF(0xF74BE4),1536);assert(relayouts==6);
    void_touch_set_scale(.5f);
    dimensions(NAN,1200,1024,1536);pump();assert(relayouts==6);
    dimensions(800,0,1024,1536);pump();assert(relayouts==6);
    dimensions(800,1200,NAN,1536);pump();assert(relayouts==6);
    backbuffer_w=16384;backbuffer_h=1;dimensions(16384,1,1024,768);pump();assert(relayouts==6);
    assert(text_refreshes[0]==12&&text_refreshes[1]==6&&text_refreshes[2]==6);
    /* Repeated screen pointers and self-child links cannot cause an unbounded refresh. */
    backbuffer_w=800;backbuffer_h=1200;dimensions(800,1200,1024,1536);cycle_screens=1;
    MEM32(0xA010)=0x30000;pump();assert(relayouts==7);
    assert(text_refreshes[0]==13&&text_refreshes[1]==7&&text_refreshes[2]==7);
    cycle_screens=0;bad_cast=1;void_touch_set_scale(1);pump();assert(relayouts==8);
    assert(text_refreshes[0]==13&&text_refreshes[1]==7&&text_refreshes[2]==7);
    /* Above 100% the root keeps its 1024x768 frame at the top-left and CWindow::Layout
       places each element at its edge or centre of the smaller screen. */
    bad_cast=0;backbuffer_w=1920;backbuffer_h=1080;
    MEM32(0x24000)=MEM32(0x25000)=0xA800;
    MEM32(0xA848)=0x487990;MEM32(0xA84C)=0x488330;
    MEM32(0x240C8)=MEM32(0x250C8)=0xD000;
    MEM32(0xD0FC)=3;MEM32(0xD100)=3;
    MEM32(0x2214C)=0x52000;MEM32(0x52000)=0x52000;
    MEM32(0x2314C)=0x53000;MEM32(0x53000)=0x53000;
    static const unsigned char getter[]={0x8B,0x81,0x40,0x01,0,0,0xC3}; /* mov eax,[ecx+140h]; ret */
    memcpy(GPTR(0x70000),getter,sizeof getter);
    MEM32(0x71008)=0x70000;MEM32(0x71024)=0xA50560;
    const uint32_t root=0x24000-0xF8;
    MEM32(root)=MEM32(0x25000-0xF8)=0x71000;MEM32(root+0x140)=0x72000;MEM32(0x25000-0xF8+0x140)=0x73000;
    MEM8(0x72000+0x70)=MEM8(0x73000+0x70)=1;
    MEM32(root+0xA4)=0x74000;MEM32(root+0xA8)=0x74000+4*5;
    /* A bottom-right button, a top-left logo, a bottom panel placed by absolute position,
       a window its own code moves and a hidden dialog larger than the scaled screen. */
    static const float spec[5][7]={{100,50,2,2,-10,-20,1},{300,100,0,0,0,0,1},{200,150,0,0,2,600,1},
                                   {80,40,0,0,0,0,1},{900,700,1,1,0,0,0}};
    for(int i=0;i<5;i++){
        uint32_t e=elements[i],q=0x63000+0x200*i;
        MEM32(0x74000+4*i)=e;MEM32(e)=0x71000;MEM32(e+0x140)=q;MEM32(e+0x28)=root;
        MEMF(q+0xA4)=spec[i][0];MEMF(q+0xA8)=spec[i][1];
        MEM32(q+0x9C)=(uint32_t)spec[i][2];MEM32(q+0x94)=(uint32_t)spec[i][3];
        MEMF(q+0x88)=spec[i][4];MEMF(q+0x8C)=spec[i][5];MEM8(q+0x70)=(uint8_t)spec[i][6];
    }
    #define AT(i,x,y) (near(MEMF(elements[i]+0x64),x),near(MEMF(elements[i]+0x68),y))
    dimensions(1920,1080,1366,768);void_touch_set_scale(9);
    int relayouts_before=relayouts;
    gesture_active=1;pump();near(MEMF(0xF74BE0),683);near(MEMF(0xF74BE4),384);
    assert(viewport_calls==1&&!gesture_active&&relayouts==relayouts_before+1);
    near(MEMF(root+0x64),7);near(MEMF(root+0x68),9); /* The root frame stays at the top. */
    AT(0,573,314);AT(1,0,0);AT(2,2,216);AT(3,0,0);
    /* The dispatch entry anchored them while the original layout ran: nothing left for the pump. */
    assert(layout_entry&&!pump_layouts);
    float origin_x=MEMF(0x10268C4),origin_y=MEMF(0x10268C8);
    assert(!void_touch_ui_pan(0x22000,1920,1080)&&viewport_calls==1); /* Nothing is left to pan to. */
    int fonts=text_refreshes[0],laid=lifted_layouts;
    for(int i=0;i<20;i++)pump();
    assert(viewport_calls==1&&lifted_layouts==laid&&relayouts==relayouts_before+1&&text_refreshes[0]==fonts);
    MEMF(elements[3]+0x64)=500;MEMF(elements[3]+0x68)=300;pump(); /* Its own code moved it. */
    AT(3,500,300);assert(lifted_layouts==laid);
    MEMF(elements[3]+0x64)=500;MEMF(elements[3]+0x68)=500;pump(); /* Off the screen: kept on it. */
    AT(3,500,344);assert(pump_layouts==1);pump();AT(3,500,344);assert(pump_layouts==1);
    MEMF(root+0x64)=0;pump();assert(viewport_calls==2); /* A native relayout is anchored again. */
    AT(0,573,314);AT(1,0,0);AT(2,2,216);AT(3,0,0);pump();assert(viewport_calls==2);
    /* A stored or already shifted parent rectangle is laid out as given. */
    const float stored[4]={7-348,9-393,1031-348,777-393};
    layout_through_override(elements[0],stored);AT(0,573,314);
    /* Projected troop counts retain their world position, including offscreen. */
    uint32_t stack=elements[3],sp=MEM32(stack+0x140);
    memcpy(GPTR(0x7D000),"StackInfo",9);MEM32(sp+0x58)=0x7D000;MEM32(sp+0x5C)=0x7D009;
    MEMF(sp+0x88)=600.25f;MEMF(sp+0x8C)=400.5f;
    const float unshifted[4]={0,0,1024,768};
    layout_through_override(stack,unshifted);AT(3,600.25f,400.5f);
    pump();AT(3,600.25f,400.5f);
    MEM32(sp+0x58)=MEM32(sp+0x5C)=0;MEMF(sp+0x88)=MEMF(sp+0x8C)=0;
    memcpy(GPTR(0x7D000),"TownHeroPanel",13);MEM32(sp+0x58)=0x7D000;MEM32(sp+0x5C)=0x7D00D;
    for(int visible=0;visible<2;++visible) {
        MEM8(sp+0x70)=(uint8_t)visible;
        scale_pass measured={.view_w=683,.view_h=384,.remaining=4096,.map_bottom=384};
        scale_anchor(root,0,&measured);assert(measured.map_army==(unsigned)visible);
    }
    MEM32(sp+0x58)=MEM32(sp+0x5C)=0;
    /* A dialog larger than the screen lowers its screen's scale until it fits. */
    MEM8(0x63000+0x200*4+0x70)=1;pump();
    near(MEMF(0xF74BE0),1366/1.09);near(MEMF(0xF74BE4),768/1.09);
    assert(relayouts==relayouts_before+2&&viewport_calls==3);
    AT(4,183,2);AT(0,7+1366/1.09-110,635);AT(2,9,537);
    for(int i=0;i<5;i++)pump();assert(relayouts==relayouts_before+2&&viewport_calls==3);
    MEM8(0x63000+0x200*4+0x70)=0;pump(); /* Closed: the requested scale returns. */
    near(MEMF(0xF74BE0),683);near(MEMF(0xF74BE4),384);assert(relayouts==relayouts_before+3);
    AT(0,573,314);AT(2,2,216);
    assert(MEMF(0x10268C4)==origin_x&&MEMF(0x10268C8)==origin_y);
    /* Modal owner changes admit only the current root, not a retained window pointer. */
    alternate_top=1;pump();assert(viewport_calls==5);
    MEM32(0x53000)=0;pump();assert(viewport_calls==5);MEM32(0x53000)=0x53000;
    /* Invalid root ABI/resource modes and failed scratch allocation fail closed. */
    alternate_top=0;MEM32(0xA848)=0;viewport.root=0;pump();assert(viewport_calls==5);
    MEM32(0xA848)=0x487990;MEM32(0xD0FC)=4;pump();assert(viewport_calls==5);MEM32(0xD0FC)=3;
    viewport_scratch=0;allocation_fail=1;pump();assert(viewport_calls==5);
    allocation_fail=0;pump();assert(viewport_calls==6);
    /* Without the original getter shape the original layout is left alone. */
    MEM8(0x70006)=0x90;MEMF(root+0x64)=0;pump();AT(0,921,707);AT(1,7,9);MEM8(0x70006)=0xC3;
    void_touch_set_scale(1);pump();
    near(MEMF(0xF74BE0),1366);near(MEMF(0xF74BE4),768);
    assert(MEMF(0x24000-0xF8+0x64)==0&&MEMF(0x24000-0xF8+0x68)==0);
    AT(0,1366-110,768-70);AT(1,0,0); /* At 100% every element is where the original puts it. */
    assert(MEM32(0xD0FC)==3&&MEM32(0xD100)==3); /* Resource layout was never mutated. */
    /* HoF JoinFleeBox keeps its own position when the larger canvas now fits it.
       Both sides of the old 200 -> 165 -> 200 feedback must choose 165. */
    MEMF(root+0x64)=MEMF(root+0x68)=0;
    MEMF(0x720A4)=1024;MEMF(0x720A8)=768;
    for(int i=0;i<5;++i)MEM8(0x63000+0x200*i+0x70)=0;
    uint32_t modal_window=elements[4],modal_placement=0x63800;
    MEM8(modal_placement+0x70)=1;MEMF(modal_placement+0xA4)=526;MEMF(modal_placement+0xA8)=465;
    MEM32(modal_placement+0x94)=MEM32(modal_placement+0x9C)=1;
    MEMF(modal_placement+0x88)=MEMF(modal_placement+0x8C)=0;
    MEMF(modal_window+0x64)=168;MEMF(modal_window+0x68)=0;
    fit.screen=0x22000;MEM32(0x52000)=0x52010;
    assert(scale_fits(root,0,862,384,1724,768,200)==165);
    assert(scale_fits(root,0,172400.0f/165,76800.0f/165,1724,768,200)==165);
    MEM32(0x52000)=0x52000; /* Self-positioned non-modal dialogs must fit too. */
    assert(scale_fits(root,0,172400.0f/165,76800.0f/165,1724,768,200)==165);
    MEM8(modal_placement+0x70)=0;
    assert(scale_fits(root,0,172400.0f/165,76800.0f/165,1724,768,200)==200);
    /* Rounded render resolution cannot change the logical UI size. */
    void_android_display_size=native_size;
    backbuffer_w=1319;backbuffer_h=826;dimensions(1319,826,1227,768);pump();
    near(MEMF(0xF74BE0),1228);near(MEMF(0xF74BE4),768);
    backbuffer_w=600;backbuffer_h=375;dimensions(600,375,1229,768);pump();
    near(MEMF(0xF74BE0),1228);near(MEMF(0xF74BE4),768);
    /* A different-aspect game mode remains letterboxed and uses its own canvas. */
    backbuffer_w=1280;backbuffer_h=720;dimensions(1280,720,1366,768);
    pump();near(MEMF(0xF74BE0),1366);near(MEMF(0xF74BE4),768);
    /* The initiative strip and right combat dial share one bottom row. Their
       individual widths fit at 200%, but their combined occupied width does not. */
    {
    viewport.screen=0x9000;MEM32(viewport.screen)=0xE1DA84;
    for(int i=0;i<5;i++)MEM8(MEM32(elements[i]+0x140)+0x70)=0;
    MEMF(root+0x64)=MEMF(root+0x68)=0;
    uint32_t root_place=MEM32(root+0x140);
    MEMF(root_place+0xA4)=1024;MEMF(root_place+0xA8)=768;
    const char *names[2]={"ATBBar","Jogdial"};
    for(int i=0;i<2;i++){
        uint32_t p=MEM32(elements[i]+0x140),name=0x7B000+32*i;
        memcpy(GPTR(name),names[i],strlen(names[i]));MEM32(p+0x58)=name;MEM32(p+0x5C)=name+(uint32_t)strlen(names[i]);
        MEM8(p+0x70)=1;MEM32(p+0x94)=2;MEM32(p+0x9C)=i?2:0;
        MEMF(p+0x88)=i?-22.f:21.f;MEMF(p+0x8C)=i?-4.f:-9.f;
        MEMF(p+0xA4)=i?203.f:766.f;MEMF(p+0xA8)=i?215.f:162.f;
        native_layout(elements[i],unshifted);
    }
    int combat_fit=scale_fits(root,0,967.4418f,446.5116f,1664,768,200);
    assert(combat_fit==164);
    float combat_view=1664.0f*100/(float)combat_fit,row_pos[2],row_size[2],row_shift[2];
    scale_place(MEM32(elements[1]+0x140),unshifted,unshifted,combat_view,768.0f*100/(float)combat_fit,row_pos,row_size,row_shift);
    assert(row_pos[0]+row_shift[0]>=21+766); /* no initiative/dial overlap */
    MEM8(MEM32(elements[1]+0x140)+0x70)=0;
    assert(scale_fits(root,0,832,384,1664,768,200)==200); /* no hidden dial reservation */
    MEM8(MEM32(elements[1]+0x140)+0x70)=1;MEM32(viewport.screen)=0;
    assert(scale_fits(root,0,832,384,1664,768,200)==200); /* unrelated screens unchanged */
    }
    puts("PASS native UI scale: record-only setter, readiness, coherent inverse/ray, native relayout, abort-before-change, idempotence, resize recovery, top anchoring and fit");
    return 0;
}
'''


class TouchScaleTest(unittest.TestCase):
    def test_original_ui_scale_contract(self):
        source = (ROOT / "android/host/touch_scale.c").read_text(encoding="utf-8")
        for name in ("host.h", "input.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', '')
        source = '\n'.join(line for line in source.splitlines()
                           if not line.startswith("extern int void_android_"))
        compile_probe("touch_scale", HARNESS, {"touch_scale_impl.h": source})


if __name__ == "__main__":
    unittest.main()
