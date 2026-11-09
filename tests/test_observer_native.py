"""CChunklessSerializer forwarding versus all three production-transformed originals."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

from test_static_tls import ROOT
HERE = ROOT / 'build/tests/observer-native'
HERE.mkdir(parents=True,exist_ok=True)
SOURCE = ROOT / 'android/host/observer_native.c'
from test_scene_native import HARNESS as SCENE_HARNESS, transformed
import pefile
sys.path.insert(0,str(ROOT / 'tools'))
from editions import generated_root
from test_mmx_packed import CLANG, command, environment, pc_header

UNITS = {'toe':('game_0646.c','game_0173.c','game_0000.c','game_0383.c'),
         'vanilla':('game_0630.c','game_0200.c','game_0003.c','game_0071.c'),
         'hof':('game_0487.c','game_0063.c','game_0027.c','game_0489.c')}
VTABLES = {'toe':0xE8D7BC,'vanilla':0xE5E47C,'hof':0xE1A01C}
IMAGE_HASHES = {'toe':'6502a8c4cd0e03e9ce43b474bcb4a85acb8b8bf5050d56317e93c8f13fff50bd',
 'vanilla':'2b4e8bd32bd929e8caf1d53f74bc4aa6be56c362080549b9dc675d4e88289950',
 'hof':'bad3b0c010b9d85193811bdf8ffa2afab30b865ea924c480ff7aac78a1e73140'}

FACTS = {
    'toe': ('00C48A30', '0061F290', '004033B0', '008C7450'),
    'vanilla': ('00BB9AE0', '0065B5D0', '00409920', '004B35E0'),
    'hof': ('009EE700', '004C04D0', '0044E370', '009F4870'),
}

def adapt(source, edition):
    addresses = dict(zip(FACTS['toe'], FACTS[edition]))
    def address(match):
        value = match[1]
        if 0xC48A30 <= int(value, 16) <= 0xC48A77:
            return f'{int(FACTS[edition][0],16)+int(value,16)-0xC48A30:08X}'
        return addresses.get(value, value)
    return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])', address, source)

PREFIX = SCENE_HARNESS[:SCENE_HARNESS.index('static void callback(')]
PREFIX = PREFIX.replace('typedef struct event {unsigned kind;state cpu;} event;',
                        'typedef struct event {unsigned kind;state cpu;uint8_t *guest_memory;} event;')
PREFIX = PREFIX.replace('log_events[events].kind=kind;log_events[events++].cpu=capture();',
                        'log_events[events].guest_memory=malloc(sizeof memory);assert(log_events[events].guest_memory);'
                        'memcpy(log_events[events].guest_memory,memory,sizeof memory);'
                        'log_events[events].kind=kind;log_events[events++].cpu=capture();')
FIXTURE = r'''
enum { OWNER=0x1000,SUBJECT=0x5000,VTABLE=0x3000,VBASE=0x3800,BUFFER=0xA000,
       BUFFER2=0xA400,DATA=0xC000,DATA2=0xD000 };
static unsigned callback_mode,allocation_mode;
static uint32_t original_argument;
static jmp_buf callback_abort;
static unsigned aborted_kind;
static void subject_callback(void) {
    assert(++callbacks<MAX_EVENTS);record(1);
    assert(MEM32(g_esp+4)==original_argument);
    if(callback_mode&32){aborted_kind=1;longjmp(callback_abort,1);}
    if(callback_mode&1)MEM32(OWNER+0x14)=BUFFER2;
    if(callback_mode&2)MEM32(OWNER+0x14)=0;
    if(callback_mode&4)MEM32(BUFFER+0x10)=DATA+0xFC;
    if(callback_mode&8)MEM32(g_esp+12)^=0x22334455u;
    if(callback_mode&16) {
        uint32_t saved_sp=g_esp;g_esp-=8;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=7;
        g_ecx=ROOT2_VA;nested_commands();assert(g_esp==saved_sp);
    }
    g_eax=0xA5F30000u|case_number;g_ecx=0x79AABBu;g_edx=0x12345678u;
    g_flag_k=FK_TEST;g_flag_a=g_eax;g_flag_b=7;g_flag_cf=0;
    g_st[3]+=0.25;g_st_i64[2]^=0x1122334455667788ll;
    ((uint32_t *)g_xmm)[13]^=0xA8B21234u;g_mxcsr^=0x2000u;
    g_esp+=8;
}
static void allocate_callback(void) {
    assert(++callbacks<MAX_EVENTS);record(2);
    if(allocation_mode&4){aborted_kind=2;longjmp(callback_abort,1);}
    uint32_t buffer=g_ecx,offset=MEM32(g_esp+4),capacity=MEM32(g_esp+8);
    if(allocation_mode&1) {
        MEM32(buffer+4)=DATA2;MEM32(buffer+8)=DATA2+capacity;
        MEM32(buffer+0xC)=DATA2+offset;MEM32(buffer+0x10)=DATA2+offset+4;
        MEM32(buffer+0x14)&=~1u;
    } else MEM32(buffer+0x14)|=1u;
    if(allocation_mode&2)MEM32(OWNER+0x14)=BUFFER2;
    g_eax=0xFEDCBA21u;g_ecx=0x23456789u;g_edx=0xDEADBEEFu;
    g_flag_k=FK_ADD;g_flag_a=0x12345678;g_flag_b=9;g_flag_cf=0;
    g_st[2]+=0.5;g_st_i64[3]^=0xAABBCCDDEEFF0011ull;
    ((uint32_t *)g_xmm)[17]^=0xBB442211;g_mm[5]^=0x21345678ABCDEF99ull;
    g_esp+=12;
}
static void test_yield(void) {
    ++yields;record(3);g_eax^=0xAABB0000;g_edx^=0x12344321;
    g_flag_k=FK_TEST;g_flag_a=0x13572468;g_flag_b=8;g_flag_cf=0;
    g_st[1]+=0.125;g_st_i64[4]^=0x1357246813572468ll;
}
recomp_func_t void_resolve(uint32_t target) {
    if(target==0x3333)return subject_callback;
    assert(target==0x4444);return allocate_callback;
}
#include "names.h"
#include "oracle.h"
void OBSERVER_CANONICAL(void) {++oracle_calls;observer_oracle();}
#include "actual.h"

static int same_events(unsigned count) {
    if(count!=events)return 0;
    for(unsigned i=0;i<count;i++)if(saved_events[i].kind!=log_events[i].kind ||
        memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state)) ||
        memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory))return 0;
    return 1;
}

static void setup(uint32_t seed,unsigned scenario) {
    random_state=seed?seed:1;memset(memory,0xCD,sizeof memory);
    g_eax=random_next();g_ecx=OWNER;g_edx=random_next();g_ebx=random_next();
    g_esp=STACK_VA;g_ebp=random_next();g_esi=random_next();g_edi=DATA+4;
    g_flag_k=FK_ADD;g_flag_a=random_next();g_flag_b=random_next();g_flag_cf=1;
    g_backedges=seed%4;g_cur_func=0x11998877;g_enter_idx=0;
    memset(g_enter_trace,0,sizeof g_enter_trace);g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;
    g_mxcsr=0x3F80;g_fp_top=5;g_fpu_cw=0xB7F;void_fpu_cmp=0x41;
    MEM32(STACK_VA)=0xDEADC0DE;original_argument=0xBBDD0000|seed;MEM32(STACK_VA+4)=original_argument;
    MEM32(OWNER+0x10)=SUBJECT;MEM32(OWNER+0x14)=BUFFER;
    MEM32(ROOT2_VA+0x10)=0;
    MEM32(SUBJECT)=VTABLE;MEM32(VTABLE)=0x3333;MEM32(VTABLE+4)=0x4444;
    MEM32(SUBJECT+4)=VBASE;MEM32(VBASE+4)=0x3C;MEM8(SUBJECT+0x40+7)=0;
    for(unsigned i=0;i<2;i++) {
        uint32_t buffer=i?BUFFER2:BUFFER,data=i?DATA2:DATA;
        MEM32(buffer)=VTABLE;MEM32(buffer+4)=data;MEM32(buffer+8)=data+0x100;
        MEM32(buffer+0xC)=data+0x20;MEM32(buffer+0x10)=data+8;MEM32(buffer+0x14)=4;
    }
    switch(scenario%10) {
    case 0:MEM32(OWNER+0x10)=0;break;
    case 1:MEM8(SUBJECT+0x40+7)=0x80;break;
    case 2:MEM32(OWNER+0x14)=0;break;
    case 3:MEM32(BUFFER+0x10)=DATA+0xFC;break;
    case 4:MEM32(BUFFER+0x10)=DATA+0x100;break;
    case 5:MEM32(BUFFER+0x10)=DATA+0x100;MEM32(BUFFER+0x14)=1;break;
    case 6:MEM32(BUFFER+0x10)=BUFFER+0xC;break;
    case 7:MEM32(OWNER+0x14)=STACK_VA-0x18;break;
    case 8:MEM32(VBASE+4)=0xFFFFDFFCu;MEM8(SUBJECT+0xFFFFDFFCu+4+7)=0;break;
    default:break;
    }
    callbacks=yields=events=aborted_kind=0;memset(log_events,0,sizeof log_events);recomp_yield_hook=test_yield;
}
static int compare(unsigned seed,unsigned scenario,int which) {
    callback_mode=(seed>>4)&63;allocation_mode=(seed>>2)&7;
    setup(seed,scenario);
    if(which==1)g_ecx=(scenario&1)?0:SUBJECT;
    if(which==2) {
        g_ecx=BUFFER;MEM32(STACK_VA+4)=(scenario&1)?0:0xFFFFFFFCu;
        MEM32(BUFFER+0xC)=0xFFFFFF00u;MEM32(BUFFER+8)=UINT32_MAX;
    }
    nested_commands=observer_oracle;
    if(!setjmp(callback_abort)) {
        if(which==0)observer_oracle();else if(which==1)BASE_ORACLE();else ADVANCE_ORACLE();
    }
    saved_final=capture();memcpy(saved_memory,memory,sizeof memory);memcpy(saved_events,log_events,sizeof log_events);
    unsigned expected_events=events,expected_callbacks=callbacks,expected_yields=yields,expected_aborted=aborted_kind;
    setup(seed,scenario);
    if(which==1)g_ecx=(scenario&1)?0:SUBJECT;
    if(which==2) {
        g_ecx=BUFFER;MEM32(STACK_VA+4)=(scenario&1)?0:0xFFFFFFFCu;
        MEM32(BUFFER+0xC)=0xFFFFFF00u;MEM32(BUFFER+8)=UINT32_MAX;
    }
    nested_commands=void_observer_native_forward;
    if(!setjmp(callback_abort)) {
        if(which==0)void_observer_native_forward();else if(which==1)observer_base();else observer_advance();
    }
    state actual=capture();
    if(memcmp(&saved_final,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)||
       expected_events!=events||expected_callbacks!=callbacks||expected_yields!=yields||expected_aborted!=aborted_kind||
       !same_events(expected_events)) {
        fprintf(stderr,"DIFFERENTIAL FAIL case%d seed%u scenario%u entry%d events%u/%u\n",case_number,seed,scenario,which,expected_events,events);
        for(unsigned i=0;i<8;i++)if(saved_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,saved_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<4;i++)if(saved_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,saved_final.flags[i],actual.flags[i]);
        if(saved_final.trace_index!=actual.trace_index)fprintf(stderr,"traceidx%u/%u\n",saved_final.trace_index,actual.trace_index);
        for(unsigned i=0;i<events&&i<expected_events;i++)if(memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state)) ||
            memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory)){
            fprintf(stderr,"firstevent%u kind%u/%u\n",i,saved_events[i].kind,log_events[i].kind);
            for(unsigned j=0;j<8;j++)if(saved_events[i].cpu.regs[j]!=log_events[i].cpu.regs[j])fprintf(stderr,"eventreg%u %08x/%08x\n",j,saved_events[i].cpu.regs[j],log_events[i].cpu.regs[j]);break;
        }
        for(unsigned i=0;i<sizeof memory;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"memory%08x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    for(unsigned i=0;i<events;i++){free(saved_events[i].guest_memory);free(log_events[i].guest_memory);}
    return 0;
}
int main(int argc,char **argv) {
    for(unsigned i=0;i<160;i++)for(int which=0;which<3;which++) {
        ++case_number;if(compare(i*0x9E3779B9u+1u,i,which))return 1;
    }
    int native_mode=argc>1&&!strcmp(argv[1],"native");remove("native-observer");
    if(argc>1){FILE *f=fopen("native-observer","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    setup(7,0);oracle_calls=0;logs=0;void_observer_native_dispatch();assert(oracle_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-observer","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(7,0);void_observer_native_dispatch();assert(oracle_calls==(native_mode?0:2)&&logs==1);remove("native-observer");
    setup(19,9);callback_mode=16;nested_commands=void_observer_native_dispatch;
    void_observer_native_dispatch();assert(native_mode?oracle_calls==0:oracle_calls>2);assert(logs==1);
    printf("PASS %d cases(full memory/GPR/flags/x87/XMM/callback/yield/TRACE), cached mode%d\n",case_number,native_mode);
    return 0;
}
'''



class ObserverNativeTest(unittest.TestCase):
    def check_originals(self,edition):
        image=generated_root(edition)/'input/H5_Game.exe'
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),IMAGE_HASHES[edition])
        pe=pefile.PE(str(image),fast_load=True)
        get=lambda address,size:pe.get_data(address-pe.OPTIONAL_HEADER.ImageBase,size)
        word=lambda address:int.from_bytes(get(address,4),'little')
        vtable=VTABLES[edition];col=word(vtable-4);td=word(col+12)
        self.assertEqual(word(vtable+0x34),int(FACTS[edition][0],16))
        self.assertEqual((word(col),word(col+4)),(0,0))
        self.assertEqual(get(td+8,128).split(b'\0',1)[0],b'.?AVCChunklessSerializer@@')
        normalized_hashes=('39ecce1e9ed43f3dc2b9d1dee6b66e4347d52f34e5c69a6198f38777b64a9367',
            '2c0326b3b6e948c7913de646824b2ccd51fe61e4f1e236a6448ae078af9c6a60',
            'ac59db5bbab89b5eaf8d615a90ae24b70404777f09fa1c52fab0dad2ea82563c',
            'b2f81a794a4c6ccd1a56e4d5ae4516a46a17d6c0cfc69efd93f3c7fdff88dbef')
        for index,size in enumerate((0x4A,0x12,0x27,0x78)):
            address=int(FACTS[edition][index],16);data=bytearray(get(address,size))
            sites=((0xA,1),(0x34,2)) if index==0 else ((0x1D,3),) if index==2 else ()
            for offset,target_index in sites:
                self.assertEqual(data[offset],0xE8 if index==0 else 0xE9)
                target=(address+offset+5+int.from_bytes(data[offset+1:offset+5],'little',signed=True))&0xFFFFFFFF
                self.assertEqual(target,int(FACTS[edition][target_index],16))
                data[offset+1:offset+5]=b'\0'*4
            self.assertEqual(hashlib.sha256(data).hexdigest(),normalized_hashes[index])
        pe.close()

    def check_edition(self, edition, protocol=False, trace=True, mutant=None):
        entry, base, advance, grow = FACTS[edition]
        self.check_originals(edition)
        source = adapt(SOURCE.read_text(encoding='utf-8'), edition)
        if mutant:
            source = mutant(source)
        declarations = '\n'.join('void sub_' + address + '(void);' for address in (base, advance, grow))
        oracle = declarations + '\n' + '\n'.join(transformed(edition,'sub_'+FACTS[edition][index],UNITS[edition][index]) for index in (1,3,2,0))
        oracle = oracle.replace('void sub_' + entry + '(void)', 'void observer_oracle(void)', 1)
        names = f'#define OBSERVER_CANONICAL sub_{entry}\n#define BASE_ORACLE sub_{base}\n#define ADVANCE_ORACLE sub_{advance}\n'
        label = edition + ('-protocol' if protocol else '') + ('-notrace' if not trace else '') + ('-mutant' if mutant else '')
        out = HERE / ('probe-' + label)
        out.mkdir(exist_ok=True)
        header = pc_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        prefix = PREFIX if trace else PREFIX.replace('#define RECOMP_TRACE', '/* Trace disabled. */')
        files = {'recomp_types.h': header, 'host.h': '#include "recomp_types.h"\n',
                 'native_mode.h': (ROOT / 'android/host/native_mode.h').read_text(encoding='utf-8'),
                 'probe.c': prefix + FIXTURE, 'actual.h': source, 'oracle.h': oracle, 'names.h': names}
        for name, value in files.items():
            (out / name).write_text(value, encoding='utf-8')
        env, linker = environment('x64')
        flags = [CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
                 '/clang:--target=x86_64-pc-windows-msvc', '/clang:-fno-strict-aliasing', '/clang:-fwrapv', '/clang:-ffp-contract=off']
        if protocol:flags.append('/DRECOMP_PROTOCOL_CHECK')
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
        for invalid in ('0','01','1\r\n','1\nextra','2'):
            rejected=command([out / 'probe.exe', invalid],out,env,check=False)
            self.assertEqual(rejected.returncode,0,rejected.stdout+rejected.stderr)
        print(label + ': ' + tested.stdout.strip() + '; ' + enabled.stdout.strip())
        (out / 'receipt.json').write_text(json.dumps({'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'oracle_sha256': hashlib.sha256(oracle.encode()).hexdigest(), 'edition': edition,
            'protocol_check': protocol,'trace': trace,'results': [tested.stdout,enabled.stdout],
            'physical_device_executed': False},indent=2)+'\n',encoding='utf-8')

    def test_all_three_production_oracles(self):
        for edition in FACTS:
            with self.subTest(edition=edition):self.check_edition(edition)

    def test_protocol_check(self):
        self.check_edition('toe',protocol=True)

    def test_no_trace(self):
        self.check_edition('toe',trace=False)

    def test_reject_lost_upper_eax_in_advance(self):
        self.check_edition('toe',mutant=lambda s:s.replace('(eax&0xFFFFFF00u)|1u','1u'))

    def test_reject_stale_output_target(self):
        self.check_edition('toe',mutant=lambda s:s.replace('esi=FORWARDER(esi)->output;','esi=0xA000u;'))


if __name__ == '__main__':
    unittest.main()
