"""Run the prepared current-model native32 bridge as an isolated Win32 probe."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest

from test_d3d_lifecycle import function

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import prepare_windows_runtime as prepare
import build_windows as builder

HARNESS=r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "native32.h"
#ifndef RECOMP_X87_WINDOW
extern int64_t g_st_i64[8];
#endif
extern int void_fpu_cmp;
static void integer_callback(void),float_callback(void),catch_funclet(void);
const recomp_dispatch_entry_t recomp_dispatch_table[]={{0x30001000u,integer_callback},{0x30001100u,float_callback},{0x30001200u,catch_funclet}};
const uint32_t recomp_dispatch_count=3;
recomp_func_t homm5_pc_dispatch(uint32_t va){
    for(unsigned i=0;i<recomp_dispatch_count;++i)if(recomp_dispatch_table[i].address==va)return recomp_dispatch_table[i].func;
    return NULL;
}
recomp_func_t recomp_lookup_manual(uint32_t va){(void)va;return NULL;}
recomp_func_t void_resolve(uint32_t va){
    recomp_func_t f=recomp_lookup(va);if(!f)f=recomp_lookup_import(va);assert(f);return f;
}
void void_lift_trap(uint32_t va,const char *why){fprintf(stderr,"unexpected trap %08X %s\n",va,why);ExitProcess(3);}
/* ACTUAL_TLS */
/* ACTUAL_CPUID */

typedef struct {
    uint32_t r[8],f[4],fs,cur,backedges,mxcsr;
    uint64_t st[8],mm[8];int64_t shadows[8];xmm_t xmm[8];
    int top,cmp;uint16_t cw;
} state;
static void take(state *s){
    memset(s,0,sizeof *s);
    uint32_t r[]={g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp};
    uint32_t f[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s->r,r,sizeof r);memcpy(s->f,f,sizeof f);
    memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadows,g_st_i64,sizeof g_st_i64);
    memcpy(s->mm,g_mm,sizeof g_mm);memcpy(s->xmm,g_xmm,sizeof g_xmm);
    s->fs=g_fs_base;s->cur=g_cur_func;s->backedges=g_backedges;s->mxcsr=g_mxcsr;
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;
}
static void fill(uint32_t seed){
#ifdef RECOMP_X87_WINDOW
    for(unsigned i=0;i<300;++i)fp_window_push((double)i);
    for(unsigned i=0;i<300;++i)(void)fp_window_pop();
#endif
    g_eax=seed+1;g_ecx=seed+2;g_edx=seed+3;g_ebx=seed+5;
    g_esi=seed+6;g_edi=seed+7;g_ebp=seed+8;
    g_flag_k=FK_CMP;g_flag_a=seed;g_flag_b=seed+1;g_flag_cf=1;
    for(unsigned i=0;i<8;++i){
        uint64_t bits=UINT64_C(0x7FF8123456000000)+seed+i;
        memcpy(g_st+i,&bits,8);g_st_i64[i]=INT64_C(0x123456789ABC0000)+seed+i;
        g_mm[i]=bits;memset(g_xmm+i,(int)((seed+i)&255),sizeof(xmm_t));
    }
    g_fp_top=3;g_fpu_cw=(uint16_t)(0x37F|((seed&3)<<10));
    g_mxcsr=0x1F80|(seed&0x40);void_fpu_cmp=(int)(0x10000|(seed&0x4700));
    g_backedges=seed+123;g_cur_func=seed;
}
static uint32_t tls_block(void){
    uint32_t vector=MEM32(g_fs_base+0x2C);assert(vector==g_fs_base+0x100);
    uint32_t block=MEM32(vector);assert(block==g_fs_base+0x200);return block;
}
static HANDLE a_ready,b_ready;
static uint32_t fs_a,fs_b,block_a,block_b;
static volatile LONG failures;
static void expect(int condition,const char *why){if(!condition){fprintf(stderr,"FAIL %s\n",why);InterlockedIncrement(&failures);}}
static DWORD WINAPI thread_a(void *unused){
    (void)unused;mach_enter();fs_a=g_fs_base;block_a=tls_block();
    expect(!memcmp((void*)(uintptr_t)block_a,"123456789",9),"A staticTLS template");
    MEM8(block_a)=0xA5;fill(0xA10000);state expected,actual;take(&expected);mach_leave();
    SetEvent(a_ready);expect(WaitForSingleObject(b_ready,5000)==WAIT_OBJECT_0,"B signal");
    mach_enter();take(&actual);expect(!memcmp(&expected,&actual,sizeof expected),"complete A thread state restored");
    expect(g_fs_base==fs_a && MEM8(tls_block())==0xA5,"A TLS retained");mach_leave();return 0;
}
static DWORD WINAPI thread_b(void *unused){
    (void)unused;expect(WaitForSingleObject(a_ready,5000)==WAIT_OBJECT_0,"A signal");mach_enter();
    fs_b=g_fs_base;block_b=tls_block();expect(!memcmp((void*)(uintptr_t)block_b,"123456789",9),"B staticTLS template");
    MEM8(block_b)=0xB5;fill(0xB20000);mach_leave();SetEvent(b_ready);return 0;
}

typedef int (__stdcall *callback_t)(int,int);
static unsigned callbacks;
static void integer_callback(void){
    uint32_t _flag_k=FK_NONE,_flag_a=0,_flag_b=0,_cf=0;
    RECOMP_ENTER(0x30001000u);
    uint32_t sp=g_esp,left=MEM32(sp+4),right=MEM32(sp+8);
    assert(MEM8(tls_block())==0xC5);++callbacks;
    /* A native caller is still on the stack: reenter the real native bridge
       from its lifted callback, then return through both stack anchors. */
    DWORD thread=GetCurrentThreadId();
    recomp_func_t nested=recomp_lookup_import((uint32_t)(uintptr_t)GetCurrentThreadId);assert(nested);
    PUSH32(g_esp,RECOMP_RETADDR);nested();
    assert(g_eax==thread && g_esp==sp && MEM8(tls_block())==0xC5);
    fill(0xCC0000);g_fs_base+=0x100;g_eax=left+right;g_esp=sp+12;
    RECOMP_FLAGS_OUT();
}
static int __stdcall invoke_callback(callback_t fn,int value){return fn(value,7)+5;}
static void float_callback(void){
    uint32_t _flag_k=FK_NONE,_flag_a=0,_flag_b=0,_cf=0;
    RECOMP_ENTER(0x30001100u);assert(MEM32(g_esp+4)==7);
    fp_push_impl(g_st,&g_fp_top,3.5);g_esp+=8;RECOMP_FLAGS_OUT();
}
typedef double (__stdcall *float_callback_t)(int);
static double __stdcall invoke_float(float_callback_t fn){return fn(7);}
static uint64_t __stdcall wide_result(int v){assert(v==9);return UINT64_C(0x12345678AABBCCDD);}
static uint32_t __stdcall error_result(void){SetLastError(0x7788);return 0x12345678;}
static uint32_t call(void *fn,unsigned n,const uint32_t *args){
    for(unsigned i=n;i;i--)PUSH32(g_esp,args[i-1]);
    recomp_func_t bridge=recomp_lookup_import((uint32_t)(uintptr_t)fn);assert(bridge);
    PUSH32(g_esp,RECOMP_RETADDR);bridge();return g_eax;
}
static void catch_funclet(void){
#ifdef RECOMP_X87_WINDOW
    double before[8];int64_t shadow[8];int top=g_fp_top;
    memcpy(before,g_st,sizeof before);memcpy(shadow,g_st_i64,sizeof shadow);
    for(unsigned i=0;i<600;++i)fp_window_push((double)i);
    memcpy(g_st,before,sizeof before);memcpy(g_st_i64,shadow,sizeof shadow);g_fp_top=top;
    fp_window_push(9.25);
#else
    fp_push_impl(g_st,&g_fp_top,9.25);
#endif
    g_eax=0x30001300;g_esp+=4;
}
extern void native32_shim_CxxThrowException(void);
static void actual_guest_eh(void){
    uint32_t _flag_k=FK_NONE,_itail_tgt=0;
    uint32_t entry=g_esp,old_chain=MEM32(g_fs_base),rec=entry-16;
    RECOMP_EH_ENTER();
    MEM8(0x30002100)=0xB8;MEM32(0x30002101)=0x30002120;MEM8(0x30002105)=0xE9;
    MEM32(0x30002120)=0x19930522;MEM32(0x30002124)=0;MEM32(0x30002128)=0;
    MEM32(0x3000212C)=1;MEM32(0x30002130)=0x30002160;
    MEM32(0x30002160)=0;MEM32(0x30002164)=0;MEM32(0x30002168)=0;
    MEM32(0x3000216C)=1;MEM32(0x30002170)=0x30002180;
    MEM32(0x30002180)=0;MEM32(0x30002184)=0;MEM32(0x30002188)=0;MEM32(0x3000218C)=0x30001200;
    MEM32(rec)=old_chain;MEM32(rec+4)=0x30002100;MEM32(rec+8)=0;
    MEM32(rec-4)=entry-0x40;MEM32(g_fs_base)=rec;
    g_esp=entry-0x40;PUSH32(g_esp,0x300021A0);PUSH32(g_esp,0x300021C0);PUSH32(g_esp,RECOMP_RETADDR);
    native32_shim_CxxThrowException();
    expect(0,"guest throw must resume through actual EH landing pad");
_ljump:
    expect(_itail_tgt==0x30001300 && g_eax==0x30001300,"actual guest catch continuation");
    expect(g_ebp==rec+12 && g_esp==entry-0x40 && MEM32(rec+8)==1,"actual EH frame/stack continuation");
    RECOMP_EH_LEAVE();MEM32(g_fs_base)=old_chain;g_esp=entry;
}
int main(int argc,char **argv){
    assert(argc==2);
    void *template=VirtualAlloc((void*)0x010E0000,0x10000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    assert(template==(void*)0x010E0000);MEM32(0x010E5674)=0;memcpy((void*)0x010EA000,"123456789",9);
    native32_init();assert(native32_map(argv[1],0x30000000)==0x3000);
    struct {uint32_t base,span;} mapped={0x30000000,0x3000},*module=&mapped;
    /* ACTUAL_MAP_PROTECTION */
    MEMORY_BASIC_INFORMATION mbi;assert(VirtualQuery((void*)0x30001000,&mbi,sizeof mbi));
    assert(!(mbi.Protect&(PAGE_EXECUTE|PAGE_EXECUTE_READ|PAGE_EXECUTE_READWRITE|PAGE_EXECUTE_WRITECOPY)));
    assert(native32_in_guest(0x30002010) && !recomp_lookup(0x30002010));
    expect(recomp_lookup_import(0x30002010)==NULL,"unresolved guest data never falls back to native execution");
    assert(VirtualQuery((void*)0x30002010,&mbi,sizeof mbi));
    expect(mbi.Protect==PAGE_READWRITE,"guest data remains PAGE_READWRITE after import lookup");
    a_ready=CreateEvent(NULL,FALSE,FALSE,NULL);b_ready=CreateEvent(NULL,FALSE,FALSE,NULL);assert(a_ready&&b_ready);
    HANDLE a=CreateThread(NULL,0,thread_a,NULL,0,NULL),b=CreateThread(NULL,0,thread_b,NULL,0,NULL);assert(a&&b);
    assert(WaitForSingleObject(a,10000)==WAIT_OBJECT_0 && WaitForSingleObject(b,10000)==WAIT_OBJECT_0);
    CloseHandle(a);CloseHandle(b);CloseHandle(a_ready);CloseHandle(b_ready);
    expect(fs_a!=fs_b && block_a!=block_b,"separate thread TIB/staticTLS");
    mach_enter();assert(!memcmp((void*)(uintptr_t)tls_block(),"123456789",9));MEM8(tls_block())=0xC5;
    fill(0xC30000);state expected,actual;take(&expected);
    uint32_t args[]={0x30001000,30};unsigned trace_before=g_enter_idx;
    uint32_t result=call(invoke_callback,2,args);expect(result==42,"actual NX callback result");
    take(&actual);expected.r[0]=42;expected.r[2]=actual.r[2];
    expect(!memcmp(&expected,&actual,sizeof expected),"native callback restores complete outer state");
    expect(callbacks==1 && g_enter_idx==trace_before+1 && g_enter_trace[trace_before&1023]==0x30001000,"callback traced once");
    expect(MEM8(tls_block())==0xC5,"callback TLS return");
    fill(0xC30000);take(&expected);uint32_t wide_arg[]={9};call(wide_result,1,wide_arg);take(&actual);
    expected.r[0]=0xAABBCCDD;expected.r[2]=0x12345678;expect(!memcmp(&expected,&actual,sizeof expected),"EDX:EAX native return/purge");
    fill(0xC30000);take(&expected);uint32_t float_arg[]={0x30001100};call(invoke_float,1,float_arg);take(&actual);
    expected.r[0]=actual.r[0];expected.r[2]=actual.r[2];
    for(int i=7;i>0;--i){expected.st[i]=expected.st[i-1];expected.shadows[i]=expected.shadows[i-1];}
    double value=3.5;memcpy(expected.st,&value,8);expected.shadows[0]=0;++expected.top;
    expect(!memcmp(&expected,&actual,sizeof expected),"native floating callback push/shadow roundtrip");
    SetLastError(0x1122);call(error_result,0,NULL);expect(GetLastError()==0x7788,"native last-error survives machine entry");
    fill(0xC30000);take(&expected);actual_guest_eh();take(&actual);
    for(int i=7;i>0;--i){expected.st[i]=expected.st[i-1];expected.shadows[i]=expected.shadows[i-1];}
    value=9.25;memcpy(expected.st,&value,8);expected.shadows[0]=0;++expected.top;
    expect(!memcmp(expected.st,actual.st,sizeof expected.st) && !memcmp(expected.shadows,actual.shadows,sizeof expected.shadows)
        && expected.top==actual.top && expected.cmp==actual.cmp && expected.cw==actual.cw,"actual guest EH preserves full logical FPU state after window recenter");
    DWORD_PTR allowed,system;assert(GetProcessAffinityMask(GetCurrentProcess(),&allowed,&system));
    DWORD_PTR previous_mask=SetThreadAffinityMask(GetCurrentThread(),allowed&(~allowed+1));assert(previous_mask);
    const uint32_t leaves[][2]={{0,0},{1,0},{7,0},{7,1},{0x80000000,0},{0x80000001,0},{0xFFFFFFFF,3}};
    for(unsigned i=0;i<sizeof(leaves)/sizeof(leaves[0]);++i){
        int registers[4];__cpuidex(registers,(int)leaves[i][0],(int)leaves[i][1]);
        fill(0xC30000);take(&expected);void_cpuid(leaves[i][0],leaves[i][1]);take(&actual);
        expected.r[0]=(uint32_t)registers[0];expected.r[4]=(uint32_t)registers[1];
        expected.r[1]=(uint32_t)registers[2];expected.r[2]=(uint32_t)registers[3];
        expect(!memcmp(&expected,&actual,sizeof expected),"actual PC CPUID leaves/subleaves and preserved state");
    }
    assert(SetThreadAffinityMask(GetCurrentThread(),previous_mask));
    /* GENERATED_PROBE */
    mach_leave();
    if(failures)return 1;
    puts("PASS Win32 current runtime: full GPR/flags/FPU shadows/MMX/XMM/cmp/CW/backedge thread restore; real native bridge/NX callbacks/float return; actual guest C++ EH continuation; H5 staticTLS; actual hardware CPUID");
    return 0;
}
'''


def make_pe(path):
    raw=bytearray(0x600);raw[:2]=b'MZ';struct.pack_into('<I',raw,0x3C,0x80);raw[0x80:0x84]=b'PE\0\0'
    struct.pack_into('<HHIIIHH',raw,0x84,0x14C,2,0,0,0,0xE0,0x102)
    optional=0x98;struct.pack_into('<H',raw,optional,0x10B)
    for offset,value in ((16,0x1000),(20,0x1000),(28,0x30000000),(32,0x1000),(36,0x200),(56,0x3000),(60,0x200),(92,16)):
        struct.pack_into('<I',raw,optional+offset,value)
    section=optional+0xE0;raw[section:section+8]=b'.text\0\0\0'
    struct.pack_into('<IIII',raw,section+8,0x1000,0x1000,0x200,0x200)
    struct.pack_into('<I',raw,section+36,0x60000020);raw[0x200:0x400]=b'\xCC'*0x200
    section+=40;raw[section:section+8]=b'.data\0\0\0'
    struct.pack_into('<IIII',raw,section+8,0x1000,0x2000,0x200,0x400)
    struct.pack_into('<I',raw,section+36,0xC0000040);raw[0x410]=0xC3
    path.write_bytes(raw)


GENERATED_PROBE=r'''
    float left[16]={0},right[16],output[16];
    uint32_t sample=GetTickCount()&255;
    for(unsigned i=0;i<4;++i)left[i*5]=1.0f;
    for(unsigned i=0;i<16;++i){right[i]=(float)(i+sample)+0.25f;output[i]=-99.0f;}
    uint32_t original_sp=g_esp;
    g_ecx=(uint32_t)(uintptr_t)output;g_edx=(uint32_t)(uintptr_t)right;
    PUSH32(g_esp,(uint32_t)(uintptr_t)left);PUSH32(g_esp,RECOMP_RETADDR);
    sub_007CC7C0();
    expect(g_esp==original_sp && g_eax==(uint32_t)(uintptr_t)left,"actual generated matrix ret4 ABI");
    expect(!memcmp(output,right,sizeof output),"actual generated whole chunk identity-matrix result");
'''


def actual_resolver_probe(host):
    """Use the host's real dispatch, manual handlers and cache, not the template stubs."""
    fixture=(ROOT/'tests/fixtures/windows_resolver_probe.c').read_text(encoding='utf8')
    declarations,tail=fixture.split('\n/* BASELINE_RESOLVER */\n')
    baseline,checks=tail.split('\n/* RESOLVER_CHECKS */\n')
    start=host.index('typedef struct { uint32_t va; recomp_func_t fn; } pc_slot;')
    dispatch=host[start:host.index('\nvoid void_lift_trap(',start)]
    dispatch=dispatch.replace('static pc_slot resolve_cache[4096];','static pc_slot resolve_cache[4096],baseline_cache[4096];')
    dispatch=dispatch.replace('static void dispatch_init(void)','void probe_dispatch_init(void)')
    manuals='\n'.join(function(host,s) for s in ['static void thread_get_error(',
        'static void thread_set_error(', 'static void thread_tls_value(', 'recomp_func_t recomp_lookup_manual('])
    resolver='#include <windows.h>\n#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n#include "native32.h"\nextern uint32_t g_native_target;\nvoid void_lift_trap(uint32_t,const char *);\n'+dispatch+'\n'+manuals+'\n'
    resolver+=baseline.replace('void_resolve','baseline_resolve',1).replace('resolve_cache','baseline_cache')+'\n'
    resolver+=function(host,'static __attribute__((noinline)) recomp_func_t pc_resolve_slow(')+'\n'+function(host,'recomp_func_t void_resolve(')
    resolver+='\nrecomp_func_t probe_manual_expected(uint32_t va){return recomp_lookup_manual(va);}\n'
    resolver+='void probe_cache_reset(void){memset(resolve_cache,0,sizeof resolve_cache);memset(baseline_cache,0,sizeof baseline_cache);}\n'
    resolver+='int probe_caches_equal(void){return !memcmp(resolve_cache,baseline_cache,sizeof resolve_cache);}\n'
    harness=HARNESS.replace('static void integer_callback(void),float_callback(void),catch_funclet(void);',
        'static void integer_callback(void),float_callback(void),catch_funclet(void);\nstatic void collision_first(void){g_eax=0x1111;}\nstatic void collision_second(void){g_eax=0x2222;}\n'+declarations)
    start=harness.index('const recomp_dispatch_entry_t recomp_dispatch_table[]');stop=harness.index('recomp_func_t homm5_pc_dispatch(',start)
    harness=harness[:start]+'const recomp_dispatch_entry_t recomp_dispatch_table[]={{0x30001000u,integer_callback},{0x30001016u,collision_first},{0x30001100u,float_callback},{0x30001200u,catch_funclet},{0x30001A2Eu,collision_second}};\nconst uint32_t recomp_dispatch_count=5;\n'+harness[stop:]
    for signature in ['recomp_func_t homm5_pc_dispatch(', 'recomp_func_t recomp_lookup_manual(', 'recomp_func_t void_resolve(']:
        harness=harness.replace(function(harness,signature),'',1)
    harness=harness.replace(function(harness,'void void_lift_trap('),
        'void void_lift_trap(uint32_t va,const char *why){if(expecting_trap){trapped_va=va;trapped_reason=why;longjmp(trap_return,1);}fprintf(stderr,"unexpected trap %08X %s\\n",va,why);ExitProcess(3);}',1)
    harness=harness.replace('assert(native32_map(argv[1],0x30000000)==0x3000);','assert(native32_map(argv[1],0x30000000)==0x3000);probe_dispatch_init();')
    harness=harness.replace('MEM8(block_a)=0xA5;fill(', 'MEM8(block_a)=0xA5;resolver_thread_check(0xA10000);fill(')
    harness=harness.replace('MEM8(block_b)=0xB5;fill(', 'MEM8(block_b)=0xB5;resolver_thread_check(0xB20000);fill(')
    harness=harness.replace('fill(0xC30000);state expected,actual;take(&expected);','run_resolver_checks();\n    fill(0xC30000);state expected,actual;take(&expected);',1)
    harness=harness.replace('recomp_func_t bridge=recomp_lookup_import((uint32_t)(uintptr_t)fn);assert(bridge);',
        'recomp_func_t bridge=void_resolve((uint32_t)(uintptr_t)fn);assert(bridge);')
    harness=harness.replace('int main(int argc,char **argv){',checks+'\nint main(int argc,char **argv){',1)
    return harness,resolver


