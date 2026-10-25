#define WIN32_LEAN_AND_MEAN
#if defined(_WIN32)
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "recomp_types.h"
#include "native_code.h"

uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf;
uint32_t g_cur_func,g_enter_trace[1024],g_enter_idx,g_backedges;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx;
uint64_t g_mm[8];
void (*recomp_yield_hook)(void);
void before_index(void),after_index(void);

typedef struct {
    uint32_t a,c,d,sp,b,si,di,bp,flags;
    uint64_t mm[8];
} state;
_Static_assert(offsetof(state,mm)==40,"native snapshot layout");
static state input,native_out;
#if defined(_WIN32)
static uint32_t saved_host_sp;
static void *original;
#endif
enum { FIXTURE=0x03000000, BYTES=0x80000, OBJECT=FIXTURE+0x100, VECTOR=FIXTURE+0x200, WRAPPER=FIXTURE+0x300 };
static unsigned char initial[BYTES],expected[BYTES];
static unsigned char yield_expected[2][BYTES];
static state yield_state[2];
static uint32_t yield_flags[2][4];
static unsigned yield_count,reference_mode,case_number;
static uint32_t seed=0xC362E012;
static uint32_t source,destination,used;
static int groups;
static unsigned guard;
static volatile uint32_t sink;

static void fail(const char *what) {
    fprintf(stderr,"%s mismatch case %u groups %d source %08x destination %08x used %u yield %u\n",what,case_number,groups,source,destination,used,yield_count);
    exit(2);
}
static void unresolved(void) {fprintf(stderr,"unadmitted external helper\n");exit(81);}
void sub_00C357A0(void) {unresolved();}
void sub_00C67B90(void) {unresolved();}
recomp_func_t void_resolve(uint32_t va) {(void)va;unresolved();return 0;}

/* The exact unchanged 606 bytes run only in this isolated native oracle. */
#if defined(_WIN32)
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

