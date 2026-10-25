"""Exercise actual army gestures with delayed native orders and ownership limits."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_touch_troop_split import fixture


EXTRA = r'''
static int army_test_mode,army_pending,army_sent,army_denied,army_mutate_validate,army_same_player;
static uint32_t army_args[6],army_amount,army_source_min,army_target_min;
static uint32_t army_stack(unsigned row,unsigned index) { return 0xB0000+row*0x1000+index*0x100; }
static void army_set(unsigned row,unsigned index,uint32_t type,uint32_t count) {
    uint32_t stack=army_stack(row,index);MEM32(0x91000+row*0x2000+index*4)=count?stack:0;
    MEM32(stack+0x1C)=type;MEM32(stack+0x20)=count;
}
static uint32_t army_count(unsigned row,unsigned index) {
    uint32_t stack=MEM32(0x91000+row*0x2000+index*4);return stack?MEM32(stack+0x20):0;
}
static uint32_t army_spy(uint32_t va,uint32_t self,int n,const uint32_t *args) {
    if(!army_test_mode)return UINT32_MAX;
    if(va==0x812880) {assert(self==0x70000&&!n&&MEM32(0x60100)!=0xE4775C&&!army_pending);MEM32(self+0xC)=0;return 0;}
    if(va==0x410028) {
        assert(self==0x6044&&n==2);float x=MEMF(args[0]),y=MEMF(args[0]+4);
        if(troop_overlay)return 0x6900;
        if(x>700&&x<800&&y>300&&y<450)return y>370?0xB8100:0xB8000;
    }
    if(va==0x813DE0) {
        float x=MEMF(args[0]),y=MEMF(args[0]+4);
        if(x>700&&x<800&&y>300&&y<450)return 0;
    }
    if(va==0x786E20 || va==0x6BD740) {
        if(va==0x786E20){assert(self==0xA4400&&g_edx==0xA4500&&n==6);memcpy(troop_args,args,24);}
        else {assert(self==0x10140&&!n&&MEM32(self)==0xA4400&&MEM32(self+4)==0xA4500&&MEM32(self+32)==77);memcpy(troop_args,ADDR(self+8),24);}
        ++troop_creates;uint32_t occupied=0,vector=MEM32(troop_args[0]+0x100);
        for(unsigned i=0;i<7;++i)if(MEM32(vector+4*i)&&MEM32(MEM32(vector+4*i)+0x20))++occupied;
        army_source_min=(troop_args[2]&&troop_args[2]!=troop_args[5]&&occupied<2)?1:0;
        if(troop_change_on_create)mock_screen=0x5000;
        return 0xA5000;
    }
    if(va==0x7868B0) {assert(self==0xA5000&&!n);return army_source_min;}
    if(va==0x7868C0) {assert(self==0xA5000&&!n);return army_target_min;}
    if(va==0x786AF0) {
        assert(self==0xA5000&&n==1);++troop_validates;
        if(army_mutate_validate)army_set(0,0,5,21);
        if(troop_change_on_validate)mock_screen=0x5000;
        return 0xABCD00u|(uint32_t)!army_denied;
    }
    if(va==0x786B70) {
        assert(self==0xA5000&&n==1&&!army_pending&&troop_validates>army_sent);
        memcpy(army_args,troop_args,24);army_amount=args[0];army_pending=1;++army_sent;return 0;
    }
    if(va==0x6C1B90) {assert(self==0x4000&&!n);return (uint32_t)army_same_player;}
    if(va==0x490048) {assert(!n&&(self==0xA4200||self==0xA4300));return self==0xA4200?0x90000:0x92000;}
    return UINT32_MAX;
}
'''

CASES = r'''
static void army_reset(int hero) {
    troop_reset();army_test_mode=army_same_player=1;
    army_pending=army_sent=army_denied=army_mutate_validate=0;army_target_min=0;
    MEM32(0xE4002C)=0x7868B0;MEM32(0xE40030)=0x7868C0;
    MEM32(0x42A0)=0xB8000;MEM32(0x42A4)=0xB8100;
    MEM32(0xB8000)=MEM32(0xB8100)=0xAD400;
    for(unsigned r=0;r<2;++r)for(unsigned i=0;i<7;++i)army_set(r,i,0,0);
    army_set(0,0,5,23);
    if(hero) {
        MEM32(0x4000)=0xE3584C;MEM8(0x44B8)=0;MEM8(0x41B8)=1;MEM32(0x41BC)=1;
        MEM32(0x41B0)=0xA4200;MEM32(0x41B4)=0xA4300;MEM32(0x4758)=77;
        MEM32(0x41A4)=0xA4500;MEM32(0x41A8)=0xA4400;
        MEM32(0x44E8)=0xB8000;MEM32(0x4600)=0xB8100;
        MEM32(0x453C)=0xB9000;MEM32(0x4540)=0xB9054;MEM32(0x4654)=0xB9100;MEM32(0x4658)=0xB9154;
        MEM32(0xA4200)=MEM32(0xA4300)=0xBE000;MEM32(0xBE048)=0x490048;
        for(unsigned r=0;r<2;++r)for(unsigned i=0;i<7;++i) {
            uint32_t provider=0xBC000+r*0x1000+i*0x40;
            MEM32(0xB9000+r*0x100+12*i)=provider;MEM32(provider+4)=0xBF000;
            MEM32(0xBF008)=0x80000+r*0x1000+i*0x100-provider-4;
            /* Each provider's vbtable has its own offset. */
            MEM32(provider+4)=provider+0x20;MEM32(provider+0x28)=0x80000+r*0x1000+i*0x100-provider-4;
        }
    }
    event(TOUCH_BEGIN,100,400);
}
static void army_apply(void) {
    assert(army_pending);
    unsigned sr=army_args[0]==0x92000,tr=army_args[3]==0x92000;
    uint32_t source=MEM32(0x91000+sr*0x2000+4*army_args[1]);
    uint32_t total=army_count(sr,army_args[1])+army_count(tr,army_args[4]);
    uint32_t type=MEM32(source+0x1C);
    assert(army_amount<=total);
    army_set(sr,army_args[1],type,total-army_amount);army_set(tr,army_args[4],type,army_amount);army_pending=0;
}
static troop_cell army_cell(unsigned row,unsigned index) {
    troop_cell cell;assert(troop_cell_window(0x80000+row*0x1000+index*0x100,&cell));return cell;
}
static void army_finish(void) {
    for(unsigned i=0;i<20&&army_batch.mode;++i){if(army_pending)army_apply();void_touch_ui_pump();}
    assert(!army_batch.mode&&!army_pending&&troop_pins==troop_unpins);
}
static void army_tests(void) {
    troop_cell source,target;
    for(int hero=0;hero<2;++hero) {
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,1);
        assert(army_sent==1&&army_amount==22&&army_pending&&army_count(0,0)==23);
        for(int i=0;i<5;++i)void_touch_ui_pump();assert(army_sent==1); /* No speculative duplicate. */
        army_finish();assert(army_count(0,0)==1&&army_count(1,0)==22);
        army_reset(hero);army_set(0,1,6,9);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,1);army_finish();
        assert(army_sent==1&&army_count(0,1)==9&&army_count(1,0)==23);
        army_reset(hero);army_set(0,1,5,7);army_set(0,2,6,3);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,0);army_finish();
        assert(army_sent==3&&army_count(0,2)==1&&army_count(1,0)==30&&army_count(1,1)==2);
        army_reset(hero);army_set(0,1,5,7);army_set(0,2,6,3);source=army_cell(0,0);
        army_start(ARMY_COLLECT,&source,&source,0);army_finish();
        assert(army_sent==1&&army_count(0,0)==30&&!army_count(0,1)&&army_count(0,2)==3);
        army_reset(hero);army_set(0,1,5,1);army_set(0,2,6,3);army_set(0,3,5,7);source=army_cell(0,0);
        army_start(ARMY_BALANCE,&source,&source,0);army_finish();
        assert(army_count(0,1)==1&&army_count(0,2)==3);
        for(unsigned i=0;i<7;++i)if(i!=1&&i!=2)assert(army_count(0,i)==6);
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);army_denied=1;
        army_start(ARMY_TRANSFER,&source,&target,1);assert(!army_sent&&!army_batch.mode&&army_count(0,0)==23);
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,0);mock_now_ns+=6000000000ull;void_touch_ui_pump();assert(!army_batch.mode&&army_sent==1);
        army_pending=0;
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);army_set(0,1,6,10);
        army_start(ARMY_TRANSFER,&source,&target,0);army_apply();army_set(1,0,8,23);void_touch_ui_pump();assert(!army_batch.mode&&army_sent==1);
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);army_mutate_validate=1;
        army_start(ARMY_TRANSFER,&source,&target,1);assert(!army_sent&&!army_batch.mode);
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);troop_change_on_validate=1;
        army_start(ARMY_TRANSFER,&source,&target,1);assert(!army_sent&&!army_batch.mode&&troop_pins==troop_unpins);
        army_reset(hero);source=army_cell(0,0);target=army_cell(1,0);army_target_min=30;
        army_start(ARMY_TRANSFER,&source,&target,1);assert(!army_sent&&!army_batch.mode&&!troop_validates);
        army_reset(hero);army_set(0,1,5,7);
        event(TOUCH_HOLD_BEGIN,100,400);event(TOUCH_SECOND_BEGIN,200,400);event(TOUCH_SECOND_HOLD,200,400);
        assert(army_sent==1&&army_amount==15&&!dnd_held(0x60000));army_apply();
        assert(army_count(0,0)==15&&army_count(0,1)==15);
        army_reset(hero);event(TOUCH_PAN,900,500);event(TOUCH_END,900,500);
        assert(army_sent==1&&!dnd_drops&&dnd_cancels==1&&!dnd_held(0x60000)&&!drag_owner.helper&&!MEM32(0x7000C));army_finish();assert(army_count(1,0)==22);
        army_reset(hero);army_set(0,1,5,7);event(TOUCH_PAN,900,400);event(TOUCH_END,900,400);
        assert(army_sent==1&&!dnd_drops&&dnd_cancels==1&&!dnd_held(0x60000)&&!drag_owner.helper&&!MEM32(0x7000C));army_finish();assert(army_count(0,0)==30);
        army_reset(hero);event(TOUCH_HOLD_BEGIN,100,400);event(TOUCH_HOLD_DRAG,900,400);event(TOUCH_END,900,400);
        army_finish();assert(army_count(0,0)==4&&army_count(0,6)==3);
        army_reset(hero);event(TOUCH_ABORT,100,400);event(TOUCH_BEGIN,900,400);
        assert(gesture.army_portrait);event(TOUCH_HOLD_BEGIN,900,400);event(TOUCH_HOLD_DRAG,900,500);event(TOUCH_END,900,500);
        assert(army_sent==1&&!dnd_pickups&&!dnd_drops);army_finish();
        army_reset(hero);army_set(0,1,6,9);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,0);army_apply();event(TOUCH_BEGIN,100,400);void_touch_ui_pump();assert(army_sent==1&&!army_batch.mode);
        army_reset(hero);army_set(0,1,6,9);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,0);army_apply();event(TOUCH_END,100,400);event(TOUCH_ABORT,100,400);
        void_touch_ui_pump();assert(army_sent==1&&!army_batch.mode);
        army_reset(hero);army_set(0,0,5,1);source=army_cell(0,0);target=army_cell(1,0);
        army_start(ARMY_TRANSFER,&source,&target,1);assert(!army_sent&&army_count(0,0)==1);
    }
    army_reset(1);army_same_player=0;assert(!troop_cell_window(0x80000,&source));
    army_reset(1);MEM32(0x41BC)=2;assert(!troop_cell_window(0x80000,&source));
    army_reset(1);MEM8(0x41B8)=0;assert(!troop_cell_window(0x81000,&source));
    army_reset(1);MEM32(0x4540)=0xB9053;assert(!troop_cell_window(0x80000,&source));
    army_reset(0);troop_overlay=1;event(TOUCH_PAN,900,500);event(TOUCH_END,900,500);assert(!army_sent);
    puts("PASS actual army gestures: town/hero, delayed native commands, single/all transfer, merge, balanced distribution, pair balance, last unit, custom minima, queue acknowledgement/timeout, modal/player/tab guards");
}
'''


def army_fixture():
    source = fixture().replace('static uint32_t troop_call(', EXTRA+'\nstatic uint32_t troop_call(', 1)
    source = source.replace('    if(va==0x410028) {assert(self==0x6044',
                            '    {uint32_t out=army_spy(va,self,n,args);if(out!=UINT32_MAX)return out;}\n    if(va==0x410028) {assert(self==0x6044', 1)
    source = source.replace('int main(void) {\n    troop_tests();', 'static int legacy_main(void) {\n    troop_tests();', 1)
    return source + CASES + '\nint main(void){army_tests();return 0;}\n'


class ArmyTest(unittest.TestCase):
    def test_native_army_gestures(self):
        source = (ROOT/'android/host/touch_engine.c').read_text().replace('#include "host.h"','').replace('#include "touch.h"','').replace('#include "input.h"', '')
        compile_probe('touch_army', army_fixture(), {'touch_engine_actual.h':source,'touch.h':(ROOT/'android/host/touch.h').read_text()})

    def test_native_validation_and_acknowledgement_are_required(self):
        source = (ROOT/'android/host/touch_engine.c').read_text().replace('#include "host.h"','').replace('#include "touch.h"','').replace('#include "input.h"', '')
        for name, before, after in (
            ('validation','(void_call_guest_this(validate,controller,1,&destination)&0xFFu)','1'),
            ('acknowledgement','if (army_batch.waiting) {','if (0 && army_batch.waiting) {'),
            ('custom_minimum','destination>=target_minimum','destination>=target_minimum*0u'),
            ('single_transfer','army_batch.limit=source->index+1;','army_batch.limit=7;'),
        ):
            self.assertIn(before, source)
            with self.subTest(name=name), self.assertRaises(AssertionError) as error:
                compile_probe('touch_army_'+name,army_fixture(),{'touch_engine_actual.h':source.replace(before,after,1),'touch.h':(ROOT/'android/host/touch.h').read_text()})
            self.assertIn('Assertion failed:', str(error.exception))


if __name__ == '__main__':
    unittest.main()
