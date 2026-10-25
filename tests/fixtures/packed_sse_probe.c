/* The actual prepared instruction bodies and complete skinning leaf, no timings. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xmmintrin.h>
#else
#include <sys/mman.h>
#endif
#include "recomp_types.h"
#include "native_code.h"

uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf;
uint32_t g_cur_func,g_enter_trace[1024],g_enter_idx;
uint32_t g_backedges,g_mxcsr;
uint64_t g_mm[8];
xmm_t g_xmm[8];
double g_st[8];
int64_t g_st_i64[8];
int g_fp_top,void_fpu_cmp;
uint16_t g_fpu_cw;
void (*recomp_yield_hook)(void);

void before_C687C0(void),after_C687C0(void);
void before_add(void),after_add(void),before_sub(void),after_sub(void),before_mul(void),after_mul(void);
void before_add_self(void),after_add_self(void),before_sub_self(void),after_sub_self(void),before_mul_self(void),after_mul_self(void);

enum { FIXTURE=0x03000000, BYTES=0x20000, LEAF_CASES=384 };
typedef struct {
    uint32_t r[8],flags[4],backedges,mxcsr,cur,enter;
    xmm_t xmm[8];
    uint64_t mm[8],st[8];
    int64_t shadow[8];
    int top,cmp;
    uint16_t cw;
} snapshot;
typedef struct { uint32_t r[8],flags; xmm_t xmm[8]; } native_state;
_Static_assert(offsetof(native_state,xmm)==40,"native XMM snapshot layout");
static native_state input,native_out;
static snapshot entry,wanted,actual;
static unsigned char initial[BYTES],expected[BYTES];
static snapshot yields_before[16],yields_after[16];
static unsigned yield_count,yield_reference,recording_after;
static uint32_t rng=0x51C687C0;
#if defined(_WIN32)
static void (*native_operations[3])(void *,const void *);
#endif

static uint32_t random32(void) {
    uint32_t x=rng;x^=x<<13;x^=x>>17;x^=x<<5;return rng=x;
}
static void *at(uint32_t va) { return (void *)((uintptr_t)VOID_GUEST_BASE+va); }
static void take(snapshot *s) {
    memset(s,0,sizeof *s);
    uint32_t regs[]={g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp};memcpy(s->r,regs,sizeof regs);
    uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};memcpy(s->flags,flags,sizeof flags);
    s->backedges=g_backedges;s->mxcsr=g_mxcsr;s->cur=g_cur_func;s->enter=g_enter_idx;
    memcpy(s->xmm,g_xmm,sizeof g_xmm);memcpy(s->mm,g_mm,sizeof g_mm);
    memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadow,g_st_i64,sizeof g_st_i64);
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;
}
static void restore(const snapshot *s) {
    g_eax=s->r[0];g_ecx=s->r[1];g_edx=s->r[2];g_esp=s->r[3];
    g_ebx=s->r[4];g_esi=s->r[5];g_edi=s->r[6];g_ebp=s->r[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    g_backedges=s->backedges;g_mxcsr=s->mxcsr;g_cur_func=s->cur;g_enter_idx=s->enter;
    memcpy(g_xmm,s->xmm,sizeof g_xmm);memcpy(g_mm,s->mm,sizeof g_mm);
    memcpy(g_st,s->st,sizeof g_st);memcpy(g_st_i64,s->shadow,sizeof g_st_i64);
    g_fp_top=s->top;void_fpu_cmp=s->cmp;g_fpu_cw=s->cw;
}
static void seed(void) {
    memset(&entry,0,sizeof entry);
    for(unsigned i=0;i<8;++i) {
        entry.r[i]=random32();entry.mm[i]=((uint64_t)random32()<<32)|random32();
        entry.st[i]=((uint64_t)random32()<<32)|random32();
        entry.shadow[i]=(int64_t)(((uint64_t)random32()<<32)|random32());
        for(unsigned j=0;j<4;++j)entry.xmm[i].u32[j]=random32();
    }
    entry.flags[0]=FK_EFLAGS;entry.flags[1]=0x202;entry.mxcsr=0x1F80;
    entry.top=3;entry.cmp=0x1234;entry.cw=0x027F;
}
static void failure(const char *where,unsigned n) {
    fprintf(stderr,"%s mismatch case%u\n",where,n);exit(2);
}

/* A yield observes the complete published register file, visits another
   context, restores this one, then changes one lane to require reloading it. */
