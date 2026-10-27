"""Run the real placement functions against migrated legacy UI resources."""
import copy
from contextlib import ExitStack
from pathlib import Path
import posixpath
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
from editions import game_directory
import port_ui

MODES = {'EPA_LOW_END': 0, 'ERA_CENTER': 1, 'EPA_HIGH_END': 2, 'EPA_MARGIN': 3}


class Resources:
    def __init__(self, stack, folder, edition, overlay=None):
        self.files, self.cache = {}, {}
        self.overlay = {name.lower(): data for name, data in (overlay or {}).items()}
        for pak in reversed(port_ui.resource_archives(edition)):
            path = folder / pak
            if path.is_file():
                archive = stack.enter_context(zipfile.ZipFile(path))
                for name in archive.namelist():
                    self.files[name.lower()] = (archive, name)

    def node(self, name):
        name = name.lower()
        if name not in self.cache:
            archive, original = self.files[name]
            self.cache[name] = ET.fromstring(self.overlay.get(name, archive.read(original)))
        return self.cache[name]

    def value(self, name, field):
        node = self.node(name)
        value = node.find('Placement/' + field)
        shared = node.find('Shared')
        if value.findtext('Second') == 'true' or shared is None or not shared.get('href'):
            return value.find('First')
        link = shared.get('href').split('#', 1)[0]
        parent = link.lstrip('/') if link.startswith('/') else posixpath.normpath(posixpath.dirname(name) + '/' + link)
        return self.value(parent, field)

    def row(self, name):
        return [MODES[self.value(name, field).text] for field in ('HorAllign', 'VerAllign')] + [
            float(self.value(name, field).findtext(axis))
            for field in ('Position', 'Size', 'LowerMargin', 'UpperMargin') for axis in ('x', 'y')]


def native_harness(before, after, checks):
    source = (ROOT / 'android/host/touch_scale.c').read_text()
    helpers = '\n'.join(function(source, signature) for signature in (
        'static float scale_native_position(', 'static float scale_size(',
        'static int scale_near(', 'static float scale_anchor_shift('))
    # C float constants need a decimal point even when XML used integer spelling.
    def c_rows(values):
        return ',\n'.join('{' + ','.join(str(float(v)) + 'f' for v in row) + '}' for row in values)
    return r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
