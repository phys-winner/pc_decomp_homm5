#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "recomp_types.h"
#include "native_code.h"

uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf;
uint32_t g_cur_func,g_enter_trace[1024],g_enter_idx;
uint64_t g_mm[8];
void sub_00C68210(void);

typedef struct {
    uint32_t a,c,d,sp,b,si,di,bp,flags;
    uint64_t mm[8];
} state;
_Static_assert(offsetof(state,mm)==40, "native snapshot layout");
static state input,native_out;
#if defined(_M_IX86)
static uint32_t saved_host_sp;
#endif
static void *original;
#ifndef PC_COMPARE_CASES
#define PC_COMPARE_CASES 16384
#endif
#ifndef PC_COMPARE_BENCH
#define PC_COMPARE_BENCH 1
#endif
enum { FIXTURE=0x03000000, BYTES=0x20000, CASES=PC_COMPARE_CASES };
static unsigned char initial[BYTES], expected[BYTES];

/* No original code is patched: execute its exact 191 bytes at a private RX VA.
 * Its sole absolute table reference is mapped at the original table VA. */
#if defined(_M_IX86)
__declspec(naked) static void native_snapshot(void) {
    __asm {
        pushfd
        pushad
        mov saved_host_sp,esp
        mov eax,input.sp
        add eax,4
        mov esp,eax
        movq mm0,qword ptr input.mm[0]
        movq mm1,qword ptr input.mm[8]
        movq mm2,qword ptr input.mm[16]
        movq mm3,qword ptr input.mm[24]
        movq mm4,qword ptr input.mm[32]
        movq mm5,qword ptr input.mm[40]
        movq mm6,qword ptr input.mm[48]
        movq mm7,qword ptr input.mm[56]
        push 202h
        popfd
        mov eax,input.a
        mov ecx,input.c
        mov edx,input.d
        mov ebx,input.b
        mov esi,input.si
        mov edi,input.di
        mov ebp,input.bp
        call original
        mov native_out.a,eax
        mov native_out.c,ecx
        mov native_out.d,edx
        mov native_out.sp,esp
        mov native_out.b,ebx
        mov native_out.si,esi
        mov native_out.di,edi
        mov native_out.bp,ebp
        mov esp,saved_host_sp
        pushfd
        pop native_out.flags
        movq qword ptr native_out.mm[0],mm0
        movq qword ptr native_out.mm[8],mm1
        movq qword ptr native_out.mm[16],mm2
        movq qword ptr native_out.mm[24],mm3
        movq qword ptr native_out.mm[32],mm4
        movq qword ptr native_out.mm[40],mm5
        movq qword ptr native_out.mm[48],mm6
        movq qword ptr native_out.mm[56],mm7
        emms
        popad
        popfd
        ret
    }
}
#endif

