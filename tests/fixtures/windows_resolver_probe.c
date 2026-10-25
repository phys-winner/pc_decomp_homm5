/* Actual Windows resolver checks, shared by O2 and ThinLTO runtime probes. */
#include <setjmp.h>
extern uint32_t g_native_target;
void probe_dispatch_init(void),probe_cache_reset(void);
int probe_caches_equal(void);
recomp_func_t baseline_resolve(uint32_t va),probe_manual_expected(uint32_t va);
uint32_t homm5_pc_shim_address(const char *name);
static jmp_buf trap_return;
static int expecting_trap;
static uint32_t trapped_va;
static const char *trapped_reason;
static unsigned resolver_cases,native_target_cases,trap_cases;
static recomp_func_t (*volatile candidate_lookup)(uint32_t)=void_resolve;
static recomp_func_t (*volatile original_lookup)(uint32_t)=baseline_resolve;
static void fail_resolver(const char *what,uint32_t va) {
    fprintf(stderr,"FAIL resolver %s va=%08X\n",what,va);ExitProcess(25);
}
static void resolver_thread_check(uint32_t seed);

/* BASELINE_RESOLVER */
recomp_func_t void_resolve(uint32_t va)
{
    pc_slot *cached = &resolve_cache[(va * 0x9E3779B1u) >> 20];
    if (va && cached->va == va) {
        /* native_bridge reads this target before releasing the machine.
         * Publish it even on a cache hit; lifted/shim entries ignore it. */
        g_native_target = va;
        return cached->fn;
    }
    recomp_func_t body = recomp_lookup_manual(va);
    if (!body) body = recomp_lookup(va);
    if (!body && !native32_in_guest(va)) body = recomp_lookup_import(va);
    if (!body) void_lift_trap(va, "unresolved static control-flow target");
    cached->va = va; cached->fn = body;
    return body;
}

/* RESOLVER_CHECKS */