static void yield_check(void) {
    assert(yield_count<16);
    snapshot saved;take(&saved);
    if(recording_after) {
        yields_after[yield_count]=saved;
        if(yield_count>=yield_reference||memcmp(&saved,&yields_before[yield_count],sizeof saved))
            failure("yield state",yield_count);
    } else yields_before[yield_count]=saved;
    memset(g_xmm,0xCC,sizeof g_xmm);memset(g_mm,0xDD,sizeof g_mm);
    g_eax=0xDEADBEEF;g_flag_k=FK_NONE;g_backedges=0x12345678;
    restore(&saved);g_xmm[0].u32[3]^=0x00010000u;++yield_count;
}

#if defined(_M_IX86)
static uint32_t saved_host_sp;
static void *original;
/* Run the exact original PE leaf on a private guest stack, without patching it. */
__declspec(naked) static void native_snapshot(void) {
    __asm {
        pushfd
        pushad
        mov saved_host_sp,esp
        mov eax,input.r[12]
        add eax,4
        mov esp,eax
        movups xmm0,xmmword ptr input.xmm[0]
        movups xmm1,xmmword ptr input.xmm[16]
        movups xmm2,xmmword ptr input.xmm[32]
        movups xmm3,xmmword ptr input.xmm[48]
        movups xmm4,xmmword ptr input.xmm[64]
        movups xmm5,xmmword ptr input.xmm[80]
        movups xmm6,xmmword ptr input.xmm[96]
        movups xmm7,xmmword ptr input.xmm[112]
        push 202h
        popfd
        mov eax,input.r[0]
        mov ecx,input.r[4]
        mov edx,input.r[8]
        mov ebx,input.r[16]
        mov esi,input.r[20]
        mov edi,input.r[24]
        mov ebp,input.r[28]
        call original
        mov native_out.r[0],eax
        mov native_out.r[4],ecx
        mov native_out.r[8],edx
        mov native_out.r[12],esp
        mov native_out.r[16],ebx
        mov native_out.r[20],esi
        mov native_out.r[24],edi
        mov native_out.r[28],ebp
        mov esp,saved_host_sp
        pushfd
        pop native_out.flags
        movups xmmword ptr native_out.xmm[0],xmm0
        movups xmmword ptr native_out.xmm[16],xmm1
        movups xmmword ptr native_out.xmm[32],xmm2
        movups xmmword ptr native_out.xmm[48],xmm3
        movups xmmword ptr native_out.xmm[64],xmm4
        movups xmmword ptr native_out.xmm[80],xmm5
        movups xmmword ptr native_out.xmm[96],xmm6
        movups xmmword ptr native_out.xmm[112],xmm7
        popad
        popfd
        ret
    }
}
#endif

static uint32_t finite_bits(void) {
    return (random32()&0x807FFFFFu)|((120u+random32()%12u)<<23);
}
static const uint32_t specials[]={0,0x80000000u,0x3F800000u,0xBF800000u,0x7F800000u,0xFF800000u,
    1,0x80000001u,0x007FFFFFu,0x807FFFFFu,0x00800000u,0x80800000u,0x7F7FFFFFu,0xFF7FFFFFu,
    0x7FC12345u,0xFFC54321u,0x7F812345u,0xFF854321u,0x3F000001u,0xBF000001u};

