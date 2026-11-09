"""CVBCombiner indexed weight walk: exact production-body differential."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

from test_static_tls import ROOT
HERE=ROOT/'build/tests/skin-native'
HERE.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'android/host/skin_native.c'
from test_observer_native import PREFIX as OBSERVER_PREFIX
from test_scene_native import transformed
import pefile
sys.path.insert(0,str(ROOT/'tools'))
from editions import generated_root
from test_mmx_packed import CLANG,command,environment,pc_header

MAPS={'toe': {'image_sha256': '6502a8c4cd0e03e9ce43b474bcb4a85acb8b8bf5050d56317e93c8f13fff50bd',
         'owner': '.?AVCVBCombiner@NGScene@@',
         'type_descriptor': '00F46004',
         'col': '00EEB918',
         'vtable': '00E54E58',
         'slot': '20',
         'chain': ['00C6A360', '00C6A130', '00C6BA50', '00C6B7F0', '00C6B4A0', '00C6B0B0'],
         'proof': [{'from': '00C6A360',
                    'to': '00C6A130',
                    'original_site': '00C6A363',
                    'opcode': 'e8c8fdffff',
                    'normalized_rows': 10},
                   {'from': '00C6A130',
                    'to': '00C6BA50',
                    'original_site': '00C6A32A',
                    'opcode': 'e821170000',
                    'normalized_rows': 177},
                   {'from': '00C6BA50',
                    'to': '00C6B7F0',
                    'original_site': '00C6BAA9',
                    'opcode': 'e842fdffff',
                    'normalized_rows': 47},
                   {'from': '00C6B7F0',
                    'to': '00C6B4A0',
                    'original_site': '00C6B874',
                    'opcode': 'e827fcffff',
                    'normalized_rows': 88},
                   {'from': '00C6B4A0',
                    'to': '00C6B0B0',
                    'original_site': '00C6B56D',
                    'opcode': 'e83efbffff',
                    'normalized_rows': 155}],
         'entry': '00C6B0B0',
         'unit': 'game_0658.c',
         'calls': ['00C6AEF0', '00C6A930', '00C68210', '00C682D0', '00C683E0', '00BA3B00', '00CF9BE0'],
         'absolute_reads': ['0x10D9E38', '0x10D9E34', '0x10D9E34']},
 'vanilla': {'image_sha256': '2b4e8bd32bd929e8caf1d53f74bc4aa6be56c362080549b9dc675d4e88289950',
             'owner': '.?AVCVBCombiner@NGScene@@',
             'type_descriptor': '00F22CF0',
             'col': '00EB2724',
             'vtable': '00E28358',
             'slot': '20',
             'chain': ['008C7400', '008C71D0', '008C9020', '008C8E10', '008C8AC0', '008C86D0'],
             'proof': [{'from': '008C7400',
                        'to': '008C71D0',
                        'original_site': '008C7403',
                        'opcode': 'e8c8fdffff',
                        'normalized_rows': 10},
                       {'from': '008C71D0',
                        'to': '008C9020',
                        'original_site': '008C73CA',
                        'opcode': 'e8511c0000',
                        'normalized_rows': 177},
                       {'from': '008C9020',
                        'to': '008C8E10',
                        'original_site': '008C9079',
                        'opcode': 'e892fdffff',
                        'normalized_rows': 47},
                       {'from': '008C8E10',
                        'to': '008C8AC0',
                        'original_site': '008C8E94',
                        'opcode': 'e827fcffff',
                        'normalized_rows': 88},
                       {'from': '008C8AC0',
                        'to': '008C86D0',
                        'original_site': '008C8B8D',
                        'opcode': 'e83efbffff',
                        'normalized_rows': 155}],
             'entry': '008C86D0',
             'unit': 'game_0393.c',
             'calls': ['008C8510', '00961C10', '008C52B0', '008C5370', '008C5480', '00AB9520', '00BE4DB0'],
             'absolute_reads': ['0xFDDD64', '0xFDDD60', '0xFDDD60']},
 'hof': {'image_sha256': 'bad3b0c010b9d85193811bdf8ffa2afab30b865ea924c480ff7aac78a1e73140',
         'owner': '.?AVCVBCombiner@NGScene@@',
         'type_descriptor': '00ED7880',
         'col': '00E6356C',
         'vtable': '00DC8398',
         'slot': '20',
         'chain': ['00A47CE0', '00A47AB0', '00A49390', '00A491E0', '00A48E90', '00A48AA0'],
         'proof': [{'from': '00A47CE0',
                    'to': '00A47AB0',
                    'original_site': '00A47CE3',
                    'opcode': 'e8c8fdffff',
                    'normalized_rows': 10},
                   {'from': '00A47AB0',
                    'to': '00A49390',
                    'original_site': '00A47CAA',
                    'opcode': 'e8e1160000',
                    'normalized_rows': 177},
                   {'from': '00A49390',
                    'to': '00A491E0',
                    'original_site': '00A493E9',
                    'opcode': 'e8f2fdffff',
                    'normalized_rows': 47},
                   {'from': '00A491E0',
                    'to': '00A48E90',
                    'original_site': '00A49264',
                    'opcode': 'e827fcffff',
                    'normalized_rows': 88},
                   {'from': '00A48E90',
                    'to': '00A48AA0',
                    'original_site': '00A48F5D',
                    'opcode': 'e83efbffff',
                    'normalized_rows': 155}],
         'entry': '00A48AA0',
         'unit': 'game_0513.c',
         'calls': ['00A488E0', '004584E0', '00A45B90', '00A45C50', '00A45D60', '00901D00', '008FEBF0'],
         'absolute_reads': ['0x1033384', '0x1033380', '0x1033380']}}
BYTE_PROOF={'toe': {'entry': '00C6B0B0',
         'size': 458,
         'raw_sha256': 'ac78db3b17cea5ad7af20482a35b8787c8d2cc27f62680381714835dc370420d',
         'normalized_sha256': 'd0ab5d55965040279800b498a499021758f5a98d3dc25e25241101a5624e0141',
         'calls': [{'site': '00C6B0E5', 'target': '00C6AEF0', 'bytes': 'e806feffff'},
                   {'site': '00C6B141', 'target': '00C6A930', 'bytes': 'e8eaf7ffff'},
                   {'site': '00C6B1A5', 'target': '00C68210', 'bytes': 'e866d0ffff'},
                   {'site': '00C6B1DF', 'target': '00C682D0', 'bytes': 'e8ecd0ffff'},
                   {'site': '00C6B21E', 'target': '00C683E0', 'bytes': 'e8bdd1ffff'},
                   {'site': '00C6B252', 'target': '00BA3B00', 'bytes': 'e8a988f3ff'},
                   {'site': '00C6B26B', 'target': '00CF9BE0', 'bytes': 'e870e90800'}],
         'data_relocations': [{'address': '010D9E34', 'operand_offsets': [112, 157, 189, 437]},
                              {'address': '010D9E38', 'operand_offsets': [151]}]},
 'vanilla': {'entry': '008C86D0',
             'size': 458,
             'raw_sha256': '984dc0345bbe664e1f4ea599d6cc30ec6968c3d66e27229e15d4dccde2e6ed6b',
             'normalized_sha256': 'd0ab5d55965040279800b498a499021758f5a98d3dc25e25241101a5624e0141',
             'calls': [{'site': '008C8705', 'target': '008C8510', 'bytes': 'e806feffff'},
                       {'site': '008C8761', 'target': '00961C10', 'bytes': 'e8aa940900'},
                       {'site': '008C87C5', 'target': '008C52B0', 'bytes': 'e8e6caffff'},
                       {'site': '008C87FF', 'target': '008C5370', 'bytes': 'e86ccbffff'},
                       {'site': '008C883E', 'target': '008C5480', 'bytes': 'e83dccffff'},
                       {'site': '008C8872', 'target': '00AB9520', 'bytes': 'e8a90c1f00'},
                       {'site': '008C888B', 'target': '00BE4DB0', 'bytes': 'e820c53100'}],
             'data_relocations': [{'address': '00FDDD60', 'operand_offsets': [112, 157, 189, 437]},
                                  {'address': '00FDDD64', 'operand_offsets': [151]}]},
 'hof': {'entry': '00A48AA0',
         'size': 458,
         'raw_sha256': '2f3c09a7b9d0a28f3a5df3f85106aafadbaf9657faaf741f35085a3dc9d55612',
         'normalized_sha256': 'd0ab5d55965040279800b498a499021758f5a98d3dc25e25241101a5624e0141',
         'calls': [{'site': '00A48AD5', 'target': '00A488E0', 'bytes': 'e806feffff'},
                   {'site': '00A48B31', 'target': '004584E0', 'bytes': 'e8aaf9a0ff'},
                   {'site': '00A48B95', 'target': '00A45B90', 'bytes': 'e8f6cfffff'},
                   {'site': '00A48BCF', 'target': '00A45C50', 'bytes': 'e87cd0ffff'},
                   {'site': '00A48C0E', 'target': '00A45D60', 'bytes': 'e84dd1ffff'},
                   {'site': '00A48C42', 'target': '00901D00', 'bytes': 'e8b990ebff'},
                   {'site': '00A48C5B', 'target': '008FEBF0', 'bytes': 'e8905febff'}],
         'data_relocations': [{'address': '01033380', 'operand_offsets': [112, 157, 189, 437]},
                              {'address': '01033384', 'operand_offsets': [151]}]}}

def adapt(source,edition):
    peer=MAPS[edition];canonical=MAPS['toe']
    mapping=dict(zip(canonical['calls'],peer['calls']))
    mapping.update({'010D9E34':peer['absolute_reads'][1][2:].upper().zfill(8),
                    '010D9E38':peer['absolute_reads'][0][2:].upper().zfill(8)})
    def address(match):
        value=match[1]
        if 0xC6B0B0<=int(value,16)<=0xC6B279:
            return f'{int(peer["entry"],16)+int(value,16)-0xC6B0B0:08X}'
        return mapping.get(value,value)
    return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])',address,source)

PREFIX=OBSERVER_PREFIX.replace('MEMORY_BYTES=0x80000','MEMORY_BYTES=0x200000').replace('STACK_VA=0x70000','STACK_VA=0x1F0000')
PREFIX=PREFIX.replace('#include "recomp_types.h"',r'''#include "recomp_types.h"
static void *checked_pointer(uint32_t address) {
    if(address>=SCRATCH_VA && address<SCRATCH_VA+12)address=0x6000u+address-SCRATCH_VA;
    if(address>sizeof memory-16){fprintf(stderr,"DIFFERENTIAL FAIL invalid guest address %08x\n",address);exit(2);}
    return memory+address;
}
#undef RECOMP_MEM_ADDR
#define RECOMP_MEM_ADDR(va) checked_pointer((uint32_t)(va))
#undef GPTR
#define GPTR(va) checked_pointer((uint32_t)(va))
''')

FIXTURE=r'''
enum { SELF=0x1000,MESH=0x1100,INFLUENCES=0x1200,BONE_VECTOR=0x1300,
       INDICES=0x4000,INDICES2=0x4800,TEMP1=0x5000,TEMP2=0x5200,
       WEIGHT1=0x8000,WEIGHT2=0xA000,VERTICES=0x20000,VERTICES2=0x22000,
       BONES=0x30000,BONES2=0x34000 };
static unsigned policy,yp,matrix_calls,math_selector_calls,aborted;
static int32_t resized_count;
static jmp_buf callback_abort;
static void callback(unsigned kind,unsigned pop) {
    assert(++callbacks<MAX_EVENTS);record(kind);
    if(kind==2) {
        MEM32(SCRATCH_VA)=TEMP1;
        MEM32(SCRATCH_VA+4)=TEMP1+(uint32_t)resized_count*4u;
        if(policy&8)MEM32(STACK_VA+12)=VERTICES2;
    }
    if(kind>=3&&kind<=5) {
        ++matrix_calls;
        if((policy&16)&&matrix_calls==1){aborted=1;longjmp(callback_abort,1);}
        MEM32(g_ecx)=0xE1F20000u|matrix_calls;
        MEM32(g_edx)^=0xFFA5500Fu;
        if(matrix_calls==1) {
            if(policy&1)MEM32(SCRATCH_VA)=TEMP2;
            if(policy&2)MEM32(STACK_VA+16)=2;
            if(policy&4)MEM32(STACK_VA+32)=INFLUENCES;
            if(policy&32)MEM32(STACK_VA+28)=WEIGHT2;
            if(policy&64)MEM32(BONE_VECTOR)=BONES2;
        }
    }
    if(kind==6)assert(MEM32(g_esp+4)==13);
    g_eax=0xC9000000u|(kind<<16)|callbacks;
    g_ecx=0xA8000000u|callbacks;g_edx=0xAABB0000u|(kind<<8)|callbacks;
    g_flag_k=FK_ADD;g_flag_a=g_eax;g_flag_b=kind;g_flag_cf=0;
    g_st[3]+=.125;g_st_i64[2]^=0x1122334455667788ll;
    ((uint32_t *)g_xmm)[13]^=0xA8B21234u;g_mxcsr^=0x2000u;
    g_mm[4]^=0xAFFE112233445566ull;g_esp+=pop;
}
static void fallback(void){callback(1,28);}
static void resize_scratch(void){callback(2,8);}
static void one_weight(void){callback(3,12);}
static void two_weights(void){callback(4,24);}
static void three_weights(void){callback(5,32);}
static void lookup(void){callback(6,8);}
static void submit(void){callback(7,36);}
static void test_yield(void) {
    ++yields;record(8);
    if(yp==1&&yields==1)MEM32(STACK_VA+16)=0;
    if(yp==2)MEM32(SCRATCH_VA)=TEMP2;
    g_eax^=0x12345678;g_edx^=0x789ABCDE;
    g_flag_k=FK_TEST;g_flag_a=0x13572468;g_flag_b=8;g_flag_cf=0;
    g_st[1]+=.5;g_st_i64[4]^=0x1357246813572468ll;
}
recomp_func_t void_resolve(uint32_t address){(void)address;abort();}
#include "names.h"
#include "oracle.h"
void SKIN_CANONICAL(void){++oracle_calls;skin_oracle();}
/* Keep each opaque transform callback unchanged while proving that the host
 * loop reaches the independently selected math boundary for every weight. */
void void_skin_math_one_dispatch(void){++math_selector_calls;one_weight();}
void void_skin_math_two_dispatch(void){++math_selector_calls;two_weights();}
void void_skin_math_three_dispatch(void){++math_selector_calls;three_weights();}
#include "actual.h"

static void setup(unsigned seed,int32_t count,int empty) {
    random_state=seed?seed:1;memset(memory,0xCD,sizeof memory);
    g_eax=random_next();g_ecx=SELF;g_edx=random_next();g_ebx=random_next();
    g_esp=STACK_VA;g_ebp=random_next();g_esi=random_next();g_edi=random_next();
    g_flag_k=FK_ADD;g_flag_a=random_next();g_flag_b=random_next();g_flag_cf=1;
    g_backedges=seed%4;g_cur_func=0x11998877;g_enter_idx=0;
    memset(g_enter_trace,0,sizeof g_enter_trace);g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=i+.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;
    g_mxcsr=0x3F80;g_fp_top=5;g_fpu_cw=0xB7F;void_fpu_cmp=0x41;
    MEM32(STACK_VA)=RECOMP_RETADDR;
    uint32_t args[]={MESH,0xABC00002u,VERTICES,17,0x890ABCDEu,0xA0006001u,
                     WEIGHT1,INFLUENCES,BONE_VECTOR,0xA5A51234u};
    for(unsigned i=0;i<10;i++)MEM32(STACK_VA+4+4*i)=args[i];
    MEM32(SELF)=0x12344321;MEM32(MESH+0x30)=INDICES;MEM32(MESH+0x34)=INDICES+8;
    MEM32(INFLUENCES)=INDICES2;MEM32(INFLUENCES+4)=empty?INDICES2:INDICES2+8;
    MEM32(BONE_VECTOR)=BONES;MEM32(SCRATCH_VA)=TEMP1;MEM32(SCRATCH_VA+4)=TEMP1;
    const uint16_t indices[]={0,1,65535,3};
    for(unsigned i=0;i<4;i++) {
        MEM16(INDICES+2*i)=indices[i];MEM16(INDICES2+2*i)=indices[3-i];
        for(unsigned j=0;j<2;j++) {
            uint32_t at=(j?WEIGHT2:WEIGHT1)+(uint32_t)indices[i]*24u;
            MEM8(at+16)=(uint8_t)(seed+i);
            MEM8(at+17)=(i==0||i==3)?0:(uint8_t)(0x80+i);
            MEM8(at+18)=(i==1)?0:(uint8_t)(0xF0+i);
            MEM8(at+20)=(uint8_t)(i*85);MEM8(at+21)=(uint8_t)(255-i);MEM8(at+22)=(uint8_t)(128+i);
        }
    }
    resized_count=count;events=callbacks=yields=matrix_calls=math_selector_calls=aborted=0;
    memset(log_events,0,sizeof log_events);recomp_yield_hook=test_yield;
}
static int same_events(unsigned expected) {
    if(expected!=events)return 0;
    for(unsigned i=0;i<events;i++)if(saved_events[i].kind!=log_events[i].kind ||
        memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state)) ||
        memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory))return 0;
    return 1;
}
static int compare(unsigned seed,int32_t count,int empty) {
    setup(seed,count,empty);
    if(!setjmp(callback_abort))skin_oracle();
    saved_final=capture();memcpy(saved_memory,memory,sizeof memory);memcpy(saved_events,log_events,sizeof log_events);
    unsigned expected=events,expected_aborted=aborted;
    setup(seed,count,empty);
    if(!setjmp(callback_abort))void_skin_native_combine();
    state actual=capture();
    if(memcmp(&saved_final,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)||expected_aborted!=aborted||!same_events(expected)||math_selector_calls!=matrix_calls) {
        fprintf(stderr,"DIFFERENTIAL FAIL case%d seed%u count%d empty%d policy%u yp%u events%u/%u\n",case_number,seed,count,empty,policy,yp,expected,events);
        for(unsigned i=0;i<8;i++)if(saved_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,saved_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<4;i++)if(saved_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,saved_final.flags[i],actual.flags[i]);
        for(unsigned i=0;i<events&&i<expected;i++)if(memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state)) ||
            memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory)) {
            fprintf(stderr,"firstevent%u kind%u/%u\n",i,saved_events[i].kind,log_events[i].kind);
            for(unsigned j=0;j<8;j++)if(saved_events[i].cpu.regs[j]!=log_events[i].cpu.regs[j])fprintf(stderr,"eventreg%u %08x/%08x\n",j,saved_events[i].cpu.regs[j],log_events[i].cpu.regs[j]);
            for(unsigned j=0;j<4;j++)if(saved_events[i].cpu.flags[j]!=log_events[i].cpu.flags[j])fprintf(stderr,"eventflags%u %08x/%08x\n",j,saved_events[i].cpu.flags[j],log_events[i].cpu.flags[j]);break;
        }
        for(unsigned i=0;i<sizeof memory;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"memory%08x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    for(unsigned i=0;i<events;i++){free(saved_events[i].guest_memory);free(log_events[i].guest_memory);}
    return 0;
}
static void discard_events(void){for(unsigned i=0;i<events;i++)free(log_events[i].guest_memory);events=0;}
int main(int argc,char **argv) {
    const int32_t counts[]={-1,0,1,2,4};
    for(unsigned i=0;i<40;i++)for(unsigned n=0;n<5;n++) {
        policy=(i*37)&127;yp=i%3;case_number++;
        if(compare(i*0x9E3779B9u+1,counts[n],i%7==0))return 1;
    }
    int native_mode=argc>1&&!strcmp(argv[1],"native");remove("native-skin");
    if(argc>1){FILE *f=fopen("native-skin","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    policy=yp=0;setup(7,0,1);oracle_calls=logs=0;void_skin_native_dispatch();
    assert(oracle_calls==(native_mode?0:1)&&logs==1);discard_events();
    FILE *f=fopen("native-skin","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(7,0,1);void_skin_native_dispatch();assert(oracle_calls==(native_mode?0:2)&&logs==1);discard_events();remove("native-skin");
    printf("PASS %d skin cases full memory/GPR/FP/MMX/callback/yield/TRACE;cached mode%d\n",case_number,native_mode);
    return 0;
}
'''


class SkinNativeTest(unittest.TestCase):
    def check_originals(self,edition):
        facts=MAPS[edition];proof=BYTE_PROOF[edition]
        image=generated_root(edition)/'input/H5_Game.exe'
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),facts['image_sha256'])
        pe=pefile.PE(str(image),fast_load=True);base=pe.OPTIONAL_HEADER.ImageBase
        get=lambda address,size:pe.get_data(address-base,size)
        word=lambda address:int.from_bytes(get(address,4),'little')
        vt=int(facts['vtable'],16);col=word(vt-4)
        self.assertEqual(col,int(facts['col'],16));self.assertEqual((word(col),word(col+4)),(0,0))
        self.assertEqual(get(word(col+12)+8,128).split(b'\0',1)[0],b'.?AVCVBCombiner@NGScene@@')
        self.assertEqual(word(vt+0x20),int(facts['chain'][0],16))
        for call in facts['proof']:
            site=int(call['original_site'],16);data=get(site,5)
            self.assertEqual(data.hex(),call['opcode']);self.assertEqual(data[0],0xE8)
            self.assertEqual((site+5+int.from_bytes(data[1:],'little',signed=True))&0xFFFFFFFF,int(call['to'],16))
        entry=int(facts['entry'],16);code=bytearray(get(entry,0x1CA))
        self.assertEqual(hashlib.sha256(code).hexdigest(),proof['raw_sha256'])
        for call in proof['calls']:
            offset=int(call['site'],16)-entry;self.assertEqual(bytes(code[offset:offset+5]).hex(),call['bytes'])
            code[offset+1:offset+5]=b'\0'*4
        for relocation in proof['data_relocations']:
            for offset in relocation['operand_offsets']:
                self.assertEqual(int.from_bytes(code[offset:offset+4],'little'),int(relocation['address'],16))
                code[offset:offset+4]=b'\0'*4
        self.assertEqual(hashlib.sha256(code).hexdigest(),proof['normalized_sha256']);pe.close()

    def check_edition(self,edition,protocol=False,trace=True,mutant=None):
        self.check_originals(edition)
        source=adapt(SOURCE.read_text(encoding='utf-8'),edition)
        if mutant:source=mutant(source)
        record=MAPS[edition];entry=record['entry']
        names='#define SKIN_CANONICAL sub_'+entry+'\n'
        scratch=int(record['absolute_reads'][1],16)
        for actual,stub in zip(record['calls'],('fallback','resize_scratch','one_weight','two_weights','three_weights','lookup','submit')):
            names+='#define sub_'+actual+' '+stub+'\n'
        oracle=transformed(edition,'sub_'+entry,record['unit']).replace('void sub_'+entry+'(void)','void skin_oracle(void)',1)
        prefix=PREFIX if trace else PREFIX.replace('#define RECOMP_TRACE','/* TRACE disabled. */')
        probe=f'#define SCRATCH_VA 0x{scratch:08X}u\n'+prefix+FIXTURE
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
        (out/'receipt.json').write_text(json.dumps({'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'oracle_sha256':hashlib.sha256(oracle.encode()).hexdigest(),'edition':edition,'protocol_check':protocol,
            'trace':trace,'results':[tested.stdout,enabled.stdout],'physical_device_executed':False},indent=2)+'\n',encoding='utf-8')

    def test_all_three_production_oracles(self):
        for edition in MAPS:
            with self.subTest(edition=edition):self.check_edition(edition)
    def test_protocol_check(self):self.check_edition('toe',protocol=True)
    def test_no_trace(self):self.check_edition('toe',trace=False)
    def test_reject_zero_extended_weight(self):
        self.check_edition('toe',mutant=lambda s:s.replace('PUSH32(esp,ebx);\n                    PUSH32(esp,edx);','PUSH32(esp,ebx&0xFFu);\n                    PUSH32(esp,edx);',1))
    def test_reject_cached_temporary_base(self):
        self.check_edition('toe',mutant=lambda s:s.replace('if(more)ebp=MEM32(0x010D9E34u);','(void)more;'))
    def test_reject_recomputed_yield_comparison(self):
        self.check_edition('toe',mutant=lambda s:s.replace('} while(more);','} while((int32_t)esi<(int32_t)MEM32(esp+0x34));'))
    def test_reject_bypassed_math_selector(self):
        self.check_edition('toe',mutant=lambda s:s.replace('RECOMP_CALL_P(void_skin_math_one_dispatch,','RECOMP_CALL_P(sub_00C68210,'))

if __name__=='__main__':unittest.main()
