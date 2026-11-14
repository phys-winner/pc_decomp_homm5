"""Do not rebuild or reflow rows queued for removal by the original UI."""
import re
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'tools')]
from test_d3d_lifecycle import function
from test_legacy_font_aspect import body
from test_fmod_stream import HARNESS as STATE, COMPILER
from test_fmod_latency import FLAGS
from test_static_tls import compile_probe
import port_patches

runtime = (ROOT / 'android/runtime/recomp_types.h').read_text()
runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', '')
runtime = runtime.replace(function(runtime, 'static inline uint64_t __rdtsc('), '')
prefix = STATE[:STATE.index('static uint64_t clock_ns')].replace('memory[0x11070000]', 'memory[0x1100000]')
probe = r'''
#define GPTR(p) ((void *)ADDR(p))
#define ARG(i) MEM32(g_esp+4+4*(i))
typedef void (*void_fn)(void);
typedef struct { uint32_t a,c,d,s,b,si,di,bp; } void_regs;
static void void_regs_save(void_regs *r){*r=(void_regs){g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp};}
static void void_regs_load(const void_regs *r){g_eax=r->a;g_ecx=r->c;g_edx=r->d;g_esp=r->s;g_ebx=r->b;g_esi=r->si;g_edi=r->di;g_ebp=r->bp;}
static int void_vm_readable(uint32_t a,uint32_t n){return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n){return void_vm_readable(a,n);}
static uint32_t scale_read32(uint32_t a){return void_vm_readable(a,4)?MEM32(a):0;}
static uint32_t scale_placement(uint32_t w){return scale_read32(w+0x140);}
static unsigned detached,updates,refreshed,deleted_mask;
static int resized,pending;
static void native_update(void){assert(g_ecx==0x100F8);++updates;g_ecx=0xBAD;g_eax=0x1234;g_esp+=4;}
static void scale_list_update(void);
static void dummy(void){}
static void_fn void_dispatch_find(uint32_t address){(void)address;return dummy;}
static uint32_t void_call_guest_this(uint32_t address,uint32_t self,int n,const uint32_t *args){
 (void)args;assert(!n);
 if(address==0x90004){assert(self==0x180F8);return 0;}
 if(address==REORDER||address==RESIZE){assert(self==0x10000);++resized;return 0;}
 assert(address==TEXT_REFRESH&&self>=0x30400&&self<=0x32400);
 unsigned i=(self-0x30400)/0x1000;assert(!(deleted_mask&(1u<<i)));
 refreshed|=1u<<i;return 0;
}
void CAST(void){g_eax=ARG(0)-0xF8;g_esp+=4;}
void FREE(void){g_esp+=4;}
void SHIFT(void){memmove(GPTR(ARG(0)),GPTR(g_ecx),g_edx-g_ecx);g_esp+=8;}
void QUEUE_GROW(void){assert(0);}
void REMOVE_CHILD(void);
void ERASE_CHILD(void){
 assert(g_ecx==0x19000);uint32_t row=ARG(0);
 uint32_t end=MEM32(0x190A8),at=0x21000;
 while(at<end&&MEM32(at)!=row)at+=4;
 assert(at<end);memmove(GPTR(at),GPTR(at+4),end-at-4);MEM32(0x190A8)-=4;
 g_esp+=8;
}
void DETACH(void){
 assert(g_ecx==0x10000);uint32_t row=ARG(0);++detached;
 uint32_t entry=g_esp;g_ecx=0x1910C;g_esp-=8;MEM32(g_esp+4)=row+0xF8;
 REMOVE_CHILD();assert(g_esp==entry);
 uint32_t esp=g_esp;g_ecx=0x100F8;g_esp-=4;scale_list_update();g_esp=esp+8;
}
static void hide(void){assert(ARG(0)==0);deleted_mask|=1u<<((g_ecx-0x30000)/0x1000);g_esp+=8;}
static void get_name(void){g_eax=g_ecx-0xF8+0x200;g_esp+=4;}
static void compare(void){g_eax=(uint32_t)strncmp(GPTR(ARG(0)),GPTR(ARG(1)),ARG(2));g_esp+=4;}
recomp_func_t void_resolve(uint32_t target){if(target==0x90000)return get_name;if(target==0x9000C)return hide;assert(target==0x90008);return compare;}
/* SCALE */
/* ORIGINAL */
static void setup(void){
 memset(memory,0,sizeof memory);detached=updates=refreshed=deleted_mask=0;resized=0;
 MEM32(0x10000)=VT_LIST;MEM32(VT_LIST+4)=COMMON_REFRESH;
 MEM32(0x10160)=0x20000;MEM32(0x10164)=0x20060;
 MEM32(0x100A4)=0x22000;MEM32(0x100A8)=0x22004;MEM32(0x22000)=0x19000;
 MEM32(0x1015C)=0x19000;MEM32(0x19000)=0x70000;MEM32(0x70004)=COMMON_REFRESH;
 MEM32(0x190A4)=0x21000;MEM32(0x190A8)=0x2100C;
 MEM8(0x19074)=(uint8_t)pending;MEM32(0x19078)=MEM32(0x1907C)=0x23000;MEM32(0x19080)=0x2300C;
 MEM32(0x10154)=0x18000;MEM32(0x180F8)=0x73000;MEM32(0x73018)=0x90004;
 MEM32(0x71008)=0xE8;MEM32(0x72000+NAME_SLOT)=0x90000;
 MEM32(COMPARE_IAT)=0x90008;MEM32(0x74004)=TEXT_REFRESH;
 MEM32(0x70014)=0x9000C;MEM32(0x71004)=0;
 for(unsigned i=0;i<3;++i){
  uint32_t row=0x30000+i*0x1000,p=row+0x500,text=row+0x400,record=0x20000+i*32,name=row+0x300;
  MEM8(name)=(uint8_t)('1'+i);MEM32(record)=name;MEM32(record+4)=name+1;
  MEM32(row+0x200)=name;MEM32(row+0x204)=name+1;
  MEM32(row)=0x70000;MEM32(row+0x10)=0x71000;MEM32(row+0xF8)=0x72000;
  MEM32(row+0x140)=p;MEM8(p+0x70)=1;MEMF(p+0xA8)=20;
  MEM32(row+0xA4)=row+0x600;MEM32(row+0xA8)=row+0x604;MEM32(row+0x600)=text;
  MEM32(0x21000+4*i)=row;
  MEM32(text)=0x74000;MEM32(text+0x100)=row+0x700;
  MEM32(text+0x10C)=name;MEM32(text+0x110)=name+1;
  MEM32(text+0x140)=row+0x800;MEM8(row+0x870)=1;MEMF(row+0x8A8)=30;
 }
 original_list_update=native_update;original_list_layout=dummy;
}
static void remove_row(unsigned index){
 uint32_t before=MEM32(0x10164);float old_height=MEMF(0x305A8+index*0x1000);refreshed=0;g_ecx=0x100F8;g_esp=0xA0000;
 MEM32(g_esp)=0xCAFEBABE;MEM32(g_esp+4)=0x300F8+index*0x1000;
 g_esi=0x12345678;g_edi=0x23456789;g_ebx=0x34567890;g_ebp=0x456789AB;
 REMOVE();
 assert(g_esp==0xA0008&&g_esi==0x12345678&&g_edi==0x23456789&&g_ebx==0x34567890&&g_ebp==0x456789AB);
 assert(MEM32(0x10164)==before-32&&refreshed==(7u&~deleted_mask));
 assert(MEMF(0x305A8+index*0x1000)==old_height);
}
int main(void){
 for(pending=0;pending<2;++pending)for(unsigned first=0;first<3;++first){
  setup();remove_row(first);remove_row((first+1)%3);remove_row((first+2)%3);
  assert(detached==3&&updates==3&&deleted_mask==7&&MEM32(0x190A8)==(pending?0x2100C:0x21000));
  uint32_t before=MEM32(0x10164);g_ecx=0x100F8;g_esp=0xA0000;MEM32(g_esp+4)=0x300F8;REMOVE();
  assert(MEM32(0x10164)==before&&detached==3&&updates==3);
 }
 puts("PASS original list Remove + real scale Update: first/middle/last/repeated/empty, live child traversal, no removed text refresh, native RET4 and callee registers");
}
'''

