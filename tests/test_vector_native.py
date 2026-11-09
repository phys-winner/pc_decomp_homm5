"""Native reference-vector traversal versus all3 fresh production originals."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'tools')]
import pefile
from test_grid_native import HARNESS as GRID_HARNESS
from test_mmx_packed import CLANG,command,environment,pc_header
from test_scene_native import body,transformed
from editions import generated_root,protocol_root
from x87_locals import Plan,apply_x87

OUT=ROOT/'build/tests/vector-native'
FACTS={
 'toe':('004FA1A0','004FA250','game_0092.c',('00720CC0','00422F80','004FA280'),
        '004F9ED0','00E19B70','00EC9AE8','game_0092.c',
        'ff632acb8280eba39a28d0cc01b0b7775fd7d260756c620bea8e9253cc94744f'),
 'vanilla':('00459020','004590D0','game_0037.c',('0079A060','00459170','00459100'),
            '00BAA190','00E5DD20','00ED2084','game_0626.c',
            '991384a0e0e3ba34ca61e8f2fce76e9c8a12cd2ca272895a69c7831be8975479'),
 'hof':('0047B260','0047B310','game_0042.c',('00787350','007428B0','0047B340'),
        '00A1CA30','00E1BAA0','00E9A8E8','game_0500.c',
        'a23beeb03db6e68e7b7d187c473d9a76f9d535d2610f81ca52f5304f9765d8d2'),
}

def adapt(source,edition):
 entry=FACTS[edition][0];mapping=dict(zip(FACTS['toe'][3],FACTS[edition][3]))
 def address(match):
  value=match[1]
  if 0x4FA1A0<=int(value,16)<=0x4FA27F:return f'{int(entry,16)+int(value,16)-0x4FA1A0:08X}'
  return mapping.get(value,value)
 return re.sub(r'(?<![0-9A-F])([0-9A-F]{8})(?![0-9A-F])',address,source)

CALLBACKS=r'''
static int32_t archive_version,desired_count;
static void callback(unsigned kind,unsigned pop) {
    assert(++callbacks<MAX_EVENTS);record(kind);
    uint32_t arg=MEM32(g_esp+4),result=0xA5000000u|(kind<<16)|callbacks;
    if(kind==1) {
        assert(g_ecx==ARCHIVE&&arg==2&&MEM32(g_esp+12)==4&&MEM32(g_esp+16)==1);
        if(policy&3)MEM32(MEM32(g_esp+8))=(uint32_t)desired_count;
    }
    if(kind==2)result=0xF1000000u|((policy&2)?1u:0u);
    if(kind==3) {
        assert(g_ecx==ARCHIVE&&arg==1);
        result=0xB3000000u|(((policy&4)&&MEM32(g_esp+8)%2u)?0u:1u);
    }
    if(kind==4) {
        ++object_calls;
        if(!(g_ecx==ARCHIVE&&arg>=CELLS-0x1000&&arg<CELLS+0x2000)){
            fprintf(stderr,"DIFFERENTIAL FAIL callback address ecx=%08x cell=%08x case=%u\n",g_ecx,arg,case_number);exit(2);}
        MEM32(arg)^=0x12345678u;
        if((policy&8)&&object_calls==1)MEM32(STACK-4)=5;
        if((policy&16)&&object_calls==2)MEM32(STACK-4)=1;
        if(policy&32)MEM32(GRID_VA)=CELLS+0x800;
        if(policy&64)MEM32(ARCHIVE)=VTABLE+0x100;
    }
    if(kind==6) {
        assert(g_ecx==GRID_VA);MEM32(GRID_VA+4)=MEM32(GRID_VA);
    }
    if(kind==7) {
        assert(g_ecx==GRID_VA);
        MEM32(GRID_VA)=CELLS+0x400;
        MEM32(GRID_VA+4)=MEM32(GRID_VA)+arg*4u;
        if(policy&128)MEM32(STACK-4)=2;
    }
    if(kind==8)result=(uint32_t)archive_version;
    if(kind==10){assert(g_ecx==ARCHIVE&&arg==1);result=(uint32_t)desired_count;}
    g_eax=result;g_ecx=0x13570000u|callbacks;g_edx=0xC6000000u|(kind<<16)|callbacks;
    g_flag_k=FK_TEST;g_flag_a=result;g_flag_b=kind;g_flag_cf=0;
    g_st[(callbacks+3u)&7u]+=0.25;g_st_i64[callbacks&7u]^=0x1122334455667788ll;
    g_fp_top=(g_fp_top+1)&7;g_fpu_cw^=0x400u;void_fpu_cmp^=3;
    g_mm[(callbacks+1u)&7u]^=0xAABBCCDDEEFF0011ull;
    ((uint32_t *)g_xmm)[callbacks&31u]^=0x52198BCAu;g_mxcsr^=0x2000u;
    g_esp+=pop;
}
static void count_field(void){callback(1,20);}
static void reading(void){callback(2,4);}
static void field_begin(void){callback(3,12);}
static void reference_visit(void){callback(4,8);}
void void_reference_native_object_dispatch(void){++reference_selector_calls;reference_visit();}
static void field_end(void){callback(5,4);}
static void vector_clear(void){callback(6,4);}
static void vector_resize(void){callback(7,8);}
static void version(void){callback(8,4);}
static void old_count(void){callback(10,8);}
recomp_func_t void_resolve(uint32_t address) {
    switch(address){case 1:return count_field;case 2:return reading;case 3:return field_begin;
    case 5:return field_end;case 8:return version;case 10:return old_count;default:assert(0);return 0;}
}
static void test_yield(void) {
    ++yields;record(9);
    g_edx^=0x12345678u;
    if(yp==1)MEM32(STACK-4)=1;
    /* Safe next index0 distinguishes pending versus recomputed comparison. */
    if(yp==2)g_eax=0;
    g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;
    g_st[3]+=0.5;((uint32_t *)g_xmm)[11]^=0xAFFEBCCDu;
}
#include "names.h"
#include "oracle.h"
void CANONICAL_ENTRY(void){++original_calls;oracle_vector();}
#include "actual.h"
'''

SETUP=r'''
static void setup(int32_t span,int32_t ver,unsigned p,unsigned y,unsigned seed) {
    policy=p;yp=y;memset(memory,0xCD,sizeof memory);
    g_eax=seed^0x15798000;g_ecx=ARCHIVE;g_edx=seed^0xABCD1234;g_ebx=seed^0xBEEFFACE;
    g_esp=STACK;g_ebp=seed^0xEFEF2937;g_esi=seed^0x3679BEEF;g_edi=seed^0xCC811223;
    g_flag_k=FK_ADD;g_flag_a=seed;g_flag_b=0x1942;g_flag_cf=1;
    g_backedges=seed%4u;g_cur_func=0x11111111;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
    g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    /* Incoming NaN payloads and signed zero are not normalized by this integer walk. */
    const uint64_t fpbits[]={0x7FF8000012345678ull,0xFFF0000000000000ull,0x8000000000000000ull};
    memcpy(g_st_win,fpbits,sizeof fpbits);
    for(unsigned i=0;i<8;i++)g_mm[i]=0x0123456789ABCDEFull+i;
    for(unsigned i=0;i<32;i++)((uint32_t *)g_xmm)[i]=0x12B80000u+i;g_mxcsr=0x3F80;
    g_fp_top=5;g_fpu_cw=0xB7F;void_fpu_cmp=0x41;
    MEM32(STACK)=0x91919191;MEM32(STACK+4)=GRID_VA;MEM32(ARCHIVE)=VTABLE;
    for(unsigned off=0;off<=0x100;off+=0x100){
        MEM32(VTABLE+off+0x28)=1;MEM32(VTABLE+off+0x3C)=2;
        MEM32(VTABLE+off+0x1C)=3;MEM32(VTABLE+off+0x20)=5;
        MEM32(VTABLE+off+0x44)=8;MEM32(VTABLE+off+0x24)=10;
    }
    MEM32(GRID_VA)=CELLS;MEM32(GRID_VA+4)=CELLS+(uint32_t)span;MEM32(GRID_VA+8)=CELLS+0x100;
    archive_version=ver;desired_count=(policy&1)?3:(int32_t)span>>2;
    callbacks=yields=events=object_calls=reference_selector_calls=0;recomp_yield_hook=test_yield;
}
'''
COMPARE=GRID_HARNESS[GRID_HARNESS.index('static int compare('):GRID_HARNESS.index('int main(')]
COMPARE=COMPARE.replace('oracle_grid','oracle_vector').replace('void_grid_native_visit','void_vector_native_visit')
COMPARE=COMPARE.replace('memcmp(saved_events,log_events,events*sizeof log_events[0])','!same_events(nevents)')
COMPARE=COMPARE.replace('memcmp(&saved_events[i],&log_events[i],sizeof(event))','!same_event(&saved_events[i],&log_events[i])')
COMPARE=COMPARE.replace('    return 0;\n}',
 '''    for(unsigned i=0;i<events;i++){free(saved_events[i].guest_memory);free(log_events[i].guest_memory);}
    return 0;
}''')
MAIN=r'''
int main(int argc,char **argv) {
    const int32_t spans[]={0,4,12,20,40,-4,-1,-3,(int32_t)0x80000000u,(int32_t)0xFFFFFFFCu};
    const int32_t versions[]={-1,0,1,2,3,(int32_t)0x80000000u,0x7FFFFFFF};
    /* yp2 repeats index0, so stop via a callback shrink after a subsequent item. */
    if(argc==1)for(unsigned d=0;d<sizeof spans/sizeof spans[0];d++)for(unsigned v=0;v<7;v++)
    for(unsigned p=0;p<256;p+=17)for(unsigned y=0;y<2;y++){
        ++case_number;if(compare(spans[d],versions[v],p,y,case_number))return 1;}
    remove("native-vector");int native_mode=argc>1&&!strcmp(argv[1],"native");
    if(argc>1){FILE *f=fopen("native-vector","wb");assert(f);fputs(native_mode?"1\n":argv[1],f);fclose(f);}
    setup(0,0,0,0,1);original_calls=logs=0;void_vector_native_dispatch();
    assert(original_calls==(native_mode?0:1)&&logs==1);
    FILE *f=fopen("native-vector","wb");assert(f);fputs(native_mode?"0":"1",f);fclose(f);
    setup(0,0,0,0,1);void_vector_native_dispatch();assert(original_calls==(native_mode?0:2)&&logs==1);
    remove("native-vector");
    printf("PASS %u vector cases: full CPU/guest memory/callback frames, archive versions/aliases/NaN preservation; cached mode%d\n",case_number,native_mode);
    return 0;
}
'''
PREFIX=GRID_HARNESS[:GRID_HARNESS.index('static void callback(')]
PREFIX=PREFIX.replace('uint32_t stack[12];} event;','uint32_t stack[12];uint8_t *guest_memory;} event;')
PREFIX=PREFIX.replace('    log_events[events].kind=kind;',
 '''    log_events[events].guest_memory=malloc(sizeof memory);assert(log_events[events].guest_memory);
    memcpy(log_events[events].guest_memory,memory,sizeof memory);
    log_events[events].kind=kind;''')
EVENT_COMPARE=r'''
static int same_event(const event *a,const event *b) {
    return a->kind==b->kind&&!memcmp(&a->cpu,&b->cpu,sizeof(state))&&
        !memcmp(a->stack,b->stack,sizeof a->stack)&&!memcmp(a->guest_memory,b->guest_memory,sizeof memory);
}
static int same_events(unsigned count) {
    if(count!=events)return 0;
    for(unsigned i=0;i<count;i++)if(!same_event(&saved_events[i],&log_events[i]))return 0;
    return 1;
}
'''
HARNESS=PREFIX+CALLBACKS+SETUP+EVENT_COMPARE+COMPARE+MAIN

class VectorCandidate(unittest.TestCase):
 def check(self,edition,protocol=False,trace=True,mutant=None):
  entry,helper,unit,calls,caller,vt,col,owner_unit,raw_hash=FACTS[edition]
  pe=pefile.PE(str(generated_root(edition)/'input/H5_Game.exe'),fast_load=True)
  def raw(va,size):return pe.get_data(int(va,16)-pe.OPTIONAL_HEADER.ImageBase,size)
  self.assertEqual(hashlib.sha256(raw(entry,170)).hexdigest(),raw_hash)
  self.assertEqual(hashlib.sha256(raw(helper,48)).hexdigest(),'0eeb80afc1b9e90a24d1b3f9ad0de3431a1fc0e36829bb81d6444569871d778b')
  self.assertEqual(int.from_bytes(raw(f'{int(vt,16)-4:08X}',4),'little'),int(col,16))
  self.assertEqual(int.from_bytes(raw(f'{int(vt,16)+12:08X}',4),'little'),int(caller,16))
  self.assertEqual(int.from_bytes(raw(f'{int(col,16)+4:08X}',4),'little'),136)
  td=int.from_bytes(raw(f'{int(col,16)+12:08X}',4),'little');name=b'.?AVCConquest@NWorld@@\0'
  self.assertEqual(raw(f'{td+8:08X}',len(name)),name)
  owner=transformed(edition,'sub_'+caller,owner_unit)
  call=re.search(r'RECOMP_CALL_P\(sub_'+entry+r',[^\n]+/\* 0x([0-9A-F]{8}): call',owner)
  self.assertIsNotNone(call);instruction=raw(call[1],5)
  self.assertEqual(instruction[0],0xE8)
  self.assertEqual((int(call[1],16)+5+int.from_bytes(instruction[1:],'little',signed=True))&0xFFFFFFFF,int(entry,16))
  oracle=transformed(edition,'sub_'+entry,unit);field=transformed(edition,'sub_'+helper,unit)
  plan=Plan(protocol_root(edition)/'x87.json',edition=edition)
  self.assertEqual(apply_x87((field+oracle).encode(),plan),(field+oracle).encode())
  oracle=oracle.replace('void sub_'+entry+'(void)','void oracle_vector(void)',1)
  source=adapt((ROOT/'android/host/vector_native.c').read_text(),edition)
  if mutant:source=mutant(source)
  names='#define CANONICAL_ENTRY sub_'+entry+'\n'
  for actual,stub in zip(calls,('vector_clear','vector_resize','reference_visit')):names+='#define sub_'+actual+' '+stub+'\n'
  suffix=('-protocol' if protocol else '')+('-notrace' if not trace else '')+('-mutant' if mutant else '')
  out=OUT/('probe-'+edition+suffix);out.mkdir(parents=True,exist_ok=True)
  header=pc_header((ROOT/'android/runtime/recomp_types.h').read_text())
  text=HARNESS if trace else HARNESS.replace('#define RECOMP_TRACE','/* Production trace disabled. */')
  files={'recomp_types.h':header,'host.h':'#include "recomp_types.h"\n','names.h':names,'oracle.h':field+'\n'+oracle,'actual.h':source,'probe.c':text,'native_mode.h':(ROOT/'android/host/native_mode.h').read_text()}
  for name,text in files.items():(out/name).write_text(text,encoding='utf-8')
  env,linker=environment('x64')
  flags=[CLANG,'/nologo','/W0','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS','/clang:--target=x86_64-pc-windows-msvc','/clang:-fno-strict-aliasing','/clang:-fwrapv','/clang:-ffp-contract=off']
  if protocol:flags.append('/DRECOMP_PROTOCOL_CHECK')
  command([*flags,'/c','probe.c','/Foprobe.obj'],out,env)
  command([linker,'/nologo','probe.obj','/OUT:probe.exe','/STACK:1048576'],out,env)
  tested=command([out/'probe.exe'],out,env,check=False)
  if mutant:
   self.assertNotEqual(tested.returncode,0,tested.stdout+tested.stderr);self.assertIn('DIFFERENTIAL FAIL',tested.stderr);return
  self.assertEqual(tested.returncode,0,tested.stdout+tested.stderr)
  enabled=command([out/'probe.exe','native'],out,env,check=False)
  self.assertEqual(enabled.returncode,0,enabled.stdout+enabled.stderr)
  for invalid in ('0','01','1\nextra','2','1\r\n'):
   p=command([out/'probe.exe',invalid],out,env,check=False);self.assertEqual(p.returncode,0,p.stdout+p.stderr)
  (out/'receipt.json').write_text(json.dumps({'edition':edition,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'oracle_sha256':hashlib.sha256((field+oracle).encode()).hexdigest(),'runtime_sha256':hashlib.sha256(header.encode()).hexdigest(),'protocol':protocol,'trace':trace,'results':[tested.stdout,enabled.stdout],'device_tested':False},indent=2)+'\n')
  print(edition+suffix,tested.stdout.strip())
 def test_all_three(self):
  for edition in FACTS:
   with self.subTest(edition=edition):self.check(edition)
 def test_protocol(self):self.check('toe',protocol=True)
 def test_no_trace(self):self.check('toe',trace=False)
 def test_reject_unsigned_archive_version(self):self.check('toe',mutant=lambda s:s.replace('int modern=(int32_t)eax>=2;','int modern=eax>=2;'))
 def test_reject_cached_buffer(self):self.check('toe',mutant=lambda s:s.replace('ecx=VECTOR(ebx)->begin;','ecx=CELLS;'))
 def test_reject_logical_span_shift(self):self.check('toe',mutant=lambda s:s.replace('edx=(uint32_t)((int32_t)edx>>2);','edx=edx>>2;'))
 def test_reject_recomputed_yield_comparison(self):self.check('toe',mutant=lambda s:s.replace('} while(more);','} while((int32_t)eax<(int32_t)MEM32(esp+0xC));'))
 def test_reject_bypassed_reference_selector(self):self.check('toe',mutant=lambda s:s.replace('RECOMP_CALL_P(void_reference_native_object_dispatch,','RECOMP_CALL_P(sub_004FA280,'))

if __name__=='__main__':unittest.main()
