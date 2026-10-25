"""Run the production touch adapter with native Town split/order spies."""
import unittest
import re
from test_static_tls import ROOT, compile_probe
from test_touch_engine import HARNESS

EXTRA = r'''
static int troop_overlay, troop_eligible, troop_validate, troop_modal;
static int troop_creates, troop_validates, troop_commits, troop_dialogs, troop_installs, troop_sounds, troop_pins, troop_unpins;
static int troop_change_on_validate, troop_change_on_create;
static uint32_t troop_args[6];
static unsigned preview_paints,preview_count;
static uint32_t troop_window(float x,float y) {
    if (y<300 || y>450 || x<50 || x>650) return 0;
    unsigned row=y>370, index=(unsigned)((x-51)/80);
    return index<7 ? 0x80000+row*0x1000+index*0x100 : 0;
}
static uint32_t troop_call(uint32_t va,uint32_t self,int n,const uint32_t *args) {
    if(va==0x470200) {assert(self==0x71000&&n==1&&args[0]==0x80000);return 0xA6000;}
    if(va==0x470204) {assert(self==0xAE100&&!n);return 0xAE200;}
    if(va==0x470208) {assert(self==0xAE000&&n==3&&args[0]==0x80000&&args[1]==0xA6000&&args[2]==0xAE200);++preview_paints;preview_count=MEM32(0xA6020);return 0;}
    if(va==0x410028) {assert(self==0x6044&&n==2);return troop_overlay?0x6900:troop_window(MEMF(args[0]),MEMF(args[0]+4));}
    if(va==0x813DE0) {assert(self==0x60000&&n==2&&args[1]==1);return troop_window(MEMF(args[0]),MEMF(args[0]+4))?0x70000:0;}
    if(va==0x470024) {assert(self==0x71000&&n==1);return troop_window(MEMF(args[0]),MEMF(args[0]+4));}
    if(va==0x470100) {assert(self==0xA4000&&!n);return 0xA4100;}
    if(va==0x470104) {assert(self==0xA4100&&n==1&&args[0]<2);return args[0]?0:0xA4200;}
    if(va==0x614160) {assert(self==0x4000&&n==1&&(args[0]==1||args[0]==2));return args[0]==2?0x90000:0x92000;}
    if(va==0x470108) {assert(!n&&(self==0x90000||self==0x92000));return self+0x100;}
    if(va==0x786E20) {
        assert(self==0xA4400&&g_edx==0xA4500&&n==6);
        memcpy(troop_args,args,24);++troop_creates;if(troop_change_on_create)mock_screen=0x5000;return 0xA5000;
    }
    if(va==0x55AF30) {assert(self==0x10190&&n==1&&args[0]==0xA5000&&!MEM32(self));MEM32(self)=args[0];++troop_pins;return self;}
    if(va==0x59F6B0) {assert(self==0x10190&&!n&&MEM32(self)==0xA5000);++troop_unpins;return 0;}
    if(va==0x786800) {assert(self==0xA5000&&!n);return 0xBEEF00u|(uint32_t)troop_eligible;}
    if(va==0x786AF0) {assert(self==0xA5000&&n==1&&args[0]==1);++troop_validates;if(troop_change_on_validate)mock_screen=0x5000;return 0xDEAD00u|(uint32_t)troop_validate;}
    if(va==0x786B70) {
        assert(self==0xA5000&&n==1&&args[0]==1&&troop_validates>troop_commits);
        assert(!dnd_cancels&&dnd_held(0x60000));++troop_commits;
        uint32_t source=MEM32(MEM32(troop_args[0]+0x100)+4*troop_args[1]);
        uint32_t target=MEM32(troop_args[3]+0x100)+4*troop_args[4];
        assert(!MEM32(target)&&source);--MEM32(source+0x20);
        MEM32(target)=0xAA000+0x100*(unsigned)troop_commits;MEM32(MEM32(target)+0x20)=1;
        return 0;
    }
    if(va==0x587CF0) {assert(self==0xA5000&&!n);++troop_dialogs;return troop_modal?0xAB000:0;}
    if(va==0x66D290) {assert(self==0x4000&&n==1&&args[0]==0xAB000&&dnd_cancels==1);++troop_installs;mock_screen=0x5000;return 0;}
    if(va==0x490DB0) {assert(self==0x103FF38&&!n);return 0xAC000;}
    if(va==0x47010C) {assert(!n&&self>=0x80000&&self<0x82000);return 0xAC100;}
    if(va==0x470110) {assert(self==0xAC100&&n==2&&args[0]==0xAC07C&&args[1]>=0x7FF08&&args[1]<0x82000);++troop_sounds;return 0;}
    return UINT32_MAX;
}
'''

