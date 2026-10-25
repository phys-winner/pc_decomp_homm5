#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/mman.h>
#endif
#include "recomp_types.h"

void sub_F1000000(void), sub_F1000010(void), sub_F1000020(void), sub_F1000030(void);
void sub_F1000040(void), sub_F1000050(void), sub_F1000060(void), sub_F1000070(void);
void native_step(void), throw_step(void), check(unsigned ok, const char *what);
extern unsigned phase;
void sub_F1000090(void),sub_F10000A0(void),counter_macro_reset(void);

/* GENERATED_BEGIN */
void sub_F1000090(void);
void sub_F1000000(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    _mm[0] = 0x123456789ABCDEF0ull;
    RECOMP_CALL(native_step);
    check(_mm[0]==0x1111222233334444ull && _mm[1]==0x5555666677778888ull,"MMX callback reload");
    _mm[7] ^= 0xFEDCBA9876543210ull;
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void mmx_macro_reset(void) { _mm[6] = 0xA6A6A6A6A6A6A6A6ull; RECOMP_BACKEDGE_COUNTER=1234; }
void sub_F1000010(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    _xmm[0].u64[0] = 0x123456789ABCDEF0ull;
    RECOMP_CALL(native_step);
    check(_xmm[0].u64[0]==0x1111222233334444ull && _xmm[1].u64[1]==0x5555666677778888ull,"SSE callback reload");
    _xmm[7].u64[1] ^= 0xFEDCBA9876543210ull;
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void sse_macro_reset(void) { _xmm[6].u64[0] = 0xA6A6A6A6A6A6A6A6ull; }
void sub_F1000020(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    _mm[0] = _xmm[0].u64[0] = 0x123456789ABCDEF0ull;
    RECOMP_CALL(native_step);
    check(_mm[0]==0x1111222233334444ull && _mm[1]==0x5555666677778888ull,"mixed MMX reload");
    check(_xmm[0].u64[0]==0x1111222233334444ull && _xmm[1].u64[1]==0x5555666677778888ull,"mixed SSE reload");
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void mixed_macro_reset(void) { _mm[6] = _xmm[6].u64[0] = 0xA6A6A6A6A6A6A6A6ull; }
void sub_F1000030(void) {
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    _mm[1] = _xmm[1].u64[1] = 0x5555666677778888ull;
    RECOMP_REGS_OUT();
}
void sub_F1000040(void) {
    RECOMP_REGS_LOCALS
    _mm[0] = _xmm[0].u64[0] = 0x123456789ABCDEF0ull;
    RECOMP_BACKEDGE();
    check(_mm[0]==0x1111222233334444ull && _xmm[0].u64[0]==0x1111222233334444ull,"yield reload");
    check(_mm[1]==0x5555666677778888ull && _xmm[1].u64[1]==0x5555666677778888ull,"nested yield reload");
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void sub_F1000050(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0,_itail_tgt=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    RECOMP_EH_ENTER();
    _mm[0] = _xmm[0].u64[0] = 0x123456789ABCDEF0ull;
    RECOMP_CALL(throw_step);
    check(0,"throw returned");
_ljump:
    check(_itail_tgt==0xF1u,"EH continuation");
    check(_mm[0]==0x1111222233334444ull && _xmm[0].u64[0]==0x1111222233334444ull,"EH reload");
    check(_mm[1]==0x5555666677778888ull && _xmm[1].u64[1]==0x5555666677778888ull,"nested EH reload");
    RECOMP_EH_LEAVE();
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void sub_F1000060(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    _mm[0] = _xmm[0].u64[0] = 0x123456789ABCDEF0ull;
    RECOMP_ITAIL(0xF1000080u);
    check(_mm[0]==0x1111222233334444ull && _xmm[0].u64[0]==0x1111222233334444ull,"tail reload");
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}
void sub_F1000070(void) {
    RECOMP_REGS_LOCALS
    _mm[0] = 0x123456789ABCDEF0ull;
    RECOMP_BACKEDGE();
    check(_mm[0]==0x1111222233334444ull && _mm[1]==0x5555666677778888ull,"MMX-only yield reload");
    check(RECOMP_BACKEDGE_COUNTER==1,"counter callback reload");
    RECOMP_BACKEDGE();
    RECOMP_REGS_OUT();
}

void sub_F1000090(void) {
    RECOMP_REGS_LOCALS
    uint32_t count=ecx;
    for(uint32_t i=0;i<count;++i) { RECOMP_BACKEDGE(); }
    RECOMP_REGS_OUT();
}
void sub_F10000A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_BACKEDGE();
    if(ecx) { --ecx; RECOMP_CALL(sub_F10000A0); }
    RECOMP_BACKEDGE();
    esp+=4;
    RECOMP_REGS_OUT();
}
void counter_macro_reset(void) { RECOMP_BACKEDGE_COUNTER=1234; }
/* GENERATED_END */

/* ACTUAL_REGISTER_DEFS */
recomp_ehframe_t *g_eh_frames;
uint32_t g_eh_obj,g_eh_info;
/* CURRENT_STATE */
/* CURRENT_SAVE */
/* CURRENT_LOAD */
unsigned phase;
static recomp_ehframe_t *landing;
static unsigned yield_count;
static void save(void_regs *s) { memset(s,0,sizeof *s);void_regs_save(s); }
void check(unsigned ok,const char *what) { if(!ok) { fprintf(stderr,"FAIL %s phase%u\n",what,phase);exit(25); } }
void recomp_eh_push(recomp_ehframe_t *f) { f->prev=landing;landing=f; }
void recomp_eh_pop(recomp_ehframe_t *f) { check(f==landing,"EH pop");landing=f->prev; }
static void mutate(void) {
    check(g_backedges==((phase==4||phase==7)?0:3),"counter callback flush");
    void_regs saved,restored;save(&saved);
    memset(g_st,0xF1,sizeof g_st);memset(g_st_i64,0x91,sizeof g_st_i64);
    g_backedges=0xFFFFFFFEu;g_eax=0xA512;g_fp_top=-77;g_fpu_cw=0x1234;
    g_mxcsr=0x1234;g_fs_base=0xDEAD;g_eh_obj=0xCAFE;g_eh_info=0xFFFF;
    memset(g_mm,0x15,sizeof g_mm);memset(g_xmm,0x72,sizeof g_xmm);
    void_regs_load(&saved);save(&restored);check(!memcmp(&saved,&restored,sizeof saved),"actual full VM callback restore");
    if(phase!=2) check(g_mm[0]==0x123456789ABCDEF0ull,"callback MMX flush");
    if(phase!=1 && phase!=7) check(g_xmm[0].u64[0]==0x123456789ABCDEF0ull,"callback SSE flush");
    sub_F1000030();
    check(g_backedges==((phase==4||phase==7)?1:4),"nested counter publication");
    g_backedges=1;
    g_mm[0]=g_xmm[0].u64[0]=0x1111222233334444ull;
    g_eax=0x1234ABCDu;g_flag_k=FK_CMP;g_flag_a=19;g_flag_b=23;g_flag_cf=1;
}
void native_step(void) { mutate();g_esp+=4; }
static void yield_step(void) {
    if(phase==9) { check(g_backedges==0,"counter reset before yield");++yield_count;g_backedges=(yield_count&1)?0:1; }
    else mutate();
}
void throw_step(void) {
    mutate();g_esp+=4;landing->resume=0xF1u;
#ifdef _WIN32
    longjmp(landing->jb,1);
#else
    _longjmp(landing->jb,1);
#endif
}
recomp_func_t void_resolve(uint32_t va) { check(va==0xF1000080u,"tail target");return yield_step; }
void mmx_macro_reset(void),sse_macro_reset(void),mixed_macro_reset(void);
int main(void) {
    uintptr_t address=(uintptr_t)VOID_GUEST_BASE+0x03000000u;
#ifdef _WIN32
    void *memory=VirtualAlloc((void *)address,0x10000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
#else
    void *memory=mmap((void *)address,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
#endif
    check(memory==(void *)address,"guest mapping");
    void (*tests[])(void)={sub_F1000000,sub_F1000010,sub_F1000020,sub_F1000040,sub_F1000050,sub_F1000060,sub_F1000070};
    unsigned transfer_cases=0;
    if(RECOMP_YIELD_EVERY>=7) for(unsigned repeat=0;repeat<32;repeat++) for(unsigned i=0;i<7;i++) {
        phase=i+1;g_esp=0x03008000u;g_eax=0;
        g_ecx=0x99887766u;g_edx=0xAABBCCDDu;g_ebx=0x18273645u;
        g_esi=0x91827364u;g_edi=0x74839201u;g_ebp=0xFFEEDDCCu;
        uint64_t expected_mm[8];xmm_t expected_xmm[8];unsigned char expected_memory[0x10000];
        memset(memory,0x5A,0x10000);memset(expected_memory,0x5A,sizeof expected_memory);
        for(unsigned k=0;k<8;k++) { g_mm[k]=0x8787878787878787ull+k;memset(g_xmm+k,0xA7+k,sizeof(xmm_t)); }
        memcpy(expected_mm,g_mm,sizeof expected_mm);memcpy(expected_xmm,g_xmm,sizeof expected_xmm);
        expected_mm[0]=expected_xmm[0].u64[0]=0x1111222233334444ull;
        expected_mm[1]=expected_xmm[1].u64[1]=0x5555666677778888ull;
        if(phase==1)expected_mm[7]^=0xFEDCBA9876543210ull;
        if(phase==2)expected_xmm[7].u64[1]^=0xFEDCBA9876543210ull;
        if(phase==1 || phase==2 || phase==3 || phase==5) {
            uint32_t ret=RECOMP_RETADDR;memcpy(expected_memory+0x7FFC,&ret,4);
        }
        for(unsigned j=0;j<8;++j) {uint64_t raw=0x7FF0123456000000ull+repeat*32+j;memcpy(g_st+j,&raw,8);g_st_i64[j]=(int64_t)(raw^0x5555);}
        g_fs_base=0x71112233;g_eh_obj=0x12345678;g_eh_info=0x44332211;g_fpu_cw=(uint16_t)(0x37F|(repeat%4)<<10);
        g_mxcsr=0x1F80|(repeat&1)*0x40;g_fp_top=(int)repeat-16;void_fpu_cmp=(int)(repeat^0x4700);
        g_backedges=(phase==4||phase==7)?RECOMP_YIELD_EVERY-1:2;
        void_regs expected,actual;save(&expected);
        expected.eax=0x1234ABCDu;expected.flag_k=FK_CMP;expected.flag_a=19;expected.flag_b=23;expected.flag_cf=1;expected.backedges=2;
        memcpy(expected.mm,expected_mm,sizeof expected.mm);memcpy(expected.xmm,expected_xmm,sizeof expected.xmm);
        recomp_yield_hook=yield_step;tests[i]();save(&actual);
        check(!memcmp(&expected,&actual,sizeof expected),"all actual VM fields after transfer");
        check(g_eax==0x1234ABCDu && g_esp==0x03008000u && g_ecx==0x99887766u && g_edx==0xAABBCCDDu
              && g_ebx==0x18273645u && g_esi==0x91827364u && g_edi==0x74839201u && g_ebp==0xFFEEDDCCu,"eight GPR reload");
        check(g_flag_k==FK_CMP && g_flag_a==19 && g_flag_b==23 && g_flag_cf==1,"flags survive");
        check(!memcmp(g_mm,expected_mm,sizeof expected_mm),"all eight raw MMX");
        check(!memcmp(g_xmm,expected_xmm,sizeof expected_xmm),"all 128 raw SSE bytes");
        check(!memcmp(memory,expected_memory,sizeof expected_memory),"all guest memory");
        check(g_mm[0]==0x1111222233334444ull && g_mm[1]==0x5555666677778888ull,"final raw MMX");
        check(g_xmm[0].u64[0]==0x1111222233334444ull && g_xmm[1].u64[1]==0x5555666677778888ull,"final raw SSE");
        check(g_mm[5]==0x878787878787878Cull,"untouched MMX");
        check(g_xmm[5].u64[0]==0xACACACACACACACACull,"untouched SSE");
        mmx_macro_reset();sse_macro_reset();mixed_macro_reset();
        check(g_mm[6]==0xA6A6A6A6A6A6A6A6ull && g_xmm[6].u64[0]==0xA6A6A6A6A6A6A6A6ull,"macro reset");
        ++transfer_cases;
    }
    phase=9;unsigned counter_cases=0;uint32_t rng=0x12345678;
    for(unsigned mode=0;mode<2;++mode)for(unsigned trial=0;trial<1024;++trial) {
        rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;
        uint32_t starts[]={0,RECOMP_YIELD_EVERY-1,RECOMP_YIELD_EVERY,RECOMP_YIELD_EVERY+1,0xFFFFFFFEu,0xFFFFFFFFu,rng};
        uint32_t start=starts[trial%7],count=(rng>>16)%1024,expect=start,expected_yields=0;
        for(unsigned j=0;j<count;++j)if(++expect>=RECOMP_YIELD_EVERY&&mode){expect=0;++expected_yields;expect=(expected_yields&1)?0:1;}
        g_backedges=start;g_ecx=count;yield_count=0;recomp_yield_hook=mode?yield_step:NULL;sub_F1000090();
        check(g_backedges==expect&&yield_count==expected_yields,"exact random threshold wrap and hook timeline");++counter_cases;
    }
    for(unsigned mode=0;mode<2;++mode)for(unsigned depth=0;depth<32;++depth) {
        uint32_t expect=0xFFFFFFFEu,expected_yields=0;
        for(unsigned j=0;j<2*(depth+1);++j)if(++expect>=RECOMP_YIELD_EVERY&&mode){expect=0;++expected_yields;expect=(expected_yields&1)?0:1;}
        g_backedges=0xFFFFFFFEu;g_ecx=depth;g_esp=0x03008000;yield_count=0;recomp_yield_hook=mode?yield_step:NULL;sub_F10000A0();
        check(g_backedges==expect&&yield_count==expected_yields&&g_esp==0x03008004,"recursive counter and stack reload");
    }
    counter_macro_reset();check(g_backedges==1234,"counter macro reset");
    printf("PASS local backedges: %u callback/yield/tail/EH executions with full actual VM state, mixed SSE; %u random counter/threshold/wrap cases; 64 recursive cases\n",transfer_cases,counter_cases);return 0;
}
