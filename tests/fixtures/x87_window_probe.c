/* Full-state oracle for actual window helpers and actual VM save/load. */

#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "recomp_types.h"
/* ACTUAL_REGISTER_DEFS */
recomp_ehframe_t *g_eh_frames;
uint32_t g_eh_obj,g_eh_info;
#define X87_SLOTS RECOMP_X87_SLOTS
#define window_sp g_fp_sp
_Static_assert(sizeof g_st == 64, "keep old array sizeof");
_Static_assert(sizeof g_st_i64 == 64, "keep old shadow sizeof");
/* CURRENT_STATE */
/* CURRENT_SAVE */
/* CURRENT_LOAD */
static double baseline_st[8];static int64_t baseline_i64[8];static int baseline_top;
/* BASE_PUSH */
/* BASE_POP */
static unsigned recentres,operations,snapshots;
static void window_push(double value) {
    if(g_fp_sp<=8)++recentres;
    fp_window_push(value);
}
static double window_pop(void) {
    if(g_fp_sp+1>RECOMP_X87_SLOTS-9)++recentres;
    return fp_window_pop();
}
static uint64_t rng=UINT64_C(0xAD778E2426E91371);
static uint64_t random64(void) {rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;return rng;}
static void check(void) {
    assert(window_sp>=0 && window_sp+7<X87_SLOTS);
    assert(!memcmp(baseline_st,g_st,sizeof g_st));
    assert(!memcmp(baseline_i64,g_st_i64,sizeof g_st_i64));
    assert(baseline_top==g_fp_top);++operations;
}
static void seed(unsigned which) {
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=random64();memcpy(g_st+i,&bits,8);memcpy(baseline_st+i,&bits,8);
        g_st_i64[i]=baseline_i64[i]=(int64_t)random64();
        g_mm[i]=random64();g_xmm[i].u64[0]=random64();g_xmm[i].u64[1]=random64();
    }
    baseline_top=g_fp_top=(int)(which%33)-16;
    g_eax=(uint32_t)random64();g_ecx=(uint32_t)random64();g_edx=(uint32_t)random64();
    g_ebx=(uint32_t)random64();g_esp=(uint32_t)random64();g_ebp=(uint32_t)random64();
    g_esi=(uint32_t)random64();g_edi=(uint32_t)random64();g_fs_base=(uint32_t)random64();g_cur_func=(uint32_t)random64();
    g_flag_k=(uint32_t)random64();g_flag_a=(uint32_t)random64();g_flag_b=(uint32_t)random64();g_flag_cf=(uint32_t)random64();
    g_mxcsr=(uint32_t)random64();g_eh_obj=(uint32_t)random64();g_eh_info=(uint32_t)random64();g_backedges=(uint32_t)random64();
    g_fpu_cw=(uint16_t)random64();void_fpu_cmp=(int)random64();
    g_eh_frames=(recomp_ehframe_t *)(uintptr_t)((uint32_t)random64()&~3u);
}
static void save(void_regs *r) {memset(r,0,sizeof *r);void_regs_save(r);++snapshots;}
static void assert_vm(const void_regs *want) {void_regs got;save(&got);assert(!memcmp(want,&got,sizeof got));}
static void nested_callback(unsigned depth) {
    void_regs parent;save(&parent);
    for(unsigned i=0;i<600;++i)window_push((double)i);
    seed(depth+500);
    if(depth)nested_callback(depth-1);
    for(unsigned i=0;i<650;++i)(void)window_pop();
    void_regs_load(&parent);assert_vm(&parent);
}
static jmp_buf landing;
static void nonlocal_callee(void) {
    for(unsigned i=0;i<700;++i)window_push((double)i);
    seed(871);longjmp(landing,1);
}
int main(void) {
    seed(0);check();
    for(unsigned i=0;i<1200;++i) {double value=(double)(int64_t)random64();baseline_push(baseline_st,&baseline_top,value);window_push(value);check();}
    for(unsigned i=0;i<2400;++i) {double expected=baseline_pop(baseline_st,&baseline_top),got=window_pop();assert(!memcmp(&expected,&got,8));check();}
    for(unsigned trial=0;trial<200;++trial) {
        seed(trial);check();
        for(unsigned step=0;step<2000;++step) {
            unsigned op=(unsigned)random64()%5;
            if(op==0) {double v=(double)(int64_t)random64();baseline_push(baseline_st,&baseline_top,v);window_push(v);}
            else if(op==1) {double a=baseline_pop(baseline_st,&baseline_top),b=window_pop();assert(!memcmp(&a,&b,8));}
            else if(op==2) {unsigned i=(unsigned)random64()%8;uint64_t bits=random64();memcpy(baseline_st+i,&bits,8);memcpy(g_st+i,&bits,8);baseline_i64[i]=g_st_i64[i]=(int64_t)random64();}
            else if(op==3) {unsigned i=(unsigned)random64()%8;double d=baseline_st[0];baseline_st[0]=baseline_st[i];baseline_st[i]=d;d=g_st[0];g_st[0]=g_st[i];g_st[i]=d;int64_t q=baseline_i64[0];baseline_i64[0]=baseline_i64[i];baseline_i64[i]=q;q=g_st_i64[0];g_st_i64[0]=g_st_i64[i];g_st_i64[i]=q;}
            else {void_regs before;save(&before);unsigned n=(unsigned)random64()%600;for(unsigned i=0;i<n;++i)window_push((double)i);void_regs_load(&before);assert_vm(&before);}
            check();
        }
    }
    seed(5);void_regs original;save(&original);nested_callback(4);void_regs_load(&original);assert_vm(&original);
    if(!setjmp(landing))nonlocal_callee();
    void_regs_load(&original);assert_vm(&original);
    void_regs threads[2];save(&threads[0]);seed(8);save(&threads[1]);
    for(unsigned i=0;i<1000;++i) {
        void_regs_load(&threads[i&1]);assert_vm(&threads[i&1]);
        for(unsigned j=0;j<(i%31);++j)window_push((double)j);
        save(&threads[i&1]);
    }
    assert(recentres>1000 && snapshots>1000);
    printf("PASS production x87 window: %u full8 operations, %u actual void_regs snapshots, %u recentres; random raw bits/shadows, full VM state, nested callback model, alternating thread model, nonlocal restore model; sizeof64\n",operations,snapshots,recentres);
    return 0;
}
