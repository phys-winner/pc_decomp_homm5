"""Prepare an isolated Win32 platform copy of the current H5 register model.

The Android and vendor sources remain unchanged. The native32 bridge is the
pinned reference implementation; its register snapshots gain H5's current
published flags, exact integer shadows, shared x87 condition and loop counter.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VENDOR_SHA = 'b1b5008f75b6d1174ae9727566ca4d1c1796a6f45c3c030e0bd3c5ecf0a751bb'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def platform_header(source):
    source, count = re.subn(r'#if defined\(_MSC_VER\) \|\| !defined\(__aarch64__\)\n#error[^\n]*\n#endif',
                           '#include <intrin.h> /* Win32 platform intrinsic. */', source, count=1)
    if count != 1:
        raise ValueError('Expected current ARM architecture assertion')
    source, count = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}',
                           '/* Native PC RDTSC is the compiler intrinsic from intrin.h. */',
                           source, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Expected ARM counter implementation')
    return source


def platform_runtime(source):
    edits = [
        ('double    g_st[8];', '''#ifdef RECOMP_X87_WINDOW
double g_st_win[RECOMP_X87_SLOTS];
int64_t g_st_i64_win[RECOMP_X87_SLOTS];
int g_fp_sp = RECOMP_X87_SLOTS / 2;
#else
double g_st[8];
#endif'''),
        ('int native32_trace_native, native32_trace_callbacks;', '''int native32_trace_native, native32_trace_callbacks;
#ifndef RECOMP_X87_WINDOW
int64_t g_st_i64[8];
#endif
int void_fpu_cmp = 1;
uint32_t g_flag_k, g_flag_a, g_flag_b, g_flag_cf;
uint32_t g_backedges, g_es_base;
void (*recomp_yield_hook)(void);
extern void homm5_pc_thread_init(uint32_t tib);'''),
        ('    double   st[8];', '''    double   st[8];
    int64_t st_i64[8];
    int fpu_cmp;
    uint32_t flag_k, flag_a, flag_b, flag_cf, backedges;'''),
        ('    memcpy(r->st, g_st, sizeof g_st); r->fp_top = g_fp_top; r->fpu_cw = g_fpu_cw;', '''    memcpy(r->st, g_st, sizeof g_st); r->fp_top = g_fp_top; r->fpu_cw = g_fpu_cw;
    memcpy(r->st_i64, g_st_i64, sizeof g_st_i64); r->fpu_cmp = void_fpu_cmp;
    r->flag_k = g_flag_k; r->flag_a = g_flag_a; r->flag_b = g_flag_b; r->flag_cf = g_flag_cf;
    r->backedges = g_backedges;'''),
        ('    memcpy(g_st, r->st, sizeof g_st); g_fp_top = r->fp_top; g_fpu_cw = r->fpu_cw;', '''    memcpy(g_st, r->st, sizeof g_st); g_fp_top = r->fp_top; g_fpu_cw = r->fpu_cw;
    memcpy(g_st_i64, r->st_i64, sizeof g_st_i64); void_fpu_cmp = r->fpu_cmp;
    g_flag_k = r->flag_k; g_flag_a = r->flag_a; g_flag_b = r->flag_b; g_flag_cf = r->flag_cf;
    g_backedges = r->backedges;'''),
        ('        m->r.fpu_cw = 0x027F;', '        m->r.fpu_cw = 0x027F;\n        m->r.fpu_cmp = 1;'),
        ('    return (uint32_t)(uintptr_t)t;\n}',
         '    homm5_pc_thread_init((uint32_t)(uintptr_t)t);\n    return (uint32_t)(uintptr_t)t;\n}'),
        ('        const char* dll = (const char*)(b + d->Name);', '''        const char* dll = (const char*)(b + d->Name);
        /* Match the existing H5 Android loader's shipped-CRT aliases. */
        if (!_stricmp(dll, "msvcrt.dll") || !_stricmp(dll, "crtdll.dll")) dll = "msvcr71.dll";'''),
        ('static uint32_t g_native_target;', 'uint32_t g_native_target;'),
        ('''void mach_enter(void) {
    EnterCriticalSection(&g_mach);''', '''/* Threads blocked in mach_enter: the bridge keeps the machine across a native
 * call unless one is waiting or the call can block (H5 bridge policy). */
volatile LONG g_mach_waiters;
void mach_enter(void) {
    InterlockedIncrement(&g_mach_waiters);
    EnterCriticalSection(&g_mach);
    InterlockedDecrement(&g_mach_waiters);'''),
        ('''    g_cur_import = native32_name(fn);
    if (!g_cur_import) g_cur_import = "(native)";
    mach_leave();
    SetLastError(guest_error);''', '''    g_cur_import = native32_name(fn);
    if (!g_cur_import) g_cur_import = "(native)";
    /* Keep the machine (and skip the full state save/load) across calls that
     * cannot wait for another guest thread, unless one is already waiting.
     * A guest EnterCriticalSection that would block gives the machine up. */
    int bridge_policy = bridge_release_policy(fn, g_cur_import, src[0]);
    if (bridge_policy == BRIDGE_TRY_ENTER && TryEnterCriticalSection((LPCRITICAL_SECTION)(uintptr_t)src[0])) {
        g_cur_import = saved_import;
        g_esp += 4 + 4;
        SetLastError(guest_error);
        return;
    }
    int release = bridge_policy != BRIDGE_KEEP || g_mach_waiters > 0;
    int kept_level = -1;
    if (release) mach_leave();
    else if ((kept_level = t_bridge_kept++) < 64) t_bridge_late[kept_level] = 0;
    SetLastError(guest_error);'''),
        ('''    DWORD last_error = GetLastError();
    mach_enter();
    if (st_ret) fp_push_impl(g_st, &g_fp_top, r_st);''', '''    DWORD last_error = GetLastError();
    if (kept_level >= 0) {
        --t_bridge_kept;
        if (kept_level < 64 && t_bridge_late[kept_level]) release = 1;   /* a callback gave it up */
    }
    if (release) mach_enter();
    if (st_ret) fp_push_impl(g_st, &g_fp_top, r_st);'''),
        ('''    if (native32_trace_callbacks)
        fprintf(stderr, "[callback] sub_%08X (%08X %08X %08X %08X)\\n", va, sp[1], sp[2], sp[3], sp[4]);
    mach_enter();''', '''    if (native32_trace_callbacks)
        fprintf(stderr, "[callback] sub_%08X (%08X %08X %08X %08X)\\n", va, sp[1], sp[2], sp[3], sp[4]);
    if (t_bridge_kept > 0 && t_bridge_kept <= 64 && !t_bridge_late[t_bridge_kept - 1]) {
        t_bridge_late[t_bridge_kept - 1] = 1;
        mach_leave();
    }
    mach_enter();'''),
        ('static void native_bridge(void) {', '''/* Native calls that keep the machine: they cannot wait for another guest
 * thread, call back into guest code or send a window message (a window
 * owned by another guest thread would need the machine to answer it). Only
 * D3D9 COM methods past the device-management slots (state, resources,
 * drawing: vtable index 18 and up) and a few kernel/timer/D3DX functions
 * qualify; everything else gives the machine up as before. A guest
 * EnterCriticalSection tries first and only gives it up if it would block. */
enum { BRIDGE_KEEP, BRIDGE_RELEASE, BRIDGE_TRY_ENTER };
static int bridge_named_policy(const char* name) {
    static const char* const keep[] = {
        "GetTickCount", "QueryPerformanceCounter", "QueryPerformanceFrequency", "GetCurrentThreadId",
        "GetCurrentThread", "GetCurrentProcessId", "GetCurrentProcess", "TlsGetValue", "TlsSetValue",
        "InterlockedIncrement", "InterlockedDecrement", "InterlockedExchange", "InterlockedCompareExchange",
        "InterlockedExchangeAdd", "LeaveCriticalSection", "RtlLeaveCriticalSection", "HeapAlloc", "HeapFree",
        "HeapReAlloc", "HeapSize", "GetProcessHeap", "GetLastError", "SetLastError", "timeGetTime", NULL};
    const char* bang = strchr(name, '!');
    const char* f = bang ? bang + 1 : name;
    if (!strcmp(f, "EnterCriticalSection") || !strcmp(f, "RtlEnterCriticalSection")) return BRIDGE_TRY_ENTER;
    if (bang && (!_strnicmp(name, "d3dx9", 5))) return BRIDGE_KEEP;
    for (int i = 0; keep[i]; i++)
        if (!strcmp(f, keep[i])) return BRIDGE_KEEP;
    return BRIDGE_RELEASE;
}
static int bridge_readable(uint32_t va, uint32_t bytes) {
    MEMORY_BASIC_INFORMATION mbi;
    if (va < 0x10000u || !VirtualQuery((void*)(uintptr_t)va, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT ||
        (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    return (uintptr_t)va + bytes <= (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
}
static int bridge_com_policy(uint32_t fn, uint32_t self) {
    static uint32_t d3d9_lo, d3d9_hi;
    if (!d3d9_lo) {
        HMODULE d3d9 = GetModuleHandleA("d3d9.dll");
        if (!d3d9) return BRIDGE_RELEASE;
        IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)((char*)d3d9 + ((IMAGE_DOS_HEADER*)d3d9)->e_lfanew);
        d3d9_lo = (uint32_t)(uintptr_t)d3d9;
        d3d9_hi = d3d9_lo + nt->OptionalHeader.SizeOfImage;
    }
    if (fn < d3d9_lo || fn >= d3d9_hi || !bridge_readable(self, 4)) return BRIDGE_RELEASE;
    uint32_t vtable = *(uint32_t*)(uintptr_t)self;
    MEMORY_BASIC_INFORMATION mbi;
    if (vtable < 0x10000u || !VirtualQuery((void*)(uintptr_t)vtable, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT ||
        (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return BRIDGE_RELEASE;
    uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
    for (uint32_t i = 0; i < 200 && (uintptr_t)vtable + 4 * i + 4 <= end; i++)
        if (((uint32_t*)(uintptr_t)vtable)[i] == fn) return i >= 18 ? BRIDGE_KEEP : BRIDGE_RELEASE;
    return BRIDGE_RELEASE;
}
/* Per-target decision table (open addressing, never evicted: a few hundred
 * distinct native targets); only the thread holding the machine fills it. */
static struct { uint32_t va; int policy; } g_bridge_policy[4096];
static int bridge_release_policy(uint32_t va, const char* name, uint32_t self) {
    unsigned slot = (va * 0x9E3779B1u) >> 20;
    for (unsigned probe = 0; probe < 4096; probe++, slot = (slot + 1) & 4095) {
        if (g_bridge_policy[slot].va == va) return g_bridge_policy[slot].policy;
        if (!g_bridge_policy[slot].va) {
            int policy = strcmp(name, "(native)") ? bridge_named_policy(name) : bridge_com_policy(va, self);
            g_bridge_policy[slot].policy = policy;
            g_bridge_policy[slot].va = va;
            return policy;
        }
    }
    return BRIDGE_RELEASE;
}
/* Kept native calls active on this thread. A callback that arrives inside one
 * gives the machine up on its behalf (the outer bridge takes it back after
 * the call), so callbacks always run as they did with every call released. */
static __declspec(thread) int t_bridge_kept;
static __declspec(thread) unsigned char t_bridge_late[64];

static void native_bridge(void) {'''),
        ('''const char* native32_name(uint32_t va) {
    for (int i = 0; i < g_name_n; i++)
        if (g_names[i].va == va) return g_names[i].name;
    return NULL;
}''', '''/* Names only append. Cache misses as well as hits, and invalidate them
 * when binding appends a name. Per-thread slots add no shared writes to the
 * bridge; the existing machine lock still owns guest execution/binding. */
typedef struct { uint32_t va; int count; const char* name; } name_cache_slot;
static __declspec(thread) name_cache_slot g_name_cache[256];
/* At most 4096 append-only names leave an empty slot in this index. */
static uint16_t g_name_index[8192];

const char* native32_name(uint32_t va) {
    int count = g_name_n;
    name_cache_slot* slot = &g_name_cache[(va * 0x9E3779B1u) >> 24];
    if (slot->va == va && slot->count == count) return slot->name;
    const char* name = NULL;
    unsigned bucket = (va * 0x9E3779B1u) >> 19, entry;
    while ((entry = g_name_index[bucket]) != 0) {
        if (g_names[entry - 1].va == va) { name = g_names[entry - 1].name; break; }
        bucket = (bucket + 1) & 8191;
    }
    slot->va = va; slot->count = count; slot->name = name;
    return name;
}'''),
        ('        g_names[g_name_n++].va = va;', '''        g_names[g_name_n++].va = va;
        unsigned bucket = (va * 0x9E3779B1u) >> 19;
        while (g_name_index[bucket]) bucket = (bucket + 1) & 8191;
        g_name_index[bucket] = (uint16_t)g_name_n;'''),
    ]
    for old, new in edits:
        if source.count(old) != 1:
            raise ValueError('Pinned native32 patch anchor mismatch: ' + old[:65])
        source = source.replace(old, new, 1)
    start = source.index('static recomp_func_t dispatch_find(uint32_t va) {')
    end = source.index('\n}\n', start) + 3
    source = source[:start] + '''extern recomp_func_t homm5_pc_dispatch(uint32_t va);
static recomp_func_t dispatch_find(uint32_t va) { return homm5_pc_dispatch(va); }
''' + source[end:]
    start = source.index('static int data_section_code(uint32_t va) {')
    end = source.index('\n}\n', start) + 3
    source = source[:start] + '''/* H5 is entirely statically compiled; guest data never becomes executable. */
static int data_section_code(uint32_t va) { (void)va; return 0; }
''' + source[end:]
    return source + '''
uint32_t homm5_pc_shim_address(const char *name)
{
    if ((uintptr_t)name < 0x10000u) return 0;
    for (int i = 0; i < g_nshims; ++i) if (!strcmp(name, g_shims[i].name)) return g_shims[i].va;
    return 0;
}
/* Internal lifted CRT throws reach RaiseException instead of the imported
 * _CxxThrowException built-in. Keep them on the same guest frame chain. */
void homm5_pc_raise_exception(void)
{
    uint32_t *args = (uint32_t *)(uintptr_t)(g_esp + 4);
    if (args[0] != 0xE06D7363u) { shim_RaiseException(); return; }
    uint32_t parameters[3]; SIZE_T got = 0;
    if (args[1] != EXCEPTION_NONCONTINUABLE || args[2] != 3 || !args[3] ||
        !ReadProcessMemory(GetCurrentProcess(), (void *)(uintptr_t)args[3], parameters, sizeof parameters, &got) ||
        got != sizeof parameters || (parameters[0] != EH_MAGIC_VC6 && parameters[0] != EH_MAGIC_VC7 && parameters[0] != EH_MAGIC_VC8)) {
        fprintf(stderr, "[pc-eh] Unsupported C++ RaiseException record\\n"); exit(90);
    }
    uint32_t object = parameters[1], info = parameters[2];
    if (!info) object = t_cur_obj, info = t_cur_info;
    if (!info) { fprintf(stderr, "[pc-eh] Missing throw metadata\\n"); exit(90); }
    g_esp += 4;
    dispatch(object, info);
    fprintf(stderr, "[pc-eh] Uncaught C++ exception %08X/%08X\\n", object, info); exit(90);
}
'''


def prepare(output):
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Private Windows runtime must remain under build/')
    vendor = ROOT / 'reference/pcrecomp/runtime/native32'
    raw = (vendor / 'native32.c').read_bytes()
    if digest(raw) != VENDOR_SHA:
        raise ValueError('Pinned native32 vendor SHA mismatch')
    inputs = {str(ROOT / 'android/runtime/recomp_types.h'): (ROOT / 'android/runtime/recomp_types.h').read_bytes(),
              str(vendor / 'native32.c'): raw}
    outputs = {'recomp_types.h': platform_header(inputs[str(ROOT / 'android/runtime/recomp_types.h')].decode().replace('\r\n', '\n')).encode(),
               'native32.c': platform_runtime(raw.decode().replace('\r\n', '\n')).encode()}
    for name in ('native32.h', 'eh32.c', 'x87crt.c'):
        path = vendor / name
        inputs[str(path)] = path.read_bytes()
        outputs[name] = path.read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        path = output / name
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    receipt = dict(inputs={name: digest(data) for name, data in inputs.items()},
                   outputs={name: digest(data) for name, data in outputs.items()},
                   adaptations=['Win32 intrinsic RDTSC', 'BASE0 from compiler', 'complete H5 register snapshots',
                                'per-thread H5 static TLS initializer', 'shipped CRT aliases', 'guest C++ throw routing',
                                'no native guest data/code fallback', 'thread-local name hit/miss cache with append invalidation and bounded name index',
                                'optional logical-array x87 window with exact inactive slots',
                                'machine kept across non-blocking native calls unless contended'])
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if any(Path(name).read_bytes() != data for name, data in inputs.items()):
        raise ValueError('Input changed during Windows runtime preparation')
    return receipt


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/windows-x86/runtime')
    print(json.dumps(prepare(parser.parse_args().output), indent=2))
