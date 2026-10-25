/* Actual whole 008800B0 body is linked separately in both forms. */

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "recomp_types.h"
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_esi,g_edi,g_ebp;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_cur_func,g_backedges;
uint32_t g_enter_trace[1024],g_enter_idx;
void (*recomp_yield_hook)(void);
enum { BASE=0x20000000, SP=BASE+0x80000, VEC=BASE+0x1000,
       KEYS=BASE+0x20000, SCRATCH=BASE+0x40000, OBJECT=BASE+0x90000, SPAN=0x100000 };
static unsigned checking,event_n;
static unsigned event_counts[2];
typedef struct {uint32_t regs[8],flags[4],cur,counter,enter;uint32_t trace[1024];} state;
typedef struct {state s;uint8_t memory[SPAN];} snapshot;
static snapshot before,after,expected,events[16];
static unsigned compare_mode;
static void take(state *s) {
    memset(s,0,sizeof *s);
    uint32_t r[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_esi,g_edi,g_ebp};
    uint32_t f[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s->regs,r,sizeof r);memcpy(s->flags,f,sizeof f);
    s->cur=g_cur_func;s->counter=g_backedges;s->enter=g_enter_idx;memcpy(s->trace,g_enter_trace,sizeof s->trace);
}
static void take_all(snapshot *s){take(&s->s);memcpy(s->memory,(void*)(uintptr_t)BASE,SPAN);}
static void event(void) {
    if(!checking)return;
    assert(event_n<16);
    if(!compare_mode)take_all(events+event_n);
    else {take_all(&after);assert(!memcmp(&after,events+event_n,sizeof after));}
    ++event_n;
}
void sub_008791F0(void){event();assert(MEM32(g_esp+4)<=32768);g_eax=SCRATCH;g_backedges+=23;g_esp+=4;}
void sub_00879240(void){event();assert(MEM32(g_esp+4)==SCRATCH);g_backedges+=17;g_esp+=4;}
static void yield(void){event();g_backedges=7;}
void baseline_sort(void);void local_sort(void);
static void initialize(unsigned n,unsigned mode,unsigned start) {
    memset((void*)(uintptr_t)BASE,0xA5,SPAN);
    uint32_t x=0x12345678u;
    for(unsigned i=0;i<n;++i){x^=x<<13;x^=x>>17;x^=x<<5;MEM32(VEC+i*4)=i;MEM32(KEYS+i*4)=x;}
    MEM32(OBJECT)=VEC;MEM32(OBJECT+4)=VEC+n*4;
    MEM32(SP)=RECOMP_RETADDR;MEM32(SP+4)=OBJECT;MEM32(SP+8)=mode;
    g_eax=0xEE112233;g_ecx=8;g_edx=KEYS;g_ebx=0x1234;g_esp=SP;g_esi=0x5678;g_edi=0x9ABC;g_ebp=0xDEF0;
    g_flag_k=FK_CMP;g_flag_a=5;g_flag_b=7;g_flag_cf=1;g_cur_func=0;
    memset(g_enter_trace,0x5A,sizeof g_enter_trace);g_enter_idx=0;g_backedges=start;event_n=0;
}
int main(void){
    assert(VirtualAlloc((void*)(uintptr_t)BASE,SPAN,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)==(void*)(uintptr_t)BASE);
    SetThreadAffinityMask(GetCurrentThread(),1);SetThreadPriority(GetCurrentThread(),THREAD_PRIORITY_HIGHEST);
    const unsigned ns[]={0,1,2,31,32,1024,8192};unsigned cases=0;
    for(unsigned a=0;a<7;++a)for(unsigned mode=0;mode<3;++mode)for(unsigned h=0;h<2;++h){
        checking=1;compare_mode=0;recomp_yield_hook=h?yield:NULL;
        initialize(ns[a],mode,h?65530:0);baseline_sort();take_all(&expected);event_counts[0]=event_n;
        compare_mode=1;initialize(ns[a],mode,h?65530:0);local_sort();take_all(&after);event_counts[1]=event_n;
        assert(event_counts[0]==event_counts[1]);if(h)assert(event_n>=3);assert(!memcmp(&expected,&after,sizeof expected));++cases;
    }
    checking=0;recomp_yield_hook=NULL;
    printf("PASS %u actual whole-sort comparisons; exact GPR/lazyflags/counter/trace and 1MiB guest bytes at every call/yield plus return\n",cases);
    return 0;
}
