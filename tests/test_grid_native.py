"""CHeroTrace grid traversal against each actual production-transformed body."""
import hashlib
import json
import re
import sys
import unittest

import pefile

from test_mmx_packed import CLANG, command, environment, pc_header
from test_scene_native import body, transformed
from test_static_tls import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
from editions import generated_root, protocol_root
from x87_locals import Plan, apply_x87


# RTTI secondary serializer interface -> its virtual+0xC -> direct grid call.
# Each original image was inspected independently; the other same-shape legacy
# functions belong to another owner and must not be selected by shape alone.
FACTS = {
    'toe': ('00C059B0', '00C05A90', 'game_0627.c', '00C05800', '00E88578', '00F009C4',
            ('00609AD0', '00879240', '004B04A0', '00C05AC0'),
            '236805c7cc3e41fbfff7d6271329f2b1b9adb02a299f7168914278e5e2f6b18b'),
    'vanilla': ('00A44AD0', '00A44BB0', 'game_0503.c', '00A44920', '00E48A2C', '00EC4DF8',
                ('007AFCE0', '00C00360', '00A43B50', '00A44BE0'),
                '475b4b4acd9da4ddd7babf6cc9d22f02243449fe6d914f3a42cdfa26a77ebbdd'),
    'hof': ('00807790', '00807870', 'game_0333.c', '00807630', '00DFFE14', '00E898D4',
            ('004E0030', '00A99C10', '008E4B50', '008078A0'),
            '9e8ed188521bb7cd8663cf2857d36de66b488563fa65d4436538716b173b9b5e'),
}


def adapt(source, edition):
    entry, helper, _, _, _, _, calls, _ = FACTS[edition]
    mapping = dict(zip(FACTS['toe'][6], calls))
    def address(match):
        value = match[1]
        if 0xC059B0 <= int(value, 16) <= 0xC05ABF:
            return f'{int(entry, 16) + int(value, 16) - 0xC059B0:08X}'
        return mapping.get(value, value)
    return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])', address, source)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum { BYTES=0x40000, ARCHIVE=0x1000, GRID_VA=0x1200, VTABLE=0x2000,
       ROWS=0x5000, CELLS=0xA000, STACK=0x30000, MAX_EVENTS=1024 };
