"""Exercise touch expansion through the original forced-tooltip/provider ABI."""
import re
import unittest

from test_static_tls import ROOT, compile_probe
from test_touch_engine import HARNESS


NATIVE = r'''
static uint32_t nt_eax,nt_ebx,nt_ecx,nt_edx,nt_esi,nt_edi,nt_esp;
#define RECOMP_REGS_LOCALS
#define RECOMP_REGS_OUT()
#define RECOMP_ENTER(x) ((void)(x))
#define RECOMP_FLAGS_IN()
#define RECOMP_FLAGS_OUT()
#define FK_NONE 0
#define FK_CMP 1
#define FK_TEST 2
#define FK_ADD 3
#define FK_NARROW(a,b) (a)
#define CMP_B(a,b) ((uint32_t)(a)<(uint32_t)(b))
#define TEST_Z(a,b) (!((a)&(b)))
#define TEST_NZ(a,b) (((a)&(b))!=0)
#define LO8(x) ((x)&255u)
#define SET_LO8(x,v) ((x)=((x)&0xFFFFFF00u)|((v)&255u))
#define PUSH32(s,v) do{uint32_t push_value=(v);(s)-=4;MEM32(s)=push_value;}while(0)
static uint32_t nt_pop(uint32_t *s){uint32_t v=MEM32(*s);*s+=4;return v;}
#define POP32_VAL(s) nt_pop(&(s))
#define RECOMP_CALL(f) do{PUSH32(nt_esp,0xABCD);f();}while(0)
#define RECOMP_ITAIL(va) nt_provider(va)
static int nt_updates,nt_details;

/* Model only the picker/display leaf: 8863A0 repicks the owner at tracker+8/+C.
   The root interface, two-pass force ordering, liveness test and provider
   dispatch below execute the game's generated functions without modification. */
static void nt_008863A0(void) {
    assert(nt_ecx==0x6008&&MEM32(nt_esp+8)==0x5F08&&MEM32(nt_esp+12)==1);
    ++nt_updates;
    if(MEMF(nt_ecx+8)==91&&MEMF(nt_ecx+12)==173) {
        MEM32(nt_ecx+4)=0x110000;
        MEM32(nt_ecx)=nt_details ? 0x116000 : 0x115000;
    } else {
        MEM32(nt_ecx)=MEM32(nt_ecx+4)=0;
    }
    nt_esp+=16;
}
static void nt_provider(uint32_t method) {
    assert(method==0x114000&&nt_ecx==0x111000&&nt_updates==1);
    ++nt_details;nt_esp+=4;
}
void nt_008867D0(void);
void nt_00A4E160(void);
#include "native_tooltip_actual.h"

static void native_inspect(uint32_t self,const uint32_t *args) {
    nt_updates=nt_details=0;
    MEM32(0x110010)=0x113000;MEM32(0x113004)=0;MEM8(0x110017)=0;
    MEM32(0x110024)=0x111000;MEM32(0x111000)=0x112000;MEM32(0x112004)=0x114000;
    MEM32(self+8)=0x115000;MEM32(self+12)=0x110000;MEM32(self+0x24)=0;
    nt_ecx=self;nt_ebx=0x1234;nt_esi=0x5678;nt_edi=0xABCD;nt_esp=0x120000;
    MEM32(nt_esp)=0;MEM32(nt_esp+4)=args[0];MEM32(nt_esp+8)=args[1];
    nt_00487A80();
    assert(nt_esp==0x12000C&&nt_ebx==0x1234&&nt_esi==0x5678&&nt_edi==0xABCD);
    assert(nt_updates==2&&nt_details==1&&MEM32(self+8)==0x116000&&MEM32(self+12)==0x110000);
}
'''


TRANSPARENT_POPUP = r'''
    /* A shown tooltip is deliberately absent from the interactive UI picker. */
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    MEM32(0x6008)=0x115000;MEM32(0x115000)=MEM32(0x116000)=0x118000;MEM32(0x11805C)=0xAC15C0;
    assert(!ui_pick(gesture.screen,900,250));
    event(TOUCH_SECOND_BEGIN,900,250);assert(gesture.second_info&&gesture.held&&!gesture.panning);
    event(TOUCH_SECOND_TAP,900,250);assert(inspections==1&&gesture.inspecting&&!downs&&!ups&&!commands);
    event(TOUCH_SECOND_BEGIN,920,260);event(TOUCH_SECOND_HOLD,920,260);
    assert(inspections==2&&gesture.held&&!downs&&!ups);void_touch_ui_pump();
    assert(MEMF(0x101E0)==91&&MEMF(0x101E4)==173);
    event(TOUCH_END,100,200);assert(!gesture.active);
    /* Being shown is insufficient: the second finger must hit its bounds. */
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);MEM32(0x6008)=0x115000;
    event(TOUCH_SECOND_BEGIN,1000,250);event(TOUCH_SECOND_TAP,1000,250);
    assert(!inspections&&!commands&&!downs&&!ups);
    /* Revalidate when the second finger ends: a vanished popup cannot be used. */
    reset(1);MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);MEM32(0x6008)=0x115000;
    event(TOUCH_SECOND_BEGIN,900,250);assert(gesture.second_info&&gesture.held);
    MEM32(0x6008)=0;event(TOUCH_SECOND_TAP,900,250);
    assert(!inspections&&!commands&&!downs&&!ups);
'''


