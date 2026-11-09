/* CHeroTrace's reference-grid archive visitor. The archive owns object identity,
 * allocation and reference handling; this module owns dimension/row traversal. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00C059B0(void);
extern void sub_00609AD0(void);
extern void sub_00879240(void);
extern void sub_004B04A0(void);
extern void void_reference_native_tile_dispatch(void);

typedef struct reference_grid {
    uint32_t storage, rows;
    int32_t width, height;
} reference_grid;
#define GRID(va) ((reference_grid *)GPTR(va))

#ifdef RECOMP_PROTOCOL_CHECK
#define GRID_CMP(a, b) do { _flag_a = (a); _flag_b = (b); \
    _cf = _flag_a < _flag_b; _flag_k = FK_CMP; } while (0)
#define GRID_TEST(a) do { _flag_a = _flag_b = (a); \
    _cf = 0; _flag_k = FK_TEST; } while (0)
#define GRID_BYTE_TEST(a) do { _flag_a = _flag_b = (uint32_t)(uint8_t)(a) << 24; \
    _cf = 0; _flag_k = FK_NARROW(FK_TEST, 24); } while (0)
#define GRID_ADD(a, b) do { _flag_a = (a); _flag_b = (b); \
    _cf = (uint32_t)(_flag_a + _flag_b) < _flag_a; _flag_k = FK_ADD; } while (0)
#else
#define GRID_CMP(a, b) ((void)0)
#define GRID_TEST(a) ((void)0)
#define GRID_BYTE_TEST(a) ((void)0)
#define GRID_ADD(a, b) ((void)0)
#endif

static void grid_field(void)
{
    uint32_t _cf = 0, _flag_k = FK_NONE, _flag_a = 0, _flag_b = 0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C05A90u);
    ecx = MEM32(esp + 12);
    edx = MEM32(esp + 8);
    PUSH32(esp, esi);
    esi = MEM32(esp + 8);
    eax = MEM32(esi);
    PUSH32(esp, ecx);
    PUSH32(esp, edx);
    ecx = esi;
    RECOMP_ICALL_P(MEM32(eax + 0x1C), 0x17u, 0x17u, 0, 0x00C05AA3u);
    RECOMP_FLAGS_IN();
    GRID_BYTE_TEST(eax);
    if ((uint8_t)eax) {
        eax = MEM32(esp + 0x14);
        PUSH32(esp, eax);
        ecx = esi;
        RECOMP_CALL_P(void_reference_native_tile_dispatch, 0x1Fu, 0x17u, 0, 0x00C05AB1u);
        RECOMP_FLAGS_IN();
        edx = MEM32(esi);
        ecx = esi;
        esi = POP32_VAL(esp);
        RECOMP_ITAIL_P(MEM32(edx + 0x20), 0x1Fu, 0);
        return;
    }
    esi = POP32_VAL(esp);
    esp += 4;
    RECOMP_EXIT_P(0x1Fu);
}

void void_grid_native_visit(void)
{
    uint32_t _cf = 0, _flag_k = FK_NONE, _flag_a = 0, _flag_b = 0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C059B0u);
    GRID_CMP(esp, 8u);
    esp -= 8;
    PUSH32(esp, ebx);
    PUSH32(esp, ebp);
    PUSH32(esp, esi);
    esi = MEM32(esp + 0x18);
    eax = (uint32_t)GRID(esi)->width;
    PUSH32(esp, edi);
    PUSH32(esp, 1);
    ebx = ecx;
    ecx = (uint32_t)GRID(esi)->height;
    edx = MEM32(ebx);
    MEM32(esp + 0x18) = eax;
    PUSH32(esp, 4);
    eax = esp + 0x1C;
    PUSH32(esp, eax);
    MEM32(esp + 0x1C) = ecx;
    PUSH32(esp, 1);
    ecx = ebx;
    RECOMP_ICALL_P(MEM32(edx + 0x28), 0x17u, 0x17u, 0, 0x00C059DAu);
    RECOMP_FLAGS_IN();
    edx = MEM32(ebx);
    PUSH32(esp, 1);
    PUSH32(esp, 4);
    eax = esp + 0x18;
    PUSH32(esp, eax);
    PUSH32(esp, 2);
    ecx = ebx;
    RECOMP_ICALL_P(MEM32(edx + 0x28), 0x17u, 0x17u, 0, 0x00C059ECu);
    RECOMP_FLAGS_IN();
    edx = MEM32(ebx);
    ecx = ebx;
    RECOMP_ICALL_P(MEM32(edx + 0x3C), 0x17u, 0x17u, 0, 0x00C059F3u);
    RECOMP_FLAGS_IN();
    edi = MEM32(esp + 0x14);
    GRID_BYTE_TEST(eax);
    int reading = (uint8_t)eax != 0;
    eax = MEM32(esp + 0x10);
    if (reading) {
        GRID_CMP((uint32_t)GRID(esi)->width, edi);
        ebp = eax;
        int different = (uint32_t)GRID(esi)->width != edi;
        if (!different) {
            GRID_CMP((uint32_t)GRID(esi)->height, eax);
            different = (uint32_t)GRID(esi)->height != eax;
        }
        if (different) {
            ecx = GRID(esi)->storage;
            GRID_TEST(ecx);
            if (ecx) {
                PUSH32(esp, 3);
                RECOMP_CALL_P(sub_00609AD0, 0x1Fu, 0x17u, 0, 0x00C05A16u);
                RECOMP_FLAGS_IN();
            }
            eax = GRID(esi)->rows;
            GRID_TEST(eax);
            if (eax) {
                PUSH32(esp, eax);
                RECOMP_CALL_P(sub_00879240, 0x17u, 0x17u, 0, 0x00C05A23u);
                RECOMP_FLAGS_IN();
                GRID_ADD(esp, 4u);
                esp += 4;
            }
            ecx = esi;
            GRID(esi)->width = (int32_t)edi;
            GRID(esi)->height = (int32_t)ebp;
            RECOMP_CALL_P(sub_004B04A0, 0x17u, 0x17u, 0, 0x00C05A33u);
            RECOMP_FLAGS_IN();
            edi = MEM32(esp + 0x14);
            eax = MEM32(esp + 0x10);
        }
    }
    eax *= edi;
    ecx = 0;
    GRID_TEST(eax);
    if ((int32_t)eax > 0) {
        int more;
        do {
            int64_t index = (int32_t)ecx;
            int32_t width = (int32_t)edi;
            eax = width ? (uint32_t)(index / width) : 0;
            edx = width ? (uint32_t)(index % width) : 0;
            edi = ecx + 1u;
            ecx = esp + 0x1C;
            /* The original generic visitor passes an unused fifth argument.
             * Keep its stack word: archive callbacks can inspect the frame. */
            PUSH32(esp, ecx);
            ecx = GRID(esi)->rows;
            eax = MEM32(ecx + eax * 4u);
            ecx = eax + edx * 4u;
            PUSH32(esp, ecx);
            PUSH32(esp, edi);
            PUSH32(esp, 3);
            PUSH32(esp, ebx);
            RECOMP_CALL_P(grid_field, 0x1Fu, 0x17u, 0, 0x00C05A6Bu);
            RECOMP_FLAGS_IN();
            edx = MEM32(esp + 0x24);
            ecx = edi;
            edi = MEM32(esp + 0x28);
            edx *= edi;
            GRID_ADD(esp, 0x14u);
            esp += 0x14;
            GRID_CMP(ecx, edx);
            more = (int32_t)ecx < (int32_t)edx;
            RECOMP_BACKEDGE();
        } while (more);
    }
    edi = POP32_VAL(esp);
    esi = POP32_VAL(esp);
    ebp = POP32_VAL(esp);
    ebx = POP32_VAL(esp);
    GRID_ADD(esp, 8u);
    esp += 16;
    RECOMP_EXIT_P(0xFFu);
}

void void_grid_native_dispatch(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-grid", "[grid-native] mode=%d (cached for this process)");
    if (mode) void_grid_native_visit();
    else sub_00C059B0();
}