static uint8_t memory[BYTES];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#define RECOMP_PLAIN_MEMORY
#define RECOMP_TRACE
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 4u
#include "recomp_types.h"
#ifndef RECOMP_ENTER_SIZE
#define RECOMP_ENTER_SIZE 1024
#endif
static void *checked_pointer(uint32_t address) {
    if(address>BYTES-64){fprintf(stderr,"DIFFERENTIAL FAIL invalid guest address %08x\n",address);exit(2);}
    return memory+address;
}
#undef RECOMP_MEM_ADDR
#define RECOMP_MEM_ADDR(va) checked_pointer((uint32_t)(va))
#undef GPTR
#define GPTR(va) checked_pointer((uint32_t)(va))
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_backedges,g_cur_func;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE],g_enter_idx;
uint64_t g_mm[8];xmm_t g_xmm[8];uint32_t g_mxcsr;
double g_st_win[RECOMP_X87_SLOTS];int64_t g_st_i64_win[RECOMP_X87_SLOTS];int g_fp_sp;
int g_fp_top,void_fpu_cmp;uint16_t g_fpu_cw;
void (*recomp_yield_hook)(void);
static const char *void_data_dir(void) {return ".";}
static unsigned logs,original_calls,callbacks,yields,events,policy,yp,case_number,object_calls,reference_selector_calls;
static int32_t output_width,output_height;
static void void_log(const char *format,...) {(void)format;++logs;}
typedef struct state {
    uint32_t regs[8],flags[4],backedges,cur,trace_index,trace[RECOMP_ENTER_SIZE];
    double fp[RECOMP_X87_SLOTS];int64_t fp_integer[RECOMP_X87_SLOTS];
    uint64_t mm[8];xmm_t xmm[8];uint32_t mxcsr;
    int fp_top,fp_cmp,fp_sp;uint16_t fp_cw;
} state;
typedef struct event {unsigned kind;state cpu;uint32_t stack[12];} event;
static event log_events[MAX_EVENTS],saved_events[MAX_EVENTS];
static uint8_t saved_memory[BYTES];static state saved_final;
static state capture(void) {
    state s;memset(&s,0,sizeof s);
    const uint32_t regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    const uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,regs,sizeof regs);memcpy(s.flags,flags,sizeof flags);
    s.backedges=g_backedges;s.cur=g_cur_func;s.trace_index=g_enter_idx;
    memcpy(s.trace,g_enter_trace,sizeof s.trace);memcpy(s.fp,g_st_win,sizeof s.fp);
    memcpy(s.fp_integer,g_st_i64_win,sizeof s.fp_integer);memcpy(s.mm,g_mm,sizeof s.mm);
    memcpy(s.xmm,g_xmm,sizeof s.xmm);s.mxcsr=g_mxcsr;
    s.fp_top=g_fp_top;s.fp_cmp=void_fpu_cmp;s.fp_sp=g_fp_sp;s.fp_cw=g_fpu_cw;
    return s;
}
static void record(unsigned kind) {
    if(events>=MAX_EVENTS){fprintf(stderr,"DIFFERENTIAL FAIL runaway callback\n");exit(2);}
    memset(&log_events[events],0,sizeof log_events[events]);
    log_events[events].kind=kind;log_events[events].cpu=capture();
    assert(g_esp+48<BYTES);memcpy(log_events[events].stack,GPTR(g_esp),48);++events;
}
void recomp_protocol_violation(uint32_t site,uint32_t target,uint32_t regs) {
    fprintf(stderr,"protocol violation %08x %08x %x\n",site,target,regs);abort();
}
static void callback(unsigned kind,unsigned pop) {
    assert(++callbacks<MAX_EVENTS);record(kind);
    uint32_t arg=MEM32(g_esp+4),result=0xA5000000u|(kind<<16)|callbacks;
    if(kind==1) {
        assert(g_ecx==ARCHIVE&&MEM32(g_esp+12)==4&&MEM32(g_esp+16)==1);
        assert(arg==1||arg==2);
        if(policy&1)MEM32(MEM32(g_esp+8))=(uint32_t)(arg==1?output_width:output_height);
    }
    if(kind==2)result=0xF1000000u|((policy&2)?1u:0u);
    if(kind==3) {
        assert(g_ecx==ARCHIVE&&MEM32(g_esp+4)==3);
        uint32_t index=MEM32(g_esp+8);
        result=0xB3000000u|(((policy&4)&&index%2u)?0u:1u);
    }
    if(kind==4) {
        ++object_calls;
        assert(g_ecx==ARCHIVE&&arg>=CELLS-0x1000&&arg<CELLS+0x2000);
        MEM32(arg)^=0x12345678u;
        /* These are the original guest locals, not copies in host variables. */
        if((policy&8)&&object_calls==1){MEM32(STACK-4)=2;MEM32(STACK-8)=3;}
        if((policy&16)&&object_calls==2){MEM32(STACK-4)=1;MEM32(STACK-8)=1;}
        if(policy&32)MEM32(GRID_VA+4)=ROWS+0x100;
        if(policy&64)MEM32(ARCHIVE)=VTABLE+0x100;
    }
    if(kind==8) {
        assert(g_ecx==GRID_VA);
        MEM32(GRID_VA)=CELLS;MEM32(GRID_VA+4)=ROWS;
        if(policy&128){MEM32(STACK-4)=2;MEM32(STACK-8)=2;}
    }
    g_eax=result;g_ecx=0x13570000u|callbacks;g_edx=0xC6000000u|(kind<<16)|callbacks;
    g_flag_k=FK_TEST;g_flag_a=result;g_flag_b=kind;g_flag_cf=0;
    g_st[(callbacks+3u)&7u]+=0.25;g_st_i64[callbacks&7u]^=0x1122334455667788ll;
    g_fp_top=(g_fp_top+1)&7;g_fpu_cw^=0x400u;void_fpu_cmp^=3;
    g_mm[(callbacks+1u)&7u]^=0xAABBCCDDEEFF0011ull;
    ((uint32_t *)g_xmm)[callbacks&31u]^=0x52198BCAu;g_mxcsr^=0x2000u;
    g_esp+=pop;
}
static void dimensions(void){callback(1,20);}
static void reading(void){callback(2,4);}
static void field_begin(void){callback(3,12);}
static void reference_visit(void){callback(4,8);}
void void_reference_native_tile_dispatch(void){++reference_selector_calls;reference_visit();}
static void field_end(void){callback(5,4);}
static void storage_destroy(void){callback(6,8);}
static void rows_free(void){callback(7,4);}
static void grid_rebuild(void){callback(8,4);}
recomp_func_t void_resolve(uint32_t address) {
    switch(address){case 1:return dimensions;case 2:return reading;
    case 3:return field_begin;case 5:return field_end;default:assert(0);return 0;}
}
static void test_yield(void) {
    ++yields;record(9);
    g_eax^=0x5A000000u;g_edx^=0x12345678u;
    if(yp==1){MEM32(STACK-4)=1;MEM32(STACK-8)=1;}
    if(yp==2)g_edx=0x80000000u;
    g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;
    g_st[3]+=0.5;((uint32_t *)g_xmm)[11]^=0xAFFEBCCDu;
}
#include "names.h"
#include "oracle.h"
void CANONICAL_ENTRY(void){++original_calls;oracle_grid();}
#include "actual.h"

