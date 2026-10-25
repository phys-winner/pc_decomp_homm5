/* H5 native32 host. Every game module remains statically dispatched and NX;
 * Windows supplies the actual Win32/D3D9/DirectSound/DirectInput interfaces. */
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "native32.h"
#include "recomp_trace.h"

#ifndef PC_DEFAULT_GAME_BIN
#define PC_DEFAULT_GAME_BIN "build/windows-game/bin"
#endif
#ifndef PC_DEFAULT_PROFILE
#define PC_DEFAULT_PROFILE "build/windows-profile"
#endif
void void_lift_trap(uint32_t address, const char *instruction);

typedef struct {
    const char *name, *image;
    uint32_t base, span, entry;
    int exe, state, refs;
} pc_module;
#include "pc_modules.h"

static char game_bin[MAX_PATH], profile_root[MAX_PATH], command_line[2048];
static wchar_t profile_root_w[MAX_PATH], command_line_w[2048];
static int detaching;
static pc_module *attach_order[PC_MODULE_COUNT];
static unsigned attach_count;
extern void homm5_pc_raise_exception(void);
extern uint32_t homm5_pc_shim_address(const char *name);
extern uint32_t g_native_target;
#ifdef PC_PGO_GENERATE
int __llvm_profile_dump(void);
#endif

/* Generated code addresses guest memory as g_guest_mem + VA (RECOMP_GUEST_PROVENANCE
 * in recomp_types.h): an absolute symbol at 0, since guest VAs are host addresses. */
__asm__(".globl _g_guest_mem\n\t.set _g_guest_mem, 0");

typedef struct { uint32_t va; recomp_func_t fn; } pc_slot;
static pc_slot *dispatch_slots;
static pc_slot resolve_cache[4096];
#define DISPATCH_MASK ((1u << 18) - 1u)
static void dispatch_init(void)
{
    if (recomp_dispatch_count * 2u > DISPATCH_MASK + 1u) void_lift_trap(0, "dispatch capacity exceeded");
    dispatch_slots = (pc_slot *)calloc(DISPATCH_MASK + 1u, sizeof *dispatch_slots);
    if (!dispatch_slots) void_lift_trap(0, "dispatch allocation failed");
    for (uint32_t k = 0; k < recomp_dispatch_count; ++k) {
        uint32_t va = recomp_dispatch_table[k].address;
        if (!va || (k && va <= recomp_dispatch_table[k - 1].address)) void_lift_trap(va, "dispatch not strictly sorted");
        uint32_t slot = ((va * 0x9E3779B1u) >> 7) & DISPATCH_MASK;
        while (dispatch_slots[slot].va) slot = (slot + 1) & DISPATCH_MASK;
        dispatch_slots[slot].va = va; dispatch_slots[slot].fn = recomp_dispatch_table[k].func;
    }
}
recomp_func_t homm5_pc_dispatch(uint32_t va)
{
    if (!va || !dispatch_slots) return NULL;
    for (uint32_t slot = ((va * 0x9E3779B1u) >> 7) & DISPATCH_MASK;; slot = (slot + 1) & DISPATCH_MASK) {
        if (dispatch_slots[slot].va == va) return dispatch_slots[slot].fn;
        if (!dispatch_slots[slot].va) return NULL;
    }
}

void void_lift_trap(uint32_t address, const char *instruction)
{
    fprintf(stderr, "[pc-trap] %08X %s; current=%08X thread=%lu\n", address, instruction, g_cur_func, GetCurrentThreadId());
    native32_dump_icalls(32);
    recomp_dump_trace(instruction);
    fflush(stderr);
    ExitProcess(91);
}

/* Protocol-validation builds (RECOMP_PROTOCOL_CHECK) report every call site
 * where a callee changed a callee-saved register its summary says it keeps. */
void recomp_protocol_violation(uint32_t site, uint32_t target, uint32_t regs)
{
    static uint32_t seen[4096];
    static unsigned count;
    uint32_t key = site ^ (regs << 24);
    for (unsigned i = 0; i < count; ++i)
        if (seen[i] == key) return;
    if (count < sizeof seen / sizeof seen[0]) seen[count++] = key;
    fprintf(stderr, "[pc-protocol] site %08X target %08X regs %02X thread=%lu\n", site, target, regs, GetCurrentThreadId());
    fflush(stderr);
}

