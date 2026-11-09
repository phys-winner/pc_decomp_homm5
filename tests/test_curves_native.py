"""Discrete/scalar particle curves against fresh optimized originals."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'build/tests/curves-native'
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools')]
import pefile
import build_android as builder
from editions import generated_root,protocol_root
from protocol_transform import Protocol,apply_protocol
from x87_locals import Plan,apply_x87
from test_grid_native import HARNESS as GRID_HARNESS
from test_scene_native import body
from test_mmx_packed import CLANG,command,environment,pc_header

FACTS={
 'toe':('00BF5F30','00BF60E0','game_0622.c',('00E0A7E4','00E0AB70','00E0BE10')),
 'vanilla':('00A92870','00A92A20','game_0527.c',('00DE73F0','00DE3820','00DE385C')),
 'hof':('00B8D900','00B8DAB0','game_0615.c',('00DBC09C','00DBA7E8','00DBB140')),
}
TEST_CONSTANTS=('00031000','00031004','00031008')

def production(edition,va,unit):
 source=(generated_root(edition)/'game-x86'/unit).read_text()
 raw=body(source,'sub_'+va).encode()
 transformed=builder.round_x87_precision(builder.guard_fpu_memory(raw))
 transformed=apply_protocol(transformed,Protocol(protocol_root(edition)/'summary.json',edition=edition),'game')
 return apply_x87(transformed,Plan(protocol_root(edition)/'x87.json',edition=edition)).decode()

def adapt(source,edition,fixture=True):
 word,scalar,_,constants=FACTS[edition]
 def address(match):
  value=match[1]
  if 0xBF5F30<=int(value,16)<=0xBF5FB3:return f'{int(word,16)+int(value,16)-0xBF5F30:08X}'
  if 0xBF60E0<=int(value,16)<=0xBF61C9:return f'{int(scalar,16)+int(value,16)-0xBF60E0:08X}'
  return dict(zip(FACTS['toe'][3],constants)).get(value,value)
 source=re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])',address,source)
 if fixture:
  for original,target in zip(constants,TEST_CONSTANTS):source=source.replace('0x'+original,'0x'+target)
 return source

def relocate_oracle(source,edition):
 for original,target in zip(FACTS[edition][3],TEST_CONSTANTS):
  source=re.sub(r'0x0*'+original.lstrip('0')+r'\b','0x'+target,source)
 return source

PREFIX=GRID_HARNESS[:GRID_HARNESS.index('static void callback(')]
PREFIX=PREFIX.replace('uint64_t mm[8];xmm_t xmm[8];','uint64_t round_masks[2],mm[8];xmm_t xmm[8];')
PREFIX=PREFIX.replace('    return s;','    s.round_masks[0]=g_fp_round_mask;s.round_masks[1]=g_fp_store_mask;return s;')
PREFIX=PREFIX.replace('uint32_t stack[12];} event;','uint32_t stack[12];uint8_t *guest_memory;} event;')
PREFIX=PREFIX.replace('    log_events[events].kind=kind;',
 '''    log_events[events].guest_memory=malloc(sizeof memory);assert(log_events[events].guest_memory);
    memcpy(log_events[events].guest_memory,memory,sizeof memory);
    log_events[events].kind=kind;''')
HARNESS=r'''
enum { CURVE=0x1001,KEYS=0xA001,KEYS2=0xB001,OUTPUT=0x1800,ONE=0x31000,HALF=0x31004,ZERO=0x31008 };
uint64_t g_fp_round_mask,g_fp_store_mask;
static unsigned scalar_mode,yield_mode,key_count,stride;
static void test_yield(void) {
    ++yields;record(9);
    g_edx=(g_edx&0xFFFFu)|0xABCD0000u;
    if(yield_mode==1)MEM32(CURVE+2)=KEYS2;
    if(yield_mode==2)MEM32(STACK-4)=0xFFFF8000u;
    if(yield_mode==3&&key_count>3){g_esi=2;g_edi=1;}
    if(yield_mode==4)fp_set_cw(0xE7F);
    g_st[5]+=0.25;g_st_i64[3]^=0x1122334455667788ll;
    g_flag_k=FK_ADD;g_flag_a=123;g_flag_b=456;g_flag_cf=0;
}
void recomp_x87_violation(uint32_t va,int actual,int expected){fprintf(stderr,"x87 %x %d %d\n",va,actual,expected);abort();}
#include "oracle.h"
void WORD_CANONICAL(void){++original_calls;oracle_word();}
void SCALAR_CANONICAL(void){++original_calls;oracle_scalar();}
#include "actual.h"
static const uint32_t time_bits[]={0,0x80000000u,0x3F000000u,0xBF000000u,0x3F800000u,
    0x3F800001u,0x7F800000u,0xFF800000u,0x7FC12345u,0x7F812345u,
    0x4F000000u,0x4EFFFFFFu,0xCF000000u,0xCEFFFFFFu,0x477FFF00u,0xC7000000u,1u};
static const uint32_t value_bits[]={0,0x80000000u,0x3F800000u,0xBF800000u,1u,0x7F800000u,0xFF800000u,0x7FC54321u,0x7F854321u};
static const uint16_t controls[]={0xC7F,0x37F,0x27F,0x7F,0x47F,0x87F,0xA7F,0xE7F};
static void setup(unsigned seed,unsigned count,unsigned time,unsigned cw,unsigned alias,unsigned yp,unsigned duplicate) {
    memset(memory,0xCD,sizeof memory);key_count=count;stride=scalar_mode?6:4;yield_mode=yp;
    g_eax=0x81234567u^seed;g_ecx=CURVE;g_edx=0xAB987654u^seed;g_ebx=0xBEEFFACEu^seed;
    g_esp=STACK;g_ebp=0xEFEF2937u^seed;g_esi=0x3679BEEFu^seed;g_edi=0xCC811223u^seed;
    g_flag_k=FK_ADD;g_flag_a=seed;g_flag_b=0x1942;g_flag_cf=1;g_backedges=seed%4u;
    g_cur_func=0x11111111;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    g_fp_top=5;fp_set_cw(controls[cw]);void_fpu_cmp=0x41;g_mxcsr=0x3F80;
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;
    MEM32(ONE)=0x3F800000;MEM32(HALF)=0x3F000000;MEM32(ZERO)=0;
    MEM16(CURVE)=(uint16_t)count;MEM32(CURVE+2)=KEYS;
    unsigned filled=count&&count<0x8000?count:1;
    for(unsigned bank=0;bank<2;bank++)for(unsigned i=0;i<filled;i++){
        uint32_t key=(bank?KEYS2:KEYS)+stride*i;
        const int16_t times[]={-32768,-1000,-10,0,1,2,1000,32767};
        int16_t stamp=duplicate?0:count<9?times[(i*7)/(count>1?count-1:1)]:(int16_t)(i*2000-30000);
        MEM16(key)=(uint16_t)stamp;
        if(scalar_mode)MEM32(key+2)=value_bits[(seed+i+bank)%9];
        else MEM16(key+2)=(uint16_t)(0x7FFFu+i*0x1111u+bank);
    }
    uint32_t output=OUTPUT;
    if(alias==1)output=KEYS+2;
    if(alias==2)output=CURVE;
    if(alias==3)output=STACK+4;
    if(alias==4)output=STACK-4;
    if(alias==5)output=KEYS+stride*(filled-1)+2;
    if(alias==6)output=ONE;
    MEM32(STACK)=0x91919191;MEM32(STACK+4)=time_bits[time];MEM32(STACK+8)=output;
    events=yields=0;recomp_yield_hook=test_yield;
}
static int same_events(unsigned count) {
    if(count!=events)return 0;
    for(unsigned i=0;i<count;i++)if(saved_events[i].kind!=log_events[i].kind||
        memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state))||
        memcmp(saved_events[i].stack,log_events[i].stack,sizeof log_events[i].stack)||
        memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory))return 0;
    return 1;
}
static int compare(unsigned seed,unsigned count,unsigned time,unsigned cw,unsigned alias,unsigned yp,unsigned duplicate) {
    setup(seed,count,time,cw,alias,yp,duplicate);
    if(scalar_mode)oracle_scalar();else oracle_word();
    state expected=capture();memcpy(saved_memory,memory,sizeof memory);
    unsigned n=events,nyields=yields;memcpy(saved_events,log_events,n*sizeof log_events[0]);
    setup(seed,count,time,cw,alias,yp,duplicate);
    if(scalar_mode)void_curve_native_scalar();else void_curve_native_word();
    state actual=capture();
    if(memcmp(&expected,&actual,sizeof actual)||memcmp(saved_memory,memory,sizeof memory)||yields!=nyields||!same_events(n)){
        fprintf(stderr,"CURVE DIFFERENTIAL FAIL kind%u case%u count%u time%x cw%x alias%u yield%u duplicate%u\n",scalar_mode,seed,count,time_bits[time],controls[cw],alias,yp,duplicate);
        for(unsigned i=0;i<8;i++)if(expected.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,expected.regs[i],actual.regs[i]);
        if(expected.fp_cmp!=actual.fp_cmp)fprintf(stderr,"fp_cmp %d/%d\n",expected.fp_cmp,actual.fp_cmp);
        for(unsigned i=0;i<BYTES;i++)if(saved_memory[i]!=memory[i]){fprintf(stderr,"memory%x %02x/%02x\n",i,saved_memory[i],memory[i]);break;}
        return 1;
    }
    for(unsigned i=0;i<events;i++){free(saved_events[i].guest_memory);free(log_events[i].guest_memory);}
    return 0;
}
int main(int argc,char **argv) {
    const unsigned counts[]={1,2,3,8,32,0,0xFFFF};unsigned cases=0;
    if(argc==1)for(scalar_mode=0;scalar_mode<2;scalar_mode++)for(unsigned n=0;n<7;n++)
    for(unsigned time=0;time<17;time++)for(unsigned cw=0;cw<8;cw++){
        unsigned seed=++cases;unsigned alias=seed%7,yp=seed%5,duplicate=(seed/7)%2;
        if(compare(seed,counts[n],time,cw,alias,yp,duplicate))return 1;
    }
    remove("native-curves");int native_mode=argc>1&&!strcmp(argv[1],"native");
    if(argc>1){FILE *f=fopen("native-curves","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    logs=original_calls=0;scalar_mode=0;setup(1,1,0,0,0,0,0);void_curve_native_word_dispatch();
    assert(original_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-curves","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    scalar_mode=1;setup(1,1,0,0,0,0,0);void_curve_native_scalar_dispatch();
    assert(original_calls==(native_mode?0:2)&&logs==1);remove("native-curves");
    printf("PASS %u curve cases: exact memory/CPU/yield state, CW/NaN/aliases; cached mode%d\n",cases,native_mode);return 0;
}
'''

class CurvesCandidate(unittest.TestCase):
 def check(self,edition,trace=True,protocol=False,mutant=None):
  word,scalar,unit,constants=FACTS[edition]
  pe=pefile.PE(str(generated_root(edition)/'input/H5_Game.exe'),fast_load=True)
  for va,bits in zip(constants,('0000803f','0000003f','00000000')):
   self.assertEqual(pe.get_data(int(va,16)-pe.OPTIONAL_HEADER.ImageBase,4).hex(),bits)
  proof={'toe': [{'entry': '00BF60E0', 'bytes': 234, 'unit': 'game_0622.c', 'caller_site': '00BF5966', 'call_bytes': 'e875070000', 'original_sha256': 'fe6e9b4c3b05349def39ea3751d2e5fff345d6fe280473f4a5198b32418a4aa4', 'instruction_rows': 81, 'normalized_instruction_sha256': 'b2874fdd537f33edac3418911dec1adc248bdd639228cd6216b3c01dedffb8b9', 'calls': []}, {'entry': '00BF5F30', 'bytes': 132, 'unit': 'game_0622.c', 'caller_site': '00BF5991', 'call_bytes': 'e89a050000', 'original_sha256': '9123150129320aa22bcab6b7eae8db685b53360d4ea7de8d769dcec5b6872d01', 'instruction_rows': 50, 'normalized_instruction_sha256': 'a148a14d2006d4e20b854c95e9d1da8c3483e88ffe7b7d6b97b6a6bda66ef5a5', 'calls': []}], 'vanilla': [{'entry': '00A92A20', 'bytes': 234, 'unit': 'game_0527.c', 'caller_site': '00A922A6', 'call_bytes': 'e875070000', 'original_sha256': '049230d30cc0556925c5d33c38122278d3ea9a3ce8e8fc65f23ce07b07551d51', 'instruction_rows': 81, 'normalized_instruction_sha256': 'b2874fdd537f33edac3418911dec1adc248bdd639228cd6216b3c01dedffb8b9', 'calls': []}, {'entry': '00A92870', 'bytes': 132, 'unit': 'game_0527.c', 'caller_site': '00A922D1', 'call_bytes': 'e89a050000', 'original_sha256': '7557930a766191ba1856af21fd256ffaa46a992127aa1cefa4931479ae8751d4', 'instruction_rows': 50, 'normalized_instruction_sha256': 'a148a14d2006d4e20b854c95e9d1da8c3483e88ffe7b7d6b97b6a6bda66ef5a5', 'calls': []}], 'hof': [{'entry': '00B8DAB0', 'bytes': 234, 'unit': 'game_0615.c', 'caller_site': '00B8D3B6', 'call_bytes': 'e8f5060000', 'original_sha256': '23902f2989f6cf70566ee8ca5c4ea2758b6f55ab1048cbc11263e67d9da2460b', 'instruction_rows': 81, 'normalized_instruction_sha256': 'b2874fdd537f33edac3418911dec1adc248bdd639228cd6216b3c01dedffb8b9', 'calls': []}, {'entry': '00B8D900', 'bytes': 132, 'unit': 'game_0615.c', 'caller_site': '00B8D3E1', 'call_bytes': 'e81a050000', 'original_sha256': 'b411db2e3d8fefa44b714560c9f8c9462cc31f066f36635dc3963dbcf83614d9', 'instruction_rows': 50, 'normalized_instruction_sha256': 'a148a14d2006d4e20b854c95e9d1da8c3483e88ffe7b7d6b97b6a6bda66ef5a5', 'calls': []}]}
  for va,size in ((word,132),(scalar,234)):
   expected=next(r for r in proof[edition] if r['entry']==va)
   self.assertEqual(hashlib.sha256(pe.get_data(int(va,16)-pe.OPTIONAL_HEADER.ImageBase,size)).hexdigest(),expected['original_sha256'])
  original_word=production(edition,word,unit);original_scalar=production(edition,scalar,unit)
  oracle=relocate_oracle(original_word,edition).replace('void sub_'+word+'(void)','void oracle_word(void)',1)
  oracle+='\n'+relocate_oracle(original_scalar,edition).replace('void sub_'+scalar+'(void)','void oracle_scalar(void)',1)
  source=adapt((ROOT/'android/host/curves_native.c').read_text(),edition)
  if mutant:source=mutant(source)
  prefix=PREFIX if trace else PREFIX.replace('#define RECOMP_TRACE','/* Disabled. */')
  suffix=('-notrace' if not trace else '')+('-protocol' if protocol else '')+('-mutant' if mutant else '')
  out=HERE/('probe-'+edition+suffix);out.mkdir(parents=True,exist_ok=True)
  names=f'#define WORD_CANONICAL sub_{word}\n#define SCALAR_CANONICAL sub_{scalar}\n'
  text=prefix+names+HARNESS
  files={'probe.c':text,'oracle.h':oracle,'actual.h':source,'host.h':'#include "recomp_types.h"\n',
         'native_mode.h':(ROOT/'android/host/native_mode.h').read_text(),
         'recomp_types.h':pc_header((ROOT/'android/runtime/recomp_types.h').read_text())}
  for name,value in files.items():(out/name).write_text(value,encoding='utf-8')
  env,linker=environment('x64');flags=[CLANG,'/nologo','/W0','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS','/clang:--target=x86_64-pc-windows-msvc','/clang:-fwrapv','/clang:-fno-strict-aliasing','/clang:-ffp-contract=off']
  if protocol:flags.append('/DRECOMP_PROTOCOL_CHECK')
  command([*flags,'/c','probe.c','/Foprobe.obj'],out,env)
  command([linker,'/nologo','probe.obj','/OUT:probe.exe','/STACK:1048576'],out,env)
  result=command([out/'probe.exe'],out,env,check=False)
  if mutant:
   self.assertNotEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('CURVE DIFFERENTIAL FAIL',result.stderr);return
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  mode=command([out/'probe.exe','native'],out,env,check=False);self.assertEqual(mode.returncode,0,mode.stdout+mode.stderr)
  for invalid in ('0','01','1\r\n','1\nextra','2'):
   rejected=command([out/'probe.exe',invalid],out,env,check=False);self.assertEqual(rejected.returncode,0,rejected.stdout+rejected.stderr)
  (out/'receipt.json').write_text(json.dumps({'edition':edition,'native_sha256':hashlib.sha256(source.encode()).hexdigest(),
   'oracle_sha256':hashlib.sha256(oracle.encode()).hexdigest(),'trace':trace,'protocol':protocol,'result':result.stdout,'device_tested':False},indent=2)+'\n')
  print(edition+suffix,result.stdout.strip())
 def test_all_three(self):
  for edition in FACTS:
   with self.subTest(edition=edition):self.check(edition)
 def test_no_trace(self):self.check('toe',trace=False)
 def test_protocol(self):self.check('toe',protocol=True)
 def test_reject_missing_float32_threshold(self):self.check('toe',mutant=lambda s:s.replace('fp_to_int((double)MEMF(esp+0x10))','fp_to_int(time)').replace('fp_to_int((double)MEMF(esp+8))','fp_to_int(time)'))
 def test_reject_unordered_clamp_to_zero(self):self.check('toe',mutant=lambda s:s.replace('if(!RECOMP_PF(((eax>>8)&5u)<<24,24))','if(void_fpu_cmp==2||!RECOMP_PF(((eax>>8)&5u)<<24,24))'))

if __name__=='__main__':unittest.main()