/* HELPERS */
static const float before[][10]={/* BEFORE */};
static const float after[][10]={/* AFTER */};
static void place(const float *row,float width,float height,float *out) {
 for(int axis=0;axis<2;++axis) {
  out[axis+2]=scale_size((uint32_t)row[axis],axis?height:width,row[4+axis],row[6+axis],row[8+axis]);
  out[axis]=scale_native_position((uint32_t)row[axis],0,axis?height:width,row[2+axis],row[6+axis],out[axis+2]);
 }
}
int main(void) {
 for(unsigned i=0;i<sizeof before/sizeof before[0];++i) {
  float a[4],b[4];place(before[i],1024,768,a);place(after[i],1024,768,b);
  for(int n=0;n<4;++n)assert(fabsf(a[n]-b[n])<.001f);
 }
 /* CHECKS */
 puts("PASS native legacy UI placement: unchanged 4:3 bounds, dynamic edges/centres and fixed control/font geometry");
}
'''.replace('/* HELPERS */', helpers).replace('/* BEFORE */', c_rows(before)).replace('/* AFTER */', c_rows(after)).replace('/* CHECKS */', checks)


class LegacyWidescreenTest(unittest.TestCase):
    def test_native_oracle_rejects_the_original_fixed_4_3_button(self):
        before = [[0, 0, 913, 694, 57, 57, 0, 0, 0, 0]]
        after = [[2, 2, -54, -17, 57, 57, 0, 0, 0, 0]]
        check = 'float box[4];place(after[0],1707,768,box);assert(box[0]+box[2]==1707-54);'
        compile_probe('legacy-widescreen-control', native_harness(before, after, check), {})
        with self.assertRaisesRegex(AssertionError, '1707-54'):
            compile_probe('legacy-widescreen-original-negative', native_harness(before, before, check), {})

    def test_actual_original_corpus_keeps_bindings_and_4_3_geometry(self):
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition), ExitStack() as stack:
                try:
                    game, reference = game_directory(edition), game_directory('toe')
                except (FileNotFoundError, ValueError):
                    self.skipTest('Original resource configuration unavailable')
                if not game.is_dir() or not reference.is_dir():
                    self.skipTest('Original game resources unavailable')
                with tempfile.TemporaryDirectory() as missing_reference:
                    with self.assertRaisesRegex(ValueError, 'widescreen reference resource'):
                        port_ui.legacy_widescreen(game, Path(missing_reference), edition, {})
                changed = port_ui.legacy_widescreen(game, reference, edition, {})
                original = Resources(stack, game, edition)
                patched = Resources(stack, game, edition, changed)
                before, after, names = [], [], []
                for name, data in changed.items():
                    a, b = copy.deepcopy(original.node(name)), ET.fromstring(data)
                    a.remove(a.find('Placement'))
                    b.remove(b.find('Placement'))
                    self.assertEqual(ET.tostring(a), ET.tostring(b), name)
                    before.append(original.row(name))
                    after.append(patched.row(name))
                    names.append(name)
                self.assertGreater(len(changed), 150)
                checks = []
                for name in ('UI/AdventureScreen-Heavy.(WindowScreen).xdb', 'UI/TownScreen.(WindowScreen).xdb',
                             'UI/HeroScreen3.(WindowScreen).xdb', 'UI/CombatScreen-Heavy.(WindowScreen).xdb',
                             'UI/MainMenu2.(WindowScreen).xdb'):
                    index = names.index(next(n for n in names if n.lower() == name.lower()))
                    self.assertEqual(after[index][:2], [3, 3], name)
                    checks.append('float root' + str(index) + '[4];place(after[' + str(index) + '],1707,768,root' + str(index) + ');assert(root' + str(index) + '[0]==0&&root' + str(index) + '[2]==1707);')
                # These are the exact visible controls from the device screenshots.
                targets = {
                    'UI/AdventureScreen-heavy/OnJog-Menu.(WindowMSButton).xdb': 2,
                    'UI/AdventureScreen-heavy/resource-bar-heavy.(WindowSimple).xdb': 1,
                    'UI/AdventureScreen-heavy/Minimap-heavy.(WindowSimple).xdb': 0,
                }
                for name, mode in targets.items():
                    key = next(n for n in names if n.lower() == name.lower()) if mode else name
                    old, new = original.row(key), patched.row(key)
                    self.assertEqual(new[0], mode)
                    if mode:
                        index = names.index(key)
                        checks.append('''
 {const float scales[]={.5f,1,2};for(unsigned k=0;k<3;++k) {
   float view=1707/scales[k],height=768/scales[k],frame=fmaxf(1024,view),fh=fmaxf(768,height);
   float box[4],base[4];place(after[%d],frame,fh,box);place(after[%d],1024,768,base);
   box[0]+=scale_anchor_shift((uint32_t)after[%d][0],box[0],box[2],0,frame,view);
   assert(box[2]==base[2]&&box[3]==base[3]);
   assert(fabsf((box[0]-base[0])-(view-1024)*%s)<1.1f);
 }}''' % (index, index, index, '1' if mode == 2 else '.5f'))
                modal = 'UI/SetFirstProfileName/SetFirstProfileName.(WindowScreen).xdb'
                self.assertEqual(patched.row(modal)[0], 1)
                index = next(i for i, n in enumerate(names) if n.lower() == modal.lower())
                checks.append('float dialog[4];place(after[' + str(index) + '],1707,768,dialog);assert(fabsf(dialog[0]+dialog[2]*.5f-853.5f)<=.5f);')
                compile_probe('legacy-widescreen-' + edition, native_harness(before, after, '\n'.join(checks)), {})


if __name__ == '__main__':
    unittest.main()
