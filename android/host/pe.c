/* Module manager: maps the lifted PE images at their (pre-based) addresses,
 * binds imports to lifted exports or host shims, runs the lifted DllMain on
 * LoadLibrary/FreeLibrary with Windows' reference counting, and answers the
 * module APIs. System DLLs are pseudo-modules: a header page and a name, with
 * GetProcAddress resolving to host shims. */
#define _GNU_SOURCE
#include "host.h"
#include <ctype.h>
#include <errno.h>
#include <strings.h>
#include <unistd.h>

#define DLL_PROCESS_DETACH_ 0
#define DLL_PROCESS_ATTACH_ 1

enum { MOD_LIFTED_EXE, MOD_LIFTED_DLL, MOD_PSEUDO };
enum { ST_UNMAPPED, ST_MAPPED, ST_INITIALIZING, ST_READY, ST_DETACHING, ST_DETACHED };

struct void_module {
    char name[64];            /* file name as Windows reports it */
    char win_path[260];       /* GetModuleFileName result */
    int kind;
    int state;
    uint32_t base, size, entry;
    uint32_t refs;
    uint32_t attach_events, detach_events;
    uint8_t *pristine;        /* image bytes after binding, for reload after detach */
    int deps[16];             /* lifted modules this one imports statically */
    int dep_count;
    int holds_deps;
};

#define MAX_MODULES 64
static void_module modules[MAX_MODULES];
static int module_count;
static pthread_mutex_t loader_lock = PTHREAD_MUTEX_INITIALIZER;

/* Lifted images, in the Windows build's order and bases. The Windows module
 * name is what the guest asks for; the file is the pre-based private copy. */
typedef struct { const char *name; const char *file; uint32_t base; int exe; int optional; } lifted_spec;
static const lifted_spec lifted[] = {
#ifdef HOMM5_MODULES_INCLUDE
#include HOMM5_MODULES_INCLUDE
#else
#include "modules.inc"
#endif
};

static const char *pseudo_names[] = {
    "kernel32.dll", "ntdll.dll", "kernelbase.dll", "user32.dll", "gdi32.dll", "advapi32.dll",
    "shell32.dll", "shlwapi.dll", "ole32.dll", "oleaut32.dll", "winmm.dll", "dbghelp.dll",
    "d3d9.dll", "d3dx9_36.dll", "d3dx9_25.dll", "dinput8.dll", "dsound.dll", "physxloader.dll", "msacm32.dll",
    "ws2_32.dll", "wsock32.dll", "setupapi.dll", "iphlpapi.dll", "version.dll", "imm32.dll",
    "comctl32.dll", "comdlg32.dll", "uxtheme.dll", "dwmapi.dll", "xinput1_3.dll",
    "rpcrt4.dll", "wininet.dll", "oleacc.dll", "winspool.drv",
};

#ifndef HOMM5_BIN
#define HOMM5_BIN "bin"
#endif
#define VIRTUAL_BIN "C:\\Games\\HeroesV\\" HOMM5_BIN
static uint32_t exe_base;

/* ------------------------------------------------------------ PE helpers */
static uint32_t nt_header(uint32_t base) { return base + MEM32(base + 0x3C); }
static uint32_t dir_rva(uint32_t base, int index) { return MEM32(nt_header(base) + 0x78 + 8 * (uint32_t)index); }
static uint32_t dir_size(uint32_t base, int index) { return MEM32(nt_header(base) + 0x7C + 8 * (uint32_t)index); }

static int name_matches(const char *want, const char *module_name)
{
    const char *file = want;
    for (const char *p = want; *p; ++p) if (*p == '\\' || *p == '/') file = p + 1;
    if (!strcasecmp(file, module_name)) return 1;
    /* "Engine" matches "Engine.dll": Windows appends .dll to a bare name. */
    size_t stem = strlen(module_name);
    const char *dot = strrchr(module_name, '.');
    if (dot && !strcasecmp(dot, ".dll")) stem = (size_t)(dot - module_name);
    return strlen(file) == stem && !strncasecmp(file, module_name, stem) && !strchr(file, '.');
}

static void_module *find_by_name(const char *name)
{
    /* FMOD's 47 MSVCRT imports (including data) exist in the shipped VC7.1 CRT. */
    if (name_matches(name, "msvcrt.dll") || name_matches(name, "crtdll.dll")) name = "msvcr71.dll";
    for (int i = 0; i < module_count; ++i) if (name_matches(name, modules[i].name)) return &modules[i];
    return NULL;
}

