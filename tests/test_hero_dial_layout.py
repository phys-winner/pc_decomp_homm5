"""The real five-button hero dial must follow the viewport's bottom-right edge."""
import copy
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

from test_d3d_lifecycle import function
from test_legacy_ui import generated_body
from test_legacy_widescreen import Resources
from test_static_tls import compile_probe
from test_town_title_layout import SPECS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_windows
from editions import game_directory
import port_ui
import prepare_windows_runtime


class HeroDialLayoutTest(unittest.TestCase):
    def test_actual_resources_and_native_layout_keep_the_hero_dial_at_the_bottom_right(self):
        reference = game_directory('toe')
        if not reference.is_dir():
            self.skipTest('Original ToE resources unavailable')
        name = 'UI/Common/JogDial/JogDial.xdb'
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        scale = function((ROOT / 'android/host/touch_scale.c').read_text(), 'static float scale_anchor_shift(')
        compiler, _, _ = build_windows.compiler_environment()
        self.assertEqual(port_ui.legacy_widescreen(reference, reference, 'toe', {}), {})
        for edition, spec in SPECS.items():
            with self.subTest(edition=edition), ExitStack() as stack:
                game = game_directory(edition)
                if not game.is_dir():
                    self.skipTest('Original game resources unavailable')
                changes = port_ui.legacy_widescreen(game, reference, edition, {})
                original = Resources(stack, game, edition)
                patched = Resources(stack, game, edition, changes)
                root = original.node('UI/UIGameRoot.(UIGameRoot).xdb')
                callers = [item for item in root.iter('Item') if item.findtext('ID') == 'JOG_DIAL_5BUTTONS']
                self.assertEqual(len(callers), 1)
                self.assertEqual(callers[0].find('Window').get('href'),
                                 'Common/JogDial/JogDial.xdb#xpointer(/WindowSimple)')
                self.assertIn(name, changes)
                before, after = original.row(name), patched.row(name)
                self.assertEqual(before[:6], [0, 0, 800, 565, 203, 176])
                self.assertEqual(after[:6], [2, 2, -21, -27, 203, 176])
                # Native actions, child buttons, style and texture bindings stay original.
                old, new = copy.deepcopy(original.node(name)), copy.deepcopy(patched.node(name))
                old.remove(old.find('Placement'))
                new.remove(new.find('Placement'))
                self.assertEqual(ET.tostring(old), ET.tostring(new))
                bodies = []
                for key, label in (('LAYOUT', 'window_layout'), ('AXIS', 'axis_layout')):
                    address = spec[key]
                    bodies.append(generated_body(edition, address).replace(f'void sub_{address:08X}(', 'void ' + label + '('))
                defines = ''.join(f'#define {key} 0x{value:X}u\n' for key, value in spec.items())
                defines += '#define VISIBLE 0xDEAD1000u\n#define PLACEMENT 0xDEAD1004u\n'
                # Reuse the bounded native CWindow::Layout spy, with this dial's
                # real resource geometry and independent edge assertions.
                fixture = (ROOT / 'tests/fixtures/town_title_layout_probe.c').read_text()
                fixture = fixture[:fixture.index('int main(void)')] + r'''
int main(void) {
 float old[4],now[4];place(original,0,1024,768,old);place(centered,0,1024,768,now);
 for(unsigned n=0;n<4;++n)assert(old[n]==now[n]);
 assert(old[0]==800&&old[1]==565&&old[2]==203&&old[3]==176);
 const float scales[]={.5f,1,2};
 for(unsigned n=0;n<3;++n){
  float view=1707/scales[n],height=768/scales[n],frame=fmaxf(1024,view),fh=fmaxf(768,height);
  place(centered,0,frame,fh,now);
  float x=scale_anchor_shift(2,now[0],now[2],0,frame,view);
  float y=scale_anchor_shift(2,now[1],now[3],0,fh,height);
  place(centered,x,frame,fh,now);now[1]+=y;
  assert(fabsf(now[0]+now[2]-(view-21))<=.51f);
  assert(fabsf(now[1]+now[3]-(height-27))<=.51f);
  assert(now[2]==203&&now[3]==176);
  place(original,0,frame,fh,old);
  assert(fabsf(old[0]+old[2]-(view-21))>100);
 }
 puts("PASS original native hero JogDial layout: unchanged4:3, bottom-right UI50/100/200, original bindings, RET4/x87/registers");
}
'''
                fixture = fixture.replace('/* STATE */', state).replace('/* SCALE */', scale)
                fixture = fixture.replace('/* ACTUAL */', '\n'.join(bodies))
                old_row = ','.join(str(float(value)) + 'f' for value in before)
                new_row = ','.join(str(float(value)) + 'f' for value in after)
                fixture = fixture.replace('/* ORIGINAL */', old_row).replace('/* CENTERED */', new_row)
                flags = ['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function']
                compile_probe('hero-dial-layout-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=flags, compiler_override=compiler)
                negative = fixture.replace('static const float centered[10]={' + new_row + '}',
                                           'static const float centered[10]={' + old_row + '}')
                with self.assertRaisesRegex(AssertionError, 'fabsf'):
                    compile_probe('hero-dial-old-low-' + edition, defines + negative, {'runtime.h': runtime},
                                  extra_flags=flags, compiler_override=compiler)


if __name__ == '__main__':
    unittest.main()