/* The same builds report every function whose x87 rewrite left the global
 * stack window at a different depth than its summary promises. */
void recomp_x87_violation(uint32_t va, int found, int expected)
{
    static uint32_t seen[4096];
    static unsigned count;
    for (unsigned i = 0; i < count; ++i)
        if (seen[i] == va) return;
    if (count < sizeof seen / sizeof seen[0]) seen[count++] = va;
    fprintf(stderr, "[pc-x87] %08X net %d expected %d thread=%lu\n", va, found, expected, GetCurrentThreadId());
    fflush(stderr);
}

void void_cpuid(uint32_t leaf, uint32_t subleaf)
{
    int result[4];
    __cpuidex(result, (int)leaf, (int)subleaf);
    g_eax = (uint32_t)result[0]; g_ebx = (uint32_t)result[1];
    g_ecx = (uint32_t)result[2]; g_edx = (uint32_t)result[3];
}

/* Exact current Android helper, compiled in the PC model too. */
void void_fpu_remainder(uint32_t address, int nearest)
{
    if (g_fp_top < 2 || g_fp_top > 8 || (nearest != 0 && nearest != 1))
        void_lift_trap(address, "unsupported FPREM stack/control word");
    double x = g_st[0], y = g_st[1];
    uint16_t status = 0;
    if (isnan(x) || isnan(y) || isinf(x) || y == 0.0) {
        uint64_t indefinite = 0xFFF8000000000000ull;
        memcpy(&g_st[0], &indefinite, sizeof indefinite);
        g_st_i64[0] = 0; void_fpu_cmp = (int)0x10000u; return;
    }
    if (isinf(y) || x == 0.0) {
        g_st_i64[0] = 0; void_fpu_cmp = (int)0x10000u; return;
    }
    int ex, ey; frexp(x, &ex); frexp(y, &ey);
    if (ex - ey < 64) {
        double rt = fmod(x, y), r8 = fmod(x, 8.0 * y);
        if (isinf(8.0 * y)) r8 = x;
        uint32_t q = (uint32_t)nearbyint(fabs((r8 - rt) / y)) & 7u;
        double r = rt;
        if (nearest) { double rn = remainder(x, y); if (rn != rt) q = (q + 1u) & 7u; r = rn; }
        if (q & 1u) status |= 0x0200u;
        if (q & 2u) status |= 0x4000u;
        if (q & 4u) status |= 0x0100u;
        g_st[0] = r;
    } else {
        int n = 32 + ((ex - ey) & 31);
        g_st[0] = fmod(x, ldexp(y, ex - ey - n)); status |= 0x0400u;
    }
    g_st_i64[0] = 0; void_fpu_cmp = (int)(0x10000u | status);
}

/* The EXE is the only image with static TLS: nine initialized bytes, no TLS
 * callbacks and no zero fill. Its original index is assigned slot0 in each
 * private guest TIB; Windows' own TEB and dynamic TLS remain untouched. */
void homm5_pc_thread_init(uint32_t tib)
{
    if (MEM32(0x010E5674u) != 0) void_lift_trap(0x010E5674u, "unexpected H5 TLS index");
    MEM32(tib + 0x2Cu) = tib + 0x100u;
    MEM32(tib + 0x100u) = tib + 0x200u;
    memcpy((void *)(uintptr_t)(tib + 0x200u), (void *)(uintptr_t)0x010EA000u, 9);
}

static const char *filename(const char *name)
{
    const char *part = name;
    if (name) for (; *name; ++name) if (*name == '/' || *name == '\\') part = name + 1;
    return part;
}
static pc_module *module_name(const char *name)
{
    if (!name || !*name) return &pc_modules[0];
    name = filename(name);
    if (!_stricmp(name, "msvcrt.dll") || !_stricmp(name, "crtdll.dll")) name = "msvcr71.dll";
    for (unsigned i = 0; i < PC_MODULE_COUNT; ++i) if (!_stricmp(name, pc_modules[i].name)) return &pc_modules[i];
    return NULL;
}
static pc_module *module_handle(uint32_t handle)
{
    if (!handle) return &pc_modules[0];
    for (unsigned i = 0; i < PC_MODULE_COUNT; ++i) if (handle == pc_modules[i].base) return &pc_modules[i];
    return NULL;
}
static pc_module *wide_module(const wchar_t *name)
{
    if (!name) return &pc_modules[0];
    char path[MAX_PATH];
    if (!WideCharToMultiByte(CP_ACP, 0, name, -1, path, sizeof path, NULL, NULL)) return NULL;
    return module_name(path);
}