static void_module *find_by_handle(uint32_t handle)
{
    for (int i = 0; i < module_count; ++i) if (modules[i].base == handle) return &modules[i];
    return NULL;
}

uint32_t void_module_exe_base(void) { return exe_base; }

/* -------------------------------------------------------------- exports */
static uint32_t export_lookup(uint32_t base, uint32_t name_or_ordinal)
{
    uint32_t rva = dir_rva(base, 0), size = dir_size(base, 0);
    if (!rva || !size) return 0;
    uint32_t dir = base + rva;
    uint32_t ordinal_base = MEM32(dir + 16), functions = MEM32(dir + 20), names = MEM32(dir + 24);
    uint32_t address_table = base + MEM32(dir + 28), name_table = base + MEM32(dir + 32);
    uint32_t ordinal_table = base + MEM32(dir + 36);
    uint32_t index = 0xFFFFFFFFu;
    if (name_or_ordinal < 0x10000u) {
        if (name_or_ordinal >= ordinal_base && name_or_ordinal - ordinal_base < functions)
            index = name_or_ordinal - ordinal_base;
    } else {
        const char *want = (const char *)GPTR(name_or_ordinal);
        for (uint32_t i = 0; i < names; ++i) {
            if (!strcmp((const char *)GPTR(base + MEM32(name_table + 4 * i)), want)) {
                index = MEM16(ordinal_table + 2 * i);
                break;
            }
        }
    }
    if (index == 0xFFFFFFFFu || index >= functions) return 0;
    uint32_t function = MEM32(address_table + 4 * index);
    if (!function) return 0;
    if (function >= rva && function < rva + size) {
        void_log("[void] forwarded export %s ignored", (const char *)GPTR(base + function));
        return 0;
    }
    return base + function;
}

/* ---------------------------------------------------------------- shims */
extern const void_shim __start_void_shims[], __stop_void_shims[];

const void_shim *void_shim_find(const char *dll, const char *name, uint32_t ordinal)
{
    for (const void_shim *s = __start_void_shims; s < __stop_void_shims; ++s) {
        if (strcasecmp(s->dll, dll)) continue;
        if (name && s->name && !strcmp(s->name, name)) return s;
        if (!name && ordinal && s->ordinal == ordinal) return s;
    }
    return NULL;
}

typedef struct { char key[96]; uint32_t va; } thunk_entry;
static thunk_entry *thunk_map;
static int thunk_map_count, thunk_map_cap;

static int missing_count;

/* Production builds keep no indirect-call trace, so each missing import gets
 * its own stub: the stub's index names the import in the trap. */
#define MISSING_STUBS 250
static const char *missing_names[MISSING_STUBS];
static uint32_t missing_vas[MISSING_STUBS];

static void missing_import_called(unsigned index)
{
    const char *name = index < MISSING_STUBS ? missing_names[index] : NULL;
    void_log("[void] unimplemented import %s called", name ? name : "?");
    void_lift_trap(index < MISSING_STUBS ? missing_vas[index] : 0, "unimplemented import");
}

