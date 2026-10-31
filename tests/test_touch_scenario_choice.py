"""Scenario swipes retain the original selection rules and native tooltip (swipes: every edition,
1.6/2.1 through their contract-adapted touch_engine.c)."""
import json
import sys
import unittest
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
import port_patches   # noqa: E402

class ScenarioChoiceTest(unittest.TestCase):
    def test_localized_specialization_description(self):
        text=(ROOT/'android/host/touch_engine.c').read_text()
        code=text[text.index('static void_fn original_choice_update;'):text.index('static int choice_named(')]
        harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef void (*void_fn)(void);
typedef int void_regs;
static unsigned char memory[0x30000];
#define ADDR(a) (memory+(a))
#define MEM32(a) (*(uint32_t *)ADDR(a))
static uint32_t g_ecx=0x1000;
static int calls,appended;
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static uint32_t read32(uint32_t p){return void_vm_readable(p,4)?MEM32(p):0;}
static void void_regs_save(void_regs *r){*r=123;}
static void void_regs_load(void_regs *r){assert(*r==123);}
static uint32_t void_galloc(uint32_t n){assert(n==65536);return 0x10000;}
static uint32_t void_call_guest(uint32_t f,int n,const uint32_t *a,int pops){assert(f==0xD119FC&&n==5&&!pops&&a[0]==0x3000);return 0x4000;}
static uint32_t void_call_guest_this(uint32_t f,uint32_t o,int n,const uint32_t *a){
 if(f==0x4A6740){assert(o==0x1088&&!n);return MEM32(0x1088);}
 if(f==0x4C7430){assert(o==0x2118&&!n);return 0x6000;}
 assert(f==0x40E960&&o==0x5008&&n==2&&a[1]-a[0]==24);
 static const uint16_t result[]={'N','m','<','b','r','>','<','b','r','>','I','f'};
 assert(!memcmp(ADDR(a[0]),result,sizeof result));++appended;return 0;
}
static void original(void){++calls;}
#include "choice_info_actual.h"
int main(void){
 original_choice_update=original;MEM32(0x1088)=0x2000;MEM32(0x1098)=0x3000;MEM32(0x4024)=0x5000;MEM32(0x5000)=0xE4E754;
 MEM32(0x5008)=0x7000;MEM32(0x500c)=0x7004;MEM32(0x6000)=0x7100;MEM32(0x6004)=0x7104;
 const uint16_t title[]={'N','m'},desc[]={'I','f'};memcpy(ADDR(0x7000),title,sizeof title);memcpy(ADDR(0x7100),desc,sizeof desc);
 choice_update();assert(calls==1&&appended==1);
 MEM32(0x1088)=0;choice_update();assert(calls==2&&appended==1);
 MEM32(0x1088)=0x2000;MEM32(0x6004)=0xffffffff;choice_update();assert(appended==1);
 puts("PASS hero information: original localized title and specialization text, random hero and invalid range guards");
}
'''
        compile_probe('scenario-choice-info',harness,{'choice_info_actual.h':code})

    def test_swipes_selection_and_screen_lifetime(self):
        for edition in ('toe', 'vanilla', 'hof'):
            with self.subTest(edition=edition):
                self.swipes(edition)

    def swipes(self, edition):
        source=ROOT/'android/host/touch_engine.c'
        addresses={}
        if edition!='toe':
            source,_=port_patches.adapt_host_source(source,ROOT/'build/tests'/('scenario-choice-'+edition),edition)
            addresses=json.loads((ROOT/'config'/(edition+'.patches.json')).read_text(encoding='utf-8'))['addresses']
        text=source.read_text()
        code=text[text.index('static int choice_named('):text.index('\nstatic void ui_event')]
        defines='#define CAST_VA 0x%su\n#define RTTI_WINDOW 0x%su\n#define ROOT_OFFSET 0x%X\n'%(
            addresses.get('00D119FC','00D119FC'),addresses.get('00F2DA88','00F2DA88'),0xA0 if edition=='toe' else 0x98)
        harness=defines+r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#define SCREEN_MENU 0
#define VLOG(...) ((void)0)
static unsigned char memory[0x20000];
#define ADDR(a) (memory+(a))
#define MEM32(a) (*(uint32_t *)ADDR(a))
#define MEMF(a) (*(float *)ADDR(a))
#define MEM8(a) memory[a]
static uint32_t scratch=0x18000,screen=0x1000,pick=0x4000;
static uint64_t touch_frame=10;
static struct {uint32_t screen,root,row,icon,left,right;uint64_t frame;} choice;
static struct {uint32_t screen,root;int kind,active,panning,held,pressed,committed,retiring;float start_x,start_y;uint64_t release_frame;} gesture;
static unsigned down,up,shown,hide,hover;static float clicked_x;
static uint32_t read32(uint32_t p){return p<sizeof memory-4?MEM32(p):0;}
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static uint32_t window_placement(uint32_t w){return w?read32(w+0x140):0;}
static uint32_t object_method(uint32_t o,unsigned slot){return o&&slot==0x44?1:0;}
static uint32_t void_call_guest_this(uint32_t f,uint32_t o,int n,const uint32_t *a){assert(f==1&&o==0x7044&&n==1);if(*a)++shown;else++hide;return 0;}
static uint32_t current_screen(void){return screen;}
static int same_screen(void){return screen==gesture.screen;}
static uint32_t ui_pick(uint32_t s,float x,float y){assert(s==screen);(void)x;(void)y;return pick;}
static uint32_t void_call_guest(uint32_t f,int n,const uint32_t *a,int pops){assert(f==CAST_VA&&n==5&&!pops&&a[3]==RTTI_WINDOW);return a[0];}
static uint32_t logical_point(float x,float y){MEMF(scratch)=x;MEMF(scratch+4)=y;return scratch;}
static uint32_t ui_point_call(uint32_t s,unsigned method,uint32_t point,uint32_t button){
 assert(s==screen&&point==scratch);if(method==0x18){++down;clicked_x=MEMF(point);assert(button==1);}
 else if(method==0x1c){++up;assert(button==1);}else{assert(method==0x24);++hover;}return 0;
}
#include "choice_actual.h"
static void window(uint32_t w,uint32_t p,const char *name,float x){
 MEM32(w+0x140)=p;MEM32(p+0x58)=p+0x200;MEM32(p+0x5c)=p+0x200+(uint32_t)strlen(name);strcpy((char *)ADDR(p+0x200),name);
 MEM8(p+0x70)=1;MEMF(p+0xa4)=55;MEMF(p+0xa8)=55;MEMF(w+0x64)=x;MEMF(w+0x68)=100;MEM32(w+0x28)=0x3000;
}
int main(void){
 gesture.screen=screen;gesture.root=0x2000;MEM32(screen+ROOT_OFFSET)=0x2000;
 window(0x4000,0xa000,"heroicon",100);window(0x5000,0xb000,"hero_change_left",40);
 window(0x6000,0xc000,"hero_change_right",170);window(0x7000,0xd000,"PortChoiceSelection",100);
 MEM32(0x30a4)=0x8000;MEM32(0x30a8)=0x800c;MEM32(0x8000)=0x4000;MEM32(0x8004)=0x5000;MEM32(0x8008)=0x6000;
 MEM32(0x40a4)=0x8100;MEM32(0x40a8)=0x8104;MEM32(0x8100)=0x7000;
 MEM32(0x7010)=0xe000;MEM32(0xe008)=0x34;
 assert(choice_begin(125,125)&&shown==1&&choice.icon==0x4000);
 gesture.start_x=125;gesture.start_y=125;gesture.panning=1;
 assert(choice_end(25,125)&&down==1&&up==1&&clicked_x==197.5f&&gesture.committed);
 touch_frame+=2;choice_pump();assert(MEMF(scratch)==127.5f&&MEMF(scratch+4)==127.5f);
 assert(choice_begin(125,125)&&hide==1);assert(choice_end(225,125)&&down==2&&clicked_x==67.5f);
 assert(choice_end(130,250)&&down==2);gesture.held=1;assert(choice_end(25,125)&&down==2);
 screen=0x1100;choice_pump();assert(!choice.icon&&hide==1);
 screen=gesture.screen;pick=0;assert(!choice_begin(0,0));
 puts("PASS scenario choices: both swipe directions, active frame, persistent tooltip centre, vertical/held guards and screen lifetime");return 0;
}
'''
        compile_probe('scenario-choice-'+edition,harness,{'choice_actual.h':code})

if __name__=='__main__': unittest.main()
