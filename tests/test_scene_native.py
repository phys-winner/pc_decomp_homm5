"""Native command maintenance versus each edition's production-transformed body."""
import hashlib
import json
import re
import sys
import unittest

from test_mmx_packed import CLANG, command, environment, pc_header
from test_static_tls import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
from editions import generated_root, protocol_root
from protocol_transform import Protocol, apply_protocol


# Independently proved original PE calls and MOV getter bodies, not derived
# from the production address adapter being tested.
FACTS = {
    'toe': ('00B1C300', 'game_0553.c', ('008C6150', '008790B0', '0087BD50', '00B1BB90',
                                    '0087BA00', '0087BA20', '0087B9F0')),
    'vanilla': ('00957950', 'game_0434.c', ('00B204D0', '00C001C0', '00891A70', '00957210',
                                        '00891720', '00891740', '00891710')),
    'hof': ('004F2C80', 'game_0083.c', ('00A020E0', '00A99A80', '00921050', '004F2540',
                                    '00920D00', '00920D20', '00920CF0')),
}


def body(source, symbol):
    start = source.index('void ' + symbol + '(void) {')
    end = source.index('\n}', start) + 2
    return source[start:end] + '\n'


def transformed(edition, symbol, unit=None):
    root = generated_root(edition) / 'game-x86'
    if unit is None:
        # Three small leaves share a unit in each edition.
        files = [p for p in root.glob('game_*.c') if ('void ' + symbol + '(void) {') in p.read_text()]
        assert len(files) == 1, (edition, symbol, files)
        unit = files[0].name
    original = body((root / unit).read_text(), symbol)
    proto = Protocol(protocol_root(edition) / 'summary.json', edition=edition)
    return apply_protocol(original.encode(), proto, 'game').decode()


def adapt(source, edition):
    entry, _, calls = FACTS[edition]
    canonical = FACTS['toe'][2]
    mapping = dict(zip(canonical, calls))
    def address(match):
        value = match[1]
        if 0xB1C300 <= int(value, 16) <= 0xB1C3C5:
            return f'{int(entry, 16) + int(value, 16) - 0xB1C300:08X}'
        return mapping.get(value, value)
    # Both canonical symbol names and uint32 VA constants are adapted.
    return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])', address, source)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
enum { MEMORY_BYTES=0x80000, ROOT_VA=0x1000, ROOT2_VA=0x1200, HEAD_VA=0x2000,
       VT_VA=0x3000, NODE_VA=0x10000, CMD_VA=0x20000, STACK_VA=0x70000, MAX_EVENTS=1024 };