static uint32_t call_guest(uint32_t va, unsigned count, const uint32_t *args)
{
    mach_enter();
    uint32_t esp = g_esp, seh = MEM32(g_fs_base), caller = g_cur_func;
    for (unsigned i = count; i; --i) PUSH32(g_esp, args[i - 1]);
    PUSH32(g_esp, RECOMP_RETADDR);
    recomp_func_t body = recomp_lookup(va);
    if (!body) void_lift_trap(va, "entry not statically compiled");
    body();
    uint32_t result = g_eax;
    if (g_esp != esp || MEM32(g_fs_base) != seh) void_lift_trap(va, "entry stack/SEH imbalance");
    g_cur_func = caller;
    mach_leave();
    return result;
}
static int attach(pc_module *module)
{
    if (module->exe || module->state == 2 || module->state == 1) { ++module->refs; return 1; }
    if (module->state != 0) return 0;
    module->state = 1;
    IMAGE_DOS_HEADER *dos = (void *)(uintptr_t)module->base;
    IMAGE_NT_HEADERS32 *nt = (void *)(uintptr_t)(module->base + dos->e_lfanew);
    uint32_t imports = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (imports) {
        IMAGE_IMPORT_DESCRIPTOR *entry = (void *)(uintptr_t)(module->base + imports);
        for (; entry->Name; ++entry) {
            pc_module *dependency = module_name((char *)(uintptr_t)(module->base + entry->Name));
            if (dependency && !attach(dependency)) return 0;
        }
    }
    uint32_t args[] = {module->base, DLL_PROCESS_ATTACH, 0};
    uint32_t result = call_guest(module->entry, 3, args);
    fprintf(stderr, "[pc] lifted attach %s %08X result=%u\n", module->name, module->entry, result);
    if (!result) return 0;
    module->state = 2; ++module->refs;
    if (attach_count == PC_MODULE_COUNT) void_lift_trap(module->base, "attach-order capacity exceeded");
    attach_order[attach_count++] = module;
    return 1;
}
static void detach_all(void)
{
    if (detaching) return;
    detaching = 1;
    while (attach_count) {
        pc_module *module = attach_order[--attach_count];
        if (module->state != 2) continue;
        module->state = 3;
        uint32_t args[] = {module->base, DLL_PROCESS_DETACH, 1};
        call_guest(module->entry, 3, args);
    }
}