static void primitives(void) {
    void (*before[])(void)={before_add,before_sub,before_mul,before_add_self,before_sub_self,before_mul_self};
    void (*after[])(void)={after_add,after_sub,after_mul,after_add_self,after_sub_self,after_mul_self};
    unsigned long checks=0,native_checks=0,prior_nan_payload_differences=0;
    uint32_t header[]={0x31505353u,107904,4,4};
#if defined(_WIN32)
    FILE *vectors=fopen("native-ieee.bin","wb");
    if(!vectors||fwrite(header,sizeof header,1,vectors)!=1)exit(9);
#else
    FILE *vectors=fopen("native-ieee.bin","rb");uint32_t received[4];
    if(!vectors||fread(received,sizeof received,1,vectors)!=1||memcmp(header,received,sizeof header))exit(9);
#endif
#if defined(__aarch64__)
    uint64_t saved_fpcr;__asm__ volatile("mrs %0, fpcr":"=r"(saved_fpcr));
#endif
    for(unsigned rounding=0;rounding<4;++rounding) {
#if defined(_WIN32)
        _mm_setcsr(0x1F80u|(rounding<<13));
#elif defined(__aarch64__)
        uint64_t mode=rounding==1?2:rounding==2?1:rounding;
        uint64_t fpcr=(saved_fpcr&~(3ull<<22))|(mode<<22);
        __asm__ volatile("msr fpcr, %0"::"r"(fpcr));
#endif
        for(unsigned op=0;op<6;++op)for(unsigned n=0;n<4496;++n) {
            seed();entry.mxcsr=0x1F80u|(rounding<<13);
            for(unsigned lane=0;lane<4;++lane) {
                entry.xmm[0].u32[lane]=n<400?specials[(n/20+lane)%20]:random32();
                entry.xmm[1].u32[lane]=n<400?specials[(n%20+lane)%20]:random32();
            }
            restore(&entry);before[op]();take(&wanted);
            uint32_t reference[4];
#if defined(_WIN32)
            memcpy(reference,entry.xmm[0].u32,sizeof reference);
            native_operations[op%3](reference,entry.xmm[op>=3?0:1].u32);
            for(unsigned lane=0;lane<4;++lane) {
                uint32_t a=entry.xmm[0].u32[lane],b=entry.xmm[op>=3?0:1].u32[lane],bits=reference[lane];
                uint32_t nan=(a&0x7FFFFFFFu)>0x7F800000u?(a|0x00400000u):
                    (b&0x7FFFFFFFu)>0x7F800000u?(b|0x00400000u):0xFFC00000u;
                if((bits&0x7FFFFFFFu)>0x7F800000u&&bits!=nan)failure("original SSE NaN selection",op*4496+n);
            }
            if(fwrite(reference,sizeof reference,1,vectors)!=1)exit(10);
#else
            if(fread(reference,sizeof reference,1,vectors)!=1)exit(10);
#endif
            if(memcmp(reference,wanted.xmm[0].u32,sizeof reference))++prior_nan_payload_differences;
            /* C/SLP may commute NaNs differently at O2 and ThinLTO. The exact
               SSE instruction is authoritative for this defined x86 result. */
            memcpy(wanted.xmm[0].u32,reference,sizeof reference);
#if defined(_WIN32)
            ++native_checks;
#endif
            restore(&entry);after[op]();take(&actual);
            if(memcmp(&wanted,&actual,sizeof wanted)) {
                for(unsigned r=0;r<8;++r)for(unsigned lane=0;lane<4;++lane)
                    if(wanted.xmm[r].u32[lane]!=actual.xmm[r].u32[lane])
                        fprintf(stderr,"xmm%u lane%u expected%08x actual%08x rc%u\n",r,lane,
                            wanted.xmm[r].u32[lane],actual.xmm[r].u32[lane],rounding);
                failure("packed IEEE state",op*4496+n);
            }
            ++checks;
        }
    }
#if !defined(_WIN32)
    if(fgetc(vectors)!=EOF)exit(11);
#endif
    if(fclose(vectors))exit(12);
#if defined(_WIN32)
    _mm_setcsr(0x1F80);
#elif defined(__aarch64__)
    __asm__ volatile("msr fpcr, %0"::"r"(saved_fpcr));
#endif
    printf("{\"primitive_raw_state_checks\":%lu,\"register_variants\":6,\"guest_mxcsr_modes\":4,\"native_primitive_checks\":%lu,\"prior_nan_payload_differences\":%lu}\n",
        checks,native_checks,prior_nan_payload_differences);
}