static uint32_t random_state=0x510C6821;
static uint32_t random32(void) {
    uint32_t x=random_state; x^=x<<13; x^=x>>17; x^=x<<5;
    return random_state=x;
}
static const struct { const char *name; unsigned char opcode; int shift; } operations[] = {
    {"paddw",0xFD,0},{"psubw",0xF9,0},{"paddd",0xFE,0},{"psubd",0xFA,0},
    {"paddsw",0xED,0},{"psubsw",0xE9,0},{"pmulhw",0xE5,0},{"pmullw",0xD5,0},
    {"pmaddwd",0xF5,0},{"punpcklwd",0x61,0},{"punpckhwd",0x69,0},{"punpcklbw",0x60,0},
    {"psllw",0xF1,1},{"psrlw",0xD1,1},{"psraw",0xE1,1},{"psrad",0xE2,1},
    {"packuswb",0x67,0},{"pcmpeqw",0x75,0}
};
__declspec(noinline) static uint64_t helper_current(unsigned op,uint64_t a,uint64_t b) {
    switch(op) {
    case 0:return mmx_paddw(a,b);case 1:return mmx_psubw(a,b);
    case 2:return mmx_paddd(a,b);case 3:return mmx_psubd(a,b);
    case 4:return mmx_paddsw(a,b);case 5:return mmx_psubsw(a,b);
    case 6:return mmx_pmulhw(a,b);case 7:return mmx_pmullw(a,b);
    case 8:return mmx_pmaddwd(a,b);case 9:return mmx_punpcklwd(a,b);
    case 10:return mmx_punpckhwd(a,b);case 11:return mmx_punpcklbw(a,b);
    case 12:return mmx_psllw(a,(uint32_t)b);case 13:return mmx_psrlw(a,(uint32_t)b);
    case 14:return mmx_psraw(a,(uint32_t)b);case 15:return mmx_psrad(a,(uint32_t)b);
    case 16:return mmx_packuswb(a,b);case 17:return mmx_pcmpeqw(a,b);
    default:abort();
    }
}
static void helper_oracle(void) {
    static const uint64_t edge[]={0,UINT64_MAX,0x8000800080008000ULL,0x7FFF7FFF7FFF7FFFULL,
        0xFFFF0001FFFF0001ULL,0x8000000080000000ULL,0x7FFFFFFF7FFFFFFFULL,
        0x00FF0100FFFEFFFFULL,0x7FFE800100FE0101ULL,0x0123456789ABCDEFULL};
    static const uint32_t counts[]={0,1,7,8,15,16,17,31,32,33,63,64,0xFFFFFFFFu};
    uint32_t saved_rng=random_state;
    random_state=0x704D4D58;
#if defined(_M_IX86)
    unsigned char *code=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!code)exit(20);
    /* cdecl(a:u64,b:u64)->EDX:EAX, exact hardware instruction, EMMS before C. */
    unsigned char bytes[]={0x0F,0x6F,0x44,0x24,0x04,0x0F,0x6F,0x4C,0x24,0x0C,
        0x0F,0,0xC1,0x0F,0x7E,0xC0,0x0F,0x73,0xD0,32,0x0F,0x7E,0xC2,0x0F,0x77,0xC3};
    for(unsigned op=0;op<18;op++){bytes[11]=operations[op].opcode;memcpy(code+32*op,bytes,sizeof bytes);}
    DWORD old;if(!VirtualProtect(code,4096,PAGE_EXECUTE_READ,&old))exit(21);
    FlushInstructionCache(GetCurrentProcess(),code,4096);
    FILE *vectors=fopen("helper-vectors.bin","wb");
#else
    FILE *vectors=fopen("helper-vectors.bin","rb");
