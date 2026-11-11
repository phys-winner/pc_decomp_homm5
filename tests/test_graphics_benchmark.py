"""The original graphics benchmark must time completed GPU work in each edition."""
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
import build_android
import port_patches


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
static uint32_t g_eax, g_esp;
static int device, *g_d3d_device=&device;
#define D3D_OK 0u
static unsigned submitted, pending, completed, syncs, waits, resumes;
static int threaded, on_render, machine_held=1;
static void d3d_rt_wait_begin(void) {
    ++waits;
    if (!on_render) { assert(machine_held); machine_held=0; }
}
static void d3d_rt_wait_end(void) {
    ++resumes;
    if (!on_render) { assert(!machine_held); machine_held=1; }
}
static void glFinish(void) {
    assert(!machine_held && submitted && waits==resumes+1);
    completed+=pending; pending=0;
}
static void d3d_rt_sync(void (*fn)(void *), void *args) {
    assert(!args && machine_held && !on_render);
    ++syncs; ++submitted; pending+=2;
    if (threaded) { machine_held=0; on_render=1; }
    fn(args);
    assert(!pending && waits==resumes);
    if (threaded) { machine_held=1; on_render=0; }
}
#include "actual.h"
int main(void) {
    for (threaded=0; threaded!=2; ++threaded) {
        for (unsigned sample=0; sample!=18; ++sample) {
            g_eax=0x1234; g_esp=0x1000;
            WRAPPER();
            assert(g_eax==D3D_OK && g_esp==0x1004);
            assert(machine_held && !on_render && !pending);
            assert(completed==syncs*2 && submitted==syncs && waits==syncs && resumes==syncs);
        }
    }
    g_d3d_device=NULL; g_eax=0x5678; g_esp=0x2000;
    WRAPPER();
    assert(g_eax==D3D_OK && g_esp==0x2004 && syncs==36 && waits==36);
    puts("PASS graphics calibration: submitted GPU work completed before each timing sample, render-thread and inline paths, balanced machine wait and guest return");
}
'''


class GraphicsBenchmarkTest(unittest.TestCase):
    def test_native_wait_and_edition_routing(self):
        source = ROOT / 'android/host/d3d9_gl.c'
        for edition, address in (('toe', '00C308B0'), ('vanilla', '00B21310'), ('hof', '00AC6A70')):
            with self.subTest(edition=edition):
                path, _ = port_patches.adapt_host_source(source, ROOT / 'build/tests/graphics_benchmark' / edition, edition)
                text = path.read_text(encoding='utf-8')
                name = 'sub_' + address
                actual = function(text, 'static void run_benchmark_sync(') + '\n' + function(text, 'void ' + name + '(')
                compile_probe('graphics_benchmark_' + edition, HARNESS.replace('WRAPPER', name), {'actual.h': actual})
                self.assertIn(name, port_patches.native_overrides(edition, build_android.NATIVE_OVERRIDES))

    def test_original_helpers_are_the_benchmark_buffer_lock_barrier(self):
        # Independently identified original functions: no parameters, buffer Lock(0,0,&p,0)/Unlock, RET.
        for edition, unit, address, sampler_unit, sampler in (
            ('toe', 'game_0639.c', '00C308B0', 'game_0453.c', '009D2DF0'),
            ('hof', 'game_0553.c', '00AC6A70', 'game_0596.c', '00B51470'),
            ('vanilla', 'game_0580.c', '00B21310', 'game_0422.c', '0092E680'),
        ):
            with self.subTest(edition=edition):
                folder = ROOT / 'generated' / ('' if edition=='toe' else edition) / 'game-x86'
                if not (folder / unit).is_file():
                    self.skipTest('Original generated engine fixtures are unavailable')
                original = function((folder / unit).read_text(), 'void sub_' + address + '(')
                self.assertIn('RECOMP_ICALL(MEM32(ecx + 0x2C))', original)
                self.assertIn('RECOMP_ICALL(MEM32(ecx + 0x30))', original)
                self.assertEqual(original.count('PUSH32(esp, 0);'), 3)
                self.assertRegex(original, r'RECOMP_FLAGS_OUT\(\); esp \+= 4;')
                sample = function((folder / sampler_unit).read_text(), 'void sub_' + sampler + '(')
                self.assertEqual(sample.count('RECOMP_CALL(sub_' + address + ')'), 2)
                self.assertIn('= 5;', sample)


if __name__ == '__main__':
    unittest.main()