def run_probe(negative=False,thin=False,window=False):
    out=ROOT/'build/tests'/(('windows_runtime_thinlto' if thin else 'windows_runtime_bad_shadow' if negative else 'windows_runtime')+('_window' if window else ''))
    runtime=out/'runtime';receipt=prepare.prepare(runtime)
    host=(ROOT/'native/windows_host.c').read_text(encoding='utf8')
    harness,resolver=actual_resolver_probe(host)
    (out/'resolver.c').write_text(resolver,encoding='utf8')
    harness=harness.replace('/* ACTUAL_TLS */',function(host,'void homm5_pc_thread_init('))
    harness=harness.replace('/* ACTUAL_CPUID */',function(host,'void void_cpuid('))
    protection=re.findall(r'DWORD old;\s*if \(!VirtualProtect\(\(void \*\)\(uintptr_t\)module->base, module->span, PAGE_READWRITE, &old\)\) return 66;',function(host,'int main('))
    assert len(protection)==1,'Actual host full-image NX protection changed'
    harness=harness.replace('/* ACTUAL_MAP_PROTECTION */',protection[0])
    harness=harness.replace('/* GENERATED_PROBE */',GENERATED_PROBE if thin else '')
    if thin:harness=harness.replace('static void integer_callback(void),float_callback(void),catch_funclet(void);',
        'static void integer_callback(void),float_callback(void),catch_funclet(void);\nvoid sub_007CC7C0(void);')
    (out/'probe.c').write_text(harness,encoding='utf8');make_pe(out/'callback-nx.dll')
    if negative:
        path=runtime/'native32.c';text=path.read_text(encoding='utf8')
        before='memcpy(g_st_i64, r->st_i64, sizeof g_st_i64); void_fpu_cmp = r->fpu_cmp;'
        assert before in text;path.write_text(text.replace(before,'void_fpu_cmp = r->fpu_cmp;',1),encoding='utf8')
    compiler,linker,env=builder.compiler_environment()
    flags=['/nologo','/O2','/W3','/std:c11','/D_CRT_SECURE_NO_WARNINGS','/DVOID_GUEST_BASE=0','/DRECOMP_TRACE',
        '/clang:--target=i686-pc-windows-msvc','/clang:-fno-strict-aliasing','/clang:-fwrapv','/clang:-ffp-contract=off',
        '/I'+str(runtime),'/FI'+str(runtime/'recomp_types.h'),'/I'+str(ROOT/'reference/pcrecomp/runtime/recomp32')]
    if window:flags.append('/DRECOMP_X87_WINDOW')
    sources=[out/'probe.c',out/'resolver.c',runtime/'native32.c',ROOT/'reference/pcrecomp/runtime/recomp32/image_loader.c',ROOT/'reference/pcrecomp/runtime/recomp32/recomp_trace.c']
    generated=None
    trap_symbols=[]
    if thin:
        flags+=['/clang:-flto=thin','/Gy']
        generated=builder.prepare_generated(ROOT/'generated/game-x86/game_0308.c',out)
        sources.append(generated)
        body=generated.read_text(encoding='utf8')
        defined=set(re.findall(r'^void (sub_[0-9A-F]{8})\(void\) \{',body,re.M))
        trap_symbols=sorted(set(re.findall(r'\bsub_[0-9A-F]{8}\b',body))-defined)
        assert 'sub_007CC7C0' in defined and trap_symbols
        # Link the whole real chunk; unrelated guest dependencies must trap if reached.
        stubs=out/'unused_chunk_dependencies.c'
        stubs.write_text('#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <stdio.h>\n'+''.join(
            f'void {name}(void) {{ fputs("unexpected standalone dependency {name}\\n",stderr); ExitProcess(4); }}\n'
            for name in trap_symbols),encoding='utf8')
        sources.append(stubs)
    commands=[];logs=[];objects=[]
    for source in sources:
        obj=out/(source.stem+'.obj');objects.append(obj)
        extra=['/DRECOMP_GENERATED_CODE','/DRECOMP_LOCAL_REGS','/DRECOMP_PLAIN_MEMORY','/I'+str(ROOT/'generated/game-x86')] if source==generated else []
        args=[str(compiler),*flags,*extra,'/c',str(source),'/Fo'+str(obj)];commands.append(args)
        result=subprocess.run(args,cwd=out,env=env,text=True,capture_output=True,timeout=90)
        logs.append(result.stdout+result.stderr)
        assert result.returncode==0,result.stdout+result.stderr
    linktool=[str(compiler.parent/'ld.lld.exe'),'-flavor','link'] if thin else [str(linker)]
    args=[*linktool,'/nologo',*map(str,objects),'/OUT:'+str(out/'probe.exe'),'/MACHINE:X86','/BASE:0x60000000','/DYNAMICBASE:NO','/FIXED','/NXCOMPAT','/STACK:262144']
    if thin:args+=['/OPT:REF','/OPT:ICF','/lldltocache:'+str(out/'thinlto-cache')]
    commands.append(args);result=subprocess.run(args,cwd=out,env=env,text=True,capture_output=True,timeout=90)
    logs.append(result.stdout+result.stderr);(out/'compile.log').write_text(''.join(logs),encoding='utf8')
    assert result.returncode==0,result.stdout+result.stderr
    cache_files=[]
    if thin:
        cache=out/'thinlto-cache'
        before={p.name:builder.sha(p) for p in cache.iterdir() if p.name.startswith('llvmcache-')}
        assert before,'ThinLTO linker did not populate its explicit cache'
        commands.append(args);relink=subprocess.run(args,cwd=out,env=env,text=True,capture_output=True,timeout=90)
        assert relink.returncode==0,relink.stdout+relink.stderr
        after={p.name:builder.sha(p) for p in cache.iterdir() if p.name.startswith('llvmcache-')}
        assert before==after,'identical ThinLTO relink changed cached machine-code objects'
        cache_files=sorted(after)
    result=subprocess.run([str(out/'probe.exe'),str(out/'callback-nx.dll')],cwd=out,text=True,capture_output=True,timeout=20)
    assert 'PASS actual Windows resolver: 1424 exact lookups' in result.stdout,result.stdout+result.stderr
    (out/'result.txt').write_text(result.stdout+result.stderr,encoding='utf8')
    (out/'verification.json').write_text(json.dumps(dict(exit_code=result.returncode,output=result.stdout+result.stderr,
        commands=commands,runtime=receipt,negative_shadow_control=negative,thinlto=thin,x87_window=window,
        trap_only_unexecuted_chunk_dependencies=trap_symbols,thinlto_cache_files=cache_files,
        generated_chunk_sha256=builder.sha(generated) if generated else None,
        probe_sha256=hashlib.sha256((out/'probe.c').read_bytes()).hexdigest(),
        actual_resolver_sha256=builder.sha(out/'resolver.c'),resolver_fixture_sha256=builder.sha(ROOT/'tests/fixtures/windows_resolver_probe.c'),
        tls_initializer_sha256=hashlib.sha256(function(host,'void homm5_pc_thread_init(').encode()).hexdigest(),
        executable_sha256=builder.sha(out/'probe.exe'),compiler_sha256=builder.sha(compiler)),indent=2)+'\n',encoding='utf8')
    return result


class WindowsRuntimeTest(unittest.TestCase):
    def test_full_current_runtime_threads_callbacks_and_tls(self):
        result=run_probe();self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())

    def test_old_shadow_omission_fails_actual_execution(self):
        result=run_probe(True);self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL complete A thread state restored',result.stderr)

    def test_thinlto_actual_bridge_callbacks_and_generated_chunk(self):
        result=run_probe(thin=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_window_actual_bridge_threads_callbacks_and_eh(self):
        result=run_probe(window=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())

    def test_window_thinlto_generated_chunk_and_eh(self):
        result=run_probe(thin=True,window=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_window_shadow_omission_is_detected(self):
        result=run_probe(negative=True,window=True);self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL complete A thread state restored',result.stderr)


if __name__=='__main__':unittest.main()