SCENARIOS = r'''
static void troop_reset(void) {
    reset_dnd();MEM32(0x4000)=0xE2A64C;MEM32(0x4294)=1;MEM8(0x429C)=MEM8(0x4478)=0;
    memset(&troop_preview,0,sizeof troop_preview);preview_paints=preview_count=0;
    MEM32(0x70008)=0xAE000;MEM32(0x70020)=0xAE100;
    MEM32(0xAE000)=0xAE300;MEM32(0xAE300)=0x470208;
    MEM32(0xAE100)=0xAE400;MEM32(0xAE428)=0x470204;
    MEM32(MEM32(0x71000)+0x28)=0x470200;
    troop_mode=1;troop_overlay=troop_change_on_validate=troop_change_on_create=0;
    troop_eligible=troop_validate=troop_modal=1;
    troop_creates=troop_validates=troop_commits=troop_dialogs=troop_installs=troop_sounds=troop_pins=troop_unpins=0;
    MEM32(0x42A8)=0xA0000;MEM32(0x42B4)=0xA0100;MEM32(0x4220)=0xA4000;
    MEM32(0x4224)=0xA4400;MEM32(0x421C)=0xA4500;
    MEM32(0xA4000)=0xAD000;MEM32(0xAD090)=0x470100;
    MEM32(0xA4100)=0xAD100;MEM32(0xAD100)=0x470104;
    MEM32(0x90000)=MEM32(0x92000)=0xAD200;MEM32(0xAD208)=0x470108;
    MEM32(0x90100)=0x91000;MEM32(0x90104)=0x9101C;MEM32(0x92100)=0x93000;MEM32(0x92104)=0x9301C;
    MEM32(0xA5000)=0xE40014;MEM32(0xE40020)=0x786800;MEM32(0xE40024)=0x786AF0;MEM32(0xE40028)=0x786B70;
    MEM32(0x6001C)=0x70000;MEM32(0x7000C)=0x80000;
    MEM32(0xAC100)=0xAD300;MEM32(0xAD328)=0x470110;
    for(unsigned row=0;row<2;++row)for(unsigned i=0;i<7;++i){
        uint32_t window=0x80000+row*0x1000+i*0x100;MEM32(0xA0000+row*0x100+4*i)=window;
        MEM32(window)=0xAD400;MEM32(0xAD4D8)=0;MEM32(0xAD4DC)=0x47010C;
        MEM32(0x91000+row*0x2000+4*i)=0;
    }
    MEM32(0x91000)=0xA6000;MEM32(0xA6020)=23;
    dnd_down_x=91;dnd_down_y=333;
}
static void troop_begin(int drag) {
    event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
    if(drag)event(TOUCH_HOLD_DRAG,130,402);
    event(TOUCH_SECOND_BEGIN,200,400);
    assert(gesture.x==(drag?130:100)&&gesture.y==(drag?402:400));
    assert(fabsf(MEMF(0x101E0)-(drag?115.0f:91.0f))<0.01f&&fabsf(MEMF(0x101E4)-(drag?334.6f:333.0f))<0.01f);
}
static void troop_tests(void) {
    troop_reset();troop_begin(0);event(TOUCH_SECOND_TAP,200,400);
    MEM32(0xA6020)=23;void_touch_ui_pump();assert(!preview_paints&&troop_preview.helper);
    MEM32(0xA6020)=22;void_touch_ui_pump();assert(preview_paints==1&&preview_count==22&&dnd_held(0x60000));
    void_touch_ui_pump();assert(preview_paints==1);
    event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,200,400);
    void_touch_ui_pump();assert(preview_paints==2&&preview_count==21);
    event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,200,400);
    event(TOUCH_ABORT,100,400);void_touch_ui_pump();assert(preview_paints==2&&!troop_preview.helper);
    troop_reset();troop_begin(0);event(TOUCH_SECOND_TAP,200,400);
    mock_screen=0x5000;void_touch_ui_pump();assert(!preview_paints&&!troop_preview.helper);
    /* A real hand uses two distinct cells; minor held-primary jitter preserves the source. */
    troop_reset();event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
    void_touch_ui_pump();void_touch_ui_pump();
    event(TOUCH_HOLD_DRAG,102,401);
    event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,201,401);
    assert(troop_commits==1&&troop_args[1]==0&&troop_args[4]==1&&dnd_held(0x60000));
    assert(gesture.x==102&&gesture.y==401&&!dnd_cancels);
    troop_reset();troop_begin(0);event(TOUCH_SECOND_TAP,200,400);
    assert(troop_commits==1&&troop_args[0]==0x90000&&troop_args[1]==0&&troop_args[2]==0xA4200);
    assert(troop_args[3]==0x90000&&troop_args[4]==1&&troop_args[5]==0xA4200);
    assert(MEM32(0xA6020)==22&&dnd_held(0x60000)&&!dnd_cancels&&troop_pins==troop_unpins);
    assert(gesture.x==100&&gesture.y==400&&MEMF(0x101E0)==91);
    event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,201,401);
    assert(troop_commits==2&&troop_args[4]==2&&MEM32(0xA6020)==21);
    for(unsigned i=3;i<7;++i){event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,200,400);}
    assert(troop_commits==6&&MEM32(0xA6020)==17);event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,200,400);
    assert(troop_commits==6&&troop_sounds==1&&!dnd_cancels&&dnd_held(0x60000));
    event(TOUCH_ABORT,100,400);assert(!dnd_held(0x60000)&&dnd_cancels==1);
    troop_reset();troop_begin(1);event(TOUCH_HOLD_DRAG,200,400);event(TOUCH_SECOND_TAP,300,400);
    assert(!troop_creates); /* Primary left its original source cell. */
    event(TOUCH_HOLD_DRAG,100,400);
    troop_overlay=1;event(TOUCH_SECOND_TAP,200,400);assert(!troop_creates&&!troop_sounds);troop_overlay=0;
    event(TOUCH_SECOND_TAP,200,400);assert(troop_commits==1);
    troop_reset();troop_begin(0);troop_validate=0;event(TOUCH_SECOND_TAP,100,400);
    assert(troop_creates==1&&troop_validates==1&&!troop_commits&&troop_sounds==1&&troop_pins==troop_unpins&&dnd_held(0x60000));
    troop_reset();troop_begin(0);troop_eligible=0;event(TOUCH_SECOND_TAP,100,400);
    assert(!troop_validates&&!troop_commits&&troop_sounds==1&&troop_pins==troop_unpins);
    troop_reset();troop_begin(0);troop_change_on_validate=1;event(TOUCH_SECOND_TAP,100,400);
    assert(!troop_commits&&troop_pins==troop_unpins&&!troop_sounds);
    troop_reset();troop_begin(0);event(TOUCH_SECOND_HOLD,200,400);
    assert(troop_dialogs==1&&troop_installs==1&&!troop_commits&&troop_pins==troop_unpins&&!dnd_held(0x60000));
    event(TOUCH_SECOND_TAP,200,400);event(TOUCH_END,100,400);assert(troop_dialogs==1&&troop_installs==1&&!troop_commits);
    troop_reset();troop_begin(0);event(TOUCH_SECOND_HOLD,100,400);assert(!troop_creates); /* Occupied source. */
    troop_reset();troop_begin(0);MEM32(0x91004)=0xA6100;MEM32(0xA611C)=99;event(TOUCH_SECOND_HOLD,200,400);assert(!troop_creates);
    troop_reset();troop_begin(0);troop_modal=0;event(TOUCH_SECOND_HOLD,200,400);
    assert(troop_dialogs==1&&!troop_installs&&!dnd_cancels&&dnd_held(0x60000)&&troop_pins==troop_unpins);
    troop_reset();troop_begin(0);event(TOUCH_HOLD_DRAG,100,500);event(TOUCH_SECOND_BEGIN,200,500);event(TOUCH_SECOND_TAP,200,500);
    assert(!troop_commits); /* A source from the hero cannot fast-split over the garrison. */
    event(TOUCH_SECOND_HOLD,200,500);
    assert(troop_dialogs==1&&troop_args[3]==0x92000&&troop_args[4]==1&&!troop_args[5]); /* Quantity dialog still permits a cross-row destination. */
    troop_reset();MEM32(0x7000C)=0x81000;MEM32(0x91000)=0;MEM32(0x93000)=0xA6000;dnd_down_y=413;
    event(TOUCH_BEGIN,100,500);event(TOUCH_HOLD_BEGIN,100,500);
    event(TOUCH_SECOND_BEGIN,200,500);event(TOUCH_SECOND_TAP,200,500);
    assert(troop_commits==1&&troop_args[0]==0x92000&&troop_args[3]==0x92000&&troop_args[4]==1&&!troop_args[5]);
    troop_reset();MEM32(0x4294)=0; /* Army slots remain usable during the native city flyby. */
    event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
    event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,200,400);
    assert(troop_commits==1&&MEM32(0x4294)==0); /* No manual camera initialization. */
    for(unsigned guard=0;guard<4;++guard){
        troop_reset();MEM32(0x4294)=0;
        event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
        if(guard==0)town_blocked=1;
        else if(guard==1)MEM8(0x429C)=1;
        else if(guard==2)MEM8(0x4478)=1;
        else MEM32(0x4F00)=0x4F04;
        event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_TAP,201,401);
        assert(!troop_creates&&!troop_commits&&!dnd_pickups);
    } /* Removing the camera gate must preserve every busy/modal/native eligibility gate. */
    troop_reset();troop_begin(0);event(TOUCH_SECOND_TAP,900,400);assert(!troop_creates&&!troop_sounds&&dnd_held(0x60000));
    event(TOUCH_SECOND_TAP,200,200);assert(!troop_creates&&!troop_sounds&&dnd_held(0x60000)); /* Non-army UI/background never activates. */
    troop_reset();event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
    void_touch_ui_pump();assert(!dnd_downs&&!dnd_pickups);
    event(TOUCH_HOLD_DRAG,130,402);assert(dnd_downs==1&&dnd_pickups==1&&gesture.dnd_pressed&&gesture.held);
    event(TOUCH_SECOND_BEGIN,280,400);event(TOUCH_SECOND_TAP,281,401);assert(troop_commits==1);
    event(TOUCH_END,130,402);assert(!gesture.active&&dnd_drops==1&&!dnd_held(0x60000));
    troop_reset();troop_begin(0);event(TOUCH_TWO_FINGER_BEGIN,100,400);event(TOUCH_SECOND_TAP,100,400);
    assert(!troop_creates&&!dnd_held(0x60000)&&dnd_cancels==1);
    troop_reset();troop_begin(0);event(TOUCH_HOLD_DRAG,200,400);assert(gesture.x==200&&dnd_moves>=2);
    event(TOUCH_END,200,400);assert(!gesture.active&&!dnd_held(0x60000)&&dnd_drops==1);
    troop_reset();troop_overlay=1;troop_begin(0);assert(!gesture.second_troop&&!dnd_pickups);
    troop_mode=0;
    puts("PASS troop native splitting: physically separate contacts, held-source/repeat/free/source exclusion/full sound, long-hold drag, flyby-independent army, controller ABI+validation, modal/crossrow UI ownership");
}
'''