typedef struct {
    state vm;
    uint32_t enter[1024],icall[ICALL_TRACE_SIZE],from[ICALL_TRACE_SIZE],enter_idx,icall_idx,target;
    unsigned char stack[256];
    int physical_window;
    DWORD error;
} lookup_state;
static void lookup_snapshot(lookup_state *s) {
    DWORD error=GetLastError();memset(s,0,sizeof *s);take(&s->vm);
    memcpy(s->enter,g_enter_trace,sizeof s->enter);memcpy(s->icall,g_icall_trace,sizeof s->icall);
    memcpy(s->from,g_icall_from,sizeof s->from);s->enter_idx=g_enter_idx;s->icall_idx=g_icall_trace_idx;
    memcpy(s->stack,(void *)(uintptr_t)(g_esp-128),sizeof s->stack);
    #ifdef RECOMP_X87_WINDOW
    s->physical_window=g_fp_sp;
    #endif
    s->target=g_native_target;s->error=error;
}
static void lookup_compare(uint32_t va) {
    lookup_state before,left,right;
    fill(0xD70000u+resolver_cases);g_native_target=0xC001D00Du;SetLastError(0xD1234567u);
    lookup_snapshot(&before);recomp_func_t a=original_lookup(va);lookup_snapshot(&left);
    g_native_target=0xC001D00Du;SetLastError(0xD1234567u);
    recomp_func_t b=candidate_lookup(va);lookup_snapshot(&right);
    if(a!=b)fail_resolver("pointer",va);
    recomp_func_t manual=probe_manual_expected(va);
    if(manual&&(a!=manual||b!=manual))fail_resolver("manual lookup priority",va);
    if(left.target!=right.target)fail_resolver("native target",va);
    if(memcmp(&left,&right,sizeof left))fail_resolver("complete state/trace/stack/LastError",va);
    left.target=before.target;left.error=before.error;
    if(memcmp(&left,&before,sizeof left))fail_resolver("guest state modified by lookup",va);
    if(!probe_caches_equal())fail_resolver("cache contents",va);
    ++resolver_cases;
}
static void lookup_trap(uint32_t va) {
    const char *messages[2]={0};uint32_t addresses[2]={0};
    recomp_func_t (*lookups[])(uint32_t)={baseline_resolve,void_resolve};
    for(unsigned i=0;i<2;i++) {
        expecting_trap=1;trapped_reason=NULL;trapped_va=0;
        if(!setjmp(trap_return)) {lookups[i](va);fail_resolver("returned instead of trap",va);}
        expecting_trap=0;messages[i]=trapped_reason;addresses[i]=trapped_va;
    }
    if(addresses[0]!=va||addresses[1]!=va||!messages[0]||!messages[1]||strcmp(messages[0],messages[1]))fail_resolver("trap mismatch",va);
    ++trap_cases;
}
static uint32_t call_resolved(void *fn,unsigned count,const uint32_t *args) {
    for(unsigned i=count;i;i--)PUSH32(g_esp,args[i-1]);
    recomp_func_t bridge=candidate_lookup((uint32_t)(uintptr_t)fn);
    if(!bridge)fail_resolver("NULL callable",(uint32_t)(uintptr_t)fn);
    PUSH32(g_esp,RECOMP_RETADDR);bridge();return g_eax;
}
static uint32_t __stdcall native_a(void) {SetLastError(0xA001);return 0xAA112233;}
static uint32_t __stdcall native_b(void) {SetLastError(0xB002);return 0xBB445566;}
static void resolver_thread_check(uint32_t seed) {
    DWORD id=GetCurrentThreadId();uint32_t sp=g_esp;SetLastError(seed);
    uint32_t got=call_resolved((void *)GetCurrentThreadId,0,NULL);DWORD error=GetLastError();
    if(got!=id||g_esp!=sp||error!=seed)fail_resolver("serialized thread/native/LastError",id);
}
static void run_resolver_checks(void) {
    probe_cache_reset();
    HMODULE kernel=GetModuleHandleA("kernel32.dll");
    FARPROC error_get=GetProcAddress(kernel,"GetLastError");
    FARPROC error_set=GetProcAddress(kernel,"SetLastError");
    FARPROC tls_get=GetProcAddress(kernel,"TlsGetValue");
    if(!error_get||!probe_manual_expected((uint32_t)(uintptr_t)error_get))fail_resolver("manual fixture GetLastError absent",(uint32_t)(uintptr_t)error_get);
    if(!error_set||!probe_manual_expected((uint32_t)(uintptr_t)error_set))fail_resolver("manual fixture SetLastError absent",(uint32_t)(uintptr_t)error_set);
    if(!tls_get||!probe_manual_expected((uint32_t)(uintptr_t)tls_get))fail_resolver("manual fixture TlsGetValue absent",(uint32_t)(uintptr_t)tls_get);
    lookup_trap(0);lookup_trap(0xFFFF);lookup_trap(0x30002010);lookup_trap(0x30001FFF);
    uint32_t targets[]={0x30001000,0x30001100,0x30001200,0x30001016,0x30001A2E,
        (uint32_t)(uintptr_t)error_get,(uint32_t)(uintptr_t)error_set,(uint32_t)(uintptr_t)tls_get,
        (uint32_t)(uintptr_t)native_a,(uint32_t)(uintptr_t)native_b,0x10000,RECOMP_RETADDR};
    for(unsigned round=0;round<96;++round)for(unsigned i=0;i<sizeof targets/sizeof *targets;++i)lookup_compare(targets[(i+round)%12]);
    if(((0x30001016u*0x9E3779B1u)>>20)!=((0x30001A2Eu*0x9E3779B1u)>>20))fail_resolver("fixture collision absent",0);
    for(unsigned i=0;i<128;i++){lookup_compare(0x30001016);lookup_compare(0x30001A2E);}
    uint32_t sp=g_esp;
    for(unsigned i=0;i<128;i++) {
        g_native_target=0xDEADBEEFu;
        uint32_t a=call_resolved((void *)native_a,0,NULL);DWORD ea=GetLastError();
        uint32_t b=call_resolved((void *)native_b,0,NULL);DWORD eb=GetLastError();
        uint32_t again=call_resolved((void *)native_a,0,NULL);DWORD ec=GetLastError();
        if(a!=0xAA112233u||again!=a||b!=0xBB445566u||ea!=0xA001||eb!=0xB002||ec!=ea||g_esp!=sp)fail_resolver("real native A B A hit",i);
        ++native_target_cases;
    }
    for(unsigned i=0;i<8;i++) {
        SetLastError(0x88112233u+i);uint32_t error=call_resolved((void *)error_get,0,NULL);
        if(error!=0x88112233u+i||g_esp!=sp)fail_resolver("manual GetLastError",i);
        uint32_t value=0x77223344u+i;call_resolved((void *)error_set,1,&value);
        if(GetLastError()!=value||g_esp!=sp)fail_resolver("manual SetLastError",i);
    }
    uint32_t key=TlsAlloc();if(key==TLS_OUT_OF_INDEXES||!TlsSetValue(key,(void *)0x12345678u))fail_resolver("TLS fixture",0);
    for(unsigned i=0;i<8;i++) {
        SetLastError(0xAABBCCDDu);uint32_t value=call_resolved((void *)tls_get,1,&key);DWORD error=GetLastError();
        if(value!=0x12345678u||error||g_esp!=sp)fail_resolver("manual TlsGetValue",i);
    }
    TlsFree(key);
    /* Native-only call checks populated one cache; start the next differential phase equally. */
    probe_cache_reset();
    native32_shim_t shims[]={{"FixtureFirst",collision_first},{"FixtureSecond",collision_second}};
    for(unsigned repeat=0;repeat<2;repeat++) {
        if(native32_bind(0x30000000u,shims,2))fail_resolver("bind",0);
        uint32_t va=homm5_pc_shim_address("FixtureFirst");if(!va)fail_resolver("shim address",0);
        for(unsigned i=0;i<8;i++)lookup_compare(va);
    }
    printf("PASS actual Windows resolver: %u exact lookups, %u native A B A cache-hit cycles, %u strict traps; full VM/trace/stack/physical window/LastError, full-VA collisions, actual manual shims, repeat identical binding, serialized thread callbacks\n",resolver_cases,native_target_cases,trap_cases);
}
