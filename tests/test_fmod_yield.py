"""Execute the production backedge, FIFO handoff and full register save/load."""
import importlib.util
import sys
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

sys.path.insert(0,str(ROOT/"tools"))   # build_android.py imports its sibling transforms
spec=importlib.util.spec_from_file_location("yield_builder",ROOT/"tools/build_android.py")
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

HARNESS=r'''
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <errno.h>
typedef union {uint64_t u64[2];uint32_t u32[4];double f64[2];} xmm_t;
typedef struct recomp_ehframe_t {int unused;} recomp_ehframe_t;
/* ACTUAL_REG_TYPE */
static uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,g_fs_base,g_cur_func;
static uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_mxcsr,g_eh_obj,g_eh_info;
static double g_st[8];static int64_t g_st_i64[8];static int g_fp_top,void_fpu_cmp;
static uint16_t g_fpu_cw;static uint64_t g_fp_round_mask,g_fp_store_mask;static uint64_t g_mm[8];static xmm_t g_xmm[8];
static recomp_ehframe_t *g_eh_frames;
static uint32_t g_backedges;
/* ACTUAL_REG_SAVE_LOAD */

/* Native Windows primitives supply the pthread mutex/condition interface;
   the production FIFO ticket algorithm and yield hook execute unchanged. */
typedef SRWLOCK pthread_mutex_t;
typedef CONDITION_VARIABLE pthread_cond_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
#define PTHREAD_COND_INITIALIZER CONDITION_VARIABLE_INIT
static void pthread_mutex_lock(pthread_mutex_t *m) {AcquireSRWLockExclusive(m);}
static void pthread_mutex_unlock(pthread_mutex_t *m) {ReleaseSRWLockExclusive(m);}
static void pthread_cond_wait(pthread_cond_t *c,pthread_mutex_t *m) {
    assert(SleepConditionVariableSRW(c,m,INFINITE,0));
}
static void check_broadcast(void);
static void pthread_cond_broadcast(pthread_cond_t *c) {check_broadcast();WakeAllConditionVariable(c);}
typedef struct {void_regs regs;int depth;} void_thread;
static __declspec(thread) void_thread *t_self;
static pthread_mutex_t mlock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t mcond=PTHREAD_COND_INITIALIZER;
static uint64_t ticket_next,ticket_serving;
static __declspec(thread) uint64_t t_lock_wait_ns;
static unsigned yields,progress,owner_steps,seen_step[2],seen_order[2];
static unsigned handoffs,native_sleeps;
static void_thread *handoff_owner;
static uint64_t expected_next,expected_serving;
static void queue_waiter(uint64_t target);
static void check_broadcast(void) {
    if(t_self==handoff_owner) {
        /* This executes under mlock, before any waiting thread can run.
           Release-then-requeue deterministically lacks the owner's ticket. */
        assert(ticket_next==expected_next && ticket_serving==expected_serving);
        ++handoffs;handoff_owner=NULL;
    }
}
static uint64_t now_ns(void) {return GetTickCount64()*1000000ull;}
static int sched_yield(void) {++yields;SwitchToThread();return 0;}
static int nanosleep(const struct timespec *request,struct timespec *remaining) {
    (void)remaining;assert(request->tv_sec==0 && request->tv_nsec==1000000);
    ++native_sleeps;return 0;
}
static void void_fatal(const char *message) {fputs(message,stderr);assert(0);}
static volatile LONG pins;
static void pin_guest_thread(void) {InterlockedIncrement(&pins);}
/* ACTUAL_MACHINE */
/* ACTUAL_BLOCKING_AND_YIELD */
/* ACTUAL_SLEEP */
static void (*recomp_yield_hook)(void);
static void_thread audio,render[2];
static void_regs expected_yield;
static void capture_expected(uint32_t a,uint32_t c,uint32_t d,uint32_t b,
                             uint32_t sp,uint32_t bp,uint32_t si,uint32_t di) {
    void_regs_save(&expected_yield);
#ifndef TEST_SLEEP_HANDOFF
    expected_yield.backedges=0; /* The backedge macro resets before invoking the hook. */
#endif
    expected_yield.eax=a;expected_yield.ecx=c;expected_yield.edx=d;expected_yield.ebx=b;
    expected_yield.esp=sp;expected_yield.ebp=bp;expected_yield.esi=si;expected_yield.edi=di;
}
/* ACTUAL_LOCAL_REG_MACROS */
/* ACTUAL_BACKEDGE_MACRO */

static void run_lifted(unsigned count,int pending) {
    RECOMP_REGS_LOCALS
    uint32_t _cf=1,_flag_k=17,_flag_a=0x9ABC1234u,_flag_b=0x87654321u;
    for(unsigned i=1;i<=count;++i) {
        eax+=i;ecx^=i*3;edx+=i*7;ebx-=i*9;esp+=i*11;ebp^=i*13;esi+=i*17;edi-=i*19;
        g_st[0]+=0.25;g_st_i64[1]^=i;g_fp_top=(int)(i&7);
        g_mm[2]+=i;g_xmm[3].u32[1]^=i;g_flag_a^=i;
        if(pending && i==RECOMP_YIELD_EVERY) {
            capture_expected(eax,ecx,edx,ebx,esp,ebp,esi,edi);
        }
        owner_steps=i;
#ifdef TEST_SLEEP_HANDOFF
        if(pending && i==RECOMP_YIELD_EVERY) {
            RECOMP_REGS_OUT();sleep_ms(0);RECOMP_REGS_IN();
        }
#endif
        RECOMP_BACKEDGE();
        assert(_cf==1 && _flag_k==17 && _flag_a==0x9ABC1234u && _flag_b==0x87654321u);
    }
    RECOMP_REGS_OUT();
}
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi

static DWORD WINAPI renderer(void *arg) {
    unsigned which=(unsigned)(uintptr_t)arg;
    t_self=&render[which];machine_acquire();
    assert(handoffs==1 && ticket_next==expected_next);
    assert(!memcmp(&audio.regs,&expected_yield,sizeof expected_yield));
    seen_step[which]=owner_steps;seen_order[which]=++progress;
    void_regs_load(&render[which].regs);
    g_eax^=0xFFFFFFFFu;g_st[0]=-999.5;g_st_i64[1]=INT64_MIN;
    g_xmm[3].u64[0]^=UINT64_MAX;g_flag_a=0xBADBADu;g_eh_obj=0xBAD123u;
    void_regs_save(&render[which].regs);machine_release();return 0;
}
static void queue_waiter(uint64_t target) {
    ULONGLONG deadline=GetTickCount64()+2000;
    while(__atomic_load_n(&ticket_next,__ATOMIC_RELAXED)!=target) {
        assert(GetTickCount64()<deadline);Sleep(0);
    }
}
static void initialize(void_regs *r,uint32_t seed) {
    memset(r,0,sizeof *r);
    r->eax=seed+1;r->ecx=seed+2;r->edx=seed+3;r->ebx=seed+4;
    r->esp=seed+5;r->ebp=seed+6;r->esi=seed+7;r->edi=seed+8;
    r->fs=seed+9;r->cur=seed+10;r->flag_k=seed+11;r->flag_a=seed+12;r->flag_b=seed+13;r->flag_cf=seed+14;
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=UINT64_C(0x7FF8123456789ABC)+seed+i;
        memcpy(&r->st[i],&bits,8);r->st_i64[i]=INT64_MAX-seed-i;
        r->mm[i]=UINT64_C(0xAA00BB11CC22DD33)+seed+i;
        r->xmm[i].u64[0]=seed+i;r->xmm[i].u64[1]=UINT64_MAX-seed-i;
    }
    r->st[0]=0.5;r->fp_top=3;r->fpu_cmp=-1;r->fpu_cw=0x77F;r->mxcsr=0x1F80;
    r->eh_frames=(void *)(uintptr_t)(seed+0x100);r->eh_obj=seed+15;r->eh_info=seed+16;
}
int main(void) {
    void_regs initial,serial,actual;initialize(&initial,0x12340000u);
    t_self=&audio;audio.depth=1;machine_acquire();void_regs_load(&initial);
    /* NULL hook remains harmless even past the compile-time threshold. */
    recomp_yield_hook=NULL;g_backedges=0;run_lifted(RECOMP_YIELD_EVERY*2+7,0);
    assert(!yields && g_backedges==RECOMP_YIELD_EVERY*2+7);
    memset(&serial,0,sizeof serial);void_regs_save(&serial);
    void_regs_load(&initial);g_backedges=0;recomp_yield_hook=yield_hook;
    initialize(&render[0].regs,0x43210000u);initialize(&render[1].regs,0x56780000u);
    render[0].depth=render[1].depth=1;
    uint64_t first_target=ticket_next+1;
    HANDLE first=CreateThread(NULL,0,renderer,(void *)(uintptr_t)0,0,NULL);assert(first);queue_waiter(first_target);
    HANDLE second=CreateThread(NULL,0,renderer,(void *)(uintptr_t)1,0,NULL);assert(second);queue_waiter(first_target+1);
    assert(machine_contended());handoff_owner=t_self;
    expected_next=ticket_next+1;expected_serving=ticket_serving+1;
    run_lifted(RECOMP_YIELD_EVERY*2+7,1);
    assert(progress==2 && seen_order[0]==1 && seen_order[1]==2);
    assert(seen_step[0]==RECOMP_YIELD_EVERY && seen_step[1]==RECOMP_YIELD_EVERY);
    assert(handoffs==1 && !yields && g_backedges==7 && !machine_contended());
    memset(&actual,0,sizeof actual);void_regs_save(&actual);
    assert(serial.backedges==RECOMP_YIELD_EVERY*2+7 && actual.backedges==7);
    /* NULL-hook serial execution retains a different scheduling budget.
       Compare architectural state separately, without weakening budget checks. */
    serial.backedges=actual.backedges;assert(!memcmp(&serial,&actual,sizeof serial));
    /* Modules retain the same current thread's budget. Entering FMOD within
       that thread with an already-large count still polls at the next edge. */
    g_backedges=RECOMP_YIELD_EVERY+17;run_lifted(1,0);assert(!g_backedges && !yields);
    assert(pins==4); /* Initial owner, both waiters, owner's atomic return. */
    sleep_ms(0);assert(yields==1 && pins==4); /* No waiter: retain the native yield. */
    sleep_ms(1);assert(native_sleeps==1 && pins==5 && audio.depth==1);
    machine_release();assert(WaitForSingleObject(first,2000)==WAIT_OBJECT_0);
    assert(WaitForSingleObject(second,2000)==WAIT_OBJECT_0);CloseHandle(first);CloseHandle(second);
    printf("PASS yield=%u: owner return ticket reserved before broadcast/first waiter; FIFO/full GPR/FPU/i64/MMX/XMM/flags/EH exact; local flags and affinity survive; contended/no-waiter Sleep paths safe\n",RECOMP_YIELD_EVERY);
    return 0;
}
'''