#endif
    if(!vectors)exit(22);
    for(unsigned op=0;op<18;op++)for(unsigned n=0;n<20000;n++) {
        uint64_t a=((uint64_t)random32()<<32)|random32();
        uint64_t b=((uint64_t)random32()<<32)|random32();
        if(n<100){a=edge[n/10];b=edge[n%10];}
        if(operations[op].shift) b=n<130?counts[n%13]:(uint32_t)b;
        uint64_t wanted;
#if defined(_M_IX86)
        typedef uint64_t (__cdecl *instruction)(uint64_t,uint64_t);
        wanted=((instruction)(code+32*op))(a,b);
        if(fwrite(&wanted,8,1,vectors)!=1)exit(23);
#else
        if(fread(&wanted,8,1,vectors)!=1)exit(24);
#endif
        uint64_t actual=helper_current(op,a,b);
        if(wanted!=actual){fprintf(stderr,"helper %s case%u mismatch %016llx/%016llx a%016llx b%016llx\n",operations[op].name,n,(unsigned long long)wanted,(unsigned long long)actual,(unsigned long long)a,(unsigned long long)b);exit(25);}
    }
    fclose(vectors);random_state=saved_rng;
    puts("{\"helper_oracle\":\"PASS\",\"helpers\":18,\"cases_per_helper\":20000,\"native_instruction_results\":360000}");
}
static void *at(uint32_t va) { return (void *)((uintptr_t)VOID_GUEST_BASE+va); }
static uint64_t hash_memory(const unsigned char *p) {
    uint64_t h=1469598103934665603ULL;
    for(unsigned i=0;i<BYTES;i++) h=(h^p[i])*1099511628211ULL;
    return h;
}
static void seed_c(void) {
    g_eax=input.a;g_ecx=input.c;g_edx=input.d;g_esp=input.sp;
    g_ebx=input.b;g_esi=input.si;g_edi=input.di;g_ebp=input.bp;
    g_flag_k=FK_NONE;g_flag_a=g_flag_b=g_flag_cf=0;
    memcpy(g_mm,input.mm,sizeof g_mm);
}
static void oracle(void) {
    state actual;
#if defined(_M_IX86)
    FILE *vectors=fopen("native-vectors.bin","wb");
#else
    FILE *vectors=fopen("native-vectors.bin","rb");
#endif
    if(!vectors) exit(10);
    for(unsigned n=0;n<CASES;n++) {
        for(unsigned i=0;i<BYTES;i+=4) *(uint32_t *)(initial+i)=random32();
        memset(&input,0,sizeof input);
        input.a=random32();input.b=random32();input.si=random32();
        input.di=random32();input.bp=random32();
        input.c=FIXTURE+0x100;input.d=FIXTURE+0x200;
        input.sp=FIXTURE+0x10000+16*(n&127);
        for(unsigned i=0;i<8;i++) input.mm[i]=((uint64_t)random32()<<32)|random32();
        uint32_t bias=FIXTURE+0x300,rows=FIXTURE+0x400;
        if((n&7)==1) input.d=input.c;
        if((n&7)==2) bias=input.c;
        if((n&7)==3) rows=input.d;
        if((n&7)==4) bias=rows;
        if((n&7)==5) input.c=rows+8;
        if((n&7)==6) input.c=bias+4;
        memcpy(at(FIXTURE),initial,BYTES);
        *(uint32_t *)at(input.sp+4)=bias;
        *(uint32_t *)at(input.sp+8)=rows;
#if defined(_M_IX86)
        native_snapshot();
        memcpy(expected,at(FIXTURE),BYTES);
        uint32_t return_address=*(uint32_t *)at(input.sp);
        native_out.flags&=0x8D5;
        uint32_t changed=0;
        for(unsigned i=0;i<BYTES;i++) changed+=expected[i]!=initial[i];
        if(changed>64) exit(13);
        if(fwrite(&native_out,sizeof native_out,1,vectors)!=1||fwrite(&return_address,4,1,vectors)!=1||fwrite(&changed,4,1,vectors)!=1) exit(11);
        for(uint32_t i=0;i<BYTES;i++) if(expected[i]!=initial[i]) {
            if(fwrite(&i,4,1,vectors)!=1||fwrite(expected+i,1,1,vectors)!=1) exit(11);
        }
#else
        uint32_t return_address;
        uint32_t changed;
        if(fread(&native_out,sizeof native_out,1,vectors)!=1||fread(&return_address,4,1,vectors)!=1||fread(&changed,4,1,vectors)!=1||changed>64) exit(12);
        memcpy(expected,initial,BYTES);
        for(uint32_t i=0;i<changed;i++) {
            uint32_t offset;unsigned char value;
            if(fread(&offset,4,1,vectors)!=1||fread(&value,1,1,vectors)!=1||offset>=BYTES) exit(14);
            expected[offset]=value;
        }
#endif
        memcpy(at(FIXTURE),initial,BYTES);
        *(uint32_t *)at(input.sp)=return_address;
        *(uint32_t *)at(input.sp+4)=bias;
        *(uint32_t *)at(input.sp+8)=rows;
        seed_c();sub_00C68210();
        memset(&actual,0,sizeof actual);
        actual.a=g_eax;actual.c=g_ecx;actual.d=g_edx;actual.sp=g_esp;
        actual.b=g_ebx;actual.si=g_esi;actual.di=g_edi;actual.bp=g_ebp;
        actual.flags=recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1);
        memcpy(actual.mm,g_mm,sizeof g_mm);
        native_out.flags&=0x8D5;actual.flags&=0x8D5;
        /* Padding has no machine meaning. Compare fields and all 8 raw MMX regs. */
        if(memcmp(&actual,&native_out,36)||memcmp(actual.mm,native_out.mm,64)||memcmp(at(FIXTURE),expected,BYTES)) {
            fprintf(stderr,"oracle mismatch case %u flags %x/%x\n",n,native_out.flags,actual.flags);
            for(unsigned i=0;i<36;i++) if(((unsigned char *)&actual)[i]!=((unsigned char *)&native_out)[i])
                fprintf(stderr,"state byte %u expected %02x actual %02x\n",i,((unsigned char *)&native_out)[i],((unsigned char *)&actual)[i]);
            exit(2);
        }
    }
    fclose(vectors);
    printf("{\"oracle\":\"PASS\",\"cases\":%u,\"full_guest_memory_bytes\":%u,\"gprs\":8,\"mmx_raw\":8,\"arithmetic_eflags_mask\":2261,\"alias_cases\":7,\"host_bits\":%u}\n",CASES,BYTES,(unsigned)(8*sizeof(void *)));
}

