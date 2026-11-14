"""Exercise pre-context LoadingScreen scaling against actual adapted runtime C."""
import re
import sys
import unittest
from pathlib import Path

from test_d3d_lifecycle import function
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import port_patches

# Independent original PE/lifted-code facts, not derived from the patch maps.
ORIGINAL = {
    "toe": ("00E34674", "006B1317", "009D53A0", "006B1346", "006B1B40", "006B139A"),
    "vanilla": ("00E12E5C", "0066B527", "00BE3920", "0066B556", "0066BCF0", "0066B5AA"),
    "hof": ("00DE831C", "0066D8E7", "00A4B880", "0066D916", "0066E0F0", "0066D96A"),
}
LAYOUT = {
    "vanilla": ("00F07D4C", "00AF8620", "00A77250", "00AF8E10"),
    "hof": ("00F24178", "00A35EE0", "00BE1C30", "00A366D0"),
}

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x1200000];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define MEMF(a) (*(float *)(memory+(uint32_t)(a)))
#define GPTR(a) (memory+(uint32_t)(a))
#define VLOG(...) ((void)0)
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int locked;
static void pthread_mutex_lock(pthread_mutex_t*p){(void)p;assert(!locked);locked=1;}
static void pthread_mutex_unlock(pthread_mutex_t*p){(void)p;assert(locked);locked=0;}
typedef void (*void_fn)(void);
typedef struct {int kind;float scale;} void_touch_event;
enum {TOUCH_ABORT=10};
typedef union {uint8_t b[16];uint64_t q[2];} xmm_t;
/* ACTUAL_REGS */
static void_regs machine;
static uint32_t g_ecx,g_esp;
static int g_fp_top;
static void void_regs_save(void_regs*r){machine.ecx=g_ecx;machine.esp=g_esp;machine.fp_top=g_fp_top;*r=machine;}
static void void_regs_load(const void_regs*r){machine=*r;g_ecx=r->ecx;g_esp=r->esp;g_fp_top=r->fp_top;}
static uint32_t fixture_hwnd=1,owner_thread=7,thread=7;
static uint32_t void_window_main(void){return fixture_hwnd;}
static uint32_t void_window_thread(uint32_t w){(void)w;return owner_thread;}
static uint32_t void_thread_id(void){return thread;}
static int backbuffer_w=1920,backbuffer_h=1080,mapped=1,writable=1,dispatch=1,allocation_fail;
static uint32_t current_menu=0x22000,loading_screen=0x23000,missing_method;
static int phase,layouts,invalidates,children,texts,registered_layouts,aborts,race;
static uint32_t last_root;
static float root_rect[4];
static int (*void_android_display_size)(int*,int*);
static uint32_t void_module_exe_base(void){return 0x400000;}
static int void_vm_readable(uint32_t a,uint32_t n){return mapped&&a>0&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n){return writable&&void_vm_readable(a,n);}
static uint32_t scale_current_screen(void){return current_menu;}
static void dummy(void){}
static void sub_00A50560(void){}
static void scale_layout_override(void){}
static void scale_list_layout(void){}
static void_fn original_list_layout;
static void_fn void_dispatch_find(uint32_t a){
 if(a==0x8885D0||a==0xA50560||a==missing_method)return NULL;
 return dispatch?dummy:NULL;
}
static void void_dispatch_add(uint32_t a,void_fn f){(void)a;(void)f;assert(0);}
static uint32_t void_galloc(uint32_t n){assert(n==16);return allocation_fail?0:0x80000;}
static void void_input_screen_size(int*w,int*h){*w=backbuffer_w;*h=backbuffer_h;}
static void void_touch_engine_event(const void_touch_event*e){assert(!locked&&e->kind==TOUCH_ABORT&&e->scale==1);++aborts;}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t*a,int pops){
 assert(!locked&&pops);
 if(va==0x8385A0){assert(!n&&!a);return 0x20000;}
 assert(va==0x66A4D0&&n==1&&a&&!a[0]);++registered_layouts;return 0;
}
#ifdef HOMM5_LEGACY_UI
#define INVALIDATES 0
static void void_touch_legacy_relayout(void){++registered_layouts;}
#else
#define INVALIDATES 1
#endif
static void scale_refresh_text(void){++texts;}
static void void_touch_combat_frame(uint32_t s,float w,float h,float hud,float a,float b){(void)s;(void)w;(void)h;(void)hud;(void)a;(void)b;}
static int scale_viewport_ready(float w,float h){(void)w;(void)h;return 0;}
static int scale_is_root(uint32_t r){(void)r;return 0;}
static int scale_fits(uint32_t r,int a,float w,float h,float bw,float bh,int p){(void)r;(void)a;(void)w;(void)h;(void)bw;(void)bh;return p;}
void void_touch_loading_frame(uint32_t screen);
static void clobber(void){memset(&machine,0x5a,sizeof machine);machine.esp=0x7f000;machine.fp_top=0;g_ecx=0xdead;g_esp=0x7f000;g_fp_top=0;}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t*a){
 assert(!locked&&g_fp_top==0&&g_esp==0x7f000);
 if(va==0x487990){
  assert(!phase&&n==1&&a&&a[0]==0x80000);phase=1;++layouts;last_root=self;
  memcpy(root_rect,GPTR(a[0]),16);assert(root_rect[0]==0&&root_rect[1]==0);
  if(race==1)MEM32(loading_screen+0xA0)=0x26000;
  if(race==4)void_touch_loading_frame(loading_screen);
 }else if(va==0xA504B0){assert(phase==1&&self==last_root+0x14&&!n&&!a);phase=2;++invalidates;if(race==2)fixture_hwnd=2;}
 else {assert(va==0x488220&&phase==1+INVALIDATES&&self==last_root-0xF8&&!n&&!a);phase=3;++children;if(race==2)fixture_hwnd=2;}
 clobber();return 0;
}
static void scale_refresh_window(uint32_t root,unsigned depth,unsigned*remaining){
 assert(phase==3&&root==last_root-0xF8&&!depth&&remaining&&*remaining==4096);phase=0;++texts;
 if(race==3)MEMF(0xF74BE0)=999;
 clobber();
}
/* ACTUAL_GLOBALS */
/* ACTUAL_FUNCTIONS */
static void near(float a,float b){if(fabsf(a-b)>=.0002f)fprintf(stderr,"%.4f != %.4f\n",a,b);assert(fabsf(a-b)<.0002f);}
static void root_ready(uint32_t root){
 MEM32(loading_screen+0xA0)=root;MEM32(loading_screen+0x14C)=0x6000;MEM32(0x6000)=0x6000;
 MEM32(root)=0x70000;MEM32(0x70048)=0x487990;MEM32(0x7004C)=0x488330;
}
static void reset(float choice){
 memset(memory,0,sizeof memory);mapped=writable=dispatch=1;allocation_fail=0;missing_method=0;fixture_hwnd=1;owner_thread=thread=7;
 backbuffer_w=1920;backbuffer_h=1080;MEMF(0xF74BE8)=1024;MEMF(0xF74BEC)=768;MEMF(0xF74BF0)=1920;MEMF(0xF74BF4)=1080;
 MEMF(0xF74BE0)=1366;MEMF(0xF74BE4)=768;MEM32(0xFE719C)=0x10000;
 MEM32(current_menu)=0x00E00000;MEM32(loading_screen)=0x00E34674;root_ready(0x25000);
 void_touch_set_scale(choice);void_touch_scale_pump();
 phase=layouts=invalidates=children=texts=registered_layouts=aborts=race=0;
 viewport_scratch=0;
}
static void frame(void){
 phase=0;memset(&machine,0xa6,sizeof machine);machine.esp=0x7f000;machine.fp_top=7;g_ecx=machine.ecx;g_esp=machine.esp;g_fp_top=machine.fp_top;
 void_regs saved=machine;void_touch_loading_frame(loading_screen);
 assert(!memcmp(&saved,&machine,sizeof saved)&&g_ecx==saved.ecx&&g_esp==saved.esp&&g_fp_top==saved.fp_top);
}
/* MAIN */
'''

MAIN = r'''
int main(void){
 reset(2);MEM32(0x6000)=0x6100;MEM32(0x6100)=0x6000;
 assert(!scale_screen_root(loading_screen)); /* Ordinary fitting still requires an idle auxiliary list. */
 frame();near(MEMF(0xF74BE0),1366);near(MEMF(0xF74BE4),768);
 assert(layouts==1&&invalidates==INVALIDATES&&children==1&&last_root==0x25000&&scale_percent==200);
 near(root_rect[2],1366);near(root_rect[3],768);
 for(int i=0;i<12;i++)frame();assert(layouts==1&&invalidates==INVALIDATES&&children==1);
 /* Equal global canvas is insufficient: a deferred explicit root must be laid out later. */
 reset(2);MEMF(0xF74BE0)=1366;MEMF(0xF74BE4)=768;MEM32(loading_screen+0xA0)=0;frame();assert(!layouts);
 root_ready(0x25000);frame();assert(layouts==1);root_ready(0x26000);frame();assert(layouts==2&&last_root==0x26000);
 /* Resize races defer; a coherent resize updates the root once. */
 backbuffer_w=1280;backbuffer_h=800;frame();assert(layouts==2);
 MEMF(0xF74BF0)=1280;MEMF(0xF74BF4)=800;frame();assert(layouts==3);near(root_rect[2],1229);near(root_rect[3],768);frame();assert(layouts==3);
 /* A normal screen restores200 and clears the successful cache, including pointer reuse. */
 void_touch_scale_pump();near(MEMF(0xF74BE0),614.5f);assert(scale_percent==200);frame();assert(layouts==4);
 for(int fault=1;fault<=3;fault++){
  reset(2);race=fault;frame();int before=layouts;
  race=0;fixture_hwnd=1;root_ready(0x25000);MEMF(0xF74BE0)=1366;MEMF(0xF74BE4)=768;frame();
  assert(layouts==before+1&&invalidates>=INVALIDATES&&children>=1);frame();assert(layouts==before+1);
 }
 reset(1.25f);race=4;frame();assert(layouts==1&&invalidates==INVALIDATES&&children==1&&scale_percent==125);
 reset(2);fixture_hwnd=0;frame();assert(!layouts);fixture_hwnd=1;owner_thread=8;frame();assert(!layouts);owner_thread=7;
 missing_method=0xA504B0;frame();assert(!layouts);missing_method=0;allocation_fail=1;frame();assert(!layouts);
 allocation_fail=0;frame();assert(layouts==1);
 puts("PASS explicit Loading pre-context native100: ordinary current screen, ready/deferred/replaced roots, cache/idempotence/exit/resize, callback races/reentry, owner guards and full guest state");
 return 0;
}
'''

SEAM_MAIN = r'''
static int service_calls;
static void /* SERVICE */(void){
 assert(g_esp==0x7f000&&machine.esi==0x30000&&g_fp_top==7);
 near(MEMF(0xF74BE0),1366);assert(layouts==1&&invalidates==INVALIDATES&&children==1);
 ++service_calls;
}
#define RECOMP_FLAGS_OUT() do{machine.flag_k=caller.flag_k;machine.flag_a=caller.flag_a;machine.flag_b=caller.flag_b;machine.flag_cf=caller.flag_cf;}while(0)
#define RECOMP_REGS_OUT() do{machine=caller;machine.esi=esi;machine.esp=esp;g_ecx=machine.ecx;g_esp=esp;g_fp_top=machine.fp_top;}while(0)
#define RECOMP_REGS_IN() do{caller=machine;esi=machine.esi;esp=machine.esp;}while(0)
#define RECOMP_FLAGS_IN() do{caller.flag_k=machine.flag_k;caller.flag_a=machine.flag_a;caller.flag_b=machine.flag_b;caller.flag_cf=machine.flag_cf;}while(0)
#define RECOMP_CALL(fn) fn()
static void generated_caller(void){
 void_regs caller;memset(&caller,0xa6,sizeof caller);caller.ecx=caller.esi=0x30000;caller.esp=0x7f000;caller.fp_top=7;
 uint32_t esi=caller.esi,esp=caller.esp;MEM32(esi+0x24)=loading_screen;
 /* Deliberately stale globals: the inserted call MUST publish generated locals first. */
 memset(&machine,0x33,sizeof machine);g_ecx=0x1111;g_esp=0x1234;g_fp_top=2;
 /* SEAM */
 assert(esi==0x30000&&esp==0x7f000&&caller.ecx==0x30000&&caller.fp_top==7);
}
int main(void){
 (void)frame;reset(2);generated_caller();assert(service_calls==1);
 puts("PASS actual generated pre-context seam publishes/restores local machine state and original service sees native Loading geometry");return 0;
}
'''


def fixture(source, edition="toe", main=MAIN):
    host = (ROOT / "android/host/host.h").read_text()
    regs = host[host.index("typedef struct void_regs {"):host.index("} void_regs;") + len("} void_regs;")]
    globals_ = source[source.index("static pthread_mutex_t scale_lock"):source.index("static uint32_t scale_read32(")]
    selected = "\n".join(function(source, name) for name in (
        "static uint32_t scale_read32(", "static uint32_t scale_root(",
        "static uint32_t scale_screen_root(", "void void_touch_set_scale("))
    selected += source[source.index("static int scale_pump("):]
    result = HARNESS.replace("/* ACTUAL_REGS */", regs).replace("/* ACTUAL_GLOBALS */", globals_)
    result = result.replace("/* ACTUAL_FUNCTIONS */", selected).replace("/* MAIN */", main)
    if edition != "toe":
        addresses = port_patches.load_contract(edition)["addresses"]
        for key, value in zip(("00F74BE0", "00487990", "00A504B0", "00488220"), LAYOUT[edition]):
            assert addresses[key] == value
        result = re.sub(r'(0x|sub_)([0-9A-Fa-f]{6,8})(?![0-9A-Fa-f])',
                        lambda m: m[1] + addresses.get(m[2].upper().zfill(8), m[2]), result)
        result = result.replace('loading_screen+0xA0', 'loading_screen+0x98').replace('loading_screen+0x14C', 'loading_screen+0x144')
        result = "#define HOMM5_LEGACY_UI 1\n" + result
    return result


class LoadingFrameTest(unittest.TestCase):
    def test_actual_all_editions_pre_context_loading(self):
        for edition in ORIGINAL:
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_scale.c"
                if edition != "toe":
                    path, _ = port_patches.adapt_host_source(path, ROOT / "build/tests" / ("loading-frame-" + edition), edition)
                source = path.read_text(encoding="utf8")
                guard = re.search(r"if \((.*?)\) return;", function(source, "void void_touch_loading_frame("), re.S)[1]
                # A rejected foreign thread must not read the owner-thread-only reentry flag.
                self.assertLess(guard.index("void_window_thread"), guard.index("active"))
                compile_probe("loading-frame-" + edition, fixture(source, edition), {})

    def test_rejects_old_current_screen_only_policy(self):
        source = (ROOT / "android/host/touch_scale.c").read_text(encoding="utf8")
        old = function(source, "void void_touch_loading_frame(")
        source = source.replace(old, "void void_touch_loading_frame(uint32_t screen){void_regs saved;void_regs_save(&saved);(void)screen;void_touch_scale_pump();void_regs_load(&saved);}")
        # Keep the now-unused static helper referenced without changing behavior.
        source += "\nstatic int (*loading_guard_reference)(uint32_t,uint32_t,uint32_t,float,float)=loading_same;\n"
        probe = fixture(source).replace(" reset(2);frame();", " (void)loading_guard_reference;(void)void_call_guest_this;(void)scale_refresh_window;reset(2);frame();", 1)
        with self.assertRaisesRegex(AssertionError, r"683\.0000 != 1366\.0000"):
            compile_probe("loading-frame-old-policy-negative", probe, {})

    def test_original_progress_seams_and_argument_abi(self):
        for edition, (kind, seam, service, draw, forward, ret) in ORIGINAL.items():
            with self.subTest(edition=edition):
                contract = port_patches.load_contract(edition)
                self.assertEqual(contract.get("addresses", {}).get("00E34674", "00E34674"), kind)
                patches = [p for p in contract["generated_patches"] if "void_touch_loading_frame" in p["new"]]
                self.assertEqual(len(patches), 1)
                old, new = patches[0]["old"], patches[0]["new"]
                self.assertIn("0x" + seam + ":", old)
                self.assertIn("RECOMP_CALL(sub_" + service + ")", old)
                self.assertEqual(new.count(old), 1)
                positions = [new.index(token) for token in ("RECOMP_FLAGS_OUT", "RECOMP_REGS_OUT", "void_touch_loading_frame(MEM32", "RECOMP_REGS_IN", "RECOMP_FLAGS_IN", old)]
                self.assertEqual(positions, sorted(positions))
                self.assertRegex(new, r"void_touch_loading_frame\(MEM32\(esi\s*\+\s*0x24\)\)")
                folder = ROOT / "generated" / (edition if edition != "toe" else "") / "game-x86"
                body = next(function(p.read_text(), "void sub_" + f"{int(seam,16)-7:08X}" + "(") for p in folder.glob("game_*.c") if "void sub_" + f"{int(seam,16)-7:08X}" + "(" in p.read_text())
                self.assertLess(body.index("0x" + seam + ":"), body.index("0x" + draw + ":"))
                self.assertIn("/* 0x" + ret + ": ret  */", body)  # zero stack arguments
                self.assertIn("RECOMP_CALL(sub_" + forward + ")", body)

    def test_generated_seam_preserves_local_register_state(self):
        for edition, (_, _, service, _, _, _) in ORIGINAL.items():
            with self.subTest(edition=edition):
                contract = port_patches.load_contract(edition)
                seam = next(p["new"] for p in contract["generated_patches"] if "void_touch_loading_frame" in p["new"])
                path = ROOT / "android/host/touch_scale.c"
                if edition != "toe":
                    path, _ = port_patches.adapt_host_source(path, ROOT / "build/tests" / ("loading-frame-seam-" + edition), edition)
                main = SEAM_MAIN.replace("/* SERVICE */", "sub_" + service).replace("/* SEAM */", seam)
                probe = fixture(path.read_text(encoding="utf8"), edition, main)
                compile_probe("loading-frame-seam-" + edition, probe, {})
                # With no REGOUT, geometry callbacks see stale caller ESP. Never accept this insertion.
                unsynced = probe.replace("RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT();", "RECOMP_FLAGS_OUT();", 1)
                with self.assertRaisesRegex(AssertionError, "g_esp==0x7f000"):
                    compile_probe("loading-frame-seam-unsynced-" + edition, unsynced, {})


if __name__ == "__main__":
    unittest.main()
