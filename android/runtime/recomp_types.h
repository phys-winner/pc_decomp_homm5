/*
 * The Void ARM64 runtime header: a private copy of pcrecomp
 * runtime/recomp32/recomp_types.h (MIT, revision
 * 904ac3129d0c9d05efbeec19a1dce6abbe7f5d26, SHA-256
 * 3c0afef3412074932f0134af4462ec31c05402ccbe38d5692b38e9271bf687cf).
 *
 * The generated x86 C is unchanged; only what the macros expand to differs:
 *   - guest addresses live in one reserved 4 GiB host window at the constant
 *     VOID_GUEST_BASE, so ADDR() is a single add and needs no global load;
 *   - published flags, the shared x87 condition word and the exact int64 x87
 *     shadows are ordinary globals, swapped with the registers when the guest
 *     machine changes hands (the native32 model, without Windows TLS);
 *   - float -> int conversions reproduce x86's "integer indefinite" instead of
 *     C's undefined (and ARM64's saturating) out-of-range result;
 *   - CPUID answers from a fixed table instead of the host CPU.
 *
 * All recompiled functions include this header.
 */

#ifndef RECOMP_TYPES_H
#define RECOMP_TYPES_H

#include <stdint.h>
#include <stddef.h>   /* ptrdiff_t (g_mem_base); MSVC pulls it in transitively, gcc/clang do not */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#if defined(__aarch64__)
#include <arm_neon.h>
#endif

#if defined(_MSC_VER) || !defined(__aarch64__)
#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"
#endif

#define VOID_HIDDEN __attribute__((visibility("hidden")))

/* The guest window. Every guest VA is an offset into it; the host reserves it
 * once at exactly this address (void_guest_reserve) and fails otherwise. */
#ifndef VOID_GUEST_BASE
#define VOID_GUEST_BASE 0x2000000000ull
#endif
#define VOID_GUEST_SPAN 0x100000000ull

/* ============================================================
 * Global Register Model
 *
 * x86 registers are global variables. ebp is local per-function
 * since most VC6 code uses FPO (Frame Pointer Omission).
 * ============================================================ */

/* Volatile (caller-saved) registers */
extern VOID_HIDDEN uint32_t g_eax, g_ecx, g_edx, g_esp;

/* Callee-saved registers (also global for implicit parameter passing).
 * ebp is global too, not a per-function local: MSVC's __EH_prolog sets its
 * CALLER's frame pointer (lea ebp, [esp+0xC]) and returns, so a local ebp
 * would discard it and every C++ EH function would then address off zero.
 * Real x86 has one ebp; FPO functions that never touch it simply pass the
 * caller's through, which is exactly the behaviour we want. */
extern VOID_HIDDEN uint32_t g_ebx, g_esi, g_edi, g_ebp;
extern VOID_HIDDEN uint64_t g_mm[8];

/* The x87 FPU stack is GLOBAL (8 shared registers), not per-function: helpers
 * like __ftol receive their argument on the FPU stack from the caller, and the
 * control word persists across calls. A per-function local stack would make every
 * cross-call FPU value read as 0. */
#ifdef RECOMP_X87_WINDOW
/* Adapted from NFSU2 patch 0014; keep array semantics for register snapshots. */
#define RECOMP_X87_SLOTS 256
extern VOID_HIDDEN double g_st_win[RECOMP_X87_SLOTS];
extern VOID_HIDDEN int64_t g_st_i64_win[RECOMP_X87_SLOTS];
extern VOID_HIDDEN int g_fp_sp;
#define g_st (*(double (*)[8])(g_st_win + g_fp_sp))
#define g_st_i64 (*(int64_t (*)[8])(g_st_i64_win + g_fp_sp))
_Static_assert(sizeof g_st == 8 * sizeof(double), "x87 snapshot array size");
_Static_assert(sizeof g_st_i64 == 8 * sizeof(int64_t), "x87 shadow snapshot array size");
#else
extern VOID_HIDDEN double   g_st[8];
#endif
extern VOID_HIDDEN int      g_fp_top;
extern VOID_HIDDEN uint16_t g_fpu_cw;

/* The arithmetic flags a function RETURNS with. The lazy flag state is local
 * to each lifted function, but assembly and the CRT return results in flags:
 * MSVC's sin/cos call a helper that returns ZF = "argument is Inf/NaN", and
 * the caller's `je` read its own stale flags instead -- every sin took the
 * NaN path (Gunman's view vectors, and with them the whole frame, went
 * black). So every `ret` publishes the state and every call picks it back up;
 * where the caller overwrites the flags first, the compiler drops the loads.
 * Defined here, weakly, so no project's runtime has to. */
#define RECOMP_WEAK __attribute__((weak))
/* Ordinary globals here: the machine lock swaps them with the registers. */
extern VOID_HIDDEN uint32_t g_flag_k, g_flag_a, g_flag_b, g_flag_cf;
#define RECOMP_FLAGS_OUT() (g_flag_k = _flag_k, g_flag_a = _flag_a, g_flag_b = _flag_b, g_flag_cf = _cf)
#define RECOMP_FLAGS_IN()  (_flag_k = g_flag_k, _flag_a = g_flag_a, _flag_b = g_flag_b, _cf = g_flag_cf)

/* The project's shared x87 condition encoding (native/recomp_types.h): the
 * generated FCOM/FNSTSW pairs may sit in different functions. */
extern VOID_HIDDEN int void_fpu_cmp;
void void_fpu_remainder(uint32_t address, int nearest);
#ifdef RECOMP_GENERATED_CODE
#define _fpu_cmp void_fpu_cmp
#endif

/* Segment registers (flat mode Win32 - effectively unused) */
extern VOID_HIDDEN uint16_t g_seg_cs, g_seg_ds, g_seg_es, g_seg_fs, g_seg_gs, g_seg_ss;

/* Function pointer type for recompiled functions */
typedef void (*recomp_func_t)(void);

/* Dispatch table entry */
typedef struct {
    uint32_t address;
    recomp_func_t func;
} recomp_dispatch_entry_t;

/* Dispatch table (generated) */
extern const recomp_dispatch_entry_t recomp_dispatch_table[];
extern const uint32_t recomp_dispatch_count;

/* ============================================================
 * Register Name Aliases (used in generated code)
 * ============================================================ */

#if defined(RECOMP_GENERATED_CODE) && defined(RECOMP_LOCAL_REGS)
/* RECOMP_LOCAL_REGS: each lifted function works on local copies of the eight
 * registers, loaded on entry and written back before every call, tail call
 * and return (and reloaded after calls, which may run native code, callbacks
 * or other lifted functions). Globals can alias any guest memory store, so
 * the optimiser had to reload them after every MEM32 write; locals whose
 * address is never taken stay in host registers. Opt-in: every exit from a
 * body must pass RECOMP_REGS_OUT, which generate.py arranges. */
#define eax l_eax
#define ecx l_ecx
#define edx l_edx
#define ebx l_ebx
#define esp l_esp
#define esi l_esi
#define edi l_edi
#define ebp l_ebp
#define RECOMP_REGS_LOCALS uint32_t l_eax = g_eax, l_ecx = g_ecx, l_edx = g_edx, l_ebx = g_ebx, l_esp = g_esp, l_esi = g_esi, l_edi = g_edi, l_ebp = g_ebp;
#define RECOMP_REGS_OUT() (g_eax = l_eax, g_ecx = l_ecx, g_edx = l_edx, g_ebx = l_ebx, g_esp = l_esp, g_esi = l_esi, g_edi = l_edi, g_ebp = l_ebp, RECOMP_XMM_OUT(), RECOMP_BACKEDGE_OUT())
#define RECOMP_REGS_IN() (l_eax = g_eax, l_ecx = g_ecx, l_edx = g_edx, l_ebx = g_ebx, l_esp = g_esp, l_esi = g_esi, l_edi = g_edi, l_ebp = g_ebp, RECOMP_XMM_IN(), RECOMP_BACKEDGE_IN())
/* The SSE file travels the same way in the bodies that use it:
 * tools/build_android.py wraps each of them in definitions that make _xmm a
 * local l_xmm[8] and these two macros copy it (generated code indexes the
 * file only by constants, so the copies stay in NEON registers). */
#define RECOMP_XMM_OUT() ((void)0)
#define RECOMP_XMM_IN() ((void)0)
#define RECOMP_BACKEDGE_OUT() ((void)0)
#define RECOMP_BACKEDGE_IN() ((void)0)
#else
#define RECOMP_REGS_LOCALS
#define RECOMP_REGS_OUT() ((void)0)
#define RECOMP_REGS_IN() ((void)0)
#endif

#if defined(RECOMP_GENERATED_CODE) && !defined(RECOMP_LOCAL_REGS)
#define eax g_eax
#define ecx g_ecx
#define edx g_edx
#define ebx g_ebx
#define esp g_esp
#define esi g_esi
#define edi g_edi
#define ebp g_ebp
#endif
#ifdef RECOMP_GENERATED_CODE
/* x87 FPU stack is global; _fpu_cmp stays per-function (set+used within one fn) */
#define _st g_st
#define _fp_top g_fp_top
#define _fpu_cw g_fpu_cw
/* MMX file is global too. The lifter emits _mm[n] (see lift32.MMX_REGS), so the
 * alias has to exist alongside the others or every MMX body fails to compile. */
#define _mm g_mm
/* And the SSE file (lift32_sse.py emits _xmm[n]). */
#define _xmm g_xmm
#define _seg_cs g_seg_cs
#define _seg_ds g_seg_ds
#define _seg_es g_seg_es
#define _seg_fs g_seg_fs
#define _seg_gs g_seg_gs
#define _seg_ss g_seg_ss
#endif

/* ============================================================
 * Sub-register Access
 * ============================================================ */

#define LO8(r)       ((uint8_t)((r) & 0xFF))
#define HI8(r)       ((uint8_t)(((r) >> 8) & 0xFF))
#define LO16(r)      ((uint16_t)((r) & 0xFFFF))

#define SET_LO8(r, v)   ((r) = ((r) & 0xFFFFFF00u) | ((uint32_t)(uint8_t)(v)))
#define SET_HI8(r, v)   ((r) = ((r) & 0xFFFF00FFu) | (((uint32_t)(uint8_t)(v)) << 8))
#define SET_LO16(r, v)  ((r) = ((r) & 0xFFFF0000u) | ((uint32_t)(uint16_t)(v)))

/* ============================================================
 * Memory Access
 *
 * The original XWA binary uses a fixed image base of 0x00400000.
 * We map the original data sections at their original VAs using
 * VirtualAlloc/CreateFileMapping so that address-dependent code
 * works correctly.
 *
 * g_mem_base is the offset from original VA to actual mapped address.
 * For fixed-base mapping, this is 0.
 * ============================================================ */

/* Equal to VOID_GUEST_BASE once the window is reserved; kept for code that
 * still reads it. Generated code does not: ADDR folds the constant. */
extern VOID_HIDDEN ptrdiff_t g_mem_base;

#if defined(_WIN32) && defined(__i386__) && defined(RECOMP_GENERATED_CODE) && defined(RECOMP_GUEST_PROVENANCE)
/* PC: guest VAs are host addresses. Generated code reaches guest memory
 * through g_guest_mem, an absolute symbol at address 0 (native/windows_host.c):
 * the same addresses, but the optimiser sees one object distinct from every
 * host global, so a guest store can no longer clobber the VM register file,
 * the x87 window or the loop counter, and their loads fold away. Other guest
 * threads only run inside calls, which still clobber everything. */
