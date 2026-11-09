"""Three typed fixed-point transforms versus all nine production originals."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from test_static_tls import ROOT
HERE=ROOT/'build/tests/skin-math-native'
HERE.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'android/host/skin_math_native.c'
from test_mmx_packed import CLANG,command,environment,pc_header
from test_scene_native import HARNESS as SCENE_HARNESS
from test_scene_native import transformed
import pefile
sys.path.insert(0,str(ROOT/'tools'))
from editions import generated_root

# Independently verified original PE spans and ABI facts; not derived from live adapter.
CONTRACTS={'toe': {'image_sha256': '6502a8c4cd0e03e9ce43b474bcb4a85acb8b8bf5050d56317e93c8f13fff50bd',
         'functions': [{'entry': '00C68210',
                        'unit': 'game_0657.c',
                        'size': 191,
                        'normalization_table': '010CE990',
                        'weight_table': None,
                        'raw_sha256': 'd911021330b8acf0e063d5cc0ee93b3141ed7db10f14176c33b5568c15a0694d',
                        'normalized_sha256': '31cc13adb692c81c6d17d01000c94a09f431f00f5fbdc9c102158d2a3e6902d9',
                        'data_relocations': [{'address': '010CE990', 'operand_offsets': [140]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': 'e02d5529c9e8f0ed0f0bfcc408ac2f50d55c741102dc137cb2f4fa4c43853437'},
                       {'entry': '00C682D0',
                        'unit': 'game_0657.c',
                        'size': 258,
                        'normalization_table': '010CE990',
                        'weight_table': '010CD990',
                        'raw_sha256': '1f99424b2236c8f54a39b6760a0ffb6e740dbb4e833af903bc608de2d05a13b1',
                        'normalized_sha256': '4382e24c76047ab952e104234c48d5a864816b99373b7fc6cb559babbb71e343',
                        'data_relocations': [{'address': '010CE990', 'operand_offsets': [207]},
                                             {'address': '010CD990', 'operand_offsets': [160, 168]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': '572060650dfa987bb7c53d106c2f318db32c0bc2c98e62a53f6a6283fa9d5253'},
                       {'entry': '00C683E0',
                        'unit': 'game_0657.c',
                        'size': 308,
                        'normalization_table': '010CE990',
                        'weight_table': '010CD990',
                        'raw_sha256': '01cf878cd90e0c0e4a9e2152900301408f5c4bedfef41b7cbfb23f15359c4d9f',
                        'normalized_sha256': '1598c21625f3fd23390bdfc11697169d7e12f95064b780ffb8fcf0334a4bc516',
                        'data_relocations': [{'address': '010CE990', 'operand_offsets': [257]},
                                             {'address': '010CD990', 'operand_offsets': [199, 207, 215]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': 'c71aaf3f9e8c6de68033c5639d52b389eb41aefe2e502267fda2235fac69bbd8'}]},
 'vanilla': {'image_sha256': '2b4e8bd32bd929e8caf1d53f74bc4aa6be56c362080549b9dc675d4e88289950',
             'functions': [{'entry': '008C52B0',
                            'unit': 'game_0392.c',
                            'size': 191,
                            'normalization_table': '00F7A5E8',
                            'weight_table': None,
                            'raw_sha256': 'ebf34e06edc0634c25ab3ee3ddac1665077c6465b9fd59f7d9d41c78dd3c11d0',
                            'normalized_sha256': '31cc13adb692c81c6d17d01000c94a09f431f00f5fbdc9c102158d2a3e6902d9',
                            'data_relocations': [{'address': '00F7A5E8', 'operand_offsets': [140]}],
                            'call_masks': [23, 23, 0],
                            'exit_mask': 23,
                            'flags_in': False,
                            'flags_out': False,
                            'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                            'production_sha256': '8755e7dd71458c61850bce33eda88baab9ac0dab0189a1012197f1ab9f46761c'},
                           {'entry': '008C5370',
                            'unit': 'game_0392.c',
                            'size': 258,
                            'normalization_table': '00F7A5E8',
                            'weight_table': '00F795E8',
                            'raw_sha256': 'ae6234b5a2a5ada9588b2d838bd11ce208a3e9064021202072ac75795ea729d0',
                            'normalized_sha256': '4382e24c76047ab952e104234c48d5a864816b99373b7fc6cb559babbb71e343',
                            'data_relocations': [{'address': '00F7A5E8', 'operand_offsets': [207]},
                                                 {'address': '00F795E8', 'operand_offsets': [160, 168]}],
                            'call_masks': [23, 23, 0],
                            'exit_mask': 23,
                            'flags_in': False,
                            'flags_out': False,
                            'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                            'production_sha256': 'decfa504c19b11a522d162c13eeebb8a673e81b05901358375640484016770a3'},
                           {'entry': '008C5480',
                            'unit': 'game_0392.c',
                            'size': 308,
                            'normalization_table': '00F7A5E8',
                            'weight_table': '00F795E8',
                            'raw_sha256': '828377cdfe54cedbaabc55de259c11fa86718b90050c34305d0cdb91bf74f489',
                            'normalized_sha256': '1598c21625f3fd23390bdfc11697169d7e12f95064b780ffb8fcf0334a4bc516',
                            'data_relocations': [{'address': '00F7A5E8', 'operand_offsets': [257]},
                                                 {'address': '00F795E8', 'operand_offsets': [199, 207, 215]}],
                            'call_masks': [23, 23, 0],
                            'exit_mask': 23,
                            'flags_in': False,
                            'flags_out': False,
                            'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                            'production_sha256': '3860c65c90f4fd577802469ab30d04b47b57a6dc9641f13385b42a1503c520e5'}]},
 'hof': {'image_sha256': 'bad3b0c010b9d85193811bdf8ffa2afab30b865ea924c480ff7aac78a1e73140',
         'functions': [{'entry': '00A45B90',
                        'unit': 'game_0512.c',
                        'size': 191,
                        'normalization_table': '00F9C800',
                        'weight_table': None,
                        'raw_sha256': '1a574ee263025813b2c775ff9a1f922bf67fab8f763735efa76e280a90f29924',
                        'normalized_sha256': '31cc13adb692c81c6d17d01000c94a09f431f00f5fbdc9c102158d2a3e6902d9',
                        'data_relocations': [{'address': '00F9C800', 'operand_offsets': [140]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': '6f568bf7374f93c3ba1f734ba0da4192c54eb3bfc27f8da5285b296be982f94a'},
                       {'entry': '00A45C50',
                        'unit': 'game_0512.c',
                        'size': 258,
                        'normalization_table': '00F9C800',
                        'weight_table': '00F9B800',
                        'raw_sha256': 'bf8e48f142f0a3310b0e323abd2589f9d2ae61d62efc324ca1bcf3568835b0b1',
                        'normalized_sha256': '4382e24c76047ab952e104234c48d5a864816b99373b7fc6cb559babbb71e343',
                        'data_relocations': [{'address': '00F9C800', 'operand_offsets': [207]},
                                             {'address': '00F9B800', 'operand_offsets': [160, 168]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': '76abca9ecd71ee79c2a9c44db537ae18c95fa8b0e6a6af7d3ab8e4605b1c5c82'},
                       {'entry': '00A45D60',
                        'unit': 'game_0512.c',
                        'size': 308,
                        'normalization_table': '00F9C800',
                        'weight_table': '00F9B800',
                        'raw_sha256': 'e837ab38272797115381c7772b750051aaa2f25457418f685c726ec9669f5183',
                        'normalized_sha256': '1598c21625f3fd23390bdfc11697169d7e12f95064b780ffb8fcf0334a4bc516',
                        'data_relocations': [{'address': '00F9C800', 'operand_offsets': [257]},
                                             {'address': '00F9B800', 'operand_offsets': [199, 207, 215]}],
                        'call_masks': [23, 23, 0],
                        'exit_mask': 23,
                        'flags_in': False,
                        'flags_out': False,
                        'x87': {'c': 0, 'p': 0, 'depth': {}, 'calls': {}, 'delta': {}},
                        'production_sha256': 'a9654b742a361b6aa93c520bc52eb9a3b0b440ee221c7ff67a1d875eaedec716'}]}}

def adapt(source,edition):
    originals=CONTRACTS['toe']['functions'];mapped=CONTRACTS[edition]['functions']
    mapping={old['entry']:new['entry'] for old,new in zip(originals,mapped)}
    mapping.update({'010CD990':mapped[1]['weight_table'],'010CE990':mapped[0]['normalization_table']})
    return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])',lambda m:mapping.get(m[1],m[1]),source)

PREFIX=SCENE_HARNESS[:SCENE_HARNESS.index('static void callback(')]
PREFIX=PREFIX.replace('MEMORY_BYTES=0x80000','MEMORY_BYTES=0x20000')
PREFIX=PREFIX.replace('#include "recomp_types.h"',r'''#include "recomp_types.h"
static void *checked_pointer(uint32_t address) {
    if(address>=NORM_TABLE && address<NORM_TABLE+0x8000u)address=0x10000u+address-NORM_TABLE;
    else if(address>=WEIGHT_TABLE && address<WEIGHT_TABLE+0x800u)address=0x8000u+address-WEIGHT_TABLE;
    if(address>sizeof memory-8){fprintf(stderr,"DIFFERENTIAL FAIL invalid guest address %08x\n",address);exit(2);}
    return memory+address;
}
#undef RECOMP_MEM_ADDR
#define RECOMP_MEM_ADDR(va) checked_pointer((uint32_t)(va))
#undef GPTR
#define GPTR(va) checked_pointer((uint32_t)(va))
static inline uint32_t fixture_pop32(uint32_t *stack) {
    uint32_t value=MEM32(*stack);*stack+=4;return value;
}
#undef POP32_VAL
#define POP32_VAL(stack) fixture_pop32(&(stack))
''')
PREFIX=PREFIX.replace('uint16_t g_fpu_cw;', 'uint16_t g_fpu_cw;uint64_t g_fp_round_mask,g_fp_store_mask;')
PREFIX=PREFIX.replace('int fp_top,fp_cmp,fp_sp;uint16_t fp_cw;',
    'int fp_top,fp_cmp,fp_sp;uint16_t fp_cw;uint64_t round_mask,store_mask;')
PREFIX=PREFIX.replace('s.fp_top=g_fp_top;', 's.round_mask=g_fp_round_mask;s.store_mask=g_fp_store_mask;s.fp_top=g_fp_top;')

FIXTURE=r'''
enum { DEST=0x100,SOURCE=0x200,BIAS=0x300,MATRIX0=0x400,MATRIX1=0x500,MATRIX2=0x600,STACK=0x6000 };
#include "names.h"
#include "oracle.h"
void ONE_CANONICAL(void){++oracle_calls;oracle_one();}
void TWO_CANONICAL(void){++oracle_calls;oracle_two();}
void THREE_CANONICAL(void){++oracle_calls;oracle_three();}
#include "actual.h"
static uint8_t input_memory[MEMORY_BYTES];
static state input_cpu;
static void restore(const state *s,const uint8_t *bytes) {
    memcpy(memory,bytes,sizeof memory);
    g_eax=s->regs[0];g_ecx=s->regs[1];g_edx=s->regs[2];g_ebx=s->regs[3];
    g_esp=s->regs[4];g_ebp=s->regs[5];g_esi=s->regs[6];g_edi=s->regs[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    g_backedges=s->backedges;g_cur_func=s->cur;g_enter_idx=s->trace_index;
    memcpy(g_enter_trace,s->trace,sizeof s->trace);memcpy(g_st_win,s->fp,sizeof s->fp);
    memcpy(g_st_i64_win,s->fp_integer,sizeof s->fp_integer);memcpy(g_mm,s->mm,sizeof s->mm);
    memcpy(g_xmm,s->xmm,sizeof s->xmm);g_mxcsr=s->mxcsr;
    g_fp_top=s->fp_top;void_fpu_cmp=s->fp_cmp;g_fp_sp=s->fp_sp;g_fpu_cw=s->fp_cw;
    g_fp_round_mask=s->round_mask;g_fp_store_mask=s->store_mask;
}
static void setup(uint32_t seed,unsigned alias,unsigned bones) {
    random_state=seed?seed:1;
    for(unsigned i=0;i<sizeof memory;i+=4)memcpy(memory+i,&(uint32_t){random_next()},4);
    g_eax=random_next();g_ecx=DEST;g_edx=SOURCE;g_ebx=random_next();
    g_esp=STACK;g_ebp=random_next();g_esi=random_next();g_edi=random_next();
    g_flag_k=FK_CMP;g_flag_a=random_next();g_flag_b=random_next();g_flag_cf=random_next()&1;
    g_backedges=random_next();g_cur_func=0x11998877;g_enter_idx=0;
    memset(g_enter_trace,0,sizeof g_enter_trace);g_fp_sp=120;
    const uint64_t fp_bits[]={0x7FF8000012345678ull,0x7FF0000000000001ull,0x8000000000000000ull,
        0x7FF0000000000000ull,0xFFF0000000000000ull,0xBFF8000000000000ull,0,0x0123456789ABCDEFull};
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++) {
        memcpy(g_st_win+i,fp_bits+(i&7),8);g_st_i64_win[i]=0x7000000000000000ll+i;
    }
    for(unsigned i=0;i<8;i++)g_mm[i]=((uint64_t)random_next()<<32)|random_next();
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=random_next();
    g_mxcsr=random_next();g_fp_top=(int)(seed%9)-1;g_fpu_cw=(uint16_t)(0x37F|((seed&3u)<<10));void_fpu_cmp=0x41;
    g_fp_round_mask=((uint64_t)random_next()<<32)|random_next();g_fp_store_mask=((uint64_t)random_next()<<32)|random_next();
    uint32_t bias=BIAS,m0=MATRIX0,m1=MATRIX1,m2=MATRIX2;
    switch(alias%19) {
    case 1:g_edx=g_ecx;break;
    case 2:bias=g_ecx;break;
    case 3:m0=g_edx;break;
    case 4:bias=m0;break;
    case 5:g_ecx=m0+8;break;
    case 6:g_ecx=bias+4;break;
    case 7:m1=m0;break;
    case 8:m2=m0;break;
    case 9:g_edx=STACK-4;break;
    case 10:g_edx=STACK-8;break;
    case 11:bias=STACK-16;break;
    case 12:m0=STACK-20;break;
    case 13:g_ecx=STACK-12;break;
    case 14:g_ecx=STACK-8;break;
    case 15:g_ecx=STACK+4;break;
    case 16:g_esp=NORM_TABLE+20;break;
    case 17:g_esp=WEIGHT_TABLE+20;break;
    default:break;
    }
    MEM32(g_esp)=RECOMP_RETADDR;
    MEM32(g_esp+4)=bias;MEM32(g_esp+8)=m0;
    if(bones>1) {MEM32(g_esp+12)=random_next();MEM32(g_esp+16)=m1;MEM32(g_esp+20)=random_next();}
    if(bones==3){MEM32(g_esp+24)=m2;MEM32(g_esp+28)=random_next();}
    /* Zero matrices force normalization index0, including table/frame aliases. */
    if((seed&7u)==0) {
        for(unsigned i=0;i<3;i++){MEM64(m0+8*i)=0;MEM64(m1+8*i)=0;MEM64(m2+8*i)=0;}
    }
    recomp_yield_hook=NULL;
}
static uint64_t repeated_word(uint16_t value){return(uint64_t)value*0x0001000100010001ull;}
static void target_case(unsigned target,unsigned bones) {
    MEM32(SOURCE)=0;MEM64(BIAS)=repeated_word(0x8000);MEM64(BIAS+8)=repeated_word(0x8080);
    const uint32_t matrices[]={MATRIX0,MATRIX1,MATRIX2};
    for(unsigned b=0;b<3;b++)for(unsigned c=0;c<3;c++)MEM64(matrices[b]+8*c)=0;
    MEM32(g_esp+12)=0;MEM32(g_esp+20)=1;MEM32(g_esp+28)=2;
    for(unsigned b=0;b<3;b++)MEM64(WEIGHT_TABLE+8*b)=repeated_word(0x7FFF);
    MEM16(NORM_TABLE)=0x7FFF;
    if(target==1) {
        /* Saturation after column0+column1 is observable before column2. */
        for(unsigned b=0;b<3;b++) {
            MEM64(matrices[b])=repeated_word(0x8000);
            MEM64(matrices[b]+8)=repeated_word(0x8000);
            MEM64(matrices[b]+16)=repeated_word(0x7FFF);
        }
    } else if(target==2) {
        /* +16384,+16384,-16384 distinguishes ordered bone saturation. */
        MEM32(SOURCE)=0xA5000040;MEM64(BIAS)=0;
        for(unsigned b=0;b<3;b++) {
            MEM16(matrices[b])=(uint16_t)-8192;
            MEM16(matrices[b]+10)=(uint16_t)-8192;
            MEM16(matrices[b]+20)=(uint16_t)-8192;
        }
        MEM64(WEIGHT_TABLE)=MEM64(WEIGHT_TABLE+8)=repeated_word(0x8000);
    } else if(target==3) {
        /* Four -32768 squared lanes overflow each PMADDWD pair and the sum. */
        MEM64(MATRIX0)=repeated_word(bones==1?8192:1024);
        MEM64(WEIGHT_TABLE+8)=MEM64(WEIGHT_TABLE+16)=0;
        MEM16(NORM_TABLE)=0x8000;
    } else {
        MEM16(NORM_TABLE)=0xFFFF;MEM64(BIAS+8)=UINT64_MAX;
    }
}
static int compare(uint32_t seed,unsigned alias,unsigned bones,unsigned target) {
    setup(seed,alias,bones);if(target)target_case(target,bones);
    input_cpu=capture();memcpy(input_memory,memory,sizeof memory);
    void (*original[3])(void)={oracle_one,oracle_two,oracle_three};
    void (*native[3])(void)={void_skin_math_one,void_skin_math_two,void_skin_math_three};
    original[bones-1]();saved_final=capture();memcpy(saved_memory,memory,sizeof memory);
    restore(&input_cpu,input_memory);native[bones-1]();state actual=capture();
    if(memcmp(&saved_final,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)) {
        fprintf(stderr,"DIFFERENTIAL FAIL case%d seed%u alias%u bones%u target%u\n",case_number,seed,alias,bones,target);
        for(unsigned i=0;i<8;i++)if(saved_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,saved_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<8;i++)if(saved_final.mm[i]!=actual.mm[i])fprintf(stderr,"mm%u %016llx/%016llx\n",i,(unsigned long long)saved_final.mm[i],(unsigned long long)actual.mm[i]);
        for(unsigned i=0;i<4;i++)if(saved_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,saved_final.flags[i],actual.flags[i]);
        for(unsigned i=0;i<sizeof memory;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"memory%08x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    return 0;
}
int main(int argc,char **argv) {
    for(unsigned i=0;i<256;i++)for(unsigned bones=1;bones<=3;bones++) {
        ++case_number;if(compare(i*0x9E3779B9u+1,i%19,bones,0))return 1;
    }
    for(unsigned target=1;target<=4;target++)for(unsigned bones=1;bones<=3;bones++) {
        ++case_number;if(compare(23+target,0,bones,target))return 1;
    }
    int native_mode=argc>1&&!strcmp(argv[1],"native");remove("native-skin-math");
    if(argc>1){FILE *f=fopen("native-skin-math","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    setup(7,0,1);oracle_calls=logs=0;void_skin_math_one_dispatch();assert(oracle_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-skin-math","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(7,0,2);void_skin_math_two_dispatch();assert(oracle_calls==(native_mode?0:2)&&logs==1);
    setup(7,0,3);void_skin_math_three_dispatch();assert(oracle_calls==(native_mode?0:3)&&logs==1);remove("native-skin-math");
    printf("PASS %d typed matrix cases full guest/GPR/MMX/FP-payload/flags/TRACE;cached groupmode%d\n",case_number,native_mode);
    return 0;
}
'''

class SkinMathNativeTest(unittest.TestCase):
    def test_full_actual_builder_keeps_canonical_oracles(self):
        # Isolate builder globals and patched output. Exercise the complete live
        # pipeline, including early production patches and late native routing.
        program=r'''
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tools'))
sys.path.insert(0,str(Path.cwd()/'tests'))
import build_android as builder
from editions import generated_root
from test_scene_native import body,transformed
spec=json.load(sys.stdin)
count=0
for edition,contract in spec['contracts'].items():
    builder.configure_edition(edition)
    for pgo in (False,True):
        builder.PGO_USE=pgo
        builder.OUT=Path(spec['output'])/edition/('pgo' if pgo else 'plain')
        for unit in sorted({f['unit'] for f in contract['functions']}):
            prepared,_=builder.override_source(generated_root(edition)/'game-x86'/unit,local_xmm=True)
            actual=prepared.read_bytes().replace(b'\r\n',b'\n').decode('utf-8')
            for fact in (f for f in contract['functions'] if f['unit']==unit):
                original=body(actual,'sub_'+fact['entry'])
                assert original==transformed(edition,'sub_'+fact['entry'],unit),(edition,pgo,fact['entry'])
                assert hashlib.sha256(original.encode()).hexdigest()==fact['production_sha256']
                count+=1
assert count==18
print('PASS 18 complete-builder canonical oracle comparisons')
'''
        checked=subprocess.run([sys.executable,'-X','utf8','-B','-c',program],cwd=ROOT,
            input=json.dumps({'contracts':CONTRACTS,'output':str(HERE/'actual-builder')}),
            capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        self.assertIn('PASS 18',checked.stdout)

    def check_originals(self,edition):
        contract=CONTRACTS[edition];image=generated_root(edition)/'input/H5_Game.exe'
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),contract['image_sha256'])
        pe=pefile.PE(str(image),fast_load=True)
        for facts in contract['functions']:
            code=bytearray(pe.get_data(int(facts['entry'],16)-pe.OPTIONAL_HEADER.ImageBase,facts['size']))
            self.assertEqual(hashlib.sha256(code).hexdigest(),facts['raw_sha256'])
            for relocation in facts['data_relocations']:
                for offset in relocation['operand_offsets']:
                    self.assertEqual(int.from_bytes(code[offset:offset+4],'little'),int(relocation['address'],16))
                    code[offset:offset+4]=b'\0'*4
            self.assertEqual(hashlib.sha256(code).hexdigest(),facts['normalized_sha256'])
            self.assertEqual((facts['call_masks'],facts['exit_mask'],facts['flags_in'],facts['flags_out']),([23,23,0],23,False,False))
            self.assertEqual((facts['x87']['c'],facts['x87']['p'],facts['x87']['depth'],facts['x87']['calls']),(0,0,{},{}))
        pe.close()
    def check_edition(self,edition,protocol=False,trace=True,mutant=None):
        self.check_originals(edition)
        facts=CONTRACTS[edition]['functions']
        source=adapt(SOURCE.read_text(encoding='utf-8'),edition)
        if mutant:source=mutant(source)
        originals=[transformed(edition,'sub_'+f['entry'],f['unit']) for f in facts]
        for original,fact in zip(originals,facts):
            self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),fact['production_sha256'])
        oracle='\n'.join(originals)
        names=''
        for n,role in enumerate(('one','two','three')):
            entry=facts[n]['entry'];oracle=oracle.replace('void sub_'+entry+'(void)','void oracle_'+role+'(void)',1)
            names+='#define '+role.upper()+'_CANONICAL sub_'+entry+'\n'
        prefix=PREFIX if trace else PREFIX.replace('#define RECOMP_TRACE','/* TRACE disabled. */')
        probe=f'#define NORM_TABLE 0x{facts[0]["normalization_table"]}u\n#define WEIGHT_TABLE 0x{facts[1]["weight_table"]}u\n'+prefix+FIXTURE
        label=edition+('-protocol' if protocol else '')+('-notrace' if not trace else '')+('-mutant' if mutant else '')
        out=HERE/('probe-'+label);out.mkdir(exist_ok=True)
        files={'probe.c':probe,'actual.h':source,'oracle.h':oracle,'names.h':names,
               'native_mode.h':(ROOT/'android/host/native_mode.h').read_text(encoding='utf-8'),
               'host.h':'#include "recomp_types.h"\n','recomp_types.h':pc_header((ROOT/'android/runtime/recomp_types.h').read_text())}
        for name,text in files.items():(out/name).write_text(text,encoding='utf-8')
        env,linker=environment('x64')
        flags=[CLANG,'/nologo','/W0','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS',
            '/clang:--target=x86_64-pc-windows-msvc','/clang:-fno-strict-aliasing','/clang:-fwrapv','/clang:-ffp-contract=off']
        if protocol:flags.append('/DRECOMP_PROTOCOL_CHECK')
        command([*flags,'/c','probe.c','/Foprobe.obj'],out,env)
        command([linker,'/nologo','probe.obj','/OUT:probe.exe','/STACK:1048576'],out,env)
        tested=command([out/'probe.exe'],out,env,check=False)
        if mutant:
            self.assertNotEqual(tested.returncode,0,tested.stdout+tested.stderr);self.assertIn('DIFFERENTIAL FAIL',tested.stderr);return
        self.assertEqual(tested.returncode,0,tested.stdout+tested.stderr)
        enabled=command([out/'probe.exe','native'],out,env,check=False)
        self.assertEqual(enabled.returncode,0,enabled.stdout+enabled.stderr)
        for invalid in ('0','01','1\r\n','1\nextra','2'):
            rejected=command([out/'probe.exe',invalid],out,env,check=False)
            self.assertEqual(rejected.returncode,0,rejected.stdout+rejected.stderr)
        print(label+': '+tested.stdout.strip()+'; '+enabled.stdout.strip())
        (out/'receipt.json').write_text(json.dumps({'edition':edition,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'oracle_sha256':hashlib.sha256(oracle.encode()).hexdigest(),'protocol_check':protocol,'trace':trace,
            'results':[tested.stdout,enabled.stdout],'physical_device_executed':False},indent=2)+'\n',encoding='utf-8')

    def test_all_three_production_oracles(self):
        for edition in CONTRACTS:
            with self.subTest(edition=edition):self.check_edition(edition)
    def test_protocol_check(self):self.check_edition('toe',protocol=True)
    def test_no_trace(self):self.check_edition('toe',trace=False)
    def test_reject_wrapped_matrix_accumulation(self):
        self.check_edition('toe',mutant=lambda s:s.replace('mmx_paddsw(mmx_paddsw(product[0],product[1]),product[2])','mmx_paddw(mmx_paddw(product[0],product[1]),product[2])'))
    def test_reject_reassociated_matrix_accumulation(self):
        self.check_edition('toe',mutant=lambda s:s.replace('mmx_paddsw(mmx_paddsw(product[0],product[1]),product[2])','mmx_paddsw(product[0],mmx_paddsw(product[1],product[2]))'))
    def test_reject_reassociated_bone_accumulation(self):
        self.check_edition('toe',mutant=lambda s:s.replace('combined=mmx_paddsw(weighted[0],weighted[1]);\n        if(bones==3)combined=mmx_paddsw(combined,weighted[2]);',
            'combined=bones==3?mmx_paddsw(weighted[0],mmx_paddsw(weighted[1],weighted[2])):mmx_paddsw(weighted[0],weighted[1]);'))
    def test_reject_lost_fourth_lane_repacking(self):
        self.check_edition('toe',mutant=lambda s:s.replace('mmx_paddw(decoded<<16,decoded>>32)','((decoded<<16)|(decoded>>32))'))
    def test_reject_clobbered_preserved_mmx(self):
        self.check_edition('toe',mutant=lambda s:s.replace('result.mm[5]=g_mm[5];result.mm[6]=g_mm[6];','result.mm[5]=0;result.mm[6]=0;'))
    def test_reject_lost_packed_high_lane(self):
        self.check_edition('toe',mutant=lambda s:s.replace('(packed&0xFF000000u)|(uint32_t)packed_bytes','(packed&0xFF000000u)|((uint32_t)packed_bytes&0x00FFFFFFu)'))
    def test_reject_wrong_third_weight_edx(self):
        self.check_edition('toe',mutant=lambda s:s.replace('if(bones==3)edx=result.third_weight;','(void)result.third_weight;'))

if __name__=='__main__':unittest.main()