typedef void (__fastcall *native_function)(uint32_t *,const uint32_t *,const void *,const void *);
static volatile uint32_t sink;
static double measure(int native, unsigned iterations) {
    LARGE_INTEGER before,after,freq;
    uint32_t *src=at(FIXTURE+0x2000),*out=at(FIXTURE+0x3000);
    uint32_t bias=FIXTURE+0x300,rows=FIXTURE+0x400;
    *(uint32_t *)at(input.sp+4)=bias;*(uint32_t *)at(input.sp+8)=rows;
    QueryPerformanceFrequency(&freq);QueryPerformanceCounter(&before);
#if defined(_M_IX86)
    if(native) {
        native_function fn=(native_function)original;
        for(unsigned i=0;i<iterations;i++) fn(out+(i&1023),src+(i&1023),at(bias),at(rows));
        __asm emms
    } else
#endif
    {
        for(unsigned i=0;i<iterations;i++) {
            g_ecx=(uint32_t)(uintptr_t)(out+(i&1023));g_edx=(uint32_t)(uintptr_t)(src+(i&1023));
            g_esp=input.sp;sub_00C68210();
        }
    }
    QueryPerformanceCounter(&after);
    sink^=out[123];
    return (double)(after.QuadPart-before.QuadPart)*1e9/(double)freq.QuadPart/iterations;
}
int main(void) {
    SYSTEM_INFO info;GetSystemInfo(&info);
    DWORD_PTR affinity=(DWORD_PTR)1<<(info.dwNumberOfProcessors>7?7:0);
    SetThreadAffinityMask(GetCurrentThread(),affinity);
    if(VirtualAlloc(at(FIXTURE),BYTES,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)!=at(FIXTURE)) return 3;
    if(VirtualAlloc(at(0x010C0000),0x20000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)!=at(0x010C0000)) return 4;
    uint16_t *table=at(0x10CE990);
    table[0]=32767;
    for(unsigned i=1;i<16384;i++) {
        float value=(float)(130048.0/sqrt((double)i+0.9900000095367432));
        int32_t rounded=(int32_t)nearbyint((double)value);
        table[i]=(uint16_t)(rounded>32767?32767:rounded);
    }
#if defined(_M_IX86)
    original=VirtualAlloc(NULL,sizeof original_code,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!original) return 5;
    memcpy(original,original_code,sizeof original_code);
    DWORD old;if(!VirtualProtect(original,sizeof original_code,PAGE_EXECUTE_READ,&old)) return 6;
    FlushInstructionCache(GetCurrentProcess(),original,sizeof original_code);
#endif
    helper_oracle();
    oracle();
    for(unsigned i=0;i<BYTES;i+=4) *(uint32_t *)at(FIXTURE+i)=random32();
    input.sp=FIXTURE+0x10000;
    /* Warm both instruction and normalization-table data paths. */
    if(PC_COMPARE_BENCH) {measure(1,100000);measure(0,100000);}
    for(unsigned round=0;PC_COMPARE_BENCH && round<9;round++) {
        double a,b;
#if defined(_M_IX86)
        if(round&1) { b=measure(0,1000000);a=measure(1,1000000); }
        else { a=measure(1,1000000);b=measure(0,1000000); }
        printf("{\"round\":%u,\"calls\":1000000,\"native_x86_ns\":%.6f,\"generated_c_x86_ns\":%.6f,\"ratio_c_over_native\":%.6f}\n",round,a,b,b/a);
#else
        b=measure(0,1000000);
        printf("{\"round\":%u,\"calls\":1000000,\"generated_c_x64_ns\":%.6f}\n",round,b);
#endif
    }
    printf("{\"host\":\"Windows\",\"host_bits\":%u,\"logical_processors\":%u,\"affinity_mask\":%llu,\"sink\":%u}\n",(unsigned)(8*sizeof(void *)),info.dwNumberOfProcessors,(unsigned long long)affinity,sink);
    return 0;
}