extern uint8_t g_guest_mem[];
#define ADDR(va)     ((uintptr_t)(g_guest_mem + (uint32_t)(va)))
#define RECOMP_GUEST_PTR(va) ((void *)(g_guest_mem + (uint32_t)(va)))
#elif defined(__ANDROID__) && defined(__aarch64__) && defined(RECOMP_GENERATED_CODE) && defined(RECOMP_GUEST_PROVENANCE)
/* ARM: the same single-object provenance. g_guest_mem is a hidden absolute
 * symbol at the guest window (android/host/core.c); the window lies beyond
 * PC-relative range, so a body loads it once from the GOT. */
extern __attribute__((visibility("default"))) uint8_t g_guest_mem[];
#define ADDR(va)     ((uintptr_t)(g_guest_mem + (uint32_t)(va)))
#define RECOMP_GUEST_PTR(va) ((void *)(g_guest_mem + (uint32_t)(va)))
#else
#define ADDR(va)     ((uintptr_t)(uint32_t)(va) + (uintptr_t)VOID_GUEST_BASE)
#define RECOMP_GUEST_PTR(va) ((void *)ADDR(va))
#endif
#if defined(RECOMP_GUEST_STATE_SEPARATE) && defined(__ANDROID__) && defined(__aarch64__) && defined(RECOMP_GENERATED_CODE) && \
    !defined(RECOMP_GUEST_PROVENANCE)
#if !__has_builtin(__builtin_assume_separate_storage)
#error "Guest state separation requires separate-storage support"
#endif
_Static_assert(VOID_GUEST_BASE == 0x2000000000ull, "fixed ARM guest window required");
/* Native register objects predate the non-overlapping guest reservation.
 * Keep backedges, flags and hooks unrestricted so guest polling still reloads. */
static inline __attribute__((always_inline)) uintptr_t recomp_mem_addr(uint32_t va)
{
    uintptr_t pointer = (uintptr_t)va + (uintptr_t)VOID_GUEST_BASE;
    __builtin_assume_separate_storage((const void *)pointer, g_mm);
    __builtin_assume_separate_storage((const void *)pointer, &g_eax);
    __builtin_assume_separate_storage((const void *)pointer, &g_ecx);
    __builtin_assume_separate_storage((const void *)pointer, &g_edx);
    __builtin_assume_separate_storage((const void *)pointer, &g_ebx);
    __builtin_assume_separate_storage((const void *)pointer, &g_esp);
    __builtin_assume_separate_storage((const void *)pointer, &g_esi);
    __builtin_assume_separate_storage((const void *)pointer, &g_edi);
    __builtin_assume_separate_storage((const void *)pointer, &g_ebp);
    return pointer;
}
#define RECOMP_SEPARATE_MEM_ADDR(va) recomp_mem_addr((uint32_t)(va))
#else
#define RECOMP_SEPARATE_MEM_ADDR(va) RECOMP_GUEST_PTR(va)
#endif
#define RECOMP_MEM_ADDR(va) RECOMP_GUEST_PTR(va)
/* rep movsd / rep movsb with DF=0 (tools/build_android.py fast_rep_movs): a
 * forward copy is exactly memmove unless the destination starts inside the
 * source (the copy then replicates a pattern) or a range wraps the 4 GB guest
 * space. Those, and DF=1 copies, keep the lifted loop. */
static inline int recomp_movs_fast(uint32_t d, uint32_t s, uint32_t count, uint32_t unit)
{
    uint64_t bytes = (uint64_t)count * unit;
    if (!bytes || (uint64_t)d + bytes > 0x100000000ull || (uint64_t)s + bytes > 0x100000000ull) return 0;
    if (d > s && (uint64_t)(d - s) < bytes) return 0;
    memmove(RECOMP_GUEST_PTR(d), RECOMP_GUEST_PTR(s), (size_t)bytes);
    return 1;
}
/* Host pointer <-> guest VA for host code. */
#define GPTR(va)     ((void *)ADDR(va))
#define GVA(p)       ((uint32_t)((uintptr_t)(p) - (uintptr_t)VOID_GUEST_BASE))

/* Thread-relative segment bases. In Win32, fs: points at the TIB/TEB; gs is
 * unused on x86. The lifter emits fs:/gs: accesses as FS_BASE/GS_BASE + addr,
 * so the runtime points g_fs_base at a simulated TIB (VA). cs/ds/es/ss are flat. */
extern VOID_HIDDEN uint32_t g_fs_base;
extern VOID_HIDDEN uint32_t g_gs_base;
/* generated/fs-x86/fs_entry.h reuses the name FS_BASE for FS.dll's image
 * base; host code that needs both reads the module base through its own
 * constant (VOID_FS_IMAGE_BASE) instead of including that header here. */
#define FS_BASE  g_fs_base
#define GS_BASE  g_gs_base

/* DOS-extender hooks: what Lifter(dos=True) emits for int, port I/O, cli/sti,
 * hlt and segment loads (tools/lift/lift32.py _lift_dos). A DOS host such as
 * runtime/dos32 defines them; nothing else references them. Under DOS/4GW es
 * is a real selector (the PSP, the environment), so es: overrides get a base. */
extern VOID_HIDDEN uint32_t g_es_base;
#define ES_BASE  g_es_base
void     recomp_int(int n);
uint8_t  recomp_in8(uint32_t port);
uint16_t recomp_in16(uint32_t port);
uint32_t recomp_in32(uint32_t port);
void     recomp_out8(uint32_t port, uint8_t v);
void     recomp_out16(uint32_t port, uint16_t v);
void     recomp_out32(uint32_t port, uint32_t v);
void     recomp_ins(uint32_t port, uint32_t va, int size, uint32_t count, int dir);
void     recomp_outs(uint32_t port, uint32_t va, int size, uint32_t count, int dir);
void     recomp_cli(void);
void     recomp_sti(void);
void     recomp_hlt(void);
void     recomp_set_seg(int sreg, uint32_t selector);

/* Guest memory accesses are volatile by default, as upstream has them.
 * RECOMP_PLAIN_MEMORY (generated code only) makes them ordinary accesses the
 * optimiser may combine, forward and reuse. That is sound here because only
 * the thread holding the machine runs lifted code and the machine changes
 * hands only inside calls, which the compiler already treats as clobbering
 * memory; a lifted loop polling a flag still reloads it, since its backward
 * branch stores to g_backedges, which the compiler cannot separate from a
 * guest address. -fno-strict-aliasing keeps mixed-type views of one address
 * (MEM32 store, MEMF load) well defined. */
#if defined(RECOMP_GENERATED_CODE) && defined(RECOMP_PLAIN_MEMORY)
#define RECOMP_MEM_QUAL
#else
#define RECOMP_MEM_QUAL volatile
#endif
#define MEM8(addr)   (*(RECOMP_MEM_QUAL uint8_t  *)RECOMP_MEM_ADDR(addr))
#define MEM16(addr)  (*(RECOMP_MEM_QUAL uint16_t *)RECOMP_MEM_ADDR(addr))
#define MEM32(addr)  (*(RECOMP_MEM_QUAL uint32_t *)RECOMP_MEM_ADDR(addr))
#define MEM64(addr)  (*(RECOMP_MEM_QUAL uint64_t *)RECOMP_MEM_ADDR(addr))
#define MEMF(addr)   (*(RECOMP_MEM_QUAL float    *)RECOMP_MEM_ADDR(addr))
#define MEMD(addr)   (*(RECOMP_MEM_QUAL double   *)RECOMP_MEM_ADDR(addr))

/* Set 32-bit values in memory (for rep stosd) */
static inline void MEMSET32(void* dst, uint32_t val, uint32_t count) {
    uint32_t* p = (uint32_t*)dst;
    for (uint32_t i = 0; i < count; i++) p[i] = val;
}

/* And 16-bit, for `rep stosw` -- which is how a run-length codec writes a run
 * of one colour, and so how most of a 1990s background image gets drawn. */
static inline void MEMSET16(void* dst, uint16_t val, uint32_t count) {
    uint16_t* p = (uint16_t*)dst;
    for (uint32_t i = 0; i < count; i++) p[i] = val;
}

/* ============================================================
 * Stack Operations
 * ============================================================ */

/* Evaluate the operand BEFORE moving esp. x86 reads the source of
 * push dword ptr [esp+N] at the OLD esp; decrementing first makes every
 * esp-relative push read one slot too low -- which lands on the return
 * address the caller pushed, so the callee sees RECOMP_RETADDR as an
 * argument. */
#define PUSH32(sp, val) do { \
    uint32_t _pv = (uint32_t)(val); \
    (sp) -= 4; \
    MEM32(sp) = _pv; \
} while(0)

#define POP32_VAL(sp) ({ \
    uint32_t _v = MEM32(sp); \
    (sp) += 4; \
    _v; \
})

/* MSVC doesn't support statement expressions, so use a function */
#ifdef _MSC_VER
static inline uint32_t _pop32(uint32_t* sp) {
    uint32_t v = MEM32(*sp);
    *sp += 4;
    return v;
}
#undef POP32_VAL
#define POP32_VAL(sp) _pop32(&(sp))
#endif

/* Two-arg pop: store the popped value into an lvalue destination (register or
 * MEM32(...)). The lifter emits this form for `pop r/m32`. Defined via POP32_VAL
 * so it picks up the GCC statement-expr / MSVC inline-function variant above. */
#define POP32(sp, dest) do { (dest) = POP32_VAL(sp); } while(0)

/*
 * The 16-bit forms. `push bp` / `pop bp` (66 55 / 66 5D) move esp by TWO, and
 * the pop writes only BP -- the top half of EBP is untouched.
 *
 * Lifting them as their 32-bit cousins looks harmless while a push and a pop
 * are paired, because the stack still balances. The register does not: a
 * 32-bit pop into ebp replaces the whole of it with the zero-extended word, so
 * `push bp ... pop bp ... leave` came back with ebp = 0x0000FD48 instead of
 * 0x022AFD48, handed that to esp, and the next stack read was at 64 KB. This
 * game's sprite code is full of 16-bit register traffic; that is where it bit.
 */
#define PUSH16(sp, val) do { \
    uint16_t _pv = (uint16_t)(val); \
    (sp) -= 2; \
    MEM16(sp) = _pv; \
} while(0)

static inline uint16_t _pop16(uint32_t *sp) {
    uint16_t v = MEM16(*sp);
    *sp += 2;
    return v;
}
#define POP16_VAL(sp) _pop16(&(sp))

#define PUSHAD() do { \
    uint32_t _tmp_esp = esp; \
    PUSH32(esp, eax); PUSH32(esp, ecx); PUSH32(esp, edx); PUSH32(esp, ebx); \
    PUSH32(esp, _tmp_esp); PUSH32(esp, ebp); PUSH32(esp, esi); PUSH32(esp, edi); \
} while(0)

#define POPAD() do { \
    edi = POP32_VAL(esp); esi = POP32_VAL(esp); ebp = POP32_VAL(esp); \
    esp += 4; /* skip saved ESP */ \
    ebx = POP32_VAL(esp); edx = POP32_VAL(esp); ecx = POP32_VAL(esp); eax = POP32_VAL(esp); \
} while(0)

/* ============================================================
 * Condition Macros
 *
 * Pattern-matched from flag-setter (cmp/test/sub/etc.) to
 * flag-consumer (jcc/setcc/cmovcc).
 * ============================================================ */