static uint8_t memory[MEMORY_BYTES];
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
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_backedges,g_cur_func;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE],g_enter_idx;
uint64_t g_mm[8];
xmm_t g_xmm[8];uint32_t g_mxcsr;
double g_st_win[RECOMP_X87_SLOTS];
int64_t g_st_i64_win[RECOMP_X87_SLOTS];int g_fp_sp;
int g_fp_top,void_fpu_cmp;
uint16_t g_fpu_cw;
static int callback_policy,yield_policy,case_number,oracle_calls,logs,benchmarking;
static unsigned callbacks,yields,events;
static void (*nested_commands)(void);
void (*recomp_yield_hook)(void);
static const char *void_data_dir(void) {return ".";}
static void void_log(const char *format,...) {(void)format;++logs;}
static uint32_t random_state;
static uint32_t random_next(void) {
    random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
    return random_state;
}
typedef struct state {
    uint32_t regs[8],flags[4],backedges,cur,trace_index;
    uint32_t trace[RECOMP_ENTER_SIZE];
    double fp[RECOMP_X87_SLOTS];int64_t fp_integer[RECOMP_X87_SLOTS];
    uint64_t mm[8];xmm_t xmm[8];uint32_t mxcsr;
    int fp_top,fp_cmp,fp_sp;uint16_t fp_cw;
} state;
typedef struct event {unsigned kind;state cpu;} event;
static event log_events[MAX_EVENTS],saved_events[MAX_EVENTS];
static state saved_final;
static uint8_t saved_memory[MEMORY_BYTES];
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
    if(benchmarking)return;
    if(events>=MAX_EVENTS){fprintf(stderr,"DIFFERENTIAL FAIL: runaway callback/yield loop\n");exit(2);}
    log_events[events].kind=kind;log_events[events++].cpu=capture();
}
void recomp_protocol_violation(uint32_t site,uint32_t target,uint32_t regs) {
    fprintf(stderr,"protocol violation %08x %08x %x\n",site,target,regs);abort();
}
static void callback(unsigned kind,unsigned pop) {
    assert(++callbacks<MAX_EVENTS);record(kind);
    uint32_t object=g_ecx,arg=MEM32(g_esp+4);
    if(callback_policy&1) {
        if(kind==3) {MEM32(object+0x44)=MEM32(ROOT_VA+0xA4);MEM32(object+0x14)=17;}
        if(kind==4) {MEM8(arg+0xC)=1;MEM32(arg+0x44)=MEM32(g_ecx+0xA4);}
    }
    if((callback_policy&2)&&kind==4) {
        /* A callback changes traversal order: the loop must reread next. */
        uint32_t node=MEM32(ROOT2_VA+0x10);
        if(node)MEM32(node)=HEAD_VA;
    }
    if((callback_policy&4)&&kind==4) {
        /* Mode is reread from the original guest stack after virtual calls. */
        MEM32(g_esp+0x20)=0xA5010001u;
    }
    if((callback_policy&16)&&kind==4) {
        uint32_t saved_sp=g_esp;
        g_esp-=12;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=3;MEM32(g_esp+8)=0;
        g_ecx=ROOT2_VA+0x200;nested_commands();assert(g_esp==saved_sp);
    }
    g_eax=0xA5000000u|(kind<<16)|callbacks;
    if(kind==5)g_eax=(callback_policy&8)?0xA5010001u:MEM32(ROOT2_VA+0x14);
    g_ecx=0x13570000u|callbacks;g_edx=0xC6000000u|(kind<<16)|callbacks;
    g_flag_k=FK_TEST;g_flag_a=g_eax;g_flag_b=kind;g_flag_cf=0;
    g_st[(callbacks+3u)&7u]+=0.25;g_st_i64[callbacks&7u]^=0x1122334455667788ll;
    g_fp_top=(g_fp_top+1)&7;g_fpu_cw^=0x400u;void_fpu_cmp^=3;
    g_mm[(callbacks+1u)&7u]^=0xAABBCCDDEEFF0011ull;
    ((uint32_t *)g_xmm)[callbacks&31u]^=0x52198BCAu;g_mxcsr^=0x2000u;
    g_esp+=pop;
}
static void test_yield(void) {
    ++yields;record(6);
    g_eax^=0x5A000000u;g_edx^=0x12345678u;
    if(yield_policy==1) {g_ebp=0x80000000u;MEM32(ROOT_VA+0xA4)^=1;}
    if(yield_policy==2 && g_edi==MEM32(ROOT_VA+0x68))MEM32(ROOT_VA+0x68)=ROOT2_VA+0x40;
    if(yield_policy==3)g_ebx=ROOT2_VA;
    /* Flags remain local across the yield in the actual original protocol. */
    g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;
    g_st[3]+=0.5;g_st_i64[1]^=0x1010101010101010ll;
    ((uint32_t *)g_xmm)[11]^=0xAFFEBCCDu;
}
static void weak_zero(void) {callback(1,4);}
static void node_free(void) {callback(2,4);}
static void resources_clear(void) {callback(3,4);}
static void command_rebuild(void) {callback(4,8);}
static void command_mode(void) {callback(5,4);}
recomp_func_t void_resolve(uint32_t address) {assert(address==0x1234u);return command_mode;}
#define WEAK_ZERO weak_zero
#define NODE_FREE node_free
#define RESOURCES_CLEAR resources_clear
#define COMMAND_REBUILD command_rebuild
#include "names.h"
#include "oracle.h"
void CANONICAL_ENTRY(void) {++oracle_calls;oracle_commands();}
#include "actual.h"