#define MISSING_STUB(i) static void missing_stub_##i(void) { missing_import_called(i); }
#define MISSING_STUB10(r) MISSING_STUB(r##0) MISSING_STUB(r##1) MISSING_STUB(r##2) MISSING_STUB(r##3) \
    MISSING_STUB(r##4) MISSING_STUB(r##5) MISSING_STUB(r##6) MISSING_STUB(r##7) MISSING_STUB(r##8) MISSING_STUB(r##9)
MISSING_STUB(0) MISSING_STUB(1) MISSING_STUB(2) MISSING_STUB(3) MISSING_STUB(4)
MISSING_STUB(5) MISSING_STUB(6) MISSING_STUB(7) MISSING_STUB(8) MISSING_STUB(9)
MISSING_STUB10(1) MISSING_STUB10(2) MISSING_STUB10(3) MISSING_STUB10(4) MISSING_STUB10(5) MISSING_STUB10(6)
MISSING_STUB10(7) MISSING_STUB10(8) MISSING_STUB10(9) MISSING_STUB10(10) MISSING_STUB10(11) MISSING_STUB10(12)
MISSING_STUB10(13) MISSING_STUB10(14) MISSING_STUB10(15) MISSING_STUB10(16) MISSING_STUB10(17) MISSING_STUB10(18)
MISSING_STUB10(19) MISSING_STUB10(20) MISSING_STUB10(21) MISSING_STUB10(22) MISSING_STUB10(23) MISSING_STUB10(24)

#define MISSING_REF(i) missing_stub_##i,
#define MISSING_REF10(r) MISSING_REF(r##0) MISSING_REF(r##1) MISSING_REF(r##2) MISSING_REF(r##3) MISSING_REF(r##4) \
    MISSING_REF(r##5) MISSING_REF(r##6) MISSING_REF(r##7) MISSING_REF(r##8) MISSING_REF(r##9)
static void (*const missing_stubs[MISSING_STUBS])(void) = {
    MISSING_REF(0) MISSING_REF(1) MISSING_REF(2) MISSING_REF(3) MISSING_REF(4)
    MISSING_REF(5) MISSING_REF(6) MISSING_REF(7) MISSING_REF(8) MISSING_REF(9)
    MISSING_REF10(1) MISSING_REF10(2) MISSING_REF10(3) MISSING_REF10(4) MISSING_REF10(5) MISSING_REF10(6)
    MISSING_REF10(7) MISSING_REF10(8) MISSING_REF10(9) MISSING_REF10(10) MISSING_REF10(11) MISSING_REF10(12)
    MISSING_REF10(13) MISSING_REF10(14) MISSING_REF10(15) MISSING_REF10(16) MISSING_REF10(17) MISSING_REF10(18)
    MISSING_REF10(19) MISSING_REF10(20) MISSING_REF10(21) MISSING_REF10(22) MISSING_REF10(23) MISSING_REF10(24)
};

/* Beyond the named stubs the last indirect-call record (diagnostic builds) names it. */
static void missing_import(void)
{
    uint32_t va = g_icall_trace[(g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1)];
    const char *name = void_thunk_name(va);
    void_log("[void] unimplemented import %s called from %08X", name ? name : "?", g_cur_func);
    void_lift_trap(va, "unimplemented import");
}

static uint32_t thunk_for(const char *dll, const char *name, uint32_t ordinal, int create_missing)
{
    char key[96];
    if (name) snprintf(key, sizeof key, "%s!%s", dll, name);
    else snprintf(key, sizeof key, "%s!#%u", dll, ordinal);
    for (char *p = key; *p && *p != '!'; ++p) *p = (char)tolower((unsigned char)*p);
    for (int i = 0; i < thunk_map_count; ++i) if (!strcmp(thunk_map[i].key, key)) return thunk_map[i].va;
    const void_shim *shim = void_shim_find(dll, name, ordinal);
    uint32_t va = 0;
    if (shim) {
        va = void_thunk(shim->fn, shim->name ? shim->name : key);
    } else if (create_missing) {
        char *name = strdup(key);
        if (missing_count < MISSING_STUBS) {
            va = void_thunk(missing_stubs[missing_count], name);
            missing_names[missing_count] = name;
            missing_vas[missing_count] = va;
        } else {
            va = void_thunk(missing_import, name);
        }
        ++missing_count;
        void_log("[void] import %s has no host implementation (traps if called)", key);
    } else {
        return 0;
    }
    if (thunk_map_count == thunk_map_cap) {
        thunk_map_cap = thunk_map_cap ? thunk_map_cap * 2 : 256;
        thunk_map = (thunk_entry *)realloc(thunk_map, (size_t)thunk_map_cap * sizeof *thunk_map);
    }
    snprintf(thunk_map[thunk_map_count].key, sizeof thunk_map[0].key, "%s", key);
    thunk_map[thunk_map_count++].va = va;
    return va;
}

/* --------------------------------------------------------------- mapping */
static uint8_t *read_file(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    rewind(f);
    uint8_t *data = (uint8_t *)malloc((size_t)n);
    if (!data || fread(data, 1, (size_t)n, f) != (size_t)n) { free(data); fclose(f); return NULL; }
    fclose(f);
    *size = (size_t)n;
    return data;
}

static int map_image(void_module *m, const char *path, uint32_t expected_base)
{
    size_t file_size = 0;
    uint8_t *file = read_file(path, &file_size);
    if (!file) { void_log("[void] cannot read image %s: %s", path, strerror(errno)); return 0; }
    uint32_t lfanew = file_size > 0x40 ? *(uint32_t *)(file + 0x3C) : 0;
    if (file_size < 0x40 || file[0] != 'M' || file[1] != 'Z' || lfanew + 0xF8 > file_size ||
        memcmp(file + lfanew, "PE\0\0", 4) || *(uint16_t *)(file + lfanew + 4) != 0x14C ||
        *(uint16_t *)(file + lfanew + 0x18) != 0x10B) {
        void_log("[void] %s is not a PE32 i386 image", path);
        free(file);
        return 0;
    }
    uint32_t image_base = *(uint32_t *)(file + lfanew + 0x34);
    uint32_t image_size = *(uint32_t *)(file + lfanew + 0x50);
    uint32_t headers = *(uint32_t *)(file + lfanew + 0x54);
    uint32_t entry_rva = *(uint32_t *)(file + lfanew + 0x28);
    uint16_t sections = *(uint16_t *)(file + lfanew + 6);
    uint16_t optional = *(uint16_t *)(file + lfanew + 0x14);
    if (image_base != expected_base) {
        void_log("[void] %s prefers %08X, expected pre-based %08X", path, image_base, expected_base);
        free(file);
        return 0;
    }
    if (!void_vm_claim(image_base, image_size, 0x04u)) {
        void_log("[void] cannot claim %08X+%08X for %s", image_base, image_size, path);
        free(file);
        return 0;
    }
    memcpy(GPTR(image_base), file, headers < file_size ? headers : file_size);
    uint32_t table = lfanew + 0x18 + optional;
    for (uint16_t i = 0; i < sections; ++i) {
        uint8_t *s = file + table + 40u * i;
        uint32_t va = *(uint32_t *)(s + 12), raw_size = *(uint32_t *)(s + 16), raw = *(uint32_t *)(s + 20);
        uint32_t virtual_size = *(uint32_t *)(s + 8);
        uint32_t copy = raw_size < virtual_size || !virtual_size ? raw_size : virtual_size;
        if (raw && copy) {
            if ((uint64_t)raw + copy > file_size || (uint64_t)va + copy > image_size) {
                void_log("[void] %s: section %u out of bounds", path, i);
                free(file);
                return 0;
            }
            memcpy(GPTR(image_base + va), file + raw, copy);
        }
    }
    free(file);
    m->base = image_base;
    m->size = image_size;
    m->entry = entry_rva ? image_base + entry_rva : 0;
    m->state = ST_MAPPED;
    void_dispatch_image(image_base, image_base + image_size);
    uint32_t tls = dir_rva(image_base, 9);
    if (tls && !void_tls_register(image_base, image_base + tls)) return 0;
    return 1;
}

static int bind_imports(void_module *m)
{
    uint32_t rva = dir_rva(m->base, 1);
    if (!rva) return 1;
    int unresolved = 0;
    for (uint32_t d = m->base + rva; MEM32(d + 12); d += 20) {
        const char *dll = (const char *)GPTR(m->base + MEM32(d + 12));
        uint32_t names = MEM32(d) ? m->base + MEM32(d) : m->base + MEM32(d + 16);
        uint32_t slots = m->base + MEM32(d + 16);
        void_module *target = find_by_name(dll);
        if (target && target->kind != MOD_PSEUDO) {
            int index = (int)(target - modules);
            int known = 0;
            for (int i = 0; i < m->dep_count; ++i) known |= m->deps[i] == index;
            if (!known && m->dep_count < 16) m->deps[m->dep_count++] = index;
        }
        for (uint32_t i = 0;; ++i) {
            uint32_t entry = MEM32(names + 4 * i);
            if (!entry) break;
            uint32_t value = 0;
            if (target && target->kind != MOD_PSEUDO) {
                value = export_lookup(target->base, (entry & 0x80000000u) ? (entry & 0xFFFFu) : m->base + entry + 2);
                if (!value) {
                    void_log("[void] %s: unresolved lifted import %s!%s", m->name, dll,
                        (entry & 0x80000000u) ? "#ordinal" : (const char *)GPTR(m->base + entry + 2));
                    ++unresolved;
                }
            } else if (entry & 0x80000000u) {
                value = thunk_for(dll, NULL, entry & 0xFFFFu, 1);
            } else {
                value = thunk_for(dll, (const char *)GPTR(m->base + entry + 2), 0, 1);
            }
            MEM32(slots + 4 * i) = value;
        }
    }
    return unresolved == 0;
}

static void add_pseudo(const char *name)
{
    if (module_count >= MAX_MODULES) void_fatal("module table full");
    void_module *m = &modules[module_count++];
    memset(m, 0, sizeof *m);
    snprintf(m->name, sizeof m->name, "%s", name);
    snprintf(m->win_path, sizeof m->win_path, "C:\\Windows\\system32\\%s", name);
    m->kind = MOD_PSEUDO;
    m->state = ST_READY;
    m->refs = 1;
    m->size = 0x1000;
    m->base = void_vm_alloc(0, 0x1000, 0x3000u, 0x04u);
    if (!m->base) void_fatal("pseudo module allocation failed");
    /* A minimal MZ/PE header so code that inspects a module handle sees one. */
    MEM16(m->base) = 0x5A4D;
    MEM32(m->base + 0x3C) = 0x80;
    MEM32(m->base + 0x80) = 0x00004550;
    MEM16(m->base + 0x84) = 0x14C;
    MEM16(m->base + 0x94) = 0xE0;
    MEM16(m->base + 0x98) = 0x10B;
    MEM32(m->base + 0x98 + 0x1C) = m->base;
    MEM32(m->base + 0x98 + 0x38) = 0x1000;
}

int void_modules_init(const char *image_dir)
{
    for (size_t i = 0; i < sizeof pseudo_names / sizeof pseudo_names[0]; ++i) add_pseudo(pseudo_names[i]);
    for (size_t i = 0; i < sizeof lifted / sizeof lifted[0]; ++i) {
        void_module *m = &modules[module_count++];
        memset(m, 0, sizeof *m);
        snprintf(m->name, sizeof m->name, "%s", lifted[i].name);
        snprintf(m->win_path, sizeof m->win_path, "%s\\%s", VIRTUAL_BIN, lifted[i].name);
        m->kind = lifted[i].exe ? MOD_LIFTED_EXE : MOD_LIFTED_DLL;
        char path[1024];
        snprintf(path, sizeof path, "%s/%s", image_dir, lifted[i].file);
        if (lifted[i].optional && access(path, F_OK)) {
            void_log("[void] optional module %s not installed", lifted[i].name);
            --module_count;
            continue;
        }
        if (!map_image(m, path, lifted[i].base)) return 0;
        if (lifted[i].exe) { exe_base = m->base; m->state = ST_READY; m->refs = 1; }
        void_log("[void] mapped %s at %08X size %08X entry %08X", m->name, m->base, m->size, m->entry);
    }
    int ok = 1;
    for (int i = 0; i < module_count; ++i) if (modules[i].kind != MOD_PSEUDO) ok &= bind_imports(&modules[i]);
    if (!ok) return 0;
    for (int i = 0; i < module_count; ++i) {
        void_module *m = &modules[i];
        if (m->kind != MOD_LIFTED_DLL) continue;
        m->pristine = (uint8_t *)malloc(m->size);
        memcpy(m->pristine, GPTR(m->base), m->size);
    }
    void_log("[void] %d modules ready, %d host import gaps", module_count, missing_count);
    /* VOID_DEBUG_IAT=<hex VA>: what an import slot was bound to. */
    const char *iat = getenv("VOID_DEBUG_IAT");
    if (iat && *iat) {
        uint32_t slot = (uint32_t)strtoul(iat, NULL, 16), target = MEM32(slot);
        const char *name = void_thunk_name(target);
        void_log("[void] import slot %08X -> %08X (%s)", slot, target, name ? name : "not a host thunk");
    }
    return 1;
}

/* ------------------------------------------------------------ lifecycle */
static uint32_t dll_event(void_module *m, uint32_t reason, uint32_t reserved)
{
    void_tls_callbacks(m->base, reason);
    if (!m->entry) return 1;
    uint32_t args[3] = { m->base, reason, reserved };
    uint32_t seh = MEM32(g_fs_base);
    uint32_t result = void_call_guest(m->entry, 3, args, 1);
    if (MEM32(g_fs_base) != seh) void_lift_trap(m->entry, "DLL entry did not restore its SEH chain");
    return result;
}

static int module_release(void_module *m, uint32_t reserved, int release_reference);

static uint32_t module_acquire(void_module *m)
{
    if (m->kind == MOD_PSEUDO) return m->base;
    if (m->kind == MOD_LIFTED_EXE) return m->base;
    if (m->state == ST_INITIALIZING) { ++m->refs; return m->base; }
    if (m->state == ST_DETACHED && m->pristine && !m->refs) {
        /* Final detach finished its CRT cleanup: restore the bound image so
         * the next attach starts from the original static state. */
        memcpy(GPTR(m->base), m->pristine, m->size);
        m->state = ST_MAPPED;
        void_log("[void] %s image restored for reload", m->name);
    }
    if (m->state == ST_MAPPED) {
        m->state = ST_INITIALIZING;
        /* Static imports are attached first and stay attached until this
         * module's final detach, as the Windows loader does. */
        for (int i = 0; i < m->dep_count; ++i) {
            if (!module_acquire(&modules[m->deps[i]])) {
                for (int k = 0; k < i; ++k) module_release(&modules[m->deps[k]], 0, 1);
                m->state = ST_MAPPED;
                return 0;
            }
        }
        m->holds_deps = 1;
        ++m->attach_events;
        uint32_t result = dll_event(m, DLL_PROCESS_ATTACH_, 0);
        void_log("[void] lifted %s attach #%u result=%08X", m->name, m->attach_events, result);
        if (!result) {
            m->state = ST_DETACHED;
            for (int i = 0; i < m->dep_count; ++i) module_release(&modules[m->deps[i]], 0, 1);
            m->holds_deps = 0;
            return 0;
        }
        m->state = ST_READY;
    }
    if (m->state != ST_READY) return 0;
    ++m->refs;
    return m->base;
}

int void_modules_start(void)
{
    void_module *exe = find_by_handle(exe_base);
    if (!exe) return 0;
    for (int i = 0; i < exe->dep_count; ++i)
        if (!module_acquire(&modules[exe->deps[i]])) return 0;
    void_tls_callbacks(exe->base, DLL_PROCESS_ATTACH_);
    return 1;
}

static int module_release(void_module *m, uint32_t reserved, int release_reference)
{
    if (m->kind != MOD_LIFTED_DLL) return 1;
    if (m->state != ST_READY || (release_reference && !m->refs)) return 0;
    if (release_reference && --m->refs) return 1;
    m->state = ST_DETACHING;
    ++m->detach_events;
    uint32_t result = dll_event(m, DLL_PROCESS_DETACH_, reserved);
    m->state = ST_DETACHED;
    m->refs = 0;
    void_log("[void] lifted %s detach #%u result=%08X reserved=%08X", m->name, m->detach_events, result, reserved);
    if (m->holds_deps) {
        m->holds_deps = 0;
        for (int i = 0; i < m->dep_count; ++i) module_release(&modules[m->deps[i]], reserved, 1);
    }
    return 1;
}

uint32_t void_module_load(const char *name)
{
    pthread_mutex_lock(&loader_lock);
    void_module *m = find_by_name(name);
    uint32_t handle = 0;
    if (m) {
        pthread_mutex_unlock(&loader_lock);
        handle = module_acquire(m);
        if (!handle) void_set_last_error(ERROR_DLL_INIT_FAILED_);
        return handle;
    }
    pthread_mutex_unlock(&loader_lock);
    void_log("[void] LoadLibrary(%s): no such module (caller %08X)", name, g_cur_func);
    void_set_last_error(ERROR_MOD_NOT_FOUND_);
    return 0;
}

uint32_t void_module_handle(const char *name)
{
    if (!name) return exe_base;
    void_module *m = find_by_name(name);
    if (!m) { void_set_last_error(ERROR_MOD_NOT_FOUND_); return 0; }
    if (m->kind == MOD_LIFTED_DLL && !(m->state >= ST_INITIALIZING && m->state <= ST_DETACHING)) {
        void_set_last_error(ERROR_MOD_NOT_FOUND_);
        return 0;
    }
    return m->base;
}

uint32_t void_module_proc(uint32_t handle, uint32_t name_or_ordinal)
{
    void_module *m = handle ? find_by_handle(handle) : find_by_handle(exe_base);
    if (!m) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    uint32_t address = 0;
    if (m->kind == MOD_PSEUDO) {
        if (name_or_ordinal >= 0x10000u) {
            const char *name = (const char *)GPTR(name_or_ordinal);
            address = thunk_for(m->name, name, 0, 0);
            VLOG("[void] GetProcAddress(%s, %s) = %08X", m->name, name, address);
        } else {
            address = thunk_for(m->name, NULL, name_or_ordinal, 0);
        }
    } else {
        if (m->kind == MOD_LIFTED_DLL && !(m->state >= ST_INITIALIZING && m->state <= ST_DETACHING)) {
            void_set_last_error(ERROR_INVALID_HANDLE_);
            return 0;
        }
        address = export_lookup(m->base, name_or_ordinal);
    }
    if (!address) void_set_last_error(ERROR_PROC_NOT_FOUND_);
    return address;
}

int void_module_free(uint32_t handle)
{
    void_module *m = find_by_handle(handle);
    if (!m) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (m->kind != MOD_LIFTED_DLL) return 1;
    return module_release(m, 0, 1);
}

const char *void_module_path(uint32_t handle)
{
    void_module *m = handle ? find_by_handle(handle) : find_by_handle(exe_base);
    if (!m) return NULL;
    if (m->kind == MOD_LIFTED_DLL && !(m->state >= ST_INITIALIZING && m->state <= ST_DETACHING)) return NULL;
    return m->win_path;
}

void void_modules_detach_all(uint32_t reserved)
{
    /* GameModule's cleanup may still call Engine: detach in load order. */
    for (int i = 0; i < module_count; ++i) (void)module_release(&modules[i], reserved, 0);
}

/* ------------------------------------------------------- kernel32 exports */
#define K32 "kernel32.dll"

WINAPI_EXPORT(K32, LoadLibraryA, 1)
{
    char *name = void_astr_utf8(ARG(0));
    uint32_t h = name ? void_module_load(name) : 0;
    free(name);
    return h;
}

WINAPI_EXPORT(K32, LoadLibraryW, 1)
{
    char *name = void_wstr_utf8(ARG(0));
    uint32_t h = name ? void_module_load(name) : 0;
    free(name);
    return h;
}

WINAPI_EXPORT(K32, LoadLibraryExA, 3)
{
    char *name = void_astr_utf8(ARG(0));
    uint32_t h = name ? void_module_load(name) : 0;
    free(name);
    return h;
}

WINAPI_EXPORT(K32, LoadLibraryExW, 3)
{
    char *name = void_wstr_utf8(ARG(0));
    uint32_t h = name ? void_module_load(name) : 0;
    free(name);
    return h;
}

WINAPI_EXPORT(K32, FreeLibrary, 1) { return (uint32_t)void_module_free(ARG(0)); }

WINAPI_EXPORT(K32, GetModuleHandleA, 1)
{
    char *name = void_astr_utf8(ARG(0));
    uint32_t h = void_module_handle(name);
    free(name);
    return h;
}

WINAPI_EXPORT(K32, GetModuleHandleW, 1)
{
    char *name = void_wstr_utf8(ARG(0));
    uint32_t h = void_module_handle(name);
    free(name);
    return h;
}

WINAPI_EXPORT(K32, GetProcAddress, 2) { return void_module_proc(ARG(0), ARG(1)); }

static uint32_t module_file_name(uint32_t handle, uint32_t buffer, uint32_t capacity, int wide)
{
    const char *path = void_module_path(handle);
    if (!path) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (!capacity) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return 0; }
    size_t length = strlen(path);   /* ASCII paths: units == bytes */
    size_t copy = length < capacity ? length : capacity - 1;
    for (size_t i = 0; i < copy; ++i) {
        if (wide) MEM16(buffer + 2 * (uint32_t)i) = (uint8_t)path[i];
        else MEM8(buffer + (uint32_t)i) = (uint8_t)path[i];
    }
    if (wide) MEM16(buffer + 2 * (uint32_t)copy) = 0; else MEM8(buffer + (uint32_t)copy) = 0;
    if (length >= capacity) { void_set_last_error(ERROR_INSUFFICIENT_BUFFER_); return capacity; }
    return (uint32_t)length;
}

WINAPI_EXPORT(K32, GetModuleFileNameA, 3) { return module_file_name(ARG(0), ARG(1), ARG(2), 0); }
WINAPI_EXPORT(K32, GetModuleFileNameW, 3) { return module_file_name(ARG(0), ARG(1), ARG(2), 1); }
WINAPI_EXPORT(K32, DisableThreadLibraryCalls, 1) { return 1; }