/* Compare-based conditions (from cmp a, b) */
#define CMP_EQ(a, b)   ((uint32_t)(a) == (uint32_t)(b))
#define CMP_NE(a, b)   ((uint32_t)(a) != (uint32_t)(b))
#define CMP_B(a, b)    ((uint32_t)(a) < (uint32_t)(b))      /* unsigned < */
#define CMP_BE(a, b)   ((uint32_t)(a) <= (uint32_t)(b))     /* unsigned <= */
#define CMP_A(a, b)    ((uint32_t)(a) > (uint32_t)(b))      /* unsigned > */
#define CMP_AE(a, b)   ((uint32_t)(a) >= (uint32_t)(b))     /* unsigned >= */
#define CMP_L(a, b)    ((int32_t)(a) < (int32_t)(b))        /* signed < */
#define CMP_LE(a, b)   ((int32_t)(a) <= (int32_t)(b))       /* signed <= */
#define CMP_G(a, b)    ((int32_t)(a) > (int32_t)(b))        /* signed > */
#define CMP_GE(a, b)   ((int32_t)(a) >= (int32_t)(b))       /* signed >= */
#define CMP_S(a, b)    ((int32_t)((uint32_t)(a) - (uint32_t)(b)) < 0)  /* sign flag */
#define CMP_NS(a, b)   ((int32_t)((uint32_t)(a) - (uint32_t)(b)) >= 0)
/* Overflow of a - b: the operands differ in sign and the result's sign differs from a's. */
#define CMP_O(a, b)    (((((uint32_t)(a) ^ (uint32_t)(b)) & ((uint32_t)(a) ^ ((uint32_t)(a) - (uint32_t)(b)))) >> 31) != 0)
#define CMP_NO(a, b)   (!CMP_O(a, b))
#define CMP_P(a, b)    0  /* TODO: parity */
#define CMP_NP(a, b)   1

/* Test-based conditions (from test a, b) */
#define TEST_Z(a, b)   (((uint32_t)(a) & (uint32_t)(b)) == 0)
#define TEST_NZ(a, b)  (((uint32_t)(a) & (uint32_t)(b)) != 0)
#define TEST_S(a, b)   ((int32_t)((uint32_t)(a) & (uint32_t)(b)) < 0)
#define TEST_NS(a, b)  ((int32_t)((uint32_t)(a) & (uint32_t)(b)) >= 0)
#define TEST_G(a, b)   ((int32_t)((uint32_t)(a) & (uint32_t)(b)) > 0)
#define TEST_LE(a, b)  ((int32_t)((uint32_t)(a) & (uint32_t)(b)) <= 0)

/* Bit test (from bt) */
#define BT_CF(base, bit) (((uint32_t)(base) >> ((uint32_t)(bit) & 31)) & 1)

/*
 * Runtime flag kind.
 *
 * A jcc is normally paired with its flag-setter at lift time, but the setter
 * is not always statically known: MSVC routinely branches into a block whose
 * predecessors set the flags with different instructions (the signed-modulo
 * idiom `and/jns/dec/or/inc/je` is one join, 64-bit compares another). The
 * lifter used to fall back to a stale _cf at those sites, which made the
 * branch read whatever carry happened to be lying around.
 *
 * _flag_a/_flag_b already survive across blocks -- they are plain function
 * locals -- so recording which *kind* of instruction wrote them is enough to
 * evaluate any condition exactly, wherever the branch turns up.
 */
enum {
    FK_NONE = 0,
    FK_CMP,     /* cmp, sub       -- a - b            */
    FK_ADD,     /* add            -- a + b            */
    FK_TEST,    /* and/or/xor/test/shift -- a & b     */
    FK_BT,      /* bt             -- CF = bit b of a  */
    FK_FCOM,    /* fcom           -- a is -1/0/1, 2 = unordered */
    /* INC and DEC are ADD and SUB that do NOT write CF. No condition can tell
     * them apart (a jcc reading CF after an inc is reading a flag the
     * instruction never wrote), but PUSHFD can: it has to report the carry
     * that was already there rather than the one the addition would have
     * produced. */
    FK_INC,     /* inc            -- a + b, CF preserved */
    FK_DEC,     /* dec            -- a - b, CF preserved */
    /* The flags as a literal word, from POPFD. Nothing is derived: every flag
     * is read from its own bit. The lazy triple cannot express an arbitrary
     * combination of flags, and a program that restores a saved EFLAGS is
     * asking for exactly that. */
    FK_EFLAGS
};

/* A NARROW setter's kind carries its left-align shift (24 for 8-bit, 16 for
 * 16-bit) in bits 8 and up. CF, ZF, SF and OF come out of the left-aligned
 * operands at 32 bits unchanged (lift32's _flag_capture); PF and AF are read
 * off the result's LOW byte, and only the shift says where that byte is. The
 * lifter knows the width statically, but a jcc at a join point reads the kind
 * at runtime, and there `fnstsw ax; test ah, 5; jp` -- MSVC's `x < 0.0` --
 * needs the parity of AH. Every reader masks the kind with FK_KIND. */
#define FK_NARROW(k, shift) ((uint32_t)(k) | ((uint32_t)(shift) << 8))
#define FK_KIND(k)          ((k) & 0xFFu)
#define FK_SHIFT(k)         ((k) >> 8)

enum {
    CC_E = 0, CC_NE, CC_S, CC_NS, CC_G, CC_GE, CC_L, CC_LE,
    CC_A, CC_AE, CC_B, CC_BE, CC_O, CC_NO, CC_P, CC_NP
};

static inline uint32_t recomp_parity8(uint8_t v);

static inline int recomp_cond(uint32_t kind, uint32_t a, uint32_t b, int cc) {
    uint32_t r, sh = FK_SHIFT(kind);
    int zf, sf, cf, of, pf;

    kind = FK_KIND(kind);
    if (kind == FK_EFLAGS) {
        cf = (int)(a & 1u);
        pf = (int)((a >> 2) & 1u);
        zf = (int)((a >> 6) & 1u);
        sf = (int)((a >> 7) & 1u);
        of = (int)((a >> 11) & 1u);
        goto decide;
    }

    if (kind == FK_FCOM) {
        int32_t v = (int32_t)a;          /* -1 less, 0 equal, 1 greater, 2 unordered */
        if (v == 2) {                    /* NaN: ZF = PF = CF = 1, as fcomi/sahf leave them */
            switch (cc) {
            case CC_E: case CC_B: case CC_BE: case CC_P: return 1;
            default:                                     return 0;
            }
        }
        switch (cc) {
        case CC_NP:               return 1;
        case CC_E:                return v == 0;
        case CC_NE:               return v != 0;
        case CC_B:  case CC_L:    return v <  0;
        case CC_BE: case CC_LE:   return v <= 0;
        case CC_A:  case CC_G:    return v >  0;
        case CC_AE: case CC_GE:   return v >= 0;
        default:                  return 0;
        }
    }

    switch (kind) {
    case FK_ADD:
    case FK_INC:                          /* CF here is the ADD's; after INC the
                                             real CF is the preserved one --
                                             see recomp_cond_cf */
        r  = a + b;
        cf = (r < a);
        of = (int)((~(a ^ b) & (a ^ r)) >> 31);
        break;
    case FK_TEST:
        r  = a & b;
        cf = 0;
        of = 0;
        break;
    case FK_BT:
        r  = 0;
        cf = (int)((a >> (b & 31)) & 1u);
        of = 0;
        break;
    default:                              /* FK_CMP, FK_DEC and FK_NONE */
        r  = a - b;
        cf = (a < b);
        of = (int)(((a ^ b) & (a ^ r)) >> 31);
        break;
    }
    zf = (r == 0);
    sf = (int)(r >> 31);
    pf = (int)recomp_parity8((uint8_t)(r >> sh));

decide:
    switch (cc) {
    case CC_E:   return zf;
    case CC_NE:  return !zf;
    case CC_S:   return sf;
    case CC_NS:  return !sf;
    case CC_G:   return !zf && (sf == of);
    case CC_GE:  return sf == of;
    case CC_L:   return sf != of;
    case CC_LE:  return zf || (sf != of);
    case CC_A:   return !cf && !zf;
    case CC_AE:  return !cf;
    case CC_B:   return cf;
    case CC_BE:  return cf || zf;
    case CC_O:   return of;
    case CC_NO:  return !of;
    case CC_P:   return pf;
    case CC_NP:  return !pf;
    }
    return 0;
}

/* recomp_cond, with the carry that inc/dec PRESERVE. `cmp; inc; jae` reads
 * the cmp's CF, which the lifted code still has in _cf; deriving it from the
 * inc's operands is wrong (it corrupted MSVC 6's small-block heap). */
/* x87 compare outcome: -1 less, 0 equal, 1 greater, 2 unordered (a NaN). */
#define FPU_CMP(x, y) ((x) < (y) ? -1 : (x) > (y) ? 1 : (x) == (y) ? 0 : 2)

static inline int recomp_cond_cf(uint32_t kind, uint32_t a, uint32_t b, int cc,
                                 uint32_t cf) {
    if ((FK_KIND(kind) == FK_INC || FK_KIND(kind) == FK_DEC) &&
        (cc == CC_B || cc == CC_AE || cc == CC_A || cc == CC_BE)) {
        int zf = recomp_cond(kind, a, b, CC_E);
        switch (cc) {
        case CC_B:  return cf != 0;
        case CC_AE: return cf == 0;
        case CC_A:  return cf == 0 && !zf;
        default:    return cf != 0 || zf;
        }
    }
    return recomp_cond(kind, a, b, cc);
}

/* CF as adc/sbb read it: derived from an add/sub/cmp's operands (which do
 * not write `_cf`), otherwise the `_cf` the instruction kept (adc, sbb, shifts,
 * logic ops, inc/dec, popfd/sahf). The lifter's precise_carry option. */
static inline uint32_t recomp_carry(uint32_t kind, uint32_t a, uint32_t b, uint32_t cf) {
    switch (FK_KIND(kind)) {
    case FK_ADD: return a + b < a;
    case FK_CMP: return a < b;
    default:     return cf;
    }
}

/* Bit 1 reads as 1 on every x86, and IF is set in any process this runtime
 * will ever host. A PUSHFD that omitted them differs from hardware in a way
 * guest CPU-detection code notices. */
#define RECOMP_EFLAGS_FIXED 0x00000202u

static inline uint32_t recomp_parity8(uint8_t v) {
    v ^= (uint8_t)(v >> 4);
    v ^= (uint8_t)(v >> 2);
    v ^= (uint8_t)(v >> 1);
    return (uint32_t)((~v) & 1u);
}

/* PF of a lazily captured result: parity of its low byte. `shift` undoes the
 * left-alignment _flag_capture gives narrow operands (24 for 8-bit). */
#define RECOMP_PF(r, shift) ((int)recomp_parity8((uint8_t)((uint32_t)(r) >> (shift))))

/* The six arithmetic flags as a word, given a result and the three that do
 * not come from it. */
static inline uint32_t recomp_flags_pack(uint32_t r, uint32_t cf, uint32_t af,
                                         uint32_t of) {
    uint32_t e = RECOMP_EFLAGS_FIXED | (cf & 1u) | ((af & 1u) << 4) | ((of & 1u) << 11);
    if (r == 0) e |= 0x40u;               /* ZF */
    e |= (r >> 31) << 7;                  /* SF */
    e |= recomp_parity8((uint8_t)r) << 2; /* PF */
    return e;
}

