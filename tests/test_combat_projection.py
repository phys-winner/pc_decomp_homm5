"""Compare the port's battle lens with the original 16:9 PC projection."""
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import compile_probe
from test_touch_camera import ROUTE_PACKET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_windows
import prepare_windows_runtime


PROBE = ROUTE_PACKET + "\n" + r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
#define ARG(i) MEM32(g_esp+4+4*(i))
typedef void (*void_fn)(void);
typedef struct { unsigned unused; } void_regs;
static void void_regs_save(void_regs *saved) {(void)saved;abort();}
static void void_regs_load(const void_regs *saved) {(void)saved;abort();}
static float observed_rod;
static void sub_007CD0C0(void);
static void fixture_call(uint32_t target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#define RECOMP_CALL(fn) fixture_call((uint32_t)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((uint32_t)(va))
/* NATIVE */
static void fixture_call(uint32_t target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 if(target==0xCF7D90){sub_00CF7D90();return;}
 if(target==0xCF7C30){sub_00CF7C30();return;}
 if(target==0xCF60A0||target==0xCF7AC0){g_esp+=4;return;}
 if(target==0xCF7000){g_esp+=8;return;}
 if(target==0x7CD040){
  observed_rod=MEMF(g_ecx+0x70);
  uint32_t out=MEM32(g_esp+4);memset(GPTR(out),0,64);
  for(int i=0;i<4;++i)MEMF(out+20*i)=1;
  g_eax=out;g_esp+=8;return;
 }
 fprintf(stderr,"unexpected callback %08X\n",target);abort();
}
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static void_fn void_dispatch_find(uint32_t p){return p==0x7CD0C0?sub_007CD0C0:NULL;}
static void void_dispatch_add(uint32_t p,void_fn f){assert(p==0x7CD0C0&&f);}
static uint32_t void_galloc(uint32_t n){(void)n;return 0;}
static uint32_t void_call_guest(uint32_t p,int n,const uint32_t *a,int pop){(void)p;(void)n;(void)a;(void)pop;abort();return 0;}
static uint32_t void_call_guest_this(uint32_t p,uint32_t t,int n,const uint32_t *a){(void)p;(void)t;(void)n;(void)a;abort();return 0;}
static void void_input_screen_size(int *w,int *h){*w=2400;*h=1080;}
static int void_touch_active_mode(void){return 1;}
static float void_port_camera_sensitivity(void){return 1;}
static int option_combat_fit=1;
static int void_port_combat_fit(void){return option_combat_fit;}
static void void_lift_trap(uint32_t p,const char *s){(void)p;fprintf(stderr,"%s",s);abort();}
static int void_verbose;
static void fixture_log(const char *format,...) {(void)format;}
#define VLOG(...) fixture_log(__VA_ARGS__)
#include "camera_impl.h"
static void capture(float w,float h,float fov,float rod,float centre,int patched,float matrix[16]){
 MEM32(0x10000)=0xE1DA84;MEM32(0x100A4)=0x20000;
 MEM32(0x20000)=0xE44224;MEM32(0xE44224+0x2C)=0x7CD040;
 MEMF(0x2005C)=0;MEMF(0x20060)=centre;MEMF(0x20070)=rod;
 MEMF(0x20080)=fov;MEMF(0x20084)=1;MEMF(0x20088)=500;
 MEMF(0xF74BE4)=h;MEMF(0x66000)=w;MEMF(0x66004)=h;
 g_esp=0x70000;g_ecx=0x20000;MEM32(g_esp)=RECOMP_RETADDR;
 MEM32(g_esp+4)=0x30000;MEM32(g_esp+8)=0x66000;
 g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
 fp_set_cw(0x007F);g_fp_sp=128;g_fp_top=0;
 unsigned char before[0x98];memcpy(before,GPTR(0x20000),sizeof before);
 if(patched){void_touch_combat_frame(0x10000,w,h,h-165,0,0);camera_projection();}
 else sub_007CD0C0();
 assert(g_esp==0x7000C&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
 assert(g_fp_top==0&&g_fp_sp==128);
 assert(observed_rod==rod);
 assert(!memcmp(before,GPTR(0x20000),sizeof before));
 memcpy(matrix,GPTR(0x30000),64);
}
static void point(const float m[16],float x,float y,float z,float pixel[2]){
 float w=m[12]*x+m[13]*y+m[14]*z+m[15];assert(w>0);
 pixel[0]=.5f*(1+(m[0]*x+m[1]*y+m[2]*z+m[3])/w);
 pixel[1]=.5f*(1-(m[4]*x+m[5]*y+m[6]*z+m[7])/w);
}
int main(void){
 /* CONSTANTS */
 const float views[][2]={{1024,768},{1366,768},{1707,768},{1365.6f,614.4f},{853.5f,384},{2731,768}};
 const float fovs[]={30,54,80},rods[]={9,21,42};
 for(unsigned f=0;f<3;++f)for(unsigned r=0;r<3;++r)for(unsigned v=0;v<6;++v)for(int enabled=0;enabled<2;++enabled){
  float native[16],actual[16],expected[16];option_combat_fit=enabled;
  float w=views[v][0],h=views[v][1],aspect=w/h;
  capture(w,h,fovs[f],rods[r],.09f,0,native);
  capture(1366,768,fovs[f],rods[r],.09f,0,expected);
  capture(w,h,fovs[f],rods[r],.09f,1,actual);
  if(aspect<=1366.0f/768){assert(!memcmp(native,actual,sizeof actual));continue;}
  /* The real native matrix retains PC vertical positions and pixel size per screen height. */
  for(int i=-3;i<=3;++i){
   float pc[2],phone[2],old[2];point(expected,(float)i,(float)i*.7f,10,pc);
   point(actual,(float)i,(float)i*.7f,10,phone);point(native,(float)i,(float)i*.7f,10,old);
   assert(fabsf(pc[1]-phone[1])<.000002f);
   assert(fabsf((pc[0]-.5f)*1366/768-(phone[0]-.5f)*aspect)<.000002f);
   if(i==3)assert(fabsf(old[1]-pc[1])>.01f);
  }
 }
 const float heights[]={768,614.4f,384};
 for(unsigned v=0;v<3;++v){
  float h=heights[v],w=h*2.2f,native[16],adjusted[16];
  MEM32(0x102E0)=0;void_touch_combat_frame(0,0,0,0,0,0);
  capture(w,h,54,42,.09f,1,native);
  MEM32(0x102E0)=0x80;void_touch_combat_frame(0x10000,w,h,h-125,0,0);
  float ratio=framing.ratio;
  g_esp=0x70000;g_ecx=0x20000;MEM32(g_esp)=RECOMP_RETADDR;
  MEM32(g_esp+4)=0x30000;MEM32(g_esp+8)=0x66000;
  unsigned char before[0x98];memcpy(before,GPTR(0x20000),sizeof before);
  camera_projection();memcpy(adjusted,GPTR(0x30000),64);
  assert(!memcmp(before,GPTR(0x20000),sizeof before)&&observed_rod==42&&g_esp==0x7000C);
  assert(ratio>=1&&fabsf(ratio-fmaxf(1,(1-125.0f/768)*h/(h-125)))<.00001f);
  for(int i=-3;i<=3;++i){
   float a[2],b[2];point(native,(float)i,(float)i*.7f,10,a);point(adjusted,(float)i,(float)i*.7f,10,b);
   assert(fabsf(b[0]-(.5f+(a[0]-.5f)/ratio))<.000002f);
   assert(fabsf(b[1]-a[1]/ratio)<.000002f);
  }
 }
 puts("PASS original lens: PC16:9, exact extra-HUD affine mapping, unchanged camera fields/ABI, UI100/125/200, close-ups and old flag");
}
'''


class CombatProjectionTest(unittest.TestCase):
    def test_original_combined_context_with_nonidentity_camera(self):
        import pefile
        import port_patches
        # Independently verified original projection/context/inverse/multiply
        # methods. ARG0 holds a context, not a returned matrix.
        original = {
            'toe': ('007CD0C0','00CF7D90','00CF7C30','00CF7000','008EBF00','00B71E70','0041F800'),
            'vanilla': ('00760E50','004ABC20','004ABAC0','004AAE60','004A9CC0','004ACCF0','004AC6E0'),
            'hof': ('0075BAE0','009F3C00','009F3AA0','009F2E40','0049B420','0044BBF0','0044AFE0'),
        }
        core = (ROOT / 'android/host/core.c').read_text()
        state = core[core.index('VOID_HIDDEN uint32_t g_eax'):core.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        compiler, _, _ = build_windows.compiler_environment()
        flags = ['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function']
        for edition, methods in original.items():
            with self.subTest(edition=edition):
                folder = ROOT / 'generated' / ('' if edition == 'toe' else edition)
                bodies = {}
                for path in (folder / 'game-x86').glob('game_*.c'):
                    text = path.read_text()
                    for address in methods[:6]:
                        if 'void sub_' + address + '(' in text:
                            bodies[address] = function(text, 'void sub_' + address + '(')
                    if len(bodies) == 6:
                        break
                self.assertEqual(set(bodies), set(methods[:6]))
                native = '\n'.join(bodies[address] for address in methods[:6]).replace('void sub_', 'static void sub_')
                probe = PROBE[:PROBE.index('int main(void){')]
                probe = probe.replace('if(target==0xCF7000){g_esp+=8;return;}', '''
 if(target==0xCF7000){sub_00CF7000();return;}
 if(target==0x8EBF00){sub_008EBF00();return;}
 if(target==0xB71E70){sub_00B71E70();return;}
 if(target==0x41F800){uint32_t n=MEM32(g_esp+4);for(uint32_t i=0;i<n;i++)MEM32(g_ecx+4*i)=g_edx;g_eax=g_edx;g_esp+=8;return;}
''')
                begin = probe.index(' if(target==0x7CD040){')
                end = probe.index(' fprintf(stderr,"unexpected callback', begin)
                probe = probe[:begin] + ''' if(target==0x7CD040){
  observed_rod=MEMF(g_ecx+0x70);uint32_t out=MEM32(g_esp+4);
  const float c=.7071067811865475244f;
  const float world[16]={0,c,c,30, -1,0,0,76, 0,-c,c,32, 0,0,0,1};
  memcpy(GPTR(out),world,64);g_eax=out;g_esp+=8;return;
 }
''' + probe[end:]
                probe += r'''
int main(void){
 /* CONSTANTS */
 const float h=614.4f,w=1365.6f;float perspective[16],actual[2],expected[2],wrong[2];
 MEM32(0x102E0)=0x1000;MEMF(0x20078)=-1.57079632679f;
 memset(GPTR(0x30000),0xA5,0x700);capture(w,h,54,42,0,1,perspective);
 assert(MEM32(0x30400)==2);
 float combined[16];memcpy(combined,GPTR(0x30100),64);
 assert(deployment_projection.valid&&!memcmp(deployment_projection.matrix,combined,64));
 point(deployment_projection.matrix,58,76,2,actual);point(perspective,58,76,2,wrong);
 /* Independently apply inverse of known cameraWorld, then the original P. */
 const float c=.7071067811865475244f,localY=c*(28+30),localZ=c*(28-30);
 expected[0]=.5f;expected[1]=.5f*(1-(perspective[5]*localZ+perspective[6]*localY)/localY);
 assert(fabsf(actual[0]-expected[0])<.00001f&&fabsf(actual[1]-expected[1])<.00001f);
 assert(actual[1]>0&&actual[1]<1&&wrong[1]<-10);
 printf("PASS original transform context depth2: camera inverse/basis/multiply, worldY%.3fpx versus wrong P-only %.3fpx; unchanged camera/RET8 ABI\n",actual[1]*h,wrong[1]*h);
 return 0;
}
'''
                mapping = dict(port_patches.load_contract(edition)['addresses'])
                mapping.update(zip(original['toe'], methods))
                if edition != 'toe':
                    mapping.update(zip(('00CF60A0','00CF7AC0'),
                                       ('004AA110','004AB950') if edition == 'vanilla'
                                       else ('009F20F0','009F3930')))
                    mapping.update({'000100A4':'0001009C',
                                    '000102E0':'000102D8' if edition == 'vanilla' else '000102F0'})
                # Transform fixture addresses before embedding the actual lifted bodies.
                probe = re.sub(r'(0x|sub_)([0-9A-Fa-f]+)',
                    lambda m: m[1] + mapping.get(f'{int(m[2],16):08X}',m[2]), probe)
                image = pefile.PE(str(folder / 'input/H5_Game.exe'))
                constants = []
                for address in sorted(set(int(n,16) for n in re.findall(r'ADDR\(0x([0-9A-F]+)\)',native))):
                    data = image.get_data(address-image.OPTIONAL_HEADER.ImageBase,8)
                    self.assertEqual(len(data),8)
                    constants.append(f'memcpy(GPTR(0x{address:X}),(unsigned char[]){{'+','.join(map(str,data))+'},8);')
                image.close()
                camera_path, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_camera.c',
                    ROOT / 'build/tests' / ('projection-context-' + edition), edition)
                camera = camera_path.read_text()
                for header in ('host.h','input.h','touch.h'):
                    camera = camera.replace(f'#include "{header}"\n','')
                probe = probe.replace('/* STATE */',state).replace('/* NATIVE */',native)
                probe = probe.replace('/* CONSTANTS */','\n'.join(constants))
                compile_probe('projection-context-' + edition,probe,
                    {'runtime.h':runtime,'camera_impl.h':camera},extra_flags=flags,compiler_override=compiler)
                if edition == 'toe':
                    old = 'memcpy(deployment_projection.matrix, GPTR(output + 0x100),'
                    self.assertEqual(camera.count(old),1)
                    wrong = camera.replace(old,'memcpy(deployment_projection.matrix, GPTR(output),')
                    with self.assertRaises(AssertionError):
                        compile_probe('projection-context-p-only-negative',probe,
                            {'runtime.h':runtime,'camera_impl.h':wrong},extra_flags=flags,compiler_override=compiler)

    def test_legacy_original_projection_and_extra_hud(self):
        import pefile
        import port_patches
        core = (ROOT / "android/host/core.c").read_text()
        state = core[core.index("VOID_HIDDEN uint32_t g_eax"):core.index("#define VOID_ENTER_RING")]
        for edition, roots in (("vanilla", ("00760E50", "004ABC20", "004ABAC0")),
                               ("hof", ("0075BAE0", "009F3C00", "009F3AA0"))):
            with self.subTest(edition=edition):
                native = {}
                folder = ROOT / "generated" / edition / "game-x86"
                for path in folder.glob("game_[0-9][0-9][0-9][0-9].c"):
                    text = path.read_text()
                    for address in roots:
                        signature = "void sub_" + address + "("
                        if signature in text:
                            native[address] = function(text, signature)
                    if len(native) == 3:
                        break
                self.assertEqual(set(native), set(roots))
                native = "\n".join(native[address] for address in roots).replace("void sub_", "static void sub_")
                mapping = dict(port_patches.load_contract(edition)["addresses"])
                mapping.update(zip(("007CD0C0", "00CF7D90", "00CF7C30"), roots))
                mapping.update(zip(("00CF60A0", "00CF7AC0", "00CF7000"),
                                   ("004AA110", "004AB950", "004AAE60") if edition == "vanilla"
                                   else ("009F20F0", "009F3930", "009F2E40")))
                # Fixture fields are pinned by original screen constructor and camera accessors.
                mapping.update({"000100A4": "0001009C", "000102E0": "000102D8" if edition == "vanilla" else "000102F0"})
                probe = re.sub(r'(0x|sub_)([0-9A-Fa-f]+)', lambda m:
                               m[1] + mapping.get(f'{int(m[2], 16):08X}', m[2]), PROBE)
                image = pefile.PE(str(ROOT / "generated" / edition / "input/H5_Game.exe"))
                constants = []
                for address in sorted(set(int(n, 16) for n in re.findall(r'ADDR\(0x([0-9A-F]+)\)', native))):
                    data = image.get_data(address - image.OPTIONAL_HEADER.ImageBase, 8)
                    self.assertEqual(len(data), 8)
                    values = ",".join(str(byte) for byte in data)
                    constants.append(f"memcpy(GPTR(0x{address:X}),(unsigned char[]){{{values}}},8);")
                image.close()
                camera_path, _ = port_patches.adapt_host_source(ROOT / "android/host/touch_camera.c",
                    ROOT / "build/tests" / ("legacy-projection-" + edition), edition)
                camera = camera_path.read_text()
                for header in ("host.h", "input.h", "touch.h"):
                    camera = camera.replace(f'#include "{header}"\n', "")
                probe = probe.replace("/* STATE */", state).replace("/* NATIVE */", native)
                probe = probe.replace("/* CONSTANTS */", "\n".join(constants))
                runtime = prepare_windows_runtime.platform_header((ROOT / "android/runtime/recomp_types.h").read_text())
                compiler, _, _ = build_windows.compiler_environment()
                compile_probe("combat-pc-projection-" + edition, probe, {"runtime.h": runtime, "camera_impl.h": camera},
                              extra_flags=["/clang:-Wno-unused-variable", "/clang:-Wno-unused-label", "/clang:-Wno-unused-function"],
                              compiler_override=compiler)

    def test_original_pc_lens_at_wide_phone_aspects(self):
        import pefile
        core = (ROOT / "android/host/core.c").read_text()
        state = core[core.index("VOID_HIDDEN uint32_t g_eax"):core.index("#define VOID_ENTER_RING")]
        native = function((ROOT / "generated/game-x86/game_0308.c").read_text(), "void sub_007CD0C0(")
        renderer = (ROOT / "generated/game-x86/game_0700.c").read_text()
        native += "\n" + function(renderer, "void sub_00CF7C30(") + "\n" + function(renderer, "void sub_00CF7D90(")
        native = native.replace("void sub_", "static void sub_")
        image = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"))
        constants = []
        for address, size in ((0xE12EE0, 4), (0xE34C5C, 4), (0xE0F470, 8),
                              (0xE12E00, 8), (0xE80B18, 8), (0xE0BE10, 4)):
            data = image.get_data(address - image.OPTIONAL_HEADER.ImageBase, size)
            values = ",".join(str(byte) for byte in data)
            constants.append(f"memcpy(GPTR(0x{address:X}),(unsigned char[]){{{values}}},{size});")
        camera = (ROOT / "android/host/touch_camera.c").read_text()
        for header in ("host.h", "input.h", "touch.h"):
            camera = camera.replace(f'#include "{header}"\n', "")
        probe = PROBE.replace("/* STATE */", state).replace("/* NATIVE */", native)
        probe = probe.replace("/* CONSTANTS */", "\n".join(constants))
        runtime = prepare_windows_runtime.platform_header((ROOT / "android/runtime/recomp_types.h").read_text())
        compiler, _, _ = build_windows.compiler_environment()
        flags = ["/clang:-Wno-unused-variable", "/clang:-Wno-unused-label", "/clang:-Wno-unused-function"]
        compile_probe("combat-pc-projection", probe, {"runtime.h": runtime, "camera_impl.h": camera},
                      extra_flags=flags, compiler_override=compiler)


if __name__ == "__main__":
    unittest.main()