static void setup(uint32_t seed,unsigned count) {
    assert(count<=64);random_state=seed?seed:1;memset(memory,0xCD,sizeof memory);
    g_eax=random_next();g_ecx=ROOT_VA;g_edx=random_next();g_ebx=random_next();
    g_esp=STACK_VA;g_ebp=random_next();g_esi=random_next();g_edi=random_next();
    g_flag_k=FK_ADD;g_flag_a=random_next();g_flag_b=random_next();g_flag_cf=1;
    g_backedges=seed%4u;g_cur_func=0x11111111;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
    g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;g_mxcsr=0x3F80;
    g_fp_top=5;g_fpu_cw=0xB7F;void_fpu_cmp=0x41;
    MEM32(STACK_VA)=0x91919191;MEM32(STACK_VA+4)=seed%2?10u:0x80000001u;
    MEM32(STACK_VA+8)=0xA5010001u;
    MEM32(ROOT_VA+0x68)=MEM32(ROOT2_VA+0x68)=HEAD_VA;
    MEM32(ROOT_VA+0xA4)=0x2468ACE0;MEM32(ROOT2_VA+0xA4)=0x2468ACE1;
    MEM32(ROOT2_VA+0x10)=0;MEM32(ROOT2_VA+0x14)=0xA5010001u;
    MEM32(ROOT2_VA+0x268)=0x4000;MEM32(0x4000)=MEM32(0x4004)=0x4000;
    MEM32(VT_VA+0x20)=0x1234;
    MEM32(HEAD_VA)=count?NODE_VA:HEAD_VA;
    MEM32(HEAD_VA+4)=count?NODE_VA+(count-1)*16:HEAD_VA;
    MEM32(HEAD_VA+8)=0;
    for(unsigned i=0;i<count;i++) {
        uint32_t node=NODE_VA+16*i,obj=CMD_VA+0x80*i,r=random_next();
        MEM32(node)=i+1<count?node+16:HEAD_VA;
        MEM32(node+4)=i?node-16:HEAD_VA;
        MEM32(node+8)=(r%11==0)?0:obj;
        MEM32(obj)=VT_VA;MEM32(obj+4)=(r%7==0)?0x80000000u:0;
        MEM32(obj+8)=r%3;MEM8(obj+0xC)=(uint8_t)(r%5==0?0x80u:r%4==0?1u:0u);
        const uint32_t times[]={0,1,9,10,11,0x7FFFFFFF,0x80000000,0x80000001,UINT32_MAX};
        MEM32(obj+0x10)=times[(r>>7)%9];MEM32(obj+0x14)=times[(r>>12)%9];
        MEM32(obj+0x44)=(r%4==0)?UINT32_MAX:(r%3==0)?0x2468ACE1:0x2468ACE0;
    }
    callbacks=yields=events=0;memset(log_events,0,sizeof log_events);
    recomp_yield_hook=test_yield;
}
static int compare_case(uint32_t seed,unsigned count,int policy,int yp) {
    callback_policy=policy;yield_policy=yp;setup(seed,count);nested_commands=oracle_commands;oracle_commands();
    saved_final=capture();memcpy(saved_memory,memory,sizeof memory);
    unsigned expected_events=events,expected_callbacks=callbacks,expected_yields=yields;
    memcpy(saved_events,log_events,sizeof log_events);
    setup(seed,count);nested_commands=void_scene_native_commands;void_scene_native_commands();state actual=capture();
    if(memcmp(&saved_final,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)||
       expected_events!=events||expected_callbacks!=callbacks||expected_yields!=yields||
       memcmp(saved_events,log_events,events*sizeof log_events[0])) {
        fprintf(stderr,"DIFFERENTIAL FAIL case=%d seed=%u count=%u policy=%d yield=%d events=%u/%u\n",
                case_number,seed,count,policy,yp,expected_events,events);
        for(unsigned i=0;i<8;i++)if(saved_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,saved_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<4;i++)if(saved_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,saved_final.flags[i],actual.flags[i]);
        for(unsigned i=0;i<events&&i<expected_events;i++)if(memcmp(&saved_events[i],&log_events[i],sizeof(event))){
            fprintf(stderr,"firstevent%u kinds%u/%u\n",i,saved_events[i].kind,log_events[i].kind);
            for(unsigned j=0;j<8;j++)if(saved_events[i].cpu.regs[j]!=log_events[i].cpu.regs[j])fprintf(stderr,"eventreg%u %08x/%08x\n",j,saved_events[i].cpu.regs[j],log_events[i].cpu.regs[j]);break;
        }
        for(unsigned i=0;i<sizeof memory;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"firstmemory%08x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    return 0;
}
int main(int argc,char **argv) {
    for(unsigned i=0;i<160;i++) {
        ++case_number;
        if(compare_case(i*0x9E3779B9u+1u,i%33u,(int)(i%32u),(int)(i%4u)))return 1;
    }
    /* Empty, unsigned boundary, AL-only results and captured final comparison. */
    for(unsigned n=0;n<5;n++)for(unsigned y=0;y<4;y++) {
        ++case_number;if(compare_case(0xFFFFF000u+n,n,15,(int)y))return 1;
    }
    remove("native-scene");
    int native_mode=argc>1&&!strcmp(argv[1],"native");
    if(argc>1){FILE *f=fopen("native-scene","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    setup(7,0);oracle_calls=0;logs=0;void_scene_native_dispatch();
    assert(oracle_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-scene","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(7,0);void_scene_native_dispatch();assert(oracle_calls==(native_mode?0:2)&&logs==1);
    setup(19,24);callback_policy=16;yield_policy=0;nested_commands=void_scene_native_dispatch;
    void_scene_native_dispatch();assert(native_mode?oracle_calls==0:oracle_calls>2);assert(logs==1);
    remove("native-scene");
    printf("PASS %d differential cases: full guest memory/GPR/flags/x87/MMX/XMM/TRACE/callback/yield state; cached router mode%s\n",case_number,native_mode?"1":"0");
    return 0;
}
'''


class SceneNativeTest(unittest.TestCase):
    def check_edition(self, edition, protocol_check=False, mutant=None, trace=True):
        entry, unit, calls = FACTS[edition]
        oracle = transformed(edition, 'sub_' + entry, unit)
        self.assertIn('RECOMP_EXIT_P(0xFFu)', oracle)
        self.assertNotIn('RECOMP_FLAGS_OUT(); esp += 12', oracle)
        plan = json.loads((protocol_root(edition) / 'x87.json').read_text())['sub_' + entry]
        self.assertEqual((plan['c'], plan['p'], plan['depth'], plan['calls']), (0, 0, {}, {}))
        getter_source = '\n'.join(transformed(edition, 'sub_' + address) for address in calls[4:])
        oracle = oracle.replace('void sub_' + entry + '(void)', 'void oracle_commands(void)', 1)
        source = adapt((ROOT / 'android/host/scene_native.c').read_text(), edition)
        if mutant:
            source = mutant(source)
        names = '#define CANONICAL_ENTRY sub_' + entry + '\n'
        for actual, stub in zip(calls[:4], ('WEAK_ZERO', 'NODE_FREE', 'RESOURCES_CLEAR', 'COMMAND_REBUILD')):
            names += '#define sub_' + actual + ' ' + stub + '\n'
        suffix = ('-protocol' if protocol_check else '') + ('-mutant' if mutant else '') + ('-notrace' if not trace else '')
        out = ROOT / 'build/tests' / ('scene-native-' + edition + suffix)
        out.mkdir(parents=True, exist_ok=True)
        header = pc_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        files = {'recomp_types.h': header, 'host.h': '#include "recomp_types.h"\n',
                 'native_mode.h': (ROOT / 'android/host/native_mode.h').read_text(encoding='utf-8'),
                 'names.h': names, 'oracle.h': getter_source + '\n' + oracle,
                 'actual.h': source, 'probe.c': HARNESS if trace else HARNESS.replace('#define RECOMP_TRACE', '/* Production trace disabled. */')}
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
        tested = command([out / 'probe.exe'], out, env, check=False)
        if mutant:
            self.assertNotEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            self.assertIn('DIFFERENTIAL FAIL', tested.stderr)
            return
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
        enabled = command([out / 'probe.exe', 'native'], out, env, check=False)
        self.assertEqual(enabled.returncode, 0, enabled.stdout + enabled.stderr)
        for invalid in ('0', '01', '1\nextra', '2', '1\r\n'):
            rejected = command([out / 'probe.exe', invalid], out, env, check=False)
            self.assertEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        print(edition + suffix + ': ' + tested.stdout.strip() + '; ' + enabled.stdout.strip())
        (out / 'receipt.json').write_text(json.dumps({
            'edition': edition, 'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'oracle_sha256': hashlib.sha256(oracle.encode()).hexdigest(),
            'runtime_sha256': hashlib.sha256(header.encode()).hexdigest(),
            'protocol_check': protocol_check, 'results': [tested.stdout, enabled.stdout],
            'trace': trace, 'x87_window_slots': 256,
            'device_tested': False}, indent=2) + '\n', encoding='utf-8')

    def test_all_three_current_production_bodies(self):
        for edition in FACTS:
            with self.subTest(edition=edition):
                self.check_edition(edition)

    def test_protocol_check_full_publication_and_trace(self):
        self.check_edition('toe', protocol_check=True)

    def test_production_without_trace(self):
        self.check_edition('toe', trace=False)

    def test_reject_lost_upper_eax_bits(self):
        self.check_edition('toe', mutant=lambda s: s.replace('(eax & 0xFFFFFF00u) | SCENE_COMMAND(ecx)->ready', 'SCENE_COMMAND(ecx)->ready'))

    def test_reject_recomputed_comparison_after_yield(self):
        self.check_edition('toe', mutant=lambda s: s.replace('} while (more);', '} while (edi != MEM32(ebx + 0x68));'))


if __name__ == '__main__':
    unittest.main()