/*
 * The flags as one word: PUSHFD, and the flag oracle the differential harness
 * compares against.
 *
 * The lazy tuple already holds everything the six arithmetic flags derive
 * from, so this is that derivation done all at once instead of one flag at a
 * time. CF is the exception: the tuple carries it for ADD/SUB/CMP, while
 * shifts, rotates, NEG, STC/CLC/CMC and ADC/SBB maintain the running `_cf` --
 * so every other kind takes the carry it is handed.
 *
 * AF exists here and nowhere else in the 32-bit model. It costs nothing --
 * (a ^ b ^ r) bit 4 comes out of operands the tuple already stored -- and
 * PUSHFD round-trips it, so code that saves and restores flags around a call
 * does not silently drop a flag it never mentions. Hardware leaves AF
 * undefined after a logic op; this reports 0 there, deterministically.
 */
static inline uint32_t recomp_eflags(uint32_t kind, uint32_t a, uint32_t b,
                                     uint32_t cf_in, int df) {
    uint32_t r, e, sh = FK_SHIFT(kind);
    uint32_t cf = cf_in & 1u, of = 0, af = 0;

    kind = FK_KIND(kind);

    if (kind == FK_EFLAGS) {
        /* Already a word. DF still comes from `_df`: a CLD after the POPFD
           moved it and the saved word did not follow.

           AC (18) and ID (21) ride along because a POPFD/PUSHFD pair is how
           every 1990s binary asks the CPU a yes/no question about itself: write
           the bit, read it back, see whether it stuck. ID is the CPUID probe --
           drop it here and the readback matches the original word, the program
           concludes there is no CPUID, and a game that needs MMX puts up "This
           CPU does not have an MMX unit" and quits. They are the only two bits
           user mode can actually toggle, so carrying them costs one mask. */
        e = (a & (1u | 4u | 0x10u | 0x40u | 0x80u | 0x800u
                  | 0x40000u | 0x200000u)) | RECOMP_EFLAGS_FIXED;
        return (df < 0) ? (e | 0x400u) : e;
    }

    switch (kind) {
    case FK_ADD: case FK_INC:
        r  = a + b;
        if (kind == FK_ADD) cf = (r < a);
        of = (~(a ^ b) & (a ^ r)) >> 31;
        af = ((a ^ b ^ r) >> (sh + 4)) & 1u;
        break;
    case FK_TEST:
        /* and/or/xor/test clear CF (the lifter stores that); a shift leaves
           the bit it shifted out in `_cf`. Either way the carry is `cf_in`. */
        r  = a & b;
        break;
    case FK_BT:
        r  = 0;
        cf = (a >> (b & 31)) & 1u;
        break;
    case FK_NONE: case FK_FCOM:
        /* Nothing has written the arithmetic flags (or fcom wrote a comparison
           this word cannot express). Report the carry we hold and leave the
           rest clear: deriving ZF and PF from an invented zero result would
           report two flags as set that no instruction ever set. */
        e = RECOMP_EFLAGS_FIXED | cf;
        return (df < 0) ? (e | 0x400u) : e;
    default:                              /* FK_CMP, FK_DEC */
        r  = a - b;
        if (kind == FK_CMP) cf = (a < b);
        of = ((a ^ b) & (a ^ r)) >> 31;
        af = ((a ^ b ^ r) >> (sh + 4)) & 1u;
        break;
    }

    e = recomp_flags_pack(r, cf, af, of);
    if (sh)                               /* narrow: PF of the low byte, at bit sh */
        e = (e & ~4u) | (recomp_parity8((uint8_t)(r >> sh)) << 2);
    if (df < 0) e |= 0x400u;              /* DF */
    return e;
}

/*
 * ADC and SBB take the carry as a THIRD input, and the lazy triple cannot hold
 * one: folding it into the source (`a + (b + c)`) loses it whenever b is all
 * ones, and modelling `a - b - c` as a SUB of `b + c` gets the borrow wrong
 * whenever a != b. So they compute their flags at the instruction and hand
 * back the finished word, which the caller stores as FK_EFLAGS -- the same
 * escape hatch POPFD uses.
 */
static inline uint32_t recomp_flags_adc(uint32_t a, uint32_t b, uint32_t c) {
    uint32_t r = a + b + c;
    return recomp_flags_pack(r,
                             c ? (r <= a) : (r < a),
                             ((a ^ b ^ r) >> 4) & 1u,
                             (~(a ^ b) & (a ^ r)) >> 31);
}

static inline uint32_t recomp_flags_sbb(uint32_t a, uint32_t b, uint32_t c) {
    uint32_t r = a - b - c;
    return recomp_flags_pack(r,
                             c ? (a <= b) : (a < b),
                             ((a ^ b ^ r) >> 4) & 1u,
                             ((a ^ b) & (a ^ r)) >> 31);
}

/*
 * A rotate writes CF and leaves ZF, SF and OF alone.
 *
 * The lazy flag triple cannot say that: it holds one instruction's operands, so
 * publishing the rotate's carry through it would have to throw away the compare
 * that set ZF, and NOT publishing it leaves a following `jae`/`jb` reading the
 * carry of whatever came before. The RLE sprite decoder in Gizmos & Gadgets
 * does exactly this -- `sub bx,cx; rcr cl,1; rep movsw; jae` -- where the jae
 * is asking whether the count was odd, and answering it with the sub's borrow
 * ran the decoder off the end of both the sprite and the framebuffer.
 *
 * So a rotate freezes the flags into a word, the same escape hatch ADC and
 * POPFD use, and overwrites just the carry.
 *
 * OF is carried over rather than recomputed: x86 only defines it for a rotate
 * of exactly 1, and no compiler emits a branch on it.
 */
static inline uint32_t recomp_eflags_setcf(uint32_t kind, uint32_t a, uint32_t b,
                                           uint32_t cf, int df) {
    return (recomp_eflags(kind, a, b, cf, df) & ~1u) | (cf & 1u);
}

/* ============================================================
 * Bit Manipulation
 * ============================================================ */

#define ROL32(val, n) (((uint32_t)(val) << ((n) & 31)) | ((uint32_t)(val) >> (32 - ((n) & 31))))
#define ROR32(val, n) (((uint32_t)(val) >> ((n) & 31)) | ((uint32_t)(val) << (32 - ((n) & 31))))
#define BSWAP32(val)  ( (((val) & 0xFF) << 24) | (((val) & 0xFF00) << 8) | \
                        (((val) >> 8) & 0xFF00) | (((val) >> 24) & 0xFF) )

/* ============================================================
 * MMX
 *
 * Eight 64-bit registers holding packed bytes/words/dwords. On real hardware
 * they alias the x87 stack, which is why MMX code must `emms` before touching
 * the FPU again; we keep the two apart, so `emms` is a no-op here and code that
 * deliberately interleaved them would behave differently. POD does not: it is
 * the MMX build, and its rasterizer is a well-formed MMX block per span.
 *
 * Global, like the rest of the register file here; a multi-threaded target
 * wants them thread-local instead.
 * ============================================================ */

#define MM_W(v, i)  ((int16_t)((uint64_t)(v) >> ((i) * 16)))
#define MM_D(v, i)  ((int32_t)((uint64_t)(v) >> ((i) * 32)))
#define MM_PUT_W(i, x) ((uint64_t)(uint16_t)(x) << ((i) * 16))
#define MM_PUT_D(i, x) ((uint64_t)(uint32_t)(x) << ((i) * 32))


/* Clang lowers these exact integer lanes to the host's packed instructions.
 * Raw MMX storage stays uint64_t; no floating-point state or arithmetic is used. */
#if defined(__clang__)
#if __has_builtin(__builtin_elementwise_add_sat) && __has_builtin(__builtin_elementwise_sub_sat) && __has_builtin(__builtin_elementwise_min) && __has_builtin(__builtin_elementwise_max)
#define RECOMP_MMX_PACKED 1
typedef uint8_t mmx_u8x8 __attribute__((vector_size(8)));
typedef uint16_t mmx_u16x4 __attribute__((vector_size(8)));
typedef int16_t mmx_s16x4 __attribute__((vector_size(8)));
typedef uint32_t mmx_u32x2 __attribute__((vector_size(8)));
typedef int32_t mmx_s32x2 __attribute__((vector_size(8)));
typedef int32_t mmx_s32x4 __attribute__((vector_size(16)));
typedef uint32_t mmx_u32x4 __attribute__((vector_size(16)));
typedef int16_t mmx_s16x8 __attribute__((vector_size(16)));
typedef union {
    uint64_t raw;
    mmx_u8x8 bytes;
    mmx_u16x4 words;
    mmx_s16x4 signed_words;
    mmx_u32x2 dwords;
    mmx_s32x2 signed_dwords;
} mmx_bits;
#define MMX_VIEW(member, value) ((mmx_bits){.raw = (value)}.member)
#define MMX_RAW(member, value) ((mmx_bits){.member = (value)}.raw)
#endif
#endif

static inline int16_t mmx_sat16(int32_t v) {
    return (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
}

static inline uint64_t mmx_paddw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(words, MMX_VIEW(words, a) + MMX_VIEW(words, b));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, MM_W(a, i) + MM_W(b, i));
    return r;
#endif
}
static inline uint64_t mmx_psubw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(words, MMX_VIEW(words, a) - MMX_VIEW(words, b));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, MM_W(a, i) - MM_W(b, i));
    return r;
#endif
}
static inline uint64_t mmx_paddd(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(dwords, MMX_VIEW(dwords, a) + MMX_VIEW(dwords, b));
#else
    return MM_PUT_D(0, MM_D(a, 0) + MM_D(b, 0)) | MM_PUT_D(1, MM_D(a, 1) + MM_D(b, 1));
#endif
}
static inline uint64_t mmx_psubd(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(dwords, MMX_VIEW(dwords, a) - MMX_VIEW(dwords, b));
#else
    return MM_PUT_D(0, MM_D(a, 0) - MM_D(b, 0)) | MM_PUT_D(1, MM_D(a, 1) - MM_D(b, 1));
#endif
}
static inline uint64_t mmx_paddsw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(signed_words, __builtin_elementwise_add_sat(MMX_VIEW(signed_words, a), MMX_VIEW(signed_words, b)));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, mmx_sat16(MM_W(a, i) + MM_W(b, i)));
    return r;
#endif
}
static inline uint64_t mmx_psubsw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(signed_words, __builtin_elementwise_sub_sat(MMX_VIEW(signed_words, a), MMX_VIEW(signed_words, b)));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, mmx_sat16(MM_W(a, i) - MM_W(b, i)));
    return r;
#endif
}
/* High half of each signed 16x16 product -- the fixed-point multiply an MMX
 * rasterizer scales colour and texture coordinates with. */
static inline uint64_t mmx_pmulhw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    mmx_s32x4 product = __builtin_convertvector(MMX_VIEW(signed_words, a), mmx_s32x4) * __builtin_convertvector(MMX_VIEW(signed_words, b), mmx_s32x4);
    return MMX_RAW(signed_words, __builtin_convertvector(product >> 16, mmx_s16x4));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++)
        r |= MM_PUT_W(i, (int16_t)(((int32_t)MM_W(a, i) * MM_W(b, i)) >> 16));
    return r;
#endif
}
static inline uint64_t mmx_pmullw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(words, MMX_VIEW(words, a) * MMX_VIEW(words, b));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, (int16_t)((int32_t)MM_W(a, i) * MM_W(b, i)));
    return r;