static void *at(uint32_t address) {return (void *)ADDR(address);}
static uint32_t random32(void) {
    uint32_t x=seed;x^=x<<13;x^=x>>17;x^=x<<5;return seed=x;
}
static void put32(uint32_t address,uint32_t value) {memcpy(at(address),&value,4);}
static uint32_t get32(uint32_t address) {uint32_t value;memcpy(&value,at(address),4);return value;}
static void protect(int enable) {
#if defined(_WIN32)
    DWORD previous;
    if(guard && (!VirtualProtect(at(FIXTURE+0x20000),4096,enable?PAGE_NOACCESS:PAGE_READWRITE,&previous) ||
                 !VirtualProtect(at(FIXTURE+0x60000),4096,enable?PAGE_NOACCESS:PAGE_READWRITE,&previous))) exit(83);
#else
    if(guard && (mprotect(at(FIXTURE+0x20000),4096,enable?PROT_NONE:PROT_READ|PROT_WRITE) ||
                 mprotect(at(FIXTURE+0x60000),4096,enable?PROT_NONE:PROT_READ|PROT_WRITE))) exit(83);
#endif
}
static void seed_globals(void) {
    g_eax=input.a;g_ecx=input.c;g_edx=input.d;g_esp=input.sp;
    g_ebx=input.b;g_esi=input.si;g_edi=input.di;g_ebp=input.bp;
    g_flag_k=FK_EFLAGS;g_flag_a=0x202;g_flag_b=g_flag_cf=0;
    memcpy(g_mm,input.mm,sizeof g_mm);g_cur_func=0;g_enter_idx=0;
}
static void snapshot(state *result) {
    memset(result,0,sizeof *result);
    result->a=g_eax;result->c=g_ecx;result->d=g_edx;result->sp=g_esp;
    result->b=g_ebx;result->si=g_esi;result->di=g_edi;result->bp=g_ebp;
    result->flags=recomp_eflags(g_flag_k,g_flag_a,g_flag_b,g_flag_cf,1)&0x8D5;
    memcpy(result->mm,g_mm,sizeof g_mm);
}
static int same_state(const state *a,const state *b) {
    return !memcmp(a,b,36)&&!memcmp(a->mm,b->mm,64);
}
static void compare(const state *wanted,const unsigned char *memory,const char *what) {
    state actual;snapshot(&actual);
    if(!same_state(wanted,&actual)||memcmp(memory,at(FIXTURE),BYTES)) {
        const uint32_t *a=(const uint32_t *)wanted,*b=(const uint32_t *)&actual;
        for(unsigned i=0;i<9;i++)if(a[i]!=b[i])fprintf(stderr,"state word %u expected %08x actual %08x\n",i,a[i],b[i]);
        for(unsigned i=0;i<8;i++)if(wanted->mm[i]!=actual.mm[i])fprintf(stderr,"mm%u expected %016llx actual %016llx\n",i,(unsigned long long)wanted->mm[i],(unsigned long long)actual.mm[i]);
        for(unsigned i=0;i<BYTES;i++)if(memory[i]!=((unsigned char *)at(FIXTURE))[i]) {fprintf(stderr,"memory first difference +%x expected %02x actual %02x\n",i,memory[i],((unsigned char *)at(FIXTURE))[i]);break;}
        fail(what);
    }
    if(g_esp!=input.sp+24)fail("ret14 stack cleanup");
}
static void restore(uint32_t return_address) {
    memcpy(at(FIXTURE),initial,BYTES);put32(input.sp,return_address);seed_globals();
}
static void setup(int count,unsigned layout,unsigned ordinal) {
    groups=count;case_number=ordinal;used=ordinal%6;guard=layout>=6;
    if(count>0 && used>10922u-(unsigned)count)used=10922u-(unsigned)count;
    for(unsigned i=0;i<BYTES;i+=4)memcpy(initial+i,&(uint32_t){random32()},4);
    memset(&input,0,sizeof input);
    input.a=random32();input.d=random32();input.b=random32();input.si=random32();input.di=random32();input.bp=random32();
    input.c=OBJECT;input.sp=FIXTURE+0x78000+16*(ordinal&31);
    for(unsigned i=0;i<8;i++)input.mm[i]=((uint64_t)random32()<<32)|random32();
    source=FIXTURE+0x10000;destination=FIXTURE+0x30000;
    if(layout==1){source++;destination+=3;}
    if(layout==2)destination=source;
    if(layout==3)destination=source+2;
    if(layout==4)destination=source-8;
    if(layout==5)source=destination+12;
    unsigned indices=count>0?(unsigned)count*3:0;
    if(layout>=6)source=FIXTURE+0x20000-2*indices;
    if(layout==6)destination=FIXTURE+0x40000+1;
    if(layout==7)destination=FIXTURE+0x60000-4*indices;
    memcpy(at(FIXTURE),initial,BYTES);
    put32(OBJECT+4,VECTOR);put32(OBJECT+8,VECTOR+4);put32(OBJECT+0x28,0);put32(VECTOR,WRAPPER);
    put32(OBJECT+0x10,used);put32(OBJECT+0x14,10922);
    put32(OBJECT+0x2C,ordinal&1);put32(WRAPPER+0x10,destination-12*used);
    put32(WRAPPER+0x14,0x20000);put32(WRAPPER+0xC,0);
    put32(input.sp+4,source);put32(input.sp+8,(uint32_t)count);
    static const uint32_t bases[]={0,1,0xFFFFFFFFu,0xFFFF0001u,0x7FFFFFFFu,0x80000000u,0x12345678u};
    put32(input.sp+12,bases[ordinal%7]);put32(input.sp+16,ordinal%16384);put32(input.sp+20,ordinal&1);
    static const uint16_t values[]={0,1,65535,32767,32768,65534,2,12345};
    for(unsigned i=0;i<indices;i++){uint16_t value=i<32?values[i%8]:(uint16_t)random32();memcpy(at(source+2*i),&value,2);}
    memcpy(initial,at(FIXTURE),BYTES);
    *(unsigned char *)at(0x010D755E)=0;
}
static void native_oracle(void) {
    static const int counts[]={-3,-1,0,1,2,3,4,5,6,7,10,11,12,16,17,18,21,22,23,31,32,33,34,35,63,64,65,127,128,129,10921,10922};
    unsigned cases=0;
#if defined(_WIN32)
    FILE *vectors=fopen("native-vectors.bin","wb");
#else
    FILE *vectors=fopen("native-vectors.bin","rb");
#endif
    if(!vectors)exit(87);
    for(unsigned c=0;c<sizeof counts/sizeof *counts;c++)for(unsigned layout=0;layout<8;layout++)for(unsigned bias=0;bias<7;bias++) {
        setup(counts[c],layout,cases++);
        static const uint32_t starts[]={0,65535,65536,UINT32_MAX,0xFFFFFF00u};
        uint32_t start_backedges=starts[(cases-1)%5];
        recomp_yield_hook=0;g_backedges=start_backedges;
#if defined(_WIN32)
        protect(1);native_snapshot();protect(0);
        native_out.flags&=0x8D5;
        memcpy(expected,at(FIXTURE),BYTES);uint32_t return_address=get32(input.sp);
        if(fwrite(&native_out,sizeof native_out,1,vectors)!=1||fwrite(&return_address,4,1,vectors)!=1)exit(88);
        /* Encode every changed byte, including changes outside the intended output. */
        for(uint32_t offset=0;offset<BYTES;) {
            if(expected[offset]==initial[offset]){offset++;continue;}
            uint32_t first=offset;while(offset<BYTES&&expected[offset]!=initial[offset])offset++;
            uint32_t length=offset-first;
            if(fwrite(&first,4,1,vectors)!=1||fwrite(&length,4,1,vectors)!=1||fwrite(expected+first,1,length,vectors)!=length)exit(88);
        }
        uint32_t end=UINT32_MAX;if(fwrite(&end,4,1,vectors)!=1)exit(88);
#else
        uint32_t return_address;
        if(fread(&native_out,sizeof native_out,1,vectors)!=1||fread(&return_address,4,1,vectors)!=1)exit(89);
        memcpy(expected,initial,BYTES);
        for(;;) {
            uint32_t offset,length;
            if(fread(&offset,4,1,vectors)!=1)exit(89);
            if(offset==UINT32_MAX)break;
            if(fread(&length,4,1,vectors)!=1||offset>=BYTES||length>BYTES-offset||fread(expected+offset,1,length,vectors)!=length)exit(89);
        }
#endif
        restore(return_address);g_backedges=start_backedges;protect(1);before_index();protect(0);compare(&native_out,expected,"unchanged versus native");
        uint32_t before_flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf},before_backedges=g_backedges;
        unsigned n=groups>0?(unsigned)groups*3:0;
        unsigned expected_backedges=groups>0?((n>=4?(n-2+15)/16:0)+n/4+n%4+1):0;
        if(before_backedges!=start_backedges+expected_backedges)fail("independent backedge count");
        restore(return_address);g_backedges=start_backedges;protect(1);after_index();protect(0);compare(&native_out,expected,"candidate versus native");
        uint32_t after_flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
        if(memcmp(before_flags,after_flags,sizeof before_flags)||g_backedges!=before_backedges)fail("final lazy flags/backedge count");
    }
    if(fclose(vectors))exit(90);
    printf("{\"native_whole_function\":\"PASS\",\"oracle_kind\":\"%s\",\"exact_original_bytes\":606,\"cases\":%u,\"models\":2,\"full_guest_memory_bytes\":%u,\"gprs\":8,\"raw_mmx_registers\":8,\"arithmetic_eflags_mask\":2261,\"layouts\":8,\"guard_page_layouts\":2}\n",
#if defined(_WIN32)
        "native_x86",
#else
        "recorded_original_x86",
#endif
        cases,BYTES);
}
static void mutating_hook(void) {
    if(yield_count>=2)exit(84);
    state current;snapshot(&current);
    uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    protect(0);
    if(reference_mode) {
        yield_state[yield_count]=current;memcpy(yield_expected[yield_count],at(FIXTURE),BYTES);
        memcpy(yield_flags[yield_count],flags,sizeof flags);
    } else if(!same_state(&yield_state[yield_count],&current)||memcmp(yield_expected[yield_count],at(FIXTURE),BYTES)||memcmp(yield_flags[yield_count],flags,sizeof flags))fail("yield intermediate state");
    protect(1);
    for(unsigned i=0;i<8;i++)g_mm[i]^=0xA050C030B020D010ULL+(uint64_t)i*0x102030405060708ULL;
    g_ebx^=0x10001u;
    g_flag_k=FK_EFLAGS;g_flag_a=0x845;g_flag_b=0;g_flag_cf=1;
    yield_count++;
}
static void yield_oracle(void) {
    static const int counts[]={1,2,5,6,11,22,129,10922};
    static const uint32_t budgets[]={0,1,2,3,4,5,6,7,8,16,32,2048,65535,65536,0xFFFFFFFFu};
    unsigned cases=0,observed=0;
    for(unsigned c=0;c<sizeof counts/sizeof *counts;c++)for(unsigned k=0;k<sizeof budgets/sizeof *budgets;k++) {
        setup(counts[c],c%8,10000+cases++);
        uint32_t initial_backedges=budgets[k]==0xFFFFFFFFu?budgets[k]:0x10000u-budgets[k];
        restore(0x12345678);g_backedges=initial_backedges;yield_count=0;reference_mode=1;recomp_yield_hook=mutating_hook;
        protect(1);before_index();protect(0);
        state reference;snapshot(&reference);memcpy(expected,at(FIXTURE),BYTES);
        uint32_t before_flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
        unsigned wanted_yields=yield_count;uint32_t wanted_backedges=g_backedges;observed+=wanted_yields;
        restore(0x12345678);g_backedges=initial_backedges;yield_count=0;reference_mode=0;
        protect(1);after_index();protect(0);
        if(yield_count!=wanted_yields||g_backedges!=wanted_backedges)fail("yield scheduling");
        compare(&reference,expected,"yield final state");
        uint32_t after_flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
        if(memcmp(before_flags,after_flags,sizeof before_flags))fail("yield final lazy flags");
    }
    recomp_yield_hook=0;
    printf("{\"mutating_yield\":\"PASS\",\"cases\":%u,\"recorded_intermediate_full_memory_states\":%u,\"production_period\":65536,\"unsigned_wrap_case\":true}\n",cases,observed);
}

