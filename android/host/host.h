/* The Void ARM64 host: shared declarations for the Win32 HLE runtime.
 *
 * Model: the lifted x86 code runs on global registers (recomp_types.h). One
 * guest thread owns the machine at a time (void_machine_enter/leave), exactly
 * the native32 model the Windows build validated; every guest VA is an offset
 * into the 4 GiB window at VOID_GUEST_BASE. Imports resolve to host functions
 * at synthetic VAs; a host function reads its arguments from the guest stack,
 * leaves the result in g_eax (g_edx) and pops like the original convention.
 */
#ifndef VOID_HOST_H
#define VOID_HOST_H

#include "recomp_types.h"
#include <stdarg.h>
#include <stdbool.h>
#include <pthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------ diagnostics */
/* perf.c: host work that can stall a frame, logged per long frame as [hitch]. */
enum {
    VOID_PERF_FILE_OPEN, VOID_PERF_FILE_MAP, VOID_PERF_FIND, VOID_PERF_FILE_READ,
    VOID_PERF_SHADER_COMPILE, VOID_PERF_PROGRAM_LINK, VOID_PERF_PROGRAM_CACHE, VOID_PERF_TEXTURE,
    VOID_PERF_COUNT
};
uint64_t void_perf_now_ns(void);
void void_perf_add(int kind, uint64_t ns, uint64_t bytes);
void void_perf_frame_end(uint32_t frame);
uint64_t void_perf_calls(int kind);
float void_port_fps_limit(void);
/* ToE: LAN discovery also to the launcher's VPN peers (port_settings.c, network.c). */
int void_port_lan_vpn(void);
void void_port_set_refresh_rates(const float *rates, int count);
/* The first game screen is up: the APK's loading screen goes (android_main.c). */
void void_android_load_ready(void);
void void_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
_Noreturn void void_fatal(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void void_dump_state(const char *why);
void void_lift_trap(uint32_t address, const char *instruction);
extern int void_verbose;
#define VLOG(...) do { if (void_verbose) void_log(__VA_ARGS__); } while (0)

/* ---------------------------------------------------------- guest memory */
#define GUEST_PAGE 0x1000u
#define GUEST_GRANULARITY 0x10000u
/* Windows hands a non-large-address-aware process 2 GiB; stay below it. */
#define GUEST_USER_TOP 0x7FFE0000u
/* Synthetic import / COM method VAs: never executed, only dispatched. */
#define GUEST_THUNK_BASE 0x7FF00000u
#define GUEST_THUNK_LIMIT 0x7FFD0000u

int void_guest_reserve(void);
/* Win32 VirtualAlloc semantics on the guest window. Returns 0 on failure. */
uint32_t void_vm_alloc(uint32_t address, uint32_t size, uint32_t type, uint32_t protect);
int void_vm_free(uint32_t address, uint32_t size, uint32_t type);
int void_vm_protect(uint32_t address, uint32_t size, uint32_t protect, uint32_t *old);
/* Fills a MEMORY_BASIC_INFORMATION (28 bytes) at guest VA info. */
uint32_t void_vm_query(uint32_t address, uint32_t info);
int void_vm_readable(uint32_t address, uint32_t size);
int void_vm_find(const uint8_t *pattern, uint32_t length, uint32_t *hits, int max);   /* debugging */
int void_vm_dump(const char *path);                                                   /* debugging */
int void_vm_writable(uint32_t address, uint32_t size);
/* Reserve+commit an exact range (images, fixed regions); 0 on conflict. */
int void_vm_claim(uint32_t address, uint32_t size, uint32_t protect);
uint32_t void_vm_map_file(int fd, uint64_t offset, uint32_t size, int writable, int shared);
int void_vm_unmap_file(uint32_t address);

/* Win32 heaps over dlmalloc mspaces in the guest window. */
uint32_t void_heap_create(uint32_t initial, uint32_t maximum);
int void_heap_destroy(uint32_t heap);
uint32_t void_heap_alloc(uint32_t heap, uint32_t size, int zero);
int void_heap_free(uint32_t heap, uint32_t block);
uint32_t void_heap_realloc(uint32_t heap, uint32_t block, uint32_t size, int zero, int in_place_only);
uint32_t void_heap_size(uint32_t heap, uint32_t block);
uint32_t void_process_heap(void);
/* Host-side convenience: process-heap allocation for runtime structures
 * that the guest must be able to read (strings, structs). */
uint32_t void_galloc(uint32_t size);
void void_gfree(uint32_t va);
uint32_t void_gstrdup(const char *s);

/* --------------------------------------------------------- guest strings */
size_t void_gstrlen(uint32_t va);
size_t void_gwcslen(uint32_t va);
/* UTF-16 guest string -> malloc'ed UTF-8 (NULL for va == 0). */
char *void_wstr_utf8(uint32_t va);
/* ANSI (Russian system code page 1251) guest string -> malloc'ed UTF-8. */
char *void_astr_utf8(uint32_t va);
/* UTF-8 -> guest UTF-16, capacity in UTF-16 units including terminator.
 * Returns the number of units written without the terminator, or the
 * required size (with terminator) when cap is too small (and writes nothing). */
uint32_t void_utf8_to_gw(const char *s, uint32_t dst, uint32_t cap);
uint32_t void_utf8_to_ga(const char *s, uint32_t dst, uint32_t cap);
/* System ANSI CP1251 and explicit CP1252 byte conversions. */
uint16_t void_ansi_to_u16(uint8_t c);
int void_u16_to_ansi(uint16_t u, uint8_t *out);
uint8_t void_ansi_lower(uint8_t c);
uint16_t void_cp1252_to_u16(uint8_t c);
int void_u16_to_cp1252(uint16_t u, uint8_t *out);
size_t void_utf8_encode(uint32_t cp, char *out);

/* ---------------------------------------------------------- the machine */
typedef struct void_regs {
    uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi;
    uint32_t fs, cur;
    uint32_t flag_k, flag_a, flag_b, flag_cf;
    double st[8];
    int64_t st_i64[8];
    int fp_top, fpu_cmp;
    uint16_t fpu_cw;
    uint64_t fp_round_mask, fp_store_mask;   /* of fpu_cw (fp_cw_masks) */
    uint64_t mm[8];
    xmm_t xmm[8];
    uint32_t mxcsr;
    /* Guest C++ EH state of this thread (eh.c), swapped with the machine. */
    void *eh_frames;
    uint32_t eh_obj, eh_info;
    /* Current thread's cooperative scheduling budget, outside guest state. */
    uint32_t backedges;
} void_regs;

/* eh.c: the current thread's lifted EH landing pads and active exception. */
extern VOID_HIDDEN recomp_ehframe_t *g_eh_frames;
extern VOID_HIDDEN uint32_t g_eh_obj, g_eh_info;
void void_eh_reset_thread(void);

/* threads.c */
void void_threads_init(void);
void d3d_device_lifecycle_selftest(void);
/* directory is the mapped IMAGE_TLS_DIRECTORY32 VA (0 means absent). */
int void_tls_register(uint32_t image_base, uint32_t directory);
void void_tls_callbacks(uint32_t image_base, uint32_t reason);
void void_wait_broadcast(void);
uint32_t void_wait_extra_cond(int count, const uint32_t *handles, uint32_t timeout,
    int (*extra)(void *), void *arg);

/* core.c */
void void_log_open(const char *path);
void void_log_flush(void);
void void_install_fault_handlers(void);
void void_dispatch_image(uint32_t lo, uint32_t hi);

void void_regs_save(void_regs *r);
void void_regs_load(const void_regs *r);

typedef struct void_thread void_thread;
void_thread *void_thread_self(void);
/* Claim/release the guest machine for the calling host thread. Nested claims
 * count; only the outermost loads/saves the register file. */
void void_machine_enter(void);
/* Nanoseconds the calling thread has waited for the machine lock. */
uint64_t void_lock_wait_ns(void);
void void_machine_leave(void);
/* Release the machine around a blocking host operation. */
void void_blocking_begin(void);
void void_blocking_end(void);
uint32_t void_thread_id(void);
uint32_t void_get_last_error(void);
void void_set_last_error(uint32_t e);

/* Call a guest function with stdcall/cdecl stack arguments; returns EAX.
 * Preserves the caller's register file except EAX/EDX/ECX as the callee
 * leaves them. `pop_check`: 1 = expect callee to pop (stdcall), 0 = cdecl. */
uint32_t void_call_guest(uint32_t va, int nargs, const uint32_t *args, int stdcall_pops);
/* Same, with ECX = this (thiscall). */
uint32_t void_call_guest_this(uint32_t va, uint32_t this_ptr, int nargs, const uint32_t *args);

/* --------------------------------------------------------------- dispatch */
typedef void (*void_fn)(void);
void void_dispatch_init(void);
void void_zlib_init(void);
void void_dispatch_add(uint32_t va, void_fn fn);
void_fn void_dispatch_find(uint32_t va);
/* A synthetic VA bound to a host function (imports, COM methods). */
uint32_t void_thunk(void_fn fn, const char *name);
const char *void_thunk_name(uint32_t va);
void void_thunk_stats(uint32_t frames);   /* VOID_COUNT_THUNKS=1: busiest host calls per frame */

/* ------------------------------------------------------------ shims */
typedef struct void_shim {
    const char *dll;   /* lower-case DLL name, e.g. "kernel32.dll" */
    const char *name;  /* export name, or NULL for ordinal-only */
    uint32_t ordinal;  /* 0 when exported by name only */
    void_fn fn;
} void_shim;

const void_shim *void_shim_find(const char *dll, const char *name, uint32_t ordinal);

#define VOID_SHIM_SECTION __attribute__((used, section("void_shims"), aligned(8)))

/* Arguments as the callee sees them: [esp] is the return address. */
#define ARG(i) MEM32(g_esp + 4u + 4u * (uint32_t)(i))

/* stdcall export returning EAX, popping nargs dwords. */
#define WINAPI_EXPORT(dll, name, nargs) \
    static uint32_t name##_impl(void); \
    static void name##_entry(void) { uint32_t _r = name##_impl(); g_eax = _r; g_esp += 4u + 4u * (nargs); } \
    static const void_shim name##_shim VOID_SHIM_SECTION = { dll, #name, 0, name##_entry }; \
    static uint32_t name##_impl(void)

/* Same but exported only by ordinal (e.g. dsound #11). */
#define WINAPI_ORDINAL(dll, symbol, ordinal_number, nargs) \
    static uint32_t symbol##_impl(void); \
    static void symbol##_entry(void) { uint32_t _r = symbol##_impl(); g_eax = _r; g_esp += 4u + 4u * (nargs); } \
    static const void_shim symbol##_shim VOID_SHIM_SECTION = { dll, #symbol, ordinal_number, symbol##_entry }; \
    static uint32_t symbol##_impl(void)

/* Exported by name and ordinal under its own C identifier (one export name in
 * several DLLs). An ordinal of 0 means by name only. */
#define WINAPI_EXPORT_AS(dll, symbol, export_name, ordinal_number, nargs) \
    static uint32_t symbol##_impl(void); \
    static void symbol##_entry(void) { uint32_t _r = symbol##_impl(); g_eax = _r; g_esp += 4u + 4u * (nargs); } \
    static const void_shim symbol##_shim VOID_SHIM_SECTION = { dll, export_name, ordinal_number, symbol##_entry }; \
    static uint32_t symbol##_impl(void)

/* cdecl export returning EAX: the caller pops its arguments. */
#define CDECL_EXPORT(dll, name) \
    static uint32_t name##_impl(void); \
    static void name##_entry(void) { uint32_t _r = name##_impl(); g_eax = _r; g_esp += 4u; } \
    static const void_shim name##_shim VOID_SHIM_SECTION = { dll, #name, 0, name##_entry }; \
    static uint32_t name##_impl(void)

/* A raw export: the body manages registers and the stack itself. */
#define RAW_EXPORT(dll, name) \
    static void name##_entry(void); \
    static const void_shim name##_shim VOID_SHIM_SECTION = { dll, #name, 0, name##_entry }; \
    static void name##_entry(void)

/* --------------------------------------------------------------- modules */
typedef struct void_module void_module;
int void_modules_init(const char *image_dir);
/* LoadLibrary / GetModuleHandle / GetProcAddress / FreeLibrary semantics. */
uint32_t void_module_load(const char *name);
uint32_t void_module_handle(const char *name);
uint32_t void_module_proc(uint32_t handle, uint32_t name_or_ordinal);
int void_module_free(uint32_t handle);
/* GetModuleFileName in UTF-8 Windows form, NULL if unknown. */
const char *void_module_path(uint32_t handle);
void void_modules_detach_all(uint32_t reserved);
uint32_t void_module_exe_base(void);

/* ------------------------------------------------------------- handles */
enum void_object_kind {
    VOID_OBJ_NONE, VOID_OBJ_FILE, VOID_OBJ_EVENT, VOID_OBJ_MUTEX, VOID_OBJ_SEMAPHORE,
    VOID_OBJ_THREAD, VOID_OBJ_MAPPING, VOID_OBJ_FIND, VOID_OBJ_PROCESS, VOID_OBJ_TIMER,
    VOID_OBJ_PIPE, VOID_OBJ_HEAP, VOID_OBJ_OTHER
};
typedef struct void_object {
    int kind;
    int refs;
    void (*destroy)(struct void_object *);
    /* Waitable objects: signaled state under the object lock. */
    pthread_mutex_t lock;
    pthread_cond_t cond;
    int signaled;
    int manual_reset;
    int count, max_count;          /* semaphore */
    uint32_t owner;                /* mutex owner thread id */
    int recursion;
    void *data;                    /* kind-specific */
} void_object;

uint32_t void_handle_new(void_object *object);
void_object *void_handle_get(uint32_t handle, int kind);
int void_handle_close(uint32_t handle);
uint32_t void_handle_dup(uint32_t handle);
void_object *void_object_new(int kind, size_t extra);
void void_object_release(void_object *object);
/* Waits (handles), returning WAIT_OBJECT_0+i / WAIT_TIMEOUT / WAIT_FAILED. */
uint32_t void_wait(int count, const uint32_t *handles, int wait_all, uint32_t timeout_ms);
void void_object_signal(void_object *object);

/* ---------------------------------------------------------------- files */
/* Windows path (UTF-8) -> host path; malloc'ed, NULL if outside the jail. */
char *void_path_to_host(const char *windows_path);
const char *void_root_dir(void);
const char *void_data_dir(void);
int void_files_init(const char *game_root, const char *data_root);
/* Port files (profiles, UI additions) shadowing the installation for reading. */
void void_files_set_overlay(const char *dir);
void void_files_set_cache(const char *dir);
const char *void_cache_dir(void);     /* NULL without one */
void void_files_stats(uint64_t *listing_hits, uint64_t *listing_loads);
uint32_t void_cwd_get(char *out, uint32_t cap);
int void_cwd_set(const char *windows_path);
uint32_t void_errno_to_win32(int e);
int void_file_host_fd(uint32_t handle);

/* -------------------------------------------------------------- time */
uint64_t void_now_100ns(void);       /* FILETIME epoch */
uint64_t void_monotonic_ns(void);
uint32_t void_tick_ms(void);

/* ------------------------------------------------------------ exceptions */
void void_eh_init(void);
void void_raise_cxx(void);

/* ------------------------------------------------------- window system */
uint32_t void_window_main(void);
uint32_t void_window_thread(uint32_t hwnd);
void void_window_client_size(uint32_t hwnd, int *w, int *h);
/* APK physical display size, retained across surface loss; absent in the shell. */
int void_android_display_size(int *w, int *h);
int void_android_render_ready(void);
uint64_t void_audio_pause_state(void); /* Low bit paused, upper bits lifecycle generation. */
uint32_t void_send_message(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam);
void void_post_message(uint32_t hwnd, uint32_t msg, uint32_t wparam, uint32_t lparam);

/* --------------------------------------------------------- Win32 values */
#define WIN_TRUE 1u
#define WIN_FALSE 0u
#define WIN_INVALID_HANDLE 0xFFFFFFFFu
#define WAIT_OBJECT_0_ 0u
#define WAIT_ABANDONED_0_ 0x80u
#define WAIT_TIMEOUT_ 0x102u
#define WAIT_FAILED_ 0xFFFFFFFFu
#define INFINITE_ 0xFFFFFFFFu

#define ERROR_SUCCESS_ 0u
#define ERROR_INVALID_FUNCTION_ 1u
#define ERROR_FILE_NOT_FOUND_ 2u
#define ERROR_PATH_NOT_FOUND_ 3u
#define ERROR_ACCESS_DENIED_ 5u
#define ERROR_INVALID_HANDLE_ 6u
#define ERROR_NOT_ENOUGH_MEMORY_ 8u
#define ERROR_NO_MORE_FILES_ 18u
#define ERROR_HANDLE_EOF_ 38u
#define ERROR_NOT_SUPPORTED_ 50u
#define ERROR_FILE_EXISTS_ 80u
#define ERROR_INVALID_PARAMETER_ 87u
#define ERROR_INSUFFICIENT_BUFFER_ 122u
#define ERROR_MOD_NOT_FOUND_ 126u
#define ERROR_PROC_NOT_FOUND_ 127u
#define ERROR_ALREADY_EXISTS_ 183u
#define ERROR_ENVVAR_NOT_FOUND_ 203u
#define ERROR_MORE_DATA_ 234u
#define ERROR_NO_MORE_ITEMS_ 259u
#define ERROR_INVALID_ADDRESS_ 487u
#define ERROR_NOT_OWNER_ 288u
#define ERROR_DLL_INIT_FAILED_ 1114u
#define ERROR_CLASS_ALREADY_EXISTS_ 1410u

#define S_OK_ 0u
#define S_FALSE_ 1u
#define E_NOTIMPL_ 0x80004001u
#define E_NOINTERFACE_ 0x80004002u
#define E_POINTER_ 0x80004003u
#define E_FAIL_ 0x80004005u
#define E_OUTOFMEMORY_ 0x8007000Eu
#define E_INVALIDARG_ 0x80070057u
#define REGDB_E_CLASSNOTREG_ 0x80040154u

#ifdef __cplusplus
}
#endif
#endif