def fixture():
    source = HARNESS.replace('static uint32_t void_call_guest_this(', NATIVE + '\nstatic uint32_t void_call_guest_this(', 1)
    source = source.replace('if(inspection_changes_screen)mock_screen=0x5000;return 0;',
                            'native_inspect(self,args);if(inspection_changes_screen)mock_screen=0x5000;return 0;', 1)
    source = source.replace('    if(va==0x487A80) {', r'''
    if(va==0xAC15C0) {
        assert((self==0x115000||self==0x116000)&&n==1);
        float x=MEMF(args[0]),y=MEMF(args[0]+4);
        return 0xCCDD00u|(uint32_t)(x>=700&&x<760&&y>=200&&y<300);
    }
    if(va==0x487A80) {''', 1)
    source = source.replace('inspections=inspection_changes_screen=0;MEM32(0x6000)=0;',
                            'inspections=inspection_changes_screen=0;MEM32(0x6000)=MEM32(0x6008)=0;', 1)
    return source.replace('    reset(1);void_touch_event invalid_rotation=',
                          TRANSPARENT_POPUP+'\n    reset(1);void_touch_event invalid_rotation=', 1)


def headers(source):
    functions = []
    for unit, symbol in (('0051', '00487A80'), ('0358', '008867D0'), ('0489', '00A4E160')):
        native = (ROOT / f'generated/game-x86/game_{unit}.c').read_text()
        match = re.search(r'void sub_' + symbol + r'\(void\) \{.*?\n\}', native, re.S)
        assert match, symbol
        body = re.sub(r'\b(eax|ebx|ecx|edx|esi|edi|esp)\b', r'nt_\1', match.group())
        functions.append(body.replace('sub_', 'nt_'))
    return {'native_tooltip_actual.h': '\n'.join(functions),
            'touch_engine_actual.h': source,
            'touch.h': (ROOT / 'android/host/touch.h').read_text()}


class TooltipTest(unittest.TestCase):
    def test_original_forced_tooltip_expands_held_source(self):
        source = (ROOT / 'android/host/touch_engine.c').read_text().replace('#include "host.h"', '').replace('#include "touch.h"', '').replace('#include "input.h"', '')
        compile_probe('touch_tooltip_native', fixture(), headers(source), extra_flags=('/wd4101', '/wd4102', '/wd4189'))

    def test_secondary_point_regression_drops_original_provider(self):
        source = (ROOT / 'android/host/touch_engine.c').read_text().replace('#include "host.h"', '').replace('#include "touch.h"', '').replace('#include "input.h"', '')
        begin = source.index('    else if (gesture.second_info && gesture.held && same_screen())')
        end = source.index('    /* The secondary finger', begin)
        broken = source[begin:end].replace('gesture.x,gesture.y', 'event->x,event->y')
        source = source[:begin] + broken + source[end:]
        with self.assertRaises(AssertionError) as caught:
            compile_probe('touch_tooltip_secondary_mutant', fixture(), headers(source), extra_flags=('/wd4101', '/wd4102', '/wd4189'))
        self.assertIn('nt_updates==2&&nt_details==1', str(caught.exception))

    def test_interactive_picker_regression_rejects_transparent_popup(self):
        source = (ROOT / 'android/host/touch_engine.c').read_text().replace('#include "host.h"', '').replace('#include "touch.h"', '').replace('#include "input.h"', '')
        source = source.replace('tooltip_target_at(event->x,event->y)', 'ui_pick(gesture.screen,event->x,event->y)')
        with self.assertRaises(AssertionError) as caught:
            compile_probe('touch_tooltip_picker_mutant', fixture(), headers(source), extra_flags=('/wd4101', '/wd4102', '/wd4189'))
        self.assertIn('gesture.second_info&&gesture.held&&!gesture.panning', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