#ifndef PC_INDEX_TIMING
#define PC_INDEX_TIMING 0
#endif
#if defined(_WIN32)
static void timing_hook(void) {
    g_mm[1]^=0x1000100010001ULL;g_mm[7]^=0x123456789ABCDEF0ULL;
}
static double measure(void (*fn)(void),int count,unsigned calls,int with_hook) {
    uint32_t saved_seed=seed;seed=0xC362BEEF;setup(count,0,12000);seed=saved_seed;
    LARGE_INTEGER frequency,before,after;QueryPerformanceFrequency(&frequency);
    LONGLONG ticks=0;
    for(unsigned i=0;i<calls;i++) {
        seed_globals();
        g_backedges=with_hook?65536u-((3*(unsigned)count-2+15)/16)-(3*(unsigned)count/4/2):0;
        recomp_yield_hook=with_hook?timing_hook:0;put32(OBJECT+0x10,used);
        memcpy(at(input.sp),initial+input.sp-FIXTURE,24);
        QueryPerformanceCounter(&before);fn();QueryPerformanceCounter(&after);ticks+=after.QuadPart-before.QuadPart;
        sink^=get32(destination+((unsigned)count*3-1)*4)^g_eax;
    }
    return (double)ticks*1e9/frequency.QuadPart/calls;
}
static LONG CALLBACK exception(EXCEPTION_POINTERS *e) {
    fprintf(stderr,"unexpected native/probe exception %08lx address %p EIP %08lx case %u\n",e->ExceptionRecord->ExceptionCode,e->ExceptionRecord->ExceptionAddress,e->ContextRecord->Eip,case_number);
    ExitProcess(86);return EXCEPTION_CONTINUE_SEARCH;
}
#endif
int main(void) {
#if defined(_WIN32)
    AddVectoredExceptionHandler(1,exception);
    SYSTEM_INFO info;GetSystemInfo(&info);DWORD_PTR affinity=(DWORD_PTR)1<<(info.dwNumberOfProcessors>7?7:0);
    SetThreadAffinityMask(GetCurrentThread(),affinity);
    if(VirtualAlloc(at(FIXTURE),BYTES,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)!=at(FIXTURE))return 3;
    if(VirtualAlloc(at(0x010D0000),0x10000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)!=at(0x010D0000))return 4;
    original=VirtualAlloc(0,sizeof original_code,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(!original)return 5;
    memcpy(original,original_code,sizeof original_code);DWORD previous;
    if(!VirtualProtect(original,sizeof original_code,PAGE_EXECUTE_READ,&previous))return 6;
    FlushInstructionCache(GetCurrentProcess(),original,sizeof original_code);
#else
    if(mmap(at(FIXTURE),BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)!=at(FIXTURE))return 3;
    if(mmap(at(0x010D0000),0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)!=at(0x010D0000))return 4;
#endif
    native_oracle();yield_oracle();
#if defined(_WIN32)
    if(PC_INDEX_TIMING)for(unsigned mode=0;mode<2;mode++)for(unsigned size=0;size<2;size++)for(unsigned round=0;round<9;round++) {
        int count=size?10922:22;unsigned calls=size?1000:10000;double a,b;
        if(round&1){b=measure(after_index,count,calls,mode);a=measure(before_index,count,calls,mode);}
        else{a=measure(before_index,count,calls,mode);b=measure(after_index,count,calls,mode);}
        printf("{\"round\":%u,\"groups\":%d,\"calls\":%u,\"mutating_hook\":%s,\"unchanged_ns\":%.6f,\"localized_ns\":%.6f,\"ratio_unchanged_over_local\":%.6f}\n",round,count,calls,mode?"true":"false",a,b,a/b);
    }
    printf("{\"host_bits\":32,\"affinity_mask\":%llu,\"sink\":%u,\"timing_includes_counter_overhead\":true,\"reseeding_outside_timing\":true}\n",(unsigned long long)affinity,sink);
#else
    printf("{\"host_bits\":64,\"timing_run\":false}\n");
#endif
    return 0;
}
