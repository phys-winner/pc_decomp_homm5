"""Execute complete original all3 ScalingTexture::Draw; no product edits."""
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_fmod_latency import FLAGS, COMPILER
from test_fmod_stream import HARNESS

runtime = (ROOT / 'android/runtime/recomp_types.h').read_text(encoding='utf8')
runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', '')
runtime = runtime.replace(function(runtime, 'static inline uint64_t __rdtsc('), '')
prefix = HARNESS[:HARNESS.index('static uint64_t clock_ns')].replace('memory[0x11070000]', 'memory[0x1100000]')
prefix += '#define ARG(i) MEM32(g_esp+4u+4u*(i))\n'
checks = r'''
static float destination[4],source_rect[4];
static unsigned records,draws;
static float f(uint32_t address) {float v;memcpy(&v,(const void *)ADDR(address),4);return v;}
static void put(uint32_t address,float value) {memcpy((void *)ADDR(address),&value,4);}
void READY(void) {assert(g_ecx==0x10024);g_eax=0x20000;g_esp+=4;}
void TEXTURE(void) {assert(g_ecx==0x1002C);g_eax=0x30000;g_esp+=4;}
void COLOR(void) {g_eax=0xFFFFFFFF;g_esp+=8;}
void RECORD(void) {
  ++records;
  for(unsigned i=0;i<4;++i)destination[i]=f(g_esp+4u+4u*i);
  for(unsigned i=0;i<4;++i)source_rect[i]=f(ARG(4)+4*i);
  g_esp+=28;
}
void TRANSFORM(void) {g_esp+=4;}
void FREE(void) {assert(0);}
static void renderer_draw(void) {
 assert(g_ecx==0x40000&&ARG(0)==0x30000&&ARG(1)==3);++draws;g_esp+=16;
}
recomp_func_t void_resolve(uint32_t target) {assert(target==0x70000);return renderer_draw;}
/* ACTUAL ORIGINAL DRAW */
static void run(float source_width,float source_height) {
 memset(memory,0,sizeof memory);records=draws=0;
 g_fp_top=0;g_enter_idx=g_icall_trace_idx=0;g_flag_k=FK_NONE;
 g_ecx=0x10000;g_esp=0x50000;MEM32(g_esp)=0xCAFE;MEM32(g_esp+4)=0x40000;
 g_esi=0x12345678;g_edi=0x23456789;g_ebx=0x34567890;
 put(0x10010,20);put(0x10014,30);put(0x10018,254);put(0x1001C,64);
 MEM32(0x10020)=0x1234;MEM32(0x1002C)=0x30000;
 put(0x10034,source_width);put(0x10038,source_height);
 MEM32(0x3005C)=122;MEM32(0x30060)=34;
 MEM32(0x40000)=0x41000;MEM32(0x41018)=0x70000;
 DRAW();
 assert(records==1&&draws==1&&g_esp==0x50008&&g_fp_top==0);
 assert(g_esi==0x12345678&&g_edi==0x23456789&&g_ebx==0x34567890);
 assert(destination[0]==20&&destination[1]==30&&destination[2]==234&&destination[3]==34);
 assert(source_rect[0]==0&&source_rect[1]==0);
 assert(source_rect[2]==(source_width?source_width:122));
 assert(source_rect[3]==(source_height?source_height:34));
}
int main(void) {
 run(UI_XML_SIZE,34);
 /* Sampling must stay within the original122x34 texture while target remains234x34. */
 assert(source_rect[2]==122&&source_rect[3]==34);
 run(0,0);assert(source_rect[2]==122&&source_rect[3]==34);
 run(234,34);assert(source_rect[2]==234&&destination[2]==234);
 puts("PASS original all3 ScalingTexture Draw:234 destination,122 texture source;Size0 fallback;Size234 reproduces oversampling;callee GP/RET4 preserved");
}
'''

editions = [
    ('toe', 'generated/game-x86/game_0610.c', '00BD58C0',
     ['00BD5AD0','006710A0','00A4C8C0','00486A00','00B297A0','00879240']),
    ('vanilla', 'generated/vanilla/game-x86/game_0541.c', '00ABEF70',
     ['00ABF180','00634330','00411230','00412140','004110C0','00C00360']),
    ('hof', 'generated/hof/game-x86/game_0507.c', '00A35070',
     ['00A35280','004870A0','007D9E20','004A1BB0','00B04830','00A99C10']),
]
class NativeScaledBackgroundTest(unittest.TestCase):
    def test_original_draw_source_and_destination_in_all_editions(self):
        for edition, file, draw, aliases in editions:
            body = function((ROOT / file).read_text(encoding='utf8'), 'void sub_' + draw + '(')
            harness = checks.replace('/* ACTUAL ORIGINAL DRAW */', body)
            for role, address in zip(['READY','TEXTURE','COLOR','RECORD','TRANSFORM','FREE'], aliases):
                harness = harness.replace(role, 'sub_' + address)
            harness = harness.replace('DRAW()', 'sub_' + draw + '()')
            compile_probe('native_scaled_background_' + edition, '#define UI_XML_SIZE 122\n' + prefix + harness,
                          {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            try:
                compile_probe('native_scaled_background_bad_' + edition, '#define UI_XML_SIZE 234\n' + prefix + harness,
                              {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            except AssertionError as error:
                assert 'source_rect[2]==122' in str(error), str(error)
                print('PASS old XML Size234 negative control:', edition)
            else:
                raise AssertionError('Old XML source extent unexpectedly passed: ' + edition)


if __name__ == "__main__":
    unittest.main()
