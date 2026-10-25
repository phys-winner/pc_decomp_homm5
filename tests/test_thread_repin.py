"""Run the production affinity selection and guest machine entry/reentry bodies."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CPU_SETSIZE 8
typedef uint64_t cpu_set_t;
#define CPU_ZERO(p) (*(p)=0)
#define CPU_SET(i,p) (*(p)|=UINT64_C(1)<<(i))
#define CPU_ISSET(i,p) (!!(*(p)&(UINT64_C(1)<<(i))))
static cpu_set_t big_cores, applied_mask;
static int big_cores_count, big_cores_once;
static long capacities[8], frequencies[8];
static const char *environment;
static unsigned set_calls, saved, loaded;
static int lock_depth, affinity_error, mlock, mcond;
static uint64_t ticket_next,ticket_serving,t_lock_wait_ns;
typedef struct {int regs,depth;} void_thread;
static void_thread guest;
static void_thread *t_self=&guest;
static void_thread *void_thread_self(void) {return t_self;}
static void void_regs_save(int *p) {(void)p;++saved;}
static void void_regs_load(int *p) {(void)p;++loaded;}
static void void_fatal(const char *p) {(void)p;abort();}
static uint64_t now_ns(void) {return 0;}
static void pthread_mutex_lock(int *p) {(void)p;assert(!lock_depth++);}
static void pthread_mutex_unlock(int *p) {(void)p;assert(!--lock_depth);}
static void pthread_cond_wait(int *c,int *m) {(void)c;(void)m;abort();}
static void pthread_cond_broadcast(int *c) {(void)c;}
static void pthread_once(int *once,void (*fn)(void)) {if(!*once){*once=1;fn();}}
static char *mock_getenv(const char *key) {assert(!strcmp(key,"VOID_BIG_CORES"));return (char *)environment;}
#define getenv mock_getenv
static long cpu_value(int cpu,const char *name) {
    assert(cpu>=0 && cpu<8);
    return !strcmp(name,"cpu_capacity") ? capacities[cpu] : frequencies[cpu];
}
static void void_log(const char *format,...) {(void)format;}
static int sched_setaffinity(int pid,size_t bytes,const cpu_set_t *mask) {
    assert(pid==0 && bytes==sizeof(cpu_set_t) && !lock_depth);
    ++set_calls;
    if(affinity_error)return -1;
    applied_mask=*mask;return 0;
}
static void pin_guest_thread(void);
/* PRODUCTION */
static void reset(void) {
    memset(capacities,0,sizeof capacities);memset(frequencies,0,sizeof frequencies);
    big_cores=applied_mask=0;big_cores_count=big_cores_once=0;
    environment=NULL;set_calls=saved=loaded=0;affinity_error=lock_depth=0;
    ticket_next=ticket_serving=t_lock_wait_ns=0;guest.depth=0;
}
static void pair(void) {void_machine_enter();void_machine_leave();}
int main(void) {
    reset();
    long tablet[]={221,221,221,221,996,996,996,1024};
    memcpy(capacities,tablet,sizeof tablet);
    pair();assert(set_calls==1 && applied_mask==0x80 && saved==1 && loaded==1);
    applied_mask=0xFF; /* Reproduce Android's external lifecycle reset. */
    void_machine_enter();assert(set_calls==2 && applied_mask==0x80);
    void_machine_enter();assert(set_calls==2); /* Nested guest entry is not acquisition. */
    void_machine_leave();assert(set_calls==2 && guest.depth==1);
    void_blocking_begin();applied_mask=0xFF;
    void_blocking_end();assert(set_calls==3 && applied_mask==0x80 && guest.depth==1);
    void_machine_leave();assert(!guest.depth && !lock_depth);
    applied_mask=0xFF;assert(set_calls==3); /* Host work alone does not repin. */
    affinity_error=1;pair();assert(set_calls==4 && applied_mask==0xFF); /* Nonfatal OS denial. */
    affinity_error=0;pair();assert(set_calls==5 && applied_mask==0x80); /* Retry next acquisition. */
    reset();memcpy(capacities,tablet,sizeof tablet);environment="0";pair();pair();assert(!set_calls);
    reset();for(int i=0;i<8;++i)capacities[i]=1024;pair();assert(!set_calls);
    reset();pair();assert(!set_calls); /* Unknown topology. */
    reset();capacities[0]=1024;pair();assert(!set_calls); /* One known CPU. */
    reset();long freq[]={1000,1000,1000,1000,3200000,3200000,3200000,3350000};
    memcpy(frequencies,freq,sizeof freq);pair();assert(set_calls==1 && applied_mask==0x80);
    reset();long tied[]={221,221,1024,1024,0,0,0,0};
    memcpy(capacities,tied,sizeof tied);pair();assert(set_calls==1 && applied_mask==0x0C);
    puts("PASS real guest acquire/reacquire pins only current thread after unlocking; exact-best capacity/frequency; nested/host/disabled/homogeneous/unknown paths; nonfatal failure retries");
    return 0;
}
'''


class ThreadRepinTest(unittest.TestCase):
    def test_acquisition_reasserts_existing_guest_affinity(self):
        source=(ROOT/"android/host/threads.c").read_text(encoding="utf8")
        signatures=["static void big_cores_init(","static void pin_guest_thread(void)\n{",
                    "static void machine_acquire(","static void machine_release(",
                    "void void_machine_enter(","void void_machine_leave(",
                    "void void_blocking_begin(","void void_blocking_end("]
        # Include the opening brace to distinguish pinning's forward declaration.
        functions="\n".join(body(source,s) for s in signatures)
        compile_probe("thread_repin",HARNESS.replace("/* PRODUCTION */",functions),{})


if __name__=="__main__":unittest.main()