static void get_module_a(void) { pc_module *m = module_name((char *)(uintptr_t)MEM32(g_esp + 4)); g_eax = m ? m->base : (uint32_t)(uintptr_t)GetModuleHandleA((char *)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }
static void get_module_w(void) { pc_module *m = wide_module((wchar_t *)(uintptr_t)MEM32(g_esp + 4)); g_eax = m ? m->base : (uint32_t)(uintptr_t)GetModuleHandleW((wchar_t *)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }
static void load_module_a(void) { pc_module *m = module_name((char *)(uintptr_t)MEM32(g_esp + 4)); g_eax = m ? (attach(m) ? m->base : 0) : (uint32_t)(uintptr_t)LoadLibraryA((char *)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }
static void load_module_w(void) { pc_module *m = wide_module((wchar_t *)(uintptr_t)MEM32(g_esp + 4)); g_eax = m ? (attach(m) ? m->base : 0) : (uint32_t)(uintptr_t)LoadLibraryW((wchar_t *)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }
static void free_module(void) { pc_module *m = module_handle(MEM32(g_esp + 4)); g_eax = m ? 1 : FreeLibrary((HMODULE)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }
static void proc_address(void)
{
    pc_module *m = module_handle(MEM32(g_esp + 4));
    const char *name = (char *)(uintptr_t)MEM32(g_esp + 8);
    g_eax = m ? native32_export(m->base, name) : homm5_pc_shim_address(name);
    if (!m && !g_eax) g_eax = (uint32_t)(uintptr_t)GetProcAddress((HMODULE)(uintptr_t)MEM32(g_esp + 4), name);
    g_esp += 12;
}
static void module_filename_a(void)
{
    pc_module *m = module_handle(MEM32(g_esp + 4)); char *out = (char *)(uintptr_t)MEM32(g_esp + 8); uint32_t size = MEM32(g_esp + 12);
    if (!m) g_eax = GetModuleFileNameA((HMODULE)(uintptr_t)MEM32(g_esp + 4), out, size);
    else { char path[MAX_PATH]; snprintf(path, sizeof path, "%s\\%s", game_bin, filename(m->image)); g_eax = (uint32_t)strlen(path); if (size) { strncpy(out, path, size); if (g_eax >= size) { out[size - 1] = 0; g_eax = size; SetLastError(ERROR_INSUFFICIENT_BUFFER); } } }
    g_esp += 16;
}
static void module_filename_w(void)
{
    pc_module *m = module_handle(MEM32(g_esp + 4)); wchar_t *out = (wchar_t *)(uintptr_t)MEM32(g_esp + 8); uint32_t size = MEM32(g_esp + 12);
    if (!m) g_eax = GetModuleFileNameW((HMODULE)(uintptr_t)MEM32(g_esp + 4), out, size);
    else { char path[MAX_PATH]; wchar_t wide[MAX_PATH]; snprintf(path, sizeof path, "%s\\%s", game_bin, filename(m->image)); MultiByteToWideChar(CP_ACP, 0, path, -1, wide, MAX_PATH); g_eax = (uint32_t)wcslen(wide); if (size) { wcsncpy(out, wide, size); if (g_eax >= size) { out[size - 1] = 0; g_eax = size; SetLastError(ERROR_INSUFFICIENT_BUFFER); } } }
    g_esp += 16;
}
static void folder_a(void)
{
    int folder = (int)MEM32(g_esp + 8) & 0xFF; char *out = (char *)(uintptr_t)MEM32(g_esp + 20);
    if (folder == CSIDL_PERSONAL || folder == CSIDL_APPDATA || folder == CSIDL_COMMON_APPDATA || folder == CSIDL_LOCAL_APPDATA) { snprintf(out, MAX_PATH, "%s\\%s", profile_root, folder == CSIDL_PERSONAL ? "Documents" : "AppData"); g_eax = S_OK; }
    else g_eax = SHGetFolderPathA((HWND)(uintptr_t)MEM32(g_esp + 4), (int)MEM32(g_esp + 8), (HANDLE)(uintptr_t)MEM32(g_esp + 12), MEM32(g_esp + 16), out);
    g_esp += 24;
}
static void folder_w(void)
{
    int folder = (int)MEM32(g_esp + 8) & 0xFF; wchar_t *out = (wchar_t *)(uintptr_t)MEM32(g_esp + 20);
    if (folder == CSIDL_PERSONAL || folder == CSIDL_APPDATA || folder == CSIDL_COMMON_APPDATA || folder == CSIDL_LOCAL_APPDATA) { _snwprintf(out, MAX_PATH, L"%ls\\%ls", profile_root_w, folder == CSIDL_PERSONAL ? L"Documents" : L"AppData"); g_eax = S_OK; }
    else g_eax = SHGetFolderPathW((HWND)(uintptr_t)MEM32(g_esp + 4), (int)MEM32(g_esp + 8), (HANDLE)(uintptr_t)MEM32(g_esp + 12), MEM32(g_esp + 16), out);
    g_esp += 24;
}
static void command_a(void) { g_eax = (uint32_t)(uintptr_t)command_line; g_esp += 4; }
static void command_w(void) { g_eax = (uint32_t)(uintptr_t)command_line_w; g_esp += 4; }
static void exit_process(void)
{
    uint32_t result = MEM32(g_esp + 4);
    detach_all();
#ifdef PC_PGO_GENERATE
    /* ExitProcess bypasses the profiling runtime's CRT exit handler. */
    if (__llvm_profile_dump()) fprintf(stderr, "[pc-pgo] profile dump failed\n");
#endif
    ExitProcess(result);
}
static void thread_get_error(void) { g_eax = GetLastError(); g_esp += 4; }
static void thread_set_error(void) { DWORD error = MEM32(g_esp + 4); g_esp += 8; SetLastError(error); }
static void thread_tls_value(void) { g_eax = (uint32_t)(uintptr_t)TlsGetValue(MEM32(g_esp + 4)); g_esp += 8; }
static void disable_thread_calls(void) { g_eax = module_handle(MEM32(g_esp + 4)) ? 1 : DisableThreadLibraryCalls((HMODULE)(uintptr_t)MEM32(g_esp + 4)); g_esp += 8; }

static native32_shim_t host_shims[] = {
    {"GetModuleHandleA", get_module_a}, {"GetModuleHandleW", get_module_w},
    {"LoadLibraryA", load_module_a}, {"LoadLibraryW", load_module_w},
    {"FreeLibrary", free_module}, {"GetProcAddress", proc_address},
    {"GetModuleFileNameA", module_filename_a}, {"GetModuleFileNameW", module_filename_w},
    {"SHGetFolderPathA", folder_a}, {"SHGetFolderPathW", folder_w},
    {"GetCommandLineA", command_a}, {"GetCommandLineW", command_w},
    {"ExitProcess", exit_process}, {"GetLastError", thread_get_error}, {"SetLastError", thread_set_error},
    {"TlsGetValue", thread_tls_value}, {"RaiseException", homm5_pc_raise_exception},
    {"DisableThreadLibraryCalls", disable_thread_calls}
};

recomp_func_t recomp_lookup_manual(uint32_t va)
{
    if (va == (uint32_t)(uintptr_t)GetLastError) return thread_get_error;
    if (va == (uint32_t)(uintptr_t)SetLastError) return thread_set_error;
    if (va == (uint32_t)(uintptr_t)TlsGetValue) return thread_tls_value;
    return NULL;
}
/* Keep the existing cache hit free of miss-path saved registers. */
static __attribute__((noinline)) recomp_func_t pc_resolve_slow(uint32_t va)
{
    pc_slot *cached = &resolve_cache[(va * 0x9E3779B1u) >> 20];
    recomp_func_t body = recomp_lookup_manual(va);
    if (!body) body = recomp_lookup(va);
    if (!body && !native32_in_guest(va)) body = recomp_lookup_import(va);
    if (!body) void_lift_trap(va, "unresolved static control-flow target");
    cached->va = va; cached->fn = body;
    return body;
}
recomp_func_t void_resolve(uint32_t va)
{
    pc_slot *cached = &resolve_cache[(va * 0x9E3779B1u) >> 20];
    if (va && cached->va == va) {
        /* native_bridge reads this target before releasing the machine.
         * Publish it even on a cache hit; lifted/shim entries ignore it. */
        g_native_target = va;
        return cached->fn;
    }
    return pc_resolve_slow(va);
}

static LONG WINAPI fault(EXCEPTION_POINTERS *exception)
{
    fprintf(stderr, "[pc-fault] exception=%08lX pc=%08lX guest=%08X\n", exception->ExceptionRecord->ExceptionCode,
            exception->ContextRecord->Eip, g_cur_func);
    native32_dump_icalls(24); recomp_dump_trace("Windows exception");
    return EXCEPTION_EXECUTE_HANDLER;
}
static void verify_guest_nx(void)
{
    for (unsigned i = 0; i < PC_MODULE_COUNT; ++i) {
        uint32_t cursor = pc_modules[i].base, end = cursor + pc_modules[i].span;
        while (cursor < end) {
            MEMORY_BASIC_INFORMATION region;
            if (!VirtualQuery((void *)(uintptr_t)cursor, &region, sizeof region) ||
                region.State != MEM_COMMIT || (region.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)))
                void_lift_trap(cursor, "guest image is not committed NX data");
            uintptr_t next = (uintptr_t)region.BaseAddress + region.RegionSize;
            if (next <= cursor) void_lift_trap(cursor, "invalid guest memory region");
            cursor = next < end ? (uint32_t)next : end;
        }
    }
}
static DWORD WINAPI run_game(void *parameter)
{
    int selftest = (int)(uintptr_t)parameter;
    for (unsigned i = 1; i < PC_MODULE_COUNT; ++i) if (!attach(&pc_modules[i])) return 70;
    verify_guest_nx();
    if (selftest) {
        mach_enter();
        uint32_t tls = MEM32(MEM32(g_fs_base + 0x2C));
        if (memcmp((void *)(uintptr_t)tls, (void *)(uintptr_t)0x010EA000, 9)) void_lift_trap(tls, "TLS template mismatch");
        mach_leave();
        fprintf(stderr, "[pc-selftest] all9 images NX, imports bound, DLL attach and game static TLS PASS\n");
        detach_all(); return 0;
    }
    return call_guest(pc_modules[0].entry, 0, NULL);
}

int main(int argc, char **argv)
{
    const char *bin = PC_DEFAULT_GAME_BIN;
    const char *profile = PC_DEFAULT_PROFILE, *arguments = "";
    int selftest = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--game-bin") && i + 1 < argc) bin = argv[++i];
        else if (!strcmp(argv[i], "--profile") && i + 1 < argc) profile = argv[++i];
        else if (!strcmp(argv[i], "--game-args") && i + 1 < argc) arguments = argv[++i];
        else if (!strcmp(argv[i], "--selftest")) selftest = 1;
        else if (!strcmp(argv[i], "--trace-native")) native32_trace_native = 1;
        else if (!strcmp(argv[i], "--trace-callbacks")) native32_trace_callbacks = 1;
        else { fprintf(stderr, "Unknown PC host option: %s\n", argv[i]); return 64; }
    }
    setvbuf(stderr, NULL, _IONBF, 0);
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    SetUnhandledExceptionFilter(fault);
    DWORD bin_size = GetFullPathNameA(bin, MAX_PATH, game_bin, NULL), profile_size = GetFullPathNameA(profile, MAX_PATH, profile_root, NULL);
    if (!bin_size || bin_size >= MAX_PATH - 32 || !profile_size || profile_size >= MAX_PATH - 12) return 65;
    if (!MultiByteToWideChar(CP_ACP, 0, profile_root, -1, profile_root_w, MAX_PATH)) return 65;
    int command_size = snprintf(command_line, sizeof command_line, "\"%s\\H5_Game.exe\" %s", game_bin, arguments);
    if (command_size < 0 || command_size >= sizeof command_line ||
        !MultiByteToWideChar(CP_ACP, 0, command_line, -1, command_line_w, 2048)) return 65;
    if (!SetEnvironmentVariableA("USERPROFILE", profile_root)) return 65;
    /* The hold-image parent relaunches us with the same argv/current dir.
     * Resolve relative profile paths before selecting the game directory. */
    native32_hold_image(pc_modules[0].image, pc_modules[0].base);
    if (!SetCurrentDirectoryA(game_bin) || !SetDllDirectoryA(game_bin)) return 65;
    native32_init();
    dispatch_init();
    for (unsigned i = 0; i < PC_MODULE_COUNT; ++i) {
        pc_module *module = &pc_modules[i];
        if (native32_map(module->image, module->base) != module->span) return 66;
        DWORD old;
        if (!VirtualProtect((void *)(uintptr_t)module->base, module->span, PAGE_READWRITE, &old)) return 66;
        fprintf(stderr, "[pc] mapped statically lifted %s @%08X span%X NX\n", module->name, module->base, module->span);
    }
    IMAGE_DOS_HEADER *dos = (void *)(uintptr_t)0x400000;
    IMAGE_NT_HEADERS32 *nt = (void *)(uintptr_t)(0x400000 + dos->e_lfanew);
    IMAGE_DATA_DIRECTORY td = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS];
    IMAGE_TLS_DIRECTORY32 *tls = (void *)(uintptr_t)(0x400000 + td.VirtualAddress);
    if (td.Size != 24 || tls->StartAddressOfRawData != 0x010EA000 || tls->EndAddressOfRawData != 0x010EA009 ||
        tls->AddressOfIndex != 0x010E5674 || tls->SizeOfZeroFill || MEM32(tls->AddressOfCallBacks)) return 67;
    MEM32(tls->AddressOfIndex) = 0;
    int unresolved = 0;
    for (unsigned i = 0; i < PC_MODULE_COUNT; ++i)
        unresolved += native32_bind(pc_modules[i].base, host_shims, sizeof host_shims / sizeof *host_shims);
    if (unresolved) return 68;
    verify_guest_nx();
    fprintf(stderr, "[pc] STATIC mode: all9 game modules lifted; actual Win32 graphics/audio; private profile=%s\n", profile_root);
    HANDLE thread = CreateThread(NULL, 8 << 20, run_game, (void *)(uintptr_t)selftest, STACK_SIZE_PARAM_IS_A_RESERVATION, NULL);
    if (!thread) return 69;
    WaitForSingleObject(thread, INFINITE);
    DWORD result; GetExitCodeThread(thread, &result); CloseHandle(thread);
#ifdef PC_PGO_GENERATE
    if (__llvm_profile_dump()) fprintf(stderr, "[pc-pgo] profile dump failed\n");
#endif
    return (int)result;
}