class SaveListRefreshTest(unittest.TestCase):
    def test_legacy_scale_keeps_records_instead_of_running_original_reset(self):
        for edition, reset, destroy, free, invalidate, filter_child in (
                ('vanilla', 0x413860, 0x414D30, 0xC00360, 0xA77250, 0x412530),
                ('hof', 0xA3D500, 0xA3E440, 0xA99C10, 0xBE1C30, 0xA3C1D0)):
            source, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_scale.c',
                ROOT / 'build/tests/save-reflow' / edition, edition)
            text = source.read_text()
            helpers = '\n'.join(function(text, name) for name in (
                'static uint32_t scale_read32(', 'static uint32_t scale_virtual_base(',
                'static uint32_t scale_root(', 'static uint32_t scale_screen_root(',
                'void void_touch_legacy_root_rect(', 'void void_touch_legacy_relayout('))
            original = body(edition, reset)
            # Execute the actual list reset if the host ever calls resource invalidation.
            calls = set(re.findall(r'RECOMP_CALL\((sub_[0-9A-F]{8})\)', original))
            self.assertIn(f'sub_{destroy:08X}', calls)
            self.assertIn(f'sub_{invalidate:08X}', calls)
            self.assertIn(f'sub_{filter_child:08X}', calls)
            stubs = []
            for name in sorted(calls):
                address = int(name[4:], 16)
                code = 'g_esp+=4;'
                if address == destroy:
                    code = 'assert(g_ecx==0x50000&&g_edx==0x50060);g_esp+=4;'
                elif address == free:
                    code = 'assert(MEM32(g_esp+4)==0x50000);g_esp+=4;'
                elif address == filter_child:
                    code = 'g_esp+=12;'
                stubs.append(f'void {name}(void){{{code}}}')
            harness = r'''
#define HOMM5_LEGACY_UI 1
#define GPTR(p) ((void *)ADDR(p))
uint64_t g_fp_store_mask;
static uint32_t viewport_scratch;
static unsigned layouts,children,resets;
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static uint32_t void_galloc(uint32_t n){assert(n==16);return 0x32000;}
typedef void (*void_fn)(void);
static void dummy(void){}
static void_fn void_dispatch_find(uint32_t p){(void)p;return dummy;}
recomp_func_t void_resolve(uint32_t p){(void)p;assert(0);return dummy;}
/* ORIGINAL */
static uint32_t void_call_guest(uint32_t p,int n,const uint32_t*a,int pops){
 if(p==GET_SCREEN){assert(!n&&!a&&pops);return 0x20000;}
 assert(p==CAST&&n==5&&!pops&&a[0]==0x20024);return 0x22000;
}
static uint32_t void_call_guest_this(uint32_t p,uint32_t self,int n,const uint32_t*a){
 if(p==LAYOUT){assert(self==0x300F8&&n==1&&a[0]==viewport_scratch);++layouts;}
 else if(p==INVALIDATE){
  assert(self==0x3010C&&!n&&!a);++resets;g_ecx=0x40198;g_esp=0xA0000;RESET();assert(g_esp==0xA0004);
 }else if(p==CHILDREN){assert(self==0x30000&&!n&&!a);++children;}
 else {assert(p==NEXT_SCREEN&&self==0x20000&&!n&&!a);return 0;}
 return 0;
}
/* HELPERS */
int main(void){
 MEM32(0x20004)=0x21000;MEM32(0x21004)=0x20;
 MEM32(0x22098)=0x300F8;MEM32(0x22144)=0x23000;MEM32(0x23000)=0x23000;
 MEM32(0x300F8)=0x24000;MEM32(0x24048)=LAYOUT;
 MEM32(0x40160)=0x50000;MEM32(0x40164)=0x50060;MEM32(0x40168)=0x50080;
 for(unsigned i=0;i<96;++i)MEM8(0x50000+i)=(uint8_t)(i+1);
 const int scales[]={50,75,100,125,150,175,200,100};
 for(unsigned i=0;i<sizeof scales/sizeof scales[0];++i){
  MEMF(CANVAS_X)=1707.0f*100/scales[i];MEMF(CANVAS_Y)=768.0f*100/scales[i];
  void_touch_legacy_relayout();
  assert(MEM32(0x40160)==0x50000&&MEM32(0x40164)==0x50060&&MEM32(0x40168)==0x50080);
  for(unsigned j=0;j<96;++j)assert(MEM8(0x50000+j)==j+1);
 }
 assert(layouts==8&&children==8&&!resets);
 puts("PASS legacy scale50/75/100/125/150/175/200/fit100: populated records retained; original resource-reset negative control clears them");
}
'''
            harness = harness.replace('/* ORIGINAL */', '\n'.join(stubs) + original)
            harness = harness.replace('RESET()', f'sub_{reset:08X}()').replace('/* HELPERS */', helpers)
            addresses = port_patches.load_contract(edition)['addresses']
            for name, address in {'GET_SCREEN':'008385A0', 'CAST':'00D119FC', 'LAYOUT':'00487990',
                    'INVALIDATE':'00A504B0', 'CHILDREN':'00488220', 'NEXT_SCREEN':'008384D0',
                    'CANVAS_X':'00F74BE0', 'CANVAS_Y':'00F74BE4'}.items():
                harness = re.sub(r'\b'+name+r'\b', '0x'+addresses[address]+'u', harness)
            fixture = prefix + harness
            compile_probe('save-reflow-'+edition, fixture, {'runtime.h':runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            call = f'void_call_guest_this(0x{addresses["00487990"]}u, root, 1, &viewport_scratch);'
            self.assertEqual(fixture.count(call), 1)
            old = fixture.replace(call, call+f'\nvoid_call_guest_this(0x{addresses["00A504B0"]}u, root + 0x14, 0, NULL);')
            with self.assertRaisesRegex(AssertionError, 'MEM32'):
                compile_probe('save-reflow-reset-'+edition, old, {'runtime.h':runtime}, extra_flags=FLAGS, compiler_override=COMPILER)

    def test_remove(self):
        specs = {
            'toe': (0x8894C0, (0xD119FC, 0x879240, 0x889F30, 0x888B40), 0xE8, 0xE0A2B0, (0xA51740,0xA51460,0xA53260,0xA52D90)),
            'vanilla': (0x4141B0, (0xC0D69E, 0xC00360, 0x414DE0, 0x413680), 0xDC, 0xDE32B4, (0xA784D0,0xA77FE0,0xA79DF0,0xA79E50)),
            'hof': (0xA3DE50, (0xC09BCE, 0xA99C10, 0xA3E840, 0xA3D320), 0xE4, 0xDBA298, (0xBE2EC0,0xBE29C0,0xBE4790,0xBE43E0)),
        }
        for edition, (remove, calls, slot, iat, children) in specs.items():
            source, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_scale.c', ROOT / 'build/tests/save-remove' / edition, edition)
            text = source.read_text()
            actual = text[text.index('static void_fn original_list_layout'):text.index('/* Scrollable text rows')]
            actual += '\n'.join(function(text, name) for name in ('static int scale_text_rows(', 'static int scale_has_text(', 'static void scale_refresh_window(uint32_t window, unsigned depth, unsigned *remaining)\n{'))
            mapping = port_patches.load_contract(edition)['addresses']
            required = {'VT_LIST':'00E94034','COMMON_REFRESH':'00A4E570','TEXT_REFRESH':'00B95AC0','REORDER':'008888E0','RESIZE':'00887BA0'}
            defines = ''.join(f'#define {key} 0x{mapping.get(value,value)}u\n' for key,value in required.items())
            defines += f'#define NAME_SLOT {slot}\n#define COMPARE_IAT 0x{iat:X}u\n'
            originals = body(edition, children[2]) + body(edition, children[0]) + body(edition, remove)
            fixture = probe.replace('/* SCALE */', actual).replace('/* ORIGINAL */', originals)
            for role, address in zip(('CAST', 'FREE', 'SHIFT', 'DETACH', 'REMOVE'), (*calls, remove)):
                fixture = fixture.replace(role+'(', f'sub_{address:08X}(')
            for role,address in zip(('REMOVE_CHILD','ERASE_CHILD','APPEND_CHILD','QUEUE_GROW'),children):
                fixture = fixture.replace(role+'(',f'sub_{address:08X}(')
            compile_probe('save-remove-' + edition, defines + prefix + fixture, {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            old = f'RECOMP_CALL(sub_{calls[3]:08X});'
            self.assertEqual(fixture.count(old), 1)
            mutant = fixture.replace(old, 'esp += 4;')
            with self.assertRaisesRegex(AssertionError, r'refreshed=='):
                compile_probe('save-remove-no-detach-' + edition, defines + prefix + mutant,
                              {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            old = fixture.replace('!scale_pending_removal(window, child)', '1')
            self.assertNotEqual(old, fixture)
            with self.assertRaisesRegex(AssertionError, r'!\(deleted_mask'):
                compile_probe('save-remove-stale-scale-' + edition, defines + prefix + old,
                              {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)
            old = fixture.replace('if (scale_pending_removal(holder, row)) continue;', '')
            self.assertNotEqual(old, fixture)
            with self.assertRaisesRegex(AssertionError, r'old_height'):
                compile_probe('save-remove-stale-reflow-' + edition, defines + prefix + old,
                              {'runtime.h': runtime}, extra_flags=FLAGS, compiler_override=COMPILER)

if __name__ == '__main__':
    unittest.main()