CONTROLLER = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char mem[0x20000];
#define MEM32(p) (*(uint32_t *)(mem+(uint32_t)(p)))
static uint32_t eax,ebx,ecx,edx,esi,edi,esp;
#define RECOMP_REGS_LOCALS
#define RECOMP_REGS_OUT()
#define RECOMP_ENTER(x) ((void)(x))
#define RECOMP_FLAGS_IN()
#define RECOMP_FLAGS_OUT()
#define RECOMP_BACKEDGE()
#define FK_NONE 0
#define FK_CMP 1
#define FK_TEST 2
#define FK_ADD 3
#define FK_NARROW(a,b) (a)
#define CMP_B(a,b) ((uint32_t)(a)<(uint32_t)(b))
#define CMP_L(a,b) ((int32_t)(a)<(int32_t)(b))
#define TEST_Z(a,b) (!((a)&(b)))
#define TEST_NZ(a,b) (((a)&(b))!=0)
#define LO8(x) ((x)&255u)
#define SET_LO8(x,v) ((x)=((x)&0xFFFFFF00u)|((v)&255u))
#define PUSH32(s,v) do{uint32_t push_value=(v);(s)-=4;MEM32(s)=push_value;}while(0)
static uint32_t pop(uint32_t *s){uint32_t v=MEM32(*s);*s+=4;return v;}
#define POP32_VAL(s) pop(&(s))
#define RECOMP_CALL(f) do{PUSH32(esp,0xABCD);f();}while(0)
static void indirect(uint32_t va);
#define RECOMP_ICALL(va) do{uint32_t target=(va);PUSH32(esp,0xABCD);indirect(target);}while(0)
static int built,validated,queued,validation_result;
static uint32_t queued_amount,queued_src,queued_dst,queued_src_index,queued_dst_index;
static void sub_00786AA0(void){assert(ecx==0x1000);++built;MEM32(0x5000)=MEM32(esp+4);MEM32(0x5004)=0;eax=0x5000;esp+=8;}
static void sub_004698F0(void){uint32_t cmd=MEM32(ecx);assert(cmd==0x5000&&MEM32(cmd+4)==1);--MEM32(cmd+4);esp+=4;}
static void sub_008C61D0(void){assert(ecx==0x5000&&MEM32(esp+4)==0xFFFFF);esp+=8;}
static void sub_00878FD0(void){assert(MEM32(esp+4)==0x2C);eax=0x5000;memset(mem+0x5000,0,0x2C);esp+=4;}
static void sub_00786ED0(void){
    assert(ecx==0x5000&&MEM32(esp+4)==0x100C);
    queued_src=MEM32(MEM32(esp+8));queued_src_index=MEM32(MEM32(esp+12));
    queued_dst=MEM32(MEM32(esp+16));queued_dst_index=MEM32(MEM32(esp+20));
    queued_amount=MEM32(MEM32(esp+24));
    assert(MEM32(MEM32(esp+28))==0x8100&&MEM32(MEM32(esp+32))==0x8200);
    eax=0x5000;esp+=36;
}
static void indirect(uint32_t va){
    assert(ecx==0x3000);
    if(va==0x6008){assert(MEM32(esp+4)==0x4000&&MEM32(esp+8)==0x5000);++validated;eax=0xF00D00u|(uint32_t)validation_result;esp+=12;}
    else {assert(va==0x6000&&MEM32(esp+4)==0x5000);++queued;esp+=8;}
}
#include "native_split_actual.h"
static uint32_t call(uint32_t amount,int commit){
    uint32_t saved_ebx=0x1234,saved_esi=0x5678,saved_edi=0xABCD;
    ebx=saved_ebx;esi=saved_esi;edi=saved_edi;ecx=0x1000;esp=0x10000;
    MEM32(esp)=0;MEM32(esp+4)=amount;
    if(commit)sub_00786B70();else sub_00786AF0();
    assert(esp==0x10008&&ebx==saved_ebx&&esi==saved_esi&&edi==saved_edi);
    return eax&255u;
}
int main(void){
    MEM32(0x1008)=0x3000;MEM32(0x100C)=0x4000;MEM32(0x1010)=0x2000;
    MEM32(0x101C)=1;MEM32(0x1020)=0;MEM32(0x1028)=23;
    MEM32(0x3000)=0x6000;MEM32(0x6008)=0x6008;MEM32(0x6000)=0x6000;
    MEM32(0x2000)=0x7000;MEM32(0x2004)=2;MEM32(0x2008)=0x8100;
    MEM32(0x200C)=0x7100;MEM32(0x2010)=4;MEM32(0x2014)=0x8200;
    validation_result=1;assert(call(1,0)==1&&built==1&&validated==1&&!queued&&!MEM32(0x5004));
    call(1,1);assert(queued==1&&queued_amount==1&&queued_src==0x7000&&queued_src_index==2&&queued_dst==0x7100&&queued_dst_index==4&&!MEM32(0x5004));
    assert(!call(23,0)&&built==1&&validated==1&&queued==1); /* Keep last original unit. */
    MEM32(0x1020)=2;assert(!call(1,0)&&built==1&&validated==1);
    MEM32(0x1020)=0;validation_result=0;assert(!call(1,0)&&validated==2&&queued==1&&!MEM32(0x5004));
    puts("PASS original split controller bodies: amount is destination count, validation separate from queue, limits, refcleanup and RET4 ABI");return 0;
}
'''


def fixture():
    source = HARNESS.replace('static int force_ui,', 'static int troop_mode;\nstatic int force_ui,').replace('static uint32_t void_call_guest_this(', EXTRA+'\nstatic uint32_t void_call_guest_this(', 1)
    source = source.replace('    if(va==0x6B2830)', '    if(troop_mode){uint32_t out=troop_call(va,self,n,args);if(out!=UINT32_MAX)return out;}\n    if(va==0x6B2830)', 1)
    source = source.replace('if(args[3]==0xF2DA88) {assert(args[0]==0x6044);return 0x6000;}', 'if(args[3]==0xF2DA88) {if(troop_mode&&args[0]>=0x80000&&args[0]<0x82000)return args[0]-0xF8;assert(args[0]==0x6044);return 0x6000;}')
    # The native-held assertion is a memory predicate in a pre-adapter engine spy.
    source = source.replace('dnd_held(0x60000)', '(MEM32(MEM32(0x6000C))==0xE4775C)')
    source = source.replace('int main(void) {', SCENARIOS+'\nint main(void) {\n    troop_tests();', 1)
    return source


class TroopSplitTest(unittest.TestCase):
    def test_missing_native_validation_or_cell_guard_is_rejected(self):
        original=(ROOT/'android/host/touch_engine.c').read_text().replace('#include "host.h"','').replace('#include "touch.h"','').replace('#include "input.h"', '')
        mutants=(
            ('stale_owner','if (!same_screen()) {\n            gesture.active = 0;\n            publish_point(-1, -1);\n            return;\n        }\n        troop_second(event);', 'troop_second(event);'),
            ('no_split','else if (gesture.second_troop) troop_split(', 'else if (gesture.second_troop && event->kind<0) troop_split('),
            ('validation','(void_call_guest_this(validate,controller,1,&one)&0xFFu)','1'),
            ('source_cell','if (primary.window!=source.window) return;',''),
            ('separate_contact','if (primary.window!=source.window) return;','if (primary.window!=source.window || target.window!=primary.window) return;'),
            ('held_drag','if (event->kind == TOUCH_HOLD_DRAG && gesture.dnd && gesture.dnd_claim)', 'if (event->kind == TOUCH_HOLD_DRAG && gesture.dnd_pressed && gesture.dnd && gesture.dnd_claim)'),
            ('camera_gate','if (read32(screen)!=0x00E2A64Cu || !town_army_ready()) return 0;', 'if (read32(screen)!=0x00E2A64Cu || !town_ready()) return 0;'),
            ('full_sound','troop_inactive(primary.window);return;', 'return;'),
        )
        for name,old,new in mutants:
            self.assertIn(old,original)
            with self.subTest(name=name):
                with self.assertRaises(AssertionError) as caught:
                    compile_probe('touch_troop_mutant_'+name,fixture(),{'touch_engine_actual.h':original.replace(old,new,1),'touch.h':(ROOT/'android/host/touch.h').read_text()})
                self.assertIn('Assertion failed:',str(caught.exception))

    def test_original_split_controller(self):
        native=(ROOT/'generated/game-x86/game_0287.c').read_text()
        functions=[]
        for symbol in ('00786AF0','00786B70'):
            match=re.search(r'void sub_'+symbol+r'\(void\) \{.*?\n\}',native,re.S)
            self.assertIsNotNone(match)
            functions.append(match.group())
        compile_probe('touch_troop_controller',CONTROLLER,{'native_split_actual.h':'\n'.join(functions)},extra_flags=('/wd4101','/wd4102','/wd4189'))

    def test_native_town_split_lifecycle(self):
        source = (ROOT/'android/host/touch_engine.c').read_text().replace('#include "host.h"','').replace('#include "touch.h"','').replace('#include "input.h"', '')
        compile_probe('touch_troop_split', fixture(), {'touch_engine_actual.h':source,'touch.h':(ROOT/'android/host/touch.h').read_text()})


if __name__ == '__main__':
    unittest.main()