def production_fixture(harness=HARNESS):
    runtime=(ROOT/"android/runtime/recomp_types.h").read_text(encoding="utf8")
    threads=(ROOT/"android/host/threads.c").read_text(encoding="utf8")
    core=(ROOT/"android/host/core.c").read_text(encoding="utf8")
    host=(ROOT/"android/host/host.h").read_text(encoding="utf8")
    typ=host[host.index("typedef struct void_regs {"):host.index("} void_regs;")+12]
    macros=runtime[runtime.index("#if defined(RECOMP_GENERATED_CODE) && defined(RECOMP_LOCAL_REGS)"):runtime.index("#if defined(RECOMP_GENERATED_CODE) && !defined(RECOMP_LOCAL_REGS)")]
    edge=runtime[runtime.index("#ifndef RECOMP_YIELD_EVERY"):runtime.index("/* Always-callable trace dump")]
    fixture=harness.replace("/* ACTUAL_REG_TYPE */",typ)
    fixture=fixture.replace("/* ACTUAL_REG_SAVE_LOAD */",body(core,"void void_regs_save(")+"\n"+body(core,"void void_regs_load("))
    fixture=fixture.replace("/* ACTUAL_MACHINE */","\n".join(body(threads,s) for s in ["static void machine_acquire(","static void machine_release(","static int machine_contended("]))
    fixture=fixture.replace("/* ACTUAL_BLOCKING_AND_YIELD */","\n".join(body(threads,s) for s in ["void void_blocking_begin(","void void_blocking_end(","static void yield_hook("]))
    fixture=fixture.replace("/* ACTUAL_SLEEP */",body(threads,"static void sleep_ms("))
    return fixture.replace("/* ACTUAL_LOCAL_REG_MACROS */",macros).replace("/* ACTUAL_BACKEDGE_MACRO */",edge)