#endif
}
/* Two dwords, each the sum of a neighbouring pair of 16x16 products. */
static inline uint64_t mmx_pmaddwd(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    mmx_s32x4 product = __builtin_convertvector(MMX_VIEW(signed_words, a), mmx_s32x4) * __builtin_convertvector(MMX_VIEW(signed_words, b), mmx_s32x4);
    mmx_u32x4 bits = __builtin_convertvector(product, mmx_u32x4);
    /* The exceptional (-32768 * -32768) pair wraps to 0x80000000. */
    return MMX_RAW(dwords, __builtin_shufflevector(bits, bits, 0, 2) + __builtin_shufflevector(bits, bits, 1, 3));
#else
    uint64_t r = 0;
    for (int i = 0; i < 2; i++)
        r |= MM_PUT_D(i, (int32_t)MM_W(a, i*2) * MM_W(b, i*2)
                       + (int32_t)MM_W(a, i*2+1) * MM_W(b, i*2+1));
    return r;
#endif
}
/* Interleave: the low (or high) halves of a and b, a's element first. */
static inline uint64_t mmx_punpcklwd(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(words, __builtin_shufflevector(MMX_VIEW(words, a), MMX_VIEW(words, b), 0, 4, 1, 5));
#else
    return MM_PUT_W(0, MM_W(a,0)) | MM_PUT_W(1, MM_W(b,0))
         | MM_PUT_W(2, MM_W(a,1)) | MM_PUT_W(3, MM_W(b,1));
#endif
}
static inline uint64_t mmx_punpckhwd(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(words, __builtin_shufflevector(MMX_VIEW(words, a), MMX_VIEW(words, b), 2, 6, 3, 7));
#else
    return MM_PUT_W(0, MM_W(a,2)) | MM_PUT_W(1, MM_W(b,2))
         | MM_PUT_W(2, MM_W(a,3)) | MM_PUT_W(3, MM_W(b,3));
#endif
}
static inline uint64_t mmx_punpcklbw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(bytes, __builtin_shufflevector(MMX_VIEW(bytes, a), MMX_VIEW(bytes, b), 0, 8, 1, 9, 2, 10, 3, 11));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) {
        r |= (uint64_t)(uint8_t)(a >> (i*8)) << (i*16);
        r |= (uint64_t)(uint8_t)(b >> (i*8)) << (i*16 + 8);
    }
    return r;
#endif
}
static inline uint64_t mmx_punpckhbw(uint64_t a, uint64_t b) {
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) {
        r |= (uint64_t)(uint8_t)(a >> (32 + i*8)) << (i*16);
        r |= (uint64_t)(uint8_t)(b >> (32 + i*8)) << (i*16 + 8);
    }
    return r;
}
static inline uint64_t mmx_punpckldq(uint64_t a, uint64_t b) {
    return (uint64_t)(uint32_t)a | ((uint64_t)(uint32_t)b << 32);
}
static inline uint64_t mmx_punpckhdq(uint64_t a, uint64_t b) {
    return (uint64_t)(uint32_t)(a >> 32) | ((uint64_t)(uint32_t)(b >> 32) << 32);
}
/* Shifts. A count wider than the element is not a wrapped shift on x86: the
 * logical forms produce zero and the arithmetic ones produce the sign. */
static inline uint64_t mmx_psllq(uint64_t a, uint32_t c) { return c > 63 ? 0 : a << c; }
static inline uint64_t mmx_psrlq(uint64_t a, uint32_t c) { return c > 63 ? 0 : a >> c; }
static inline uint64_t mmx_psllw(uint64_t a, uint32_t c) {
#ifdef RECOMP_MMX_PACKED
    if (c > 15) return 0;
    return MMX_RAW(words, MMX_VIEW(words, a) << c);
#else
    uint64_t r = 0;
    if (c > 15) return 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, (uint16_t)MM_W(a, i) << c);
    return r;
#endif
}
static inline uint64_t mmx_psrlw(uint64_t a, uint32_t c) {
#ifdef RECOMP_MMX_PACKED
    if (c > 15) return 0;
    return MMX_RAW(words, MMX_VIEW(words, a) >> c);
#else
    uint64_t r = 0;
    if (c > 15) return 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, (uint16_t)MM_W(a, i) >> c);
    return r;
#endif
}
static inline uint64_t mmx_psraw(uint64_t a, uint32_t c) {
#ifdef RECOMP_MMX_PACKED
    if (c > 15) c = 15;
    return MMX_RAW(signed_words, MMX_VIEW(signed_words, a) >> c);
#else
    uint64_t r = 0;
    if (c > 15) c = 15;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, (int16_t)(MM_W(a, i) >> c));
    return r;
#endif
}
static inline uint64_t mmx_pslld(uint64_t a, uint32_t c) {
    if (c > 31) return 0;
    return MM_PUT_D(0, (uint32_t)MM_D(a,0) << c) | MM_PUT_D(1, (uint32_t)MM_D(a,1) << c);
}
static inline uint64_t mmx_psrld(uint64_t a, uint32_t c) {
    if (c > 31) return 0;
    return MM_PUT_D(0, (uint32_t)MM_D(a,0) >> c) | MM_PUT_D(1, (uint32_t)MM_D(a,1) >> c);
}
static inline uint64_t mmx_psrad(uint64_t a, uint32_t c) {
#ifdef RECOMP_MMX_PACKED
    if (c > 31) c = 31;
    return MMX_RAW(signed_dwords, MMX_VIEW(signed_dwords, a) >> c);
#else
    if (c > 31) c = 31;
    return MM_PUT_D(0, MM_D(a,0) >> c) | MM_PUT_D(1, MM_D(a,1) >> c);
#endif
}
/* Pack with saturation, a's elements low. */
/* These packed forms have a different CFG from their scalar PGO ancestors. */
static inline __attribute__((no_profile_instrument_function)) uint64_t mmx_packssdw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    mmx_s32x4 values = __builtin_shufflevector(MMX_VIEW(signed_dwords, a), MMX_VIEW(signed_dwords, b), 0, 1, 2, 3);
    values = __builtin_elementwise_max(values, (mmx_s32x4){-32768,-32768,-32768,-32768});
    values = __builtin_elementwise_min(values, (mmx_s32x4){32767,32767,32767,32767});
    return MMX_RAW(signed_words, __builtin_convertvector(values, mmx_s16x4));
#else
    return MM_PUT_W(0, mmx_sat16(MM_D(a,0))) | MM_PUT_W(1, mmx_sat16(MM_D(a,1)))
         | MM_PUT_W(2, mmx_sat16(MM_D(b,0))) | MM_PUT_W(3, mmx_sat16(MM_D(b,1)));
#endif
}
static inline uint64_t mmx_packuswb(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    mmx_s16x8 words = __builtin_shufflevector(MMX_VIEW(signed_words, a), MMX_VIEW(signed_words, b), 0, 1, 2, 3, 4, 5, 6, 7);
    words = __builtin_elementwise_max(words, (mmx_s16x8){0,0,0,0,0,0,0,0});
    words = __builtin_elementwise_min(words, (mmx_s16x8){255,255,255,255,255,255,255,255});
    return MMX_RAW(bytes, __builtin_convertvector(words, mmx_u8x8));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) {
        int16_t v = MM_W(a, i); uint8_t p = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
        r |= (uint64_t)p << (i * 8);
        v = MM_W(b, i);         p = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
        r |= (uint64_t)p << (32 + i * 8);
    }
    return r;
#endif
}
static inline uint64_t mmx_pcmpeqw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(signed_words, MMX_VIEW(words, a) == MMX_VIEW(words, b));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, MM_W(a,i) == MM_W(b,i) ? 0xFFFF : 0);
    return r;
#endif
}
static inline __attribute__((no_profile_instrument_function)) uint64_t mmx_pcmpgtw(uint64_t a, uint64_t b) {
#ifdef RECOMP_MMX_PACKED
    return MMX_RAW(signed_words, MMX_VIEW(signed_words, a) > MMX_VIEW(signed_words, b));
#else
    uint64_t r = 0;
    for (int i = 0; i < 4; i++) r |= MM_PUT_W(i, MM_W(a,i) > MM_W(b,i) ? 0xFFFF : 0);
    return r;
#endif
}
static inline uint64_t mmx_pcmpeqd(uint64_t a, uint64_t b) {
    return MM_PUT_D(0, MM_D(a,0) == MM_D(b,0) ? -1 : 0) | MM_PUT_D(1, MM_D(a,1) == MM_D(b,1) ? -1 : 0);
}
static inline uint64_t mmx_pcmpgtd(uint64_t a, uint64_t b) {
    return MM_PUT_D(0, MM_D(a,0) > MM_D(b,0) ? -1 : 0) | MM_PUT_D(1, MM_D(a,1) > MM_D(b,1) ? -1 : 0);
}

/* Bytes, and the unsigned-saturating forms. A software renderer's translucency
 * is one paddusb per pixel: the texel's colour added to the screen's, each
 * channel stopping at 255. */
#define MM_B(v, i)     ((int8_t)((uint64_t)(v) >> ((i) * 8)))
#define MM_UB(v, i)    ((uint8_t)((uint64_t)(v) >> ((i) * 8)))
#define MM_UW(v, i)    ((uint16_t)((uint64_t)(v) >> ((i) * 16)))
#define MM_PUT_B(i, x) ((uint64_t)(uint8_t)(x) << ((i) * 8))
#define MMX_LANES(n, put, expr) do { for (int i = 0; i < (n); i++) r |= put(i, (expr)); } while (0)
static inline int mmx_clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

static inline uint64_t mmx_paddb(uint64_t a, uint64_t b)   { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, MM_UB(a,i) + MM_UB(b,i)); return r; }
static inline uint64_t mmx_psubb(uint64_t a, uint64_t b)   { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, MM_UB(a,i) - MM_UB(b,i)); return r; }
static inline uint64_t mmx_paddsb(uint64_t a, uint64_t b)  { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, mmx_clamp(MM_B(a,i) + MM_B(b,i), -128, 127)); return r; }
static inline uint64_t mmx_psubsb(uint64_t a, uint64_t b)  { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, mmx_clamp(MM_B(a,i) - MM_B(b,i), -128, 127)); return r; }
static inline uint64_t mmx_paddusb(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, mmx_clamp(MM_UB(a,i) + MM_UB(b,i), 0, 255)); return r; }
static inline uint64_t mmx_psubusb(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, mmx_clamp(MM_UB(a,i) - MM_UB(b,i), 0, 255)); return r; }
static inline uint64_t mmx_paddusw(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(4, MM_PUT_W, mmx_clamp(MM_UW(a,i) + MM_UW(b,i), 0, 65535)); return r; }
static inline uint64_t mmx_psubusw(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(4, MM_PUT_W, mmx_clamp(MM_UW(a,i) - MM_UW(b,i), 0, 65535)); return r; }
static inline uint64_t mmx_pcmpeqb(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, MM_UB(a,i) == MM_UB(b,i) ? 0xFF : 0); return r; }
static inline uint64_t mmx_pcmpgtb(uint64_t a, uint64_t b) { uint64_t r = 0; MMX_LANES(8, MM_PUT_B, MM_B(a,i) > MM_B(b,i) ? 0xFF : 0); return r; }
/* Signed words to signed bytes with saturation, a's elements low. */
static inline uint64_t mmx_packsswb(uint64_t a, uint64_t b) {
    uint64_t r = 0;
    MMX_LANES(4, MM_PUT_B, mmx_clamp(MM_W(a,i), -128, 127));
    for (int i = 0; i < 4; i++) r |= MM_PUT_B(4 + i, mmx_clamp(MM_W(b,i), -128, 127));
    return r;
}

/* ============================================================
 * SSE / SSE2
 *
 * Eight 128-bit registers, global like the rest of the register file; the
 * lifter emits _xmm[n] (tools/lift/lift32_sse.py has the instruction side).
 * Lanes are read through the union, so a register holds whatever bits were
 * put in it and a float lane never passes through the x87.
 *
 * MXCSR is kept for ldmxcsr/stmxcsr and its rounding field drives cvtss2si,
 * cvtsd2si and cvtps2pi. Exceptions stay masked, FTZ/DAZ are not modelled.
 * ============================================================ */