static void initialize_leaf(unsigned n) {
    for(unsigned i=0;i<BYTES;i+=4)memcpy(initial+i,&(uint32_t){random32()},4);
    seed();entry.r[3]=FIXTURE+0x18000;entry.r[1]=FIXTURE+0x500;
    entry.r[0]=n%16==0?0:n%16==1?UINT32_MAX:1+n%8;
    uint32_t src=FIXTURE+0x6000,dst=FIXTURE+0xA000,weights=FIXTURE+0x8000;
    if(n%12==0)dst=src;
    if(n%12==1)dst=src+4;
    if(n%12==2)dst=src-4;
    if(n%12==3)src+=1;
    if(n%12==4)dst+=1;
    if(n%12==5)dst=weights;
    if(n%12==6){entry.r[0]=1;src=FIXTURE+BYTES-12;}
    if(n%12==7){entry.r[0]=1;dst=FIXTURE+BYTES-12;}
    if(n%12==8){entry.r[0]=1;weights=FIXTURE+BYTES-24;}
    for(unsigned i=0;i<256;++i){uint32_t bits=finite_bits();memcpy(initial+0x1000+4*i,&bits,4);}
    for(unsigned v=0;v<8;++v) {
        if(src+12*v+12<=FIXTURE+BYTES)for(unsigned lane=0;lane<3;++lane) {
            uint32_t bits=finite_bits();memcpy(initial+src-FIXTURE+12*v+4*lane,&bits,4);
        }
        if(weights+24*v+24<=FIXTURE+BYTES) {
            unsigned char *w=initial+weights-FIXTURE+24*v;
            for(unsigned lane=0;lane<4;++lane){uint32_t bits=finite_bits();memcpy(w+4*lane,&bits,4);w[20+lane]=(n+lane+v)%4;}
            w[17]=(n>>0)&1;w[18]=(n>>1)&1;w[19]=(n>>2)&1;
        }
    }
    uint32_t bone=FIXTURE+0x1000;
    memcpy(initial+0x500,&bone,4);
    memcpy(initial+entry.r[3]-FIXTURE+4,&src,4);memcpy(initial+entry.r[3]-FIXTURE+8,&dst,4);
    memcpy(initial+entry.r[3]-FIXTURE+12,&weights,4);
}
static void leaf(void) {
    unsigned native_cases=0,yield_cases=0;
    for(unsigned n=0;n<LEAF_CASES;++n) {
        initialize_leaf(n);
#if defined(_M_IX86)
        memcpy(at(FIXTURE),initial,BYTES);memcpy(input.r,entry.r,sizeof input.r);memcpy(input.xmm,entry.xmm,sizeof input.xmm);
        native_snapshot();memcpy(expected,at(FIXTURE),BYTES);
        /* CALL writes its real return address; the lifted entry merely reads it. */
        memcpy(initial+entry.r[3]-FIXTURE,at(entry.r[3]),4);
#endif
        memcpy(at(FIXTURE),initial,BYTES);restore(&entry);recomp_yield_hook=NULL;
        before_C687C0();take(&wanted);
#if defined(_M_IX86)
        uint32_t flags=recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1);
        if(memcmp(native_out.r,wanted.r,sizeof input.r)||memcmp(native_out.xmm,wanted.xmm,sizeof input.xmm)||
           ((flags^native_out.flags)&0x8C5u)||memcmp(expected,at(FIXTURE),BYTES))failure("original PE leaf",n);
        ++native_cases;
#endif
        memcpy(expected,at(FIXTURE),BYTES);
        memcpy(at(FIXTURE),initial,BYTES);restore(&entry);after_C687C0();take(&actual);
        if(memcmp(&wanted,&actual,sizeof wanted)||memcmp(expected,at(FIXTURE),BYTES))failure("whole skinning state",n);
        if(n%8==0) {
            entry.r[0]=2;entry.backedges=0xFFFF;
            /* The page-ending single-vertex cases cannot execute a second vertex. */
            if(n%12>=6&&n%12<=8)entry.r[0]=1;
            memcpy(at(FIXTURE),initial,BYTES);restore(&entry);recomp_yield_hook=yield_check;yield_count=0;recording_after=0;
            before_C687C0();take(&wanted);yield_reference=yield_count;assert(yield_reference==1);
            memcpy(expected,at(FIXTURE),BYTES);
            memcpy(at(FIXTURE),initial,BYTES);restore(&entry);yield_count=0;recording_after=1;
            after_C687C0();take(&actual);
            if(yield_count!=yield_reference||memcmp(&wanted,&actual,sizeof wanted)||memcmp(expected,at(FIXTURE),BYTES))
                failure("whole skinning yield",n);
            ++yield_cases;
        }
        recomp_yield_hook=NULL;
    }
    printf("{\"whole_leaf_state_checks\":%u,\"original_pe_hardware_cases\":%u,\"yield_state_checks\":%u,\"all_guest_bytes\":%u}\n",
        LEAF_CASES,native_cases,yield_cases,BYTES);
}
int main(void) {
    void *base=(void *)((uintptr_t)at(FIXTURE)-65536);
#if defined(_WIN32)
    if(VirtualAlloc(base,BYTES+65536+4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)!=base)return 3;
    DWORD old;if(!VirtualProtect(at(FIXTURE-4096),4096,PAGE_NOACCESS,&old)||!VirtualProtect(at(FIXTURE+BYTES),4096,PAGE_NOACCESS,&old))return 4;
#else
    if(mmap(base,BYTES+65536+4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)!=base)return 3;
    if(mprotect(at(FIXTURE-4096),4096,PROT_NONE)||mprotect(at(FIXTURE+BYTES),4096,PROT_NONE))return 4;
#endif
#if defined(_M_IX86)
    original=VirtualAlloc(NULL,sizeof original_code,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!original)return 5;memcpy(original,original_code,sizeof original_code);
    if(!VirtualProtect(original,sizeof original_code,PAGE_EXECUTE_READ,&old))return 6;
    FlushInstructionCache(GetCurrentProcess(),original,sizeof original_code);
#endif
#if defined(_WIN32)
    unsigned char *instructions=VirtualAlloc(NULL,96,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!instructions)return 7;
#if defined(_M_IX86)
    unsigned char bytes[]={0x8B,0x44,0x24,0x04,0x8B,0x4C,0x24,0x08,0x0F,0x10,0x00,
        0x0F,0x10,0x09,0x0F,0x58,0xC1,0x0F,0x11,0x00,0xC3};
    const unsigned opcode_at=15;
#else
    unsigned char bytes[]={0x0F,0x10,0x01,0x0F,0x10,0x0A,0x0F,0x58,0xC1,0x0F,0x11,0x01,0xC3};
    const unsigned opcode_at=7;
#endif
    const unsigned char opcodes[]={0x58,0x5C,0x59};
    for(unsigned i=0;i<3;++i){bytes[opcode_at]=opcodes[i];memcpy(instructions+32*i,bytes,sizeof bytes);native_operations[i]=(void *) (instructions+32*i);}
    if(!VirtualProtect(instructions,96,PAGE_EXECUTE_READ,&old))return 8;
    FlushInstructionCache(GetCurrentProcess(),instructions,96);
#endif
    primitives();leaf();puts("PASS packed SSE current/optimized raw state and complete original skinning leaf");return 0;
}