class FMODYieldTest(unittest.TestCase):
    def test_only_fmod_receives_candidate_flag(self):
        self.assertEqual(builder.module_compile_flags("fmod-x86"),["-DRECOMP_YIELD_EVERY=4096u"])
        for module in builder.MODULES:
            if module!="fmod": self.assertEqual(builder.module_compile_flags(module+"-x86"),[])
        sources=builder.generated_sources()
        self.assertEqual(sum(bool(builder.module_compile_flags(p.parent.name)) for p in sources),21)
        self.assertFalse(builder.module_compile_flags(sources[-1].parent.name)) # Combined dispatch unchanged.

    def test_production_handoff_and_full_context(self):
        fixture=production_fixture(HARNESS)
        ndk=builder.TOOLCHAIN/"bin/clang-cl.exe"
        for threshold,sleep in ((4096,False),(65536,False),(4096,True)):
            flags=("/O2","/DRECOMP_GENERATED_CODE","/DRECOMP_LOCAL_REGS","/DRECOMP_YIELD_EVERY="+str(threshold)+"u")
            if sleep: flags+=("/DTEST_SLEEP_HANDOFF",)
            compile_probe("fmod_yield_"+str(threshold)+("_sleep" if sleep else ""),fixture,{},extra_flags=flags,compiler_override=ndk)


if __name__=="__main__":unittest.main()