typedef union {
    float    f32[4];
    double   f64[2];
    uint64_t u64[2];
    uint32_t u32[4];
    int32_t  i32[4];
    uint16_t u16[8];
    int16_t  i16[8];
    uint8_t  u8[16];
} xmm_t;

extern VOID_HIDDEN xmm_t    g_xmm[8];
extern VOID_HIDDEN uint32_t g_mxcsr;

static inline xmm_t xmm_ld(uint32_t a) { xmm_t v; memcpy(&v, (const void*)ADDR(a), 16); return v; }
static inline void  xmm_st(uint32_t a, xmm_t v) { memcpy((void*)ADDR(a), &v, 16); }
static inline float    sse_f32(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }
static inline uint32_t sse_u32(float f) { uint32_t u; memcpy(&u, &f, 4); return u; }
static inline double   sse_f64(uint64_t u) { double d; memcpy(&d, &u, 8); return d; }
static inline uint64_t sse_u64(double d) { uint64_t u; memcpy(&u, &d, 8); return u; }

/* float/double -> int32 as cvt(t)ss2si does: NaN or out of range gives the
 * "integer indefinite" 0x80000000. Rounding is MXCSR's (bits 13-14), or
 * toward zero for the cvtt forms. */
static inline int32_t sse_cvt_i32(double v, int chop) {
    if (!chop)
        switch ((g_mxcsr >> 13) & 3) {
        case 0: v = nearbyint(v); break;            /* the host's default: nearest-even */
        case 1: v = floor(v); break;
        case 2: v = ceil(v); break;
        default: v = trunc(v); break;
        }
    if (!(v > -2147483649.0 && v < 2147483648.0)) return (int32_t)0x80000000u;
    return (int32_t)v;
}

/* minss/maxss: the SECOND operand whenever the compare is false, NaN or
 * equal (+0 vs -0) included. A C fminf/fmaxf would not. */
static inline float  sse_minf(float a, float b) { return a < b ? a : b; }
static inline float  sse_maxf(float a, float b) { return a > b ? a : b; }
static inline double sse_mind(double a, double b) { return a < b ? a : b; }
static inline double sse_maxd(double a, double b) { return a > b ? a : b; }

/* comiss/ucomiss/comisd/ucomisd and fcomi: the EFLAGS word, ZF PF CF, with
 * OF SF AF clear. Unordered sets all three. */
#define SSE_COMI(a, b) ((a) < (b) ? 0x01u : (a) > (b) ? 0x00u : (a) == (b) ? 0x40u : 0x45u)

/* cmpXXps/ss predicates 0-7: eq lt le unord neq nlt nle ord. */
static inline uint32_t sse_cmp_pred(double a, double b, int p) {
    int r;
    switch (p & 7) {
    case 0: r = a == b; break;
    case 1: r = a < b; break;
    case 2: r = a <= b; break;
    case 3: r = a != a || b != b; break;
    case 4: r = !(a == b); break;
    case 5: r = !(a < b); break;
    case 6: r = !(a <= b); break;
    default: r = a == a && b == b; break;
    }
    return r ? 0xFFFFFFFFu : 0;
}

/* ============================================================
 * FPU Stack Helpers
 * ============================================================ */

/* The x87 register is 80 bits with a 64-bit mantissa; ours is a double with 53.
 * That is invisible for arithmetic but not for `fild qword / fistp qword`, the
 * era's idiom for moving 8 bytes (a packed x,y pair, a 64-bit counter): through
 * a double, a large high dword rounds away the low bits. Nocturne's clipper
 * copies vertices that way and got x = -20/65536 where the original had 0, then
 * filled a 65535-pixel span. So each slot shadows the exact int64 `fild qword`
 * loaded, and `fistp qword` stores the shadow while the slot's double still
 * equals it (nothing has computed on it since).
 *
 * selectany/weak: one shared instance, defined by the header itself, so no
 * project runtime has to grow a definition for it. */
#define RECOMP_SHARED_DATA __attribute__((weak))
#ifndef RECOMP_X87_WINDOW
extern VOID_HIDDEN int64_t g_st_i64[8];
#endif

static inline void fp_push_impl(double* st, int* top, double val) {
    /* Shift stack down, push new value */
    for (int i = 7; i > 0; i--) { st[i] = st[i-1]; g_st_i64[i] = g_st_i64[i-1]; }
    st[0] = val;
    g_st_i64[0] = 0;
    (*top)++;
}

static inline double fp_pop_impl(double* st, int* top) {
    double val = st[0];
    for (int i = 0; i < 7; i++) { st[i] = st[i+1]; g_st_i64[i] = g_st_i64[i+1]; }
    st[7] = 0.0;
    g_st_i64[7] = 0;
    (*top)--;
    return val;
}

#ifdef RECOMP_X87_WINDOW
/* Rare (the window edge): out of line, so its two block moves are not
 * copied into every push and pop. */
static __attribute__((noinline, cold)) void fp_window_recentre(void) {
    int to = RECOMP_X87_SLOTS / 2 - 4;
    memmove(g_st_win + to, g_st_win + g_fp_sp, sizeof g_st);
    memmove(g_st_i64_win + to, g_st_i64_win + g_fp_sp, sizeof g_st_i64);
    g_fp_sp = to;
}

static inline void fp_window_push(double value) {
    if (__builtin_expect(g_fp_sp <= 8, 0)) fp_window_recentre();
    --g_fp_sp;
    g_st[0] = value;
    g_st_i64[0] = 0;
    ++g_fp_top;
}

static inline double fp_window_pop(void) {
    double value = g_st[0];
    ++g_fp_sp;
    if (__builtin_expect(g_fp_sp > RECOMP_X87_SLOTS - 9, 0)) fp_window_recentre();
    /* Preserve the old model's inactive slots, including exact integer shadows. */
    g_st[7] = 0.0;
    g_st_i64[7] = 0;
    --g_fp_top;
    return value;
}
#define fp_push(val) fp_window_push((val))
#define fp_pop() fp_window_pop()
#else
#define fp_push(val) fp_push_impl(_st, &_fp_top, (val))
#define fp_pop()     fp_pop_impl(_st, &_fp_top)
#endif

/* x87 stack slots as C locals (tools/x87_locals.py): a body whose stack depth
 * is known everywhere keeps each slot and its integer shadow in a local and
 * touches the global window only at its x87 boundaries. */
#define X87_SET(s, i, v) ((s) = (double)(v), (i) = 0)
#define X87_SET_I64(s, i, v) do { int64_t _pv = (int64_t)(v); (s) = (double)_pv; (i) = _pv; } while (0)
#define X87_XCH(a, ai, b, bi) do { double _t = (a); (a) = (b); (b) = _t;     int64_t _ti = (ai); (ai) = (bi); (bi) = _ti; } while (0)
#define X87_GPUSH(s, i) do { fp_push(s); g_st_i64[0] = (i); } while (0)
#define X87_GPOP(s, i) do { (i) = g_st_i64[0]; (s) = fp_pop(); } while (0)
#ifdef RECOMP_PROTOCOL_CHECK
/* Validation builds: a rewritten body must leave the global window exactly
 * c values lower and p values higher than it found it. */
void recomp_x87_violation(uint32_t va, int found, int expected);
#define X87_CHECK_ENTER() int _x87_top0 = g_fp_top
/* u: a callee's float may pass through unseen (x87_locals.analyse_full). */
#define X87_CHECK_EXIT(va, c, p, u) do { int _x87_net = g_fp_top - _x87_top0;     if (_x87_net != (p) - (c) && !((u) && _x87_net == (p) - (c) + 1))     recomp_x87_violation((va), _x87_net, (p) - (c)); } while (0)
#else
#define X87_CHECK_ENTER() ((void)0)
#define X87_CHECK_EXIT(va, c, p, u) ((void)0)
#endif

/* fild qword: push with the exact value shadowed. */
#define fp_push_i64(v) do { int64_t _pv = (int64_t)(v); \
    fp_push((double)_pv); g_st_i64[0] = _pv; } while (0)
/* fxch st(i), keeping each slot's shadow with its value. */
#define fp_xch(i) do { double _t = _st[0]; _st[0] = _st[i]; _st[i] = _t; \
    int64_t _ti = g_st_i64[0]; g_st_i64[0] = g_st_i64[i]; g_st_i64[i] = _ti; } while (0)

/* fist/fistp round by the control word's RC field (bits 10-11), not by C's
 * truncating cast. MSVC's __ftol sets chop before its fistp, so a plain cast
 * looked right for years; Quake-lineage rasterisers deliberately run fistp in
 * nearest (the default), floor or ceil mode, and a cast shifts every span and
 * texture coordinate by up to one. */
static inline double fp_round_cw(double v, uint16_t cw) {
    switch ((cw >> 10) & 3) {
    case 0:  return nearbyint(v);   /* nearest-even: the host default mode */
    case 1:  return floor(v);
    case 2:  return ceil(v);
    default: return trunc(v);
    }
}
/* Every generated use is `(int32_t)fp_to_int(x)` (fistp dword). x86 stores the
 * integer indefinite 0x80000000 for NaN and anything outside int32 after
 * rounding; C leaves that cast undefined and ARM64 saturates. Hand the cast a
 * value it converts exactly to what the x87 would have stored. */
static inline double fp_round_i32(double v, uint16_t cw) {
    double r = fp_round_cw(v, cw);
    return (r >= -2147483648.0 && r <= 2147483647.0) ? r : -2147483648.0;
}
#define fp_to_int(v) fp_round_i32((v), _fpu_cw)

/* The control word's precision (bits 8-9) and rounding (10-11) fields.
 * Direct3D 9 sets single precision, round to nearest, on the thread that
 * creates a device without D3DCREATE_FPU_PRESERVE, as H5's does, and H5 then
 * runs that thread truncating (0x0C7F, read from the original's main thread):
 * every x87 add, subtract, multiply, divide and square root there chops its
 * result to a 24-bit significand, keeping the x87's wide exponent, and every
 * store to a float chops. H5's game data (the LAN game checksum: its own
 * decimal parser accumulates digits this way) and its simulation carry those
 * bits, so tools/build_android.py passes each such result through fp_pc and
 * each float store through fp_f32. The host stays round-to-nearest (the SSE
 * code keeps its own MXCSR rounding, as on x86): the double result is
 * rounded again here, which is exact for products and quotients of floats
 * and for sums within 29 bits of each other. The model's double is the
 * 53-bit mode (10), the Windows default; 64-bit (11) stays double. */
static inline double fp_round24(double v, unsigned rc) {
    uint64_t b;
    memcpy(&b, &v, 8);
    uint64_t low = b & 0x1FFFFFFFull;                      /* the 29 bits past a float's significand */
    if (!low || __builtin_expect((b & 0x7FF0000000000000ull) == 0x7FF0000000000000ull, 0)) return v;
    uint64_t toward_zero = b - low, away = toward_zero + 0x20000000ull;   /* a carry steps the exponent */
    switch (rc & 3) {
    case 0:  b = low > 0x10000000ull || (low == 0x10000000ull && (b & 0x20000000ull)) ? away : toward_zero; break;
    case 1:  b = b >> 63 ? away : toward_zero; break;      /* down */
    case 2:  b = b >> 63 ? toward_zero : away; break;      /* up */
    default: b = toward_zero; break;                       /* chop */
    }
    memcpy(&v, &b, 8);
    return v;
}
/* The control word as masks on a double's bits, set at every fldcw
 * (fp_set_cw) and when a thread takes the machine: an arithmetic result keeps
 * the bits of g_fp_round_mask, a float store those of g_fp_store_mask. ~0
 * keeps the double (53/64-bit precision; a store rounding to nearest), ~0x1FFFFFFF
 * chops to 24 bits (H5's 0x0C7F), 0 takes the exact rounding of the other
 * modes. H5's main thread runs chopping: one load and one AND per result. */