static void setup(int32_t width,int32_t height,unsigned test_policy,unsigned yield_policy,unsigned seed) {
    policy=test_policy;yp=yield_policy;memset(memory,0xCD,sizeof memory);
    g_eax=seed^0x15798000;g_ecx=ARCHIVE;g_edx=seed^0xABCD1234;g_ebx=seed^0xBEEFFACE;
    g_esp=STACK;g_ebp=seed^0xEFEF2937;g_esi=seed^0x3679BEEF;g_edi=seed^0xCC811223;
    g_flag_k=FK_ADD;g_flag_a=seed;g_flag_b=0x1942;g_flag_cf=1;
    g_backedges=seed%4u;g_cur_func=0x11111111;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
    g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;g_mxcsr=0x3F80;
    g_fp_top=5;g_fpu_cw=0xB7F;void_fpu_cmp=0x41;
    MEM32(STACK)=0x91919191;MEM32(STACK+4)=GRID_VA;
    MEM32(ARCHIVE)=VTABLE;
    for(unsigned off=0;off<=0x100;off+=0x100){
        MEM32(VTABLE+off+0x28)=1;MEM32(VTABLE+off+0x3C)=2;
        MEM32(VTABLE+off+0x1C)=3;MEM32(VTABLE+off+0x20)=5;
    }
    MEM32(GRID_VA)=(seed%3)?CELLS:0;MEM32(GRID_VA+4)=ROWS;
    MEM32(GRID_VA+8)=(uint32_t)width;MEM32(GRID_VA+12)=(uint32_t)height;
    /* Non-reading grids need usable rows. Reading mismatches also test nulls. */
    if((policy&3)==3&&(width!=3||height!=2)&&seed%5==0)MEM32(GRID_VA+4)=0;
    for(int row=-8;row<16;row++){
        MEM32(ROWS+4*row)=CELLS+0x80*row;
        MEM32(ROWS+0x100+4*row)=CELLS+0x800+0x80*row;
    }
    output_width=3;output_height=2;
    callbacks=yields=events=object_calls=reference_selector_calls=0;recomp_yield_hook=test_yield;
}
static int compare(int32_t width,int32_t height,unsigned p,unsigned y,unsigned seed) {
    if(getenv("GRID_VERBOSE")){fprintf(stderr,"case=%u dims=%d,%d p=%u y=%u\n",case_number,width,height,p,y);fflush(stderr);}
    setup(width,height,p,y,seed);oracle_grid();saved_final=capture();memcpy(saved_memory,memory,sizeof memory);
    unsigned nevents=events,ncallbacks=callbacks,nyields=yields;
    memcpy(saved_events,log_events,events*sizeof log_events[0]);
    setup(width,height,p,y,seed);void_grid_native_visit();state actual=capture();
    if(memcmp(&saved_final,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)||
       nevents!=events||ncallbacks!=callbacks||nyields!=yields||reference_selector_calls!=object_calls||
       memcmp(saved_events,log_events,events*sizeof log_events[0])) {
        fprintf(stderr,"DIFFERENTIAL FAIL case=%u dims=%d,%d policy=%u yield=%u events=%u/%u\n",
                case_number,width,height,p,y,nevents,events);
        for(unsigned i=0;i<8;i++)if(saved_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,saved_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<4;i++)if(saved_final.flags[i]!=actual.flags[i])fprintf(stderr,"flag%u %08x/%08x\n",i,saved_final.flags[i],actual.flags[i]);
        for(unsigned i=0;i<events&&i<nevents;i++)if(memcmp(&saved_events[i],&log_events[i],sizeof(event))){
            fprintf(stderr,"firstevent%u kinds%u/%u\n",i,saved_events[i].kind,log_events[i].kind);
            for(unsigned j=0;j<8;j++)if(saved_events[i].cpu.regs[j]!=log_events[i].cpu.regs[j])fprintf(stderr,"eventreg%u %08x/%08x\n",j,saved_events[i].cpu.regs[j],log_events[i].cpu.regs[j]);break;}
        for(unsigned i=0;i<sizeof memory;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"memory%08x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    return 0;
}
int main(int argc,char **argv) {
    const int32_t dims[][2]={{0,7},{3,0},{1,1},{3,2},{5,4},{-3,-2},{-3,2},
        {0x7FFFFFFF,2},{(int32_t)0x80000000u,1},{(int32_t)0x80000000u,-1},{0x10000,0x10000}};
    if(argc==1)for(unsigned d=0;d<sizeof dims/sizeof dims[0];d++)for(unsigned p=0;p<256;p+=7)for(unsigned y=0;y<3;y++){
        ++case_number;if(compare(dims[d][0],dims[d][1],p,y,case_number))return 1;}
    remove("native-grid");int native_mode=argc>1&&!strcmp(argv[1],"native");
    if(argc>1){FILE *f=fopen("native-grid","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    setup(0,0,0,0,1);original_calls=logs=0;void_grid_native_dispatch();
    assert(original_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-grid","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(0,0,0,0,1);void_grid_native_dispatch();assert(original_calls==(native_mode?0:2)&&logs==1);
    remove("native-grid");
    printf("PASS %u cases: complete guest state/memory/callback frames; signed dimensions, aliases, cached mode%d\n",case_number,native_mode);
    return 0;
}
'''


class GridNativeTest(unittest.TestCase):
    def check_edition(self, edition, protocol_check=False, trace=True, mutant=None):
        entry, helper, unit, caller, vt, col, calls, raw_hash = FACTS[edition]
        pe = pefile.PE(str(generated_root(edition) / 'input/H5_Game.exe'), fast_load=True)
        def original(va, size):
            return pe.get_data(int(va, 16) - pe.OPTIONAL_HEADER.ImageBase, size)
        self.assertEqual(hashlib.sha256(original(entry, 222)).hexdigest(), raw_hash)
        self.assertEqual(hashlib.sha256(original(helper, 48)).hexdigest(),
                         '0eeb80afc1b9e90a24d1b3f9ad0de3431a1fc0e36829bb81d6444569871d778b')
        self.assertEqual(int.from_bytes(original(f'{int(vt,16)-4:08X}', 4), 'little'), int(col,16))
        self.assertEqual(int.from_bytes(original(f'{int(vt,16)+12:08X}', 4), 'little'), int(caller,16))
        td = int.from_bytes(original(f'{int(col,16)+12:08X}', 4), 'little')
        type_name = b'.?AVCHeroTrace@NWorld@@\0'
        self.assertEqual(original(f'{td+8:08X}', len(type_name)), type_name)
        caller_body = transformed(edition, 'sub_' + caller, unit)
        self.assertIn('sub_' + entry, caller_body)
        call = re.search(r'RECOMP_CALL_P\(sub_' + entry + r',[^\n]+/\* 0x([0-9A-F]{8}): call', caller_body)
        self.assertIsNotNone(call)
        instruction = int(call[1],16)
        raw_call = original(call[1],5)
        self.assertEqual(raw_call[0],0xE8)
        self.assertEqual((instruction+5+int.from_bytes(raw_call[1:],'little',signed=True))&0xFFFFFFFF,int(entry,16))
        oracle = transformed(edition, 'sub_' + entry, unit)
        field = transformed(edition, 'sub_' + helper, unit)
        x87 = Plan(protocol_root(edition) / 'x87.json', edition=edition)
        plan = x87.info['sub_' + entry]
        self.assertEqual((plan['c'], plan['p'], plan['depth'], plan['calls']), (0,0,{},{}))
        self.assertNotIn('sub_' + helper, x87.info)  # indirect tail is intentionally opaque
        self.assertEqual(apply_x87((field+oracle).encode(), x87), (field+oracle).encode())
        # The oracle is the canonical body, retaining its real protocol masks.
        oracle = oracle.replace('void sub_' + entry + '(void)', 'void oracle_grid(void)', 1)
        source = adapt((ROOT / 'android/host/grid_native.c').read_text(), edition)
        if mutant:
            source = mutant(source)
        names = '#define CANONICAL_ENTRY sub_' + entry + '\n'
        for actual, stub in zip(calls, ('storage_destroy', 'rows_free', 'grid_rebuild', 'reference_visit')):
            names += '#define sub_' + actual + ' ' + stub + '\n'
        suffix = ('-protocol' if protocol_check else '') + ('-notrace' if not trace else '') + ('-mutant' if mutant else '')
        out = ROOT / 'build/tests' / ('grid-native-' + edition + suffix)
        out.mkdir(parents=True, exist_ok=True)
        header = pc_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        probe = HARNESS if trace else HARNESS.replace('#define RECOMP_TRACE', '/* Production trace disabled. */')
        files = {'recomp_types.h':header, 'host.h':'#include "recomp_types.h"\n', 'names.h':names,
                 'oracle.h':field+'\n'+oracle, 'actual.h':source, 'probe.c':probe,
                 'native_mode.h':(ROOT/'android/host/native_mode.h').read_text()}
        for name, text in files.items():
            (out / name).write_text(text, encoding='utf-8')
        env, linker = environment('x64')
        flags = [CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
                 '/clang:--target=x86_64-pc-windows-msvc', '/clang:-fno-strict-aliasing',
                 '/clang:-fwrapv', '/clang:-ffp-contract=off']
        if protocol_check:
            flags.append('/DRECOMP_PROTOCOL_CHECK')
        command([*flags, '/c', 'probe.c', '/Foprobe.obj'], out, env)
        command([linker, '/nologo', 'probe.obj', '/OUT:probe.exe', '/STACK:1048576'], out, env)
        tested = command([out/'probe.exe'], out, env, check=False)
        if mutant:
            self.assertNotEqual(tested.returncode, 0, tested.stdout+tested.stderr)
            self.assertIn('DIFFERENTIAL FAIL', tested.stderr)
            return
        self.assertEqual(tested.returncode, 0, tested.stdout+tested.stderr)
        enabled = command([out/'probe.exe', 'native'], out, env, check=False)
        self.assertEqual(enabled.returncode, 0, enabled.stdout+enabled.stderr)
        for invalid in ('0','01','1\nextra','2','1\r\n'):
            result = command([out/'probe.exe', invalid], out, env, check=False)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        print(edition+suffix+': '+tested.stdout.strip())
        (out/'receipt.json').write_text(json.dumps({
            'edition':edition,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'oracle_sha256':hashlib.sha256((field+oracle).encode()).hexdigest(),
            'runtime_sha256':hashlib.sha256(header.encode()).hexdigest(),
            'protocol_check':protocol_check,'trace':trace,'results':[tested.stdout,enabled.stdout],
            'device_tested':False},indent=2)+'\n',encoding='utf-8')

    def test_all_three_production_oracles(self):
        for edition in FACTS:
            with self.subTest(edition=edition):
                self.check_edition(edition)

    def test_full_protocol_publication(self):
        self.check_edition('toe', protocol_check=True)

    def test_production_without_trace(self):
        self.check_edition('toe', trace=False)

    def test_reject_unsigned_dimension_product(self):
        self.check_edition('toe', mutant=lambda s:s.replace('if ((int32_t)eax > 0)', 'if (eax > 0)'))

    def test_reject_recomputed_comparison_after_yield(self):
        self.check_edition('toe', mutant=lambda s:s.replace('} while (more);', '} while ((int32_t)ecx < (int32_t)edx);'))

    def test_reject_dimensions_cached_in_the_object(self):
        self.check_edition('toe', mutant=lambda s:s.replace('edi = MEM32(esp + 0x28);', 'edi = (uint32_t)GRID(esi)->width;'))

    def test_reject_bypassed_reference_selector(self):
        self.check_edition('toe', mutant=lambda s:s.replace('RECOMP_CALL_P(void_reference_native_tile_dispatch,', 'RECOMP_CALL_P(sub_00C05AC0,'))


if __name__ == '__main__':
    unittest.main()
