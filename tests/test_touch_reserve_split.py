"""Exercise reserve splitting through the original combat controller ABI."""
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


class ReserveSplitTest(unittest.TestCase):
    def test_placement_zones_do_not_require_ui_drag(self):
        source = (ROOT / 'android/host/touch_engine.c').read_text()
        code = function(source, 'static uint32_t split_zone_count(')
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint32_t memory[0x10000/4], slots[7];
#define MEM32(a) memory[(a)/4]
#define MEM8(a) ((unsigned char *)memory)[(a)]
static struct { int active,panning,cancelled,placement,dnd_pressed; uint32_t screen,dnd; } gesture;
typedef struct { unsigned index; } troop_cell;
static int idle=1,current=1;
static int same_screen(void){return current;}
static int ui_idle(void){return idle;}
static uint32_t read32(uint32_t a){assert(a<sizeof memory);return MEM32(a);}
static int void_vm_readable(uint32_t a,uint32_t n){return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *a){
 assert(va==0x576200&&self==0x2000&&n==1&&a[0]<7);return slots[a[0]];
}
static int dnd_identity(uint32_t a){(void)a;return 0;}
static int dnd_held(uint32_t a){(void)a;return 0;}
static int troop_cell_window(uint32_t a,troop_cell *c){(void)a;(void)c;return 0;}
static int troop_count(troop_cell *c,uint32_t *n,uint32_t *t){(void)c;(void)n;(void)t;return 0;}
static uint32_t troop_row_window(troop_cell *c,unsigned i){(void)c;(void)i;return 0;}
#include "zones_actual.h"
int main(void){
 gesture.active=gesture.placement=1;gesture.screen=0x1000;
 MEM32(0x1488)=0x2000;MEM32(0x12E0)=0x1000;
 MEM8(0x206C)=1;MEM32(0x2038)=4;MEM32(0x202C)=0x3000;MEM32(0x2030)=0x301C;
 slots[4]=0x5000;MEM32(0x5008)=56;
 assert(!gesture.panning&&split_zone_count()==56);
 for(unsigned i=0;i<7;++i)slots[i]=0x5000;
 assert(!split_zone_count());slots[6]=0;
 assert(split_zone_count()==56);
 MEM32(0x5008)=1;assert(!split_zone_count());MEM32(0x5008)=56;
 MEM32(0x2038)=7;assert(!split_zone_count());MEM32(0x2038)=4;
 MEM8(0x206C)=0;assert(!split_zone_count());MEM8(0x206C)=1;
 idle=0;assert(!split_zone_count());idle=1;
 current=0;assert(!split_zone_count());current=1;
 gesture.cancelled=1;assert(!split_zone_count());gesture.cancelled=0;
 gesture.placement=0;assert(!split_zone_count());
 puts("PASS placement zones: native pickup needs no UI panning; empty slot, count, ownership and idle guards");
}
'''
        compile_probe('placement-split-zones', harness, {'zones_actual.h': code})

    def test_native_controller_and_contact_guards(self):
        source = (ROOT / 'android/host/touch_engine.c').read_text()
        code = function(source, 'static void placement_cancel(') + '\n' + function(source, 'static int placement_second(')
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define VLOG(...) ((void)0)
static uint32_t split_amount = 1;
#define SCREEN_COMBAT 2
#include "touch.h"
static unsigned char memory[0x10000];
#define MEM32(a) (*(uint32_t *)(memory+(a)))
#define MEM8(a) memory[(a)]
static struct {int placement,kind,cancelled,second_troop,committed,world_hover,details;
 uint32_t screen;float start_x,start_y,x,y;} gesture;
static int current=1,valid=1,commits,dialogs,cancels,allocations;
static uint32_t validated,chosen;
static uint32_t created[10];
static int same_screen(void){return current;}
static uint32_t read32(uint32_t p){return p<sizeof memory-4?MEM32(p):0;}
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static int placement_reserve_slot(float x,float y){return y==100&&x>=0&&x<7?(int)x:-1;}
static uint32_t object_query(uint32_t p,unsigned slot){assert(p==0x7000&&slot==12);return valid;}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *a,int pops){
 assert(va==0x878FD0&&n==1&&a[0]==0x50&&!pops);++allocations;return 0x7000;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *a){
 if(va==0x576200){assert(self==0x2000&&n==1);return a[0]<7?MEM32(0x4000+a[0]*4):0;}
 if(va==0x4DB320){assert(self>=0x5000&&n==0);return 0x8000;}
 if(va==0x57A350){assert(self==0x7000&&n==10);memcpy(created,a,sizeof created);return self;}
 if(va==0x63EE50){assert(self==0x2080&&n==1&&a[0]==0x7000);return 0;}
 if(va==0x57A1A0){assert(self==0x7000&&n==1);validated=a[0];return valid;}
 if(va==0x576260){assert(self==0x2000&&!n);++cancels;return 0;}
 if(va==0x57A290){assert(self==0x7000&&n==1&&a[0]==validated);chosen=a[0];++commits;return 0;}
 if(va==0x587CF0){assert(self==0x7000&&!n);return 0x9000;}
 assert(va==0x66D290&&self==0x1000&&n==1&&a[0]==0x9000);++dialogs;return 0;
}
#include "reserve_actual.h"
static void reset(void){
 memset(memory,0,sizeof memory);memset(&gesture,0,sizeof gesture);
 gesture.placement=1;gesture.kind=SCREEN_COMBAT;gesture.screen=0x1000;
 gesture.start_y=gesture.y=100;MEM32(0x12E0)=0x1000;MEM32(0x1488)=0x2000;MEM8(0x209C)=1;
 MEM32(0x202C)=0x3000;MEM32(0x2030)=0x301C;MEM32(0x4000)=0x5000;
 MEM32(0x5008)=12;MEM32(0x501C)=8;
 current=valid=1;commits=dialogs=cancels=allocations=0;chosen=validated=0;
}
static int second(int kind,float x,float y){void_touch_event e={.kind=kind,.x=x,.y=y};return placement_second(&e,-1);}
int main(void){
 reset();assert(second(TOUCH_SECOND_BEGIN,3,100));assert(!allocations);
 MEM32(0x2038)=0;MEM8(0x206C)=1;
 assert(second(TOUCH_SECOND_TAP,3,100)&&commits==1&&cancels==1&&gesture.committed&&chosen==1);
 assert(MEM32(0x2038)==UINT32_MAX); /* The next DOWN starts a pickup, not the previous selection's drop. */
 assert(created[0]==0x2000&&created[1]==0x8000&&created[2]==0x8000&&created[3]==8&&created[4]==8);
 assert(created[5]==12&&!created[6]&&!created[7]&&created[8]==1&&created[9]==1);
 MEM32(0x4004)=0x5100;MEM32(0x5108)=1;MEM32(0x511C)=8;
 assert(second(TOUCH_SECOND_TAP,4,100)&&commits==2&&created[8]==2);
 for(unsigned i=2;i<7;i++)MEM32(0x4000+i*4)=0x5200;
 assert(second(TOUCH_SECOND_TAP,4,100)&&commits==2&&allocations==2);
 reset();second(TOUCH_SECOND_BEGIN,3,100);MEM32(0x5008)=1;
 second(TOUCH_SECOND_TAP,3,100);assert(!allocations);
 reset();second(TOUCH_SECOND_BEGIN,3,100);second(TOUCH_SECOND_TAP,3,200);assert(!allocations);
 gesture.x=1;assert(!second(TOUCH_SECOND_TAP,3,100)&&!allocations);
 reset();second(TOUCH_SECOND_BEGIN,3,100);valid=0;second(TOUCH_SECOND_TAP,3,100);assert(!commits&&!cancels);
 reset();second(TOUCH_SECOND_BEGIN,3,100);second(TOUCH_SECOND_HOLD,0,100);assert(!allocations);
 second(TOUCH_SECOND_HOLD,3,100);assert(dialogs==1&&!commits&&gesture.cancelled&&created[8]==3);
 reset();MEM32(0x4004)=0x5100;MEM32(0x5108)=2;MEM32(0x511C)=9;
 second(TOUCH_SECOND_BEGIN,1,100);second(TOUCH_SECOND_HOLD,1,100);assert(!allocations);
 current=0;assert(!second(TOUCH_SECOND_TAP,3,100));
 reset();MEM8(0x209C)=0;assert(!second(TOUCH_SECOND_BEGIN,3,100));
 reset();MEM32(0x12E0)=0x80;assert(!second(TOUCH_SECOND_BEGIN,3,100));
 reset();gesture.start_y=gesture.y=200;gesture.second_troop=1;MEM8(0x206C)=1;MEM32(0x2038)=0;
 void_touch_event zone={.kind=TOUCH_SECOND_TAP,.x=400,.y=50};
 split_amount=6;assert(placement_second(&zone,0)&&commits==1&&created[5]==12&&created[8]==1&&chosen==6);
 split_amount=1;MEM8(0x206C)=0;assert(!placement_second(&zone,0));
 MEM8(0x206C)=1;assert(!placement_second(&zone,1)&&!placement_second(&zone,7));
 puts("PASS reserve split: native constructor, validation, one-unit repeats, full row, last unit, contact ownership, modal and combat-state guards");
}
'''
        compile_probe('touch-reserve-split', harness,
                      {'reserve_actual.h': code, 'touch.h': (ROOT / 'android/host/touch.h').read_text()})


if __name__ == '__main__':
    unittest.main()