extern VOID_HIDDEN uint64_t g_fp_round_mask, g_fp_store_mask;
static inline void fp_cw_masks(uint16_t cw) {
    unsigned rc = (cw >> 10) & 3u;
    g_fp_round_mask = (cw & 0x300) ? ~0ull : rc == 3 ? ~0x1FFFFFFFull : 0;
    g_fp_store_mask = rc == 0 ? ~0ull : rc == 3 ? ~0x1FFFFFFFull : 0;
}
#define fp_set_cw(v) (_fpu_cw = (uint16_t)(v), fp_cw_masks(_fpu_cw))
static inline double fp_bits_and(double v, uint64_t mask) {
#if defined(__aarch64__)
    return vget_lane_f64(vreinterpret_f64_u64(vand_u64(vreinterpret_u64_f64(vdup_n_f64(v)), vdup_n_u64(mask))), 0);
#else
    uint64_t b;
    memcpy(&b, &v, 8);
    b &= mask;
    memcpy(&v, &b, 8);
    return v;
#endif
}
/* Calls, not conditionals in the caller: clang's profile hash counts a
 * body's branches and conditionals, so the PGO profile still fits. */
static inline double fp_pc_round(double v) {
    uint64_t mask = g_fp_round_mask;
    if (__builtin_expect(!mask, 0)) return fp_round24(v, (unsigned)g_fpu_cw >> 10);
    return fp_bits_and(v, mask);
}
#define fp_pc(v) fp_pc_round(v)
/* fst/fstp dword: to a float by the rounding field. */
static inline float fp_f32_round(double v) {
    uint64_t mask = g_fp_store_mask;
    if (__builtin_expect(!mask, 0)) return (float)fp_round24(v, (unsigned)g_fpu_cw >> 10);
    return (float)fp_bits_and(v, mask);
}
#define fp_f32(v) fp_f32_round(v)

/* fistp qword: the exact shadow while st0 is still the value fild loaded;
 * otherwise the rounded value, or the 64-bit integer indefinite. */
static inline int64_t fp_st0_to_i64(double v0, int64_t shadow, uint16_t cw) {
    if (v0 == (double)shadow) return shadow;
    double r = fp_round_cw(v0, cw);
    return (r >= -9223372036854775808.0 && r < 9223372036854775808.0) ? (int64_t)r : INT64_MIN;
}

/* The 80-bit extended format, for `fld/fstp xword`. The model's stack is
 * double, so a load rounds to double and a store widens. The CRT keeps 2*pi
 * and friends as xword constants; a load that pushed 0.0 made sin/cos reduce
 * by fmod(x, 0) = NaN, and Gunman's AngleVectors drew nothing. */
static inline double fp_ld80(const uint8_t* p) {
    uint64_t m; uint16_t se;
    memcpy(&m, p, 8); memcpy(&se, p + 8, 2);
    int e = se & 0x7FFF;
    double v;
    if (e == 0x7FFF)
        v = (m << 1) ? NAN : INFINITY;
    else
        v = ldexp((double)m, (e ? e : 1) - 16383 - 63);
    return (se & 0x8000) ? -v : v;
}
static inline void fp_st80(uint8_t* p, double v) {
    uint64_t m = 0; uint16_t se = signbit(v) ? 0x8000 : 0;
    if (isnan(v)) { se |= 0x7FFF; m = 0xC000000000000000ull; }
    else if (isinf(v)) { se |= 0x7FFF; m = 0x8000000000000000ull; }
    else if (v != 0.0) {
        int e; double f = frexp(fabs(v), &e);      /* f in [0.5, 1) */
        m = (uint64_t)ldexp(f, 64);                /* exact: 53 bits */
        se |= (uint16_t)(e - 1 + 16383);
    }
    memcpy(p, &m, 8); memcpy(p + 8, &se, 2);
}

/* ============================================================
 * CPUID stub
 * ============================================================ */

/* Feature bits the guest may see, ANDed into leaf 1 (edx/ecx) and leaf
 * 0x80000001 (edx: 3DNow!). All ones by default. Libraries that dispatch on
 * CPUID -- D3DX above all -- pick SSE/3DNow! paths on a modern host, and the
 * global-register lifter does not implement most of those instructions; a
 * host that clears the bits gets the x87 paths instead (The Movies: 16,977
 * unimplemented SIMD sites against a handful of x87 ones). */
/* There is no x86 CPU to ask. The host answers from a fixed table
 * (void_cpuid in the host runtime) describing the processor the generated
 * code was validated with on Windows. */
void void_cpuid(uint32_t leaf, uint32_t subleaf);
static inline void CPUID_impl(uint32_t eax_val, uint32_t ebx_val, uint32_t ecx_val, uint32_t edx_val) {
    (void)ebx_val; (void)edx_val;
    void_cpuid(eax_val, ecx_val);
}

/* CPUID_impl writes the global registers */
#define CPUID(a, b, c, d) do { RECOMP_REGS_OUT(); CPUID_impl(a, b, c, d); RECOMP_REGS_IN(); } while (0)

/* RDTSC: the ARM64 virtual counter rescaled to the 3.4 GHz invariant TSC of
 * the processor in the CPUID table, so cycle budgets keep their PC length. */
static inline uint64_t __rdtsc(void) {
    uint64_t ticks, freq;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(ticks));
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
    return freq ? (uint64_t)(((unsigned __int128)ticks * 3400000000u) / freq) : ticks;
}

/* ============================================================
 * Indirect Call Dispatch
 * ============================================================ */

/* The VA of the function currently executing (see RECOMP_ENTER below); an
 * unresolved dispatch is far more useful with its caller named. */
extern VOID_HIDDEN uint32_t g_cur_func;

/* ICALL trace ring buffer for crash diagnostics.
 *
 * Both halves matter. A target on its own says which vtable slot ran; the
 * CALLER is what you actually need, because an indirect call is how a null
 * `this` or a null argument gets handed across a module boundary, and the
 * function that built the argument is the one to read. Recovering it by hand
 * means a --calltrace and guessing which nearby entry was still on the stack,
 * and the entry ring is no help when the answer is 33 entries back. */
/* 32 was too small the first time it mattered: a method that makes a few
 * indirect calls of its own scrolls its own entry out of the ring, so the
 * report showed it as a caller and never as a target, and the function that
 * handed it a null argument was already gone. 128 costs a kilobyte. */
#define ICALL_TRACE_SIZE 128
extern VOID_HIDDEN uint32_t g_icall_trace[ICALL_TRACE_SIZE];
extern VOID_HIDDEN uint32_t g_icall_from[ICALL_TRACE_SIZE];
extern VOID_HIDDEN uint32_t g_icall_trace_idx;
extern VOID_HIDDEN uint32_t g_icall_count;

/* Lookup functions */
recomp_func_t recomp_lookup(uint32_t va);          /* binary search in dispatch table */
recomp_func_t recomp_lookup_manual(uint32_t va);    /* manual overrides */
recomp_func_t recomp_lookup_import(uint32_t va);    /* import bridges */
/* The three above in their x86 order (manual, lifted, import) behind one hash
 * probe. Never returns NULL: an unresolved guest target is fatal, exactly as
 * the Windows host's strict recomp_lookup_manual makes it. */
recomp_func_t void_resolve(uint32_t va);

/* The dummy return address pushed before a recompiled call. The callee's lifted
 * `ret` pops it. 0xDEAD0000 is a recognizable marker, but if a stack imbalance
 * ever leaks it into a value (e.g. a size argument) the high bits are destructive.
 * Projects that have hit such a leak can define RECOMP_RETADDR=0u so a leak is
 * benign while it's tracked down. */
#ifndef RECOMP_RETADDR
#define RECOMP_RETADDR 0xDEAD0000u
#endif

/* Flags cross every transfer, as on the CPU: each call and tail hands the
 * caller's flags over (RECOMP_FLAGS_OUT), every function starts from them
 * (RECOMP_ENTER), and `ret` hands the callee's back. Without the first two, a
 * function reached by a tail jump started from FK_NONE, and one whose first
 * conditional reads flags its predecessor set took an arbitrary branch: the
 * MSVC CRT's `cos` runs a load helper, then falls into `_CIcos`, a separate
 * function whose first `je` tests the helper's ZF (Bunghole in One's ball
 * never moved). */

/* Call-site diagnostics: the caller VA in g_cur_func and the indirect-call
 * ring. Each costs global stores at every call that guest stores may alias,
 * so they are opt-in (-DRECOMP_CALL_DIAG) for crash investigations. */
#ifdef RECOMP_CALL_DIAG
#define RECOMP_DIAG_CALLER uint32_t _caller = g_cur_func;
#define RECOMP_DIAG_RESTORE() (g_cur_func = _caller)
#define RECOMP_DIAG_ICALL(va) (g_icall_trace[g_icall_trace_idx & (ICALL_TRACE_SIZE-1)] = (va), \
    g_icall_from[g_icall_trace_idx & (ICALL_TRACE_SIZE-1)] = g_cur_func, g_icall_trace_idx++)
#else
#define RECOMP_DIAG_CALLER
#define RECOMP_DIAG_RESTORE() ((void)0)
#define RECOMP_DIAG_ICALL(va) ((void)0)
#endif

/* Direct call to a known recompiled function */
#define RECOMP_CALL(func) do { \
    RECOMP_DIAG_CALLER \
    PUSH32(esp, RECOMP_RETADDR); /* dummy return address */ \
    RECOMP_FLAGS_OUT(); \
    RECOMP_REGS_OUT(); \
    func(); \
    RECOMP_REGS_IN(); \
    RECOMP_DIAG_RESTORE(); \
} while(0)

/* Indirect call through dispatch. void_resolve traps instead of returning
 * NULL, so the x86 build's "unresolved: skip with eax = 0" path is gone; the
 * Windows host never reached it either (its manual lookup trapped first). */
#define RECOMP_ICALL(target_va) do { \
    uint32_t _va = (uint32_t)(target_va); \
    RECOMP_DIAG_ICALL(_va); \
    recomp_func_t _fn = void_resolve(_va); \
    RECOMP_DIAG_CALLER \
    PUSH32(esp, RECOMP_RETADDR); \
    RECOMP_FLAGS_OUT(); \
    RECOMP_REGS_OUT(); \
    _fn(); \
    RECOMP_REGS_IN(); \
    RECOMP_DIAG_RESTORE(); \
} while(0)

/* Indirect tail call (jmp through dispatch) */
#define RECOMP_ITAIL(target_va) do { \
    uint32_t _va = (uint32_t)(target_va); \
    RECOMP_DIAG_ICALL(_va); \
    if (_va != RECOMP_RETADDR) { /* setjmp and friends return by jumping \
        to the saved return address; that is a return, not a missing target. */ \
        recomp_func_t _fn = void_resolve(_va); \
        RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT(); _fn(); RECOMP_REGS_IN(); \
    } \
} while(0)

