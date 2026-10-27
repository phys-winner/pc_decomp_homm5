"""Keep the prediction text inside the journal border painted by the ATB bar."""
from pathlib import Path
import sys
import unittest

from test_d3d_lifecycle import function
from test_legacy_font_aspect import body
from test_static_tls import compile_probe
from test_town_title_layout import SPECS as LEGACY

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_windows
import port_patches
import prepare_windows_runtime


class BattleLogAnchorTest(unittest.TestCase):
    def test_actual_placement_keeps_text_with_the_left_atb_group(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        compiler, _, _ = build_windows.compiler_environment()
        specs = {'toe': dict(LAYOUT=0xA50560, AXIS=0xA4D630, INVALIDATE=0xA4F710,
                             HALF=0xE0AB70, JUMP=0xA4D6F0, LOW=0xA4D640,
                             CENTER=0xA4D651, HIGH=0xA4D6A6, MARGIN=0xA4D6BD), **LEGACY}
        for edition, spec in specs.items():
            with self.subTest(edition=edition):
                adapted, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_scale.c',
                                                           ROOT / 'build/tests/battle-log-' / edition, edition)
                scale = adapted.read_text()
                helpers = '\n'.join(function(scale, name) for name in (
                    'static float scale_native_position(', 'static float scale_size(',
                    'static float scale_anchor_shift(', 'static int scale_named(', 'static void scale_place('))
                helpers = ('static struct {uint32_t screen;} viewport;\n'
                           'static int void_vm_readable(uint32_t a,uint32_t n) '
                           '{return a>=0x100&&(uint64_t)a+n<=sizeof memory;}\n'
                           'static uint32_t scale_read32(uint32_t a) {return MEM32(a);}\n') + helpers
                actual = '\n'.join(body(edition, spec[key]).replace(f'void sub_{spec[key]:08X}(',
                                     'void ' + label + '(')
                                   for key, label in (('LAYOUT', 'window_layout'), ('AXIS', 'axis_layout')))
                fixture = (ROOT / 'tests/fixtures/town_title_layout_probe.c').read_text()
                fixture = fixture[:fixture.index('static const float original[10]')]
                fixture = fixture.replace('/* STATE */', state).replace('/* SCALE */', helpers)
                fixture = fixture.replace('/* ACTUAL */', actual)
                fixture = fixture.replace('float parent_x,float width', 'float parent_x,float parent_y,float width')
                fixture = fixture.replace('MEMF(0x8004)=0;', 'MEMF(0x8004)=parent_y;')
                fixture = fixture.replace('MEMF(0x800C)=height;', 'MEMF(0x800C)=parent_y+height;')
                battle = (0xE1DA84 if edition == 'toe' else
                          int(port_patches.load_contract(edition)['addresses']['00E1DA84'], 16))
                defines = ''.join(f'#define {key} 0x{value:X}u\n' for key, value in spec.items())
                defines += '#define VISIBLE 0xDEAD1000u\n#define PLACEMENT 0xDEAD1004u\n'
                defines += f'#define BATTLE 0x{battle:X}u\n'
                fixture += r'''
static void anchor(const float row[10],const char *name,uint32_t screen,float origin,
                   float frame_w,float view_w,float view_h,float result[4]) {
 memset(memory,0,sizeof memory);
 MEM32(0x3058)=0x4000;MEM32(0x305C)=0x4000+(uint32_t)strlen(name);
 memcpy(GPTR(0x4000),name,strlen(name));
 MEM32(0x309C)=(uint32_t)row[0];MEM32(0x3094)=(uint32_t)row[1];
 MEMF(0x3088)=row[2];MEMF(0x308C)=row[3];MEMF(0x30A4)=row[4];MEMF(0x30A8)=row[5];
 MEMF(0x30B0)=row[6];MEMF(0x30B4)=row[7];MEMF(0x30BC)=row[8];MEMF(0x30C0)=row[9];
 viewport.screen=0x6000;MEM32(viewport.screen)=screen;
 float parent[4]={origin,0,origin+frame_w,768},position[2],size[2],shift[2];
 scale_place(0x3000,parent,parent,view_w,view_h,position,size,shift);
 float old_y=scale_anchor_shift((uint32_t)row[1],position[1],size[1],0,768,view_h);
 assert(shift[1]==old_y&&size[0]==row[4]&&size[1]==row[5]);
 place(row,origin+shift[0],shift[1],frame_w,768,result);
}
int main(void) {
 const float prediction[10]={0,2,174,-11,604,43,0,0,0,0};
 const float atb[10]={0,2,21,-9,766,162,0,0,0,0};
 const float widths[]={3414,1707,1024,1014.6341552734375f,967.44183349609375f,853.5f,832};
 for(unsigned n=0;n<sizeof widths/sizeof widths[0];++n)for(unsigned offset=0;offset<2;++offset) {
  float view=widths[n],frame=fmaxf(1024,view),origin=(float)offset*10,box[4],bar[4],other[4];
  float height=view*1080/2340;
  anchor(prediction,"PredictionBox",BATTLE,origin,frame,view,height,box);
  anchor(atb,"ATBBar",BATTLE,origin,frame,view,height,bar);
  assert(box[0]-bar[0]==153&&box[0]+14>=bar[0]+153);
  assert(box[2]==604&&box[3]==43&&bar[2]==766&&bar[3]==162);
  /* A native child keeps its14-point inset and21-point glyph window. */
  const float text[10]={0,0,14,7,532,21,0,0,0,0};float child[4];
  place(text,box[0],box[1],box[2],box[3],child);
  assert(child[0]==box[0]+14&&child[1]==box[1]+7&&child[2]==532&&child[3]==21);
  anchor(prediction,"OtherPanel",BATTLE,origin,frame,view,height,other);
  float old_x=origin+174+scale_anchor_shift(0,origin+174,604,origin,origin+frame,view);
  assert(other[0]==old_x);
  anchor(prediction,"PredictionBox",BATTLE+4,origin,frame,view,height,other);assert(other[0]==old_x);
  if(view==967.44183349609375f&&!offset)assert(child[0]==188&&old_x+14==160);
 }
 puts("PASS native battle journal: UI50/100/200+adaptive172, all3engines, coherentATB/textX, originalY/size/childinsets, unrelatedscreens/panels unchanged, RET4/x87/registers");
}
'''
                flags = ['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function']
                compile_probe('battle-log-anchor-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=flags, compiler_override=compiler)
                # The literal old centre heuristic must reproduce the reported leftward text.
                mutant = fixture.replace('shift[0] = -frame[0];',
                                         'shift[0] = scale_anchor_shift(0,position[0],size[0],frame[0],frame[2],view_w);')
                self.assertNotEqual(mutant, fixture)
                with self.assertRaisesRegex(AssertionError, r'box\[0\]-bar\[0\]==153'):
                    compile_probe('battle-log-old-centre-' + edition, defines + mutant, {'runtime.h': runtime},
                                  extra_flags=flags, compiler_override=compiler)


if __name__ == '__main__':
    unittest.main()