/* Masked call protocol (tools/call_protocol.py, applied by the builders).
 * Bit order matches the analysis: eax ecx edx ebx esp ebp esi edi.
 * eax/ecx/edx/esp cross every call and exit, so every body's entry values of
 * them are current; ebx/esi/edi/ebp only cross where a callee may read or
 * change them outside the MSVC callee-saved discipline. A body whose
 * prologue pushes a callee-saved register and pops it before every exit does
 * not publish it: its callers keep their own copy. The flags cross only into
 * bodies that read them on entry; `ret` publishes them only where a caller
 * reads them after the call. Dead reloads into locals fold away. */
#if defined(RECOMP_GENERATED_CODE) && defined(RECOMP_LOCAL_REGS)
#define RECOMP_PUBLISH(m) do { \
    if ((m) & 0x01u) g_eax = l_eax; if ((m) & 0x02u) g_ecx = l_ecx; \
    if ((m) & 0x04u) g_edx = l_edx; if ((m) & 0x08u) g_ebx = l_ebx; \
    if ((m) & 0x10u) g_esp = l_esp; if ((m) & 0x20u) g_ebp = l_ebp; \
    if ((m) & 0x40u) g_esi = l_esi; if ((m) & 0x80u) g_edi = l_edi; \
    RECOMP_XMM_OUT(); RECOMP_BACKEDGE_OUT(); } while (0)
#define RECOMP_RELOAD(m) do { \
    if ((m) & 0x01u) l_eax = g_eax; if ((m) & 0x02u) l_ecx = g_ecx; \
    if ((m) & 0x04u) l_edx = g_edx; if ((m) & 0x08u) l_ebx = g_ebx; \
    if ((m) & 0x10u) l_esp = g_esp; if ((m) & 0x20u) l_ebp = g_ebp; \
    if ((m) & 0x40u) l_esi = g_esi; if ((m) & 0x80u) l_edi = g_edi; \
    RECOMP_XMM_IN(); RECOMP_BACKEDGE_IN(); } while (0)
#else
#define RECOMP_PUBLISH(m) do { RECOMP_XMM_OUT(); RECOMP_BACKEDGE_OUT(); } while (0)
#define RECOMP_RELOAD(m) do { RECOMP_XMM_IN(); RECOMP_BACKEDGE_IN(); } while (0)
#endif
#ifdef RECOMP_PROTOCOL_CHECK
/* Validation build: publish and reload everything, and report every
 * callee-saved register a callee changed although its summary (or the ABI,
 * for indirect calls) says it is preserved. */
void recomp_protocol_violation(uint32_t site, uint32_t target, uint32_t regs);
#define RECOMP_CHECK_PRESERVED(rel, site, target) do { \
    uint32_t _bad = 0; \
    if (!((rel) & 0x08u) && g_ebx != l_ebx) _bad |= 0x08u; \
    if (!((rel) & 0x20u) && g_ebp != l_ebp) _bad |= 0x20u; \
    if (!((rel) & 0x40u) && g_esi != l_esi) _bad |= 0x40u; \
    if (!((rel) & 0x80u) && g_edi != l_edi) _bad |= 0x80u; \
    if (_bad) recomp_protocol_violation((site), (target), _bad); \
} while (0)
#define RECOMP_CALL_P(func, pub, rel, fl, site) do { \
    PUSH32(esp, RECOMP_RETADDR); \
    RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(0xFFu); \
    func(); \
    RECOMP_CHECK_PRESERVED(rel, site, 0); \
    RECOMP_RELOAD(0xFFu); \
} while (0)
#define RECOMP_ICALL_P(target_va, pub, rel, fl, site) do { \
    uint32_t _va = (uint32_t)(target_va); \
    recomp_func_t _fn = void_resolve(_va); \
    PUSH32(esp, RECOMP_RETADDR); \
    RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(0xFFu); \
    _fn(); \
    RECOMP_CHECK_PRESERVED(rel, site, _va); \
    RECOMP_RELOAD(0xFFu); \
} while (0)
#define RECOMP_TAIL_P(func, pub, fl) do { \
    RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(0xFFu); \
    func(); \
} while (0)
#define RECOMP_ITAIL_P(target_va, pub, fl) do { \
    uint32_t _va = (uint32_t)(target_va); \
    if (_va != RECOMP_RETADDR) { \
        recomp_func_t _fn = void_resolve(_va); \
        RECOMP_FLAGS_OUT(); \
        RECOMP_PUBLISH(0xFFu); \
        _fn(); \
    } else { RECOMP_PUBLISH(0xFFu); } \
} while (0)
#define RECOMP_EXIT_P(m) RECOMP_PUBLISH(0xFFu)
#else
#define RECOMP_CALL_P(func, pub, rel, fl, site) do { \
    PUSH32(esp, RECOMP_RETADDR); \
    if (fl) RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(pub); \
    func(); \
    RECOMP_RELOAD(rel); \
} while (0)
#define RECOMP_ICALL_P(target_va, pub, rel, fl, site) do { \
    uint32_t _va = (uint32_t)(target_va); \
    recomp_func_t _fn = void_resolve(_va); \
    PUSH32(esp, RECOMP_RETADDR); \
    if (fl) RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(pub); \
    _fn(); \
    RECOMP_RELOAD(rel); \
} while (0)
/* A tail call publishes the callee's inputs and this body's exit set; the
 * callee's own exit publishes the rest, so the caller returns at once. */
#define RECOMP_TAIL_P(func, pub, fl) do { \
    if (fl) RECOMP_FLAGS_OUT(); \
    RECOMP_PUBLISH(pub); \
    func(); \
} while (0)
#define RECOMP_ITAIL_P(target_va, pub, fl) do { \
    uint32_t _va = (uint32_t)(target_va); \
    if (_va != RECOMP_RETADDR) { \
        recomp_func_t _fn = void_resolve(_va); \
        if (fl) RECOMP_FLAGS_OUT(); \
        RECOMP_PUBLISH(pub); \
        _fn(); \
    } else { RECOMP_PUBLISH(pub); } \
} while (0)
#define RECOMP_EXIT_P(m) RECOMP_PUBLISH(m)
#endif

/* `push target; ret` (Lifter dos=True): a jump to a computed address. Its own
 * name, so generate.py does not take it for an intra-function indirect jump. */
#define RECOMP_RET_JUMP(target_va) RECOMP_ITAIL(target_va)

/* ============================================================
 * Optional function-entry tracer (enable with -DRECOMP_TRACE).
 *
 * Each lifted function records its VA into a ring buffer on entry, so a crash
 * or unexpected exit can dump the last N functions that ran -- a poor-man's
 * backtrace when no debugger is available. Zero cost unless RECOMP_TRACE is set.
 * ============================================================ */
/* Always-on: the VA of the function currently executing. A plain global store
 * (no call), so unlike the ring tracer below it doesn't force register reloads --
 * useful for pinning a crash to a function without perturbing codegen. */
extern VOID_HIDDEN uint32_t g_cur_func;

#ifdef RECOMP_TRACE
/* An inline ring of the last entries, written without a call so that tracing
 * costs two stores; the host dumps it on a trap or a fatal signal. */
#define RECOMP_ENTER_SIZE 1024
extern VOID_HIDDEN uint32_t g_enter_trace[RECOMP_ENTER_SIZE];
extern VOID_HIDDEN uint32_t g_enter_idx;
#define RECOMP_ENTER(va) (g_cur_func = (va), \
    g_enter_trace[g_enter_idx++ & (RECOMP_ENTER_SIZE - 1)] = (va), RECOMP_FLAGS_IN())
#elif defined(RECOMP_CALL_DIAG)
#define RECOMP_ENTER(va) (g_cur_func = (va), RECOMP_FLAGS_IN())
#else
/* Production: no per-entry store. g_cur_func is maintained only under
 * RECOMP_CALL_DIAG/RECOMP_TRACE; host diagnostics otherwise read 0. */
#define RECOMP_ENTER(va) (RECOMP_FLAGS_IN())
#endif

/* Guest C++ exceptions (runtime/native32/eh32.c). A lifted function whose
 * prologue installs an MSVC EH frame gets a host landing pad: on a caught
 * throw the runtime longjmps here with the guest registers set for the
 * catch's continuation, and the local dispatch goes to its label.
 * entry_esp is esp at entry (at the return address): the frame's ebp + 4. */
#include <setjmp.h>
typedef struct recomp_ehframe {
    struct recomp_ehframe* prev;
    jmp_buf  jb;
    uint32_t entry_esp;
    uint32_t resume;
} recomp_ehframe_t;
void recomp_eh_push(recomp_ehframe_t* f);
void recomp_eh_pop(recomp_ehframe_t* f);
/* _setjmp: bionic's setjmp also saves the signal mask, a system call on every
 * entry to a function with an EH frame. The dispatcher pairs it with _longjmp. */
#define RECOMP_EH_ENTER()                                                     \
    recomp_ehframe_t _ehf;                                                    \
    _ehf.entry_esp = g_esp;                                                   \
    recomp_eh_push(&_ehf);                                                    \
    if (_setjmp(_ehf.jb)) { RECOMP_REGS_IN(); _flag_k = FK_NONE;              \
                           _itail_tgt = _ehf.resume; goto _ljump; }
#define RECOMP_EH_LEAVE() recomp_eh_pop(&_ehf)
/* A backward branch in lifted code: a loop. Every RECOMP_YIELD_EVERY of them,
 * hand the machine to other guest threads if the host has a way to
 * (native32_yield). A lifted spin-wait makes no native call, and native32
 * hands its machine lock over only at native calls, so a loop waiting on
 * another guest thread's flag never let that thread run: Yuri's Revenge's
 * exit spins until its sound thread acknowledges a stop (0x0040A047) and hung
 * there. The registers go back to the globals around the hand-over, which is
 * all a native call does. The counter is global and unsynchronised on purpose:
 * only the thread holding the machine runs lifted code. */
extern VOID_HIDDEN void (*recomp_yield_hook)(void);
extern VOID_HIDDEN uint32_t g_backedges;
#ifndef RECOMP_YIELD_EVERY
#define RECOMP_YIELD_EVERY 0x10000u
#endif
/* Private source copies keep the loop counter local, publishing it at transfers. */
#define RECOMP_BACKEDGE_COUNTER g_backedges
#if defined(RECOMP_YIELD_ON_WAITERS)
/* PC: count loop iterations only while another guest thread waits for the
 * machine (native32's g_mach_waiters); with nobody waiting a backward branch
 * is one load. The hand-over quantum is unchanged. */
extern volatile long g_mach_waiters;
#define RECOMP_BACKEDGE() do { \
    if (__builtin_expect(g_mach_waiters != 0, 0) && ++RECOMP_BACKEDGE_COUNTER >= RECOMP_YIELD_EVERY && \
        recomp_yield_hook) { \
        RECOMP_BACKEDGE_COUNTER = 0; \
        RECOMP_REGS_OUT(); recomp_yield_hook(); RECOMP_REGS_IN(); \
    } } while (0)
#else
#define RECOMP_BACKEDGE() do { \
    if (++RECOMP_BACKEDGE_COUNTER >= RECOMP_YIELD_EVERY && recomp_yield_hook) { \
        RECOMP_BACKEDGE_COUNTER = 0; \
        RECOMP_REGS_OUT(); recomp_yield_hook(); RECOMP_REGS_IN(); \
    } } while (0)
#endif

/* Always-callable trace dump (no-op unless RECOMP_TRACE). */
void recomp_dump_trace(const char* why);

/* Stub macro for unimplemented imports */
#define STUB(name) do { \
    static int _warned = 0; \
    if (!_warned) { fprintf(stderr, "STUB: %s called\n", name); _warned = 1; } \
} while(0)

#endif /* RECOMP_TYPES_H */
