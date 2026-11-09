/* Exact observed ToE world pure leaves. Original bodies retain their names.
 * Private candidate only; every actual native entry has a separate router. */
#ifndef HOMM5_LEGACY_UI
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"
static int leaf_mode(void) {
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-leaves", "[leaf-native] mode=%d (cached for this process)");
    return mode;
}

extern void sub_0044FF40(void);

void void_leaf_native_0044FF40(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0044FF40u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFE8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0044FF40(void) { if(leaf_mode())void_leaf_native_0044FF40();else sub_0044FF40(); }

extern void sub_00454300(void);

void void_leaf_native_00454300(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00454300u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0xFFFFFF88u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00454300(void) { if(leaf_mode())void_leaf_native_00454300();else sub_00454300(); }

extern void sub_00454360(void);

void void_leaf_native_00454360(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00454360u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0xFFFFFF98u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00454360(void) { if(leaf_mode())void_leaf_native_00454360();else sub_00454360(); }

extern void sub_00454380(void);

void void_leaf_native_00454380(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00454380u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0xFFFFFFA4u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00454380(void) { if(leaf_mode())void_leaf_native_00454380();else sub_00454380(); }

extern void sub_0048EBF0(void);

void void_leaf_native_0048EBF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0048EBF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000001C0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0048EBF0(void) { if(leaf_mode())void_leaf_native_0048EBF0();else sub_0048EBF0(); }

extern void sub_004B4690(void);

void void_leaf_native_004B4690(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004B4690u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0xFFFFFFC4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004B4690(void) { if(leaf_mode())void_leaf_native_004B4690();else sub_004B4690(); }

extern void sub_004F88A0(void);

void void_leaf_native_004F88A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004F88A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000002Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004F88A0(void) { if(leaf_mode())void_leaf_native_004F88A0();else sub_004F88A0(); }

extern void sub_004F8BE0(void);

void void_leaf_native_004F8BE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004F8BE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000070u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004F8BE0(void) { if(leaf_mode())void_leaf_native_004F8BE0();else sub_004F8BE0(); }

extern void sub_004FB7A0(void);

void void_leaf_native_004FB7A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FB7A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000018u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FB7A0(void) { if(leaf_mode())void_leaf_native_004FB7A0();else sub_004FB7A0(); }

extern void sub_004FB7B0(void);

void void_leaf_native_004FB7B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FB7B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000016Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FB7B0(void) { if(leaf_mode())void_leaf_native_004FB7B0();else sub_004FB7B0(); }

extern void sub_004FB7C0(void);

void void_leaf_native_004FB7C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FB7C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000098u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FB7C0(void) { if(leaf_mode())void_leaf_native_004FB7C0();else sub_004FB7C0(); }

extern void sub_004FBE80(void);

void void_leaf_native_004FBE80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FBE80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000608u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FBE80(void) { if(leaf_mode())void_leaf_native_004FBE80();else sub_004FBE80(); }

extern void sub_00500C10(void);

void void_leaf_native_00500C10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500C10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000634u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500C10(void) { if(leaf_mode())void_leaf_native_00500C10();else sub_00500C10(); }

extern void sub_00500C40(void);

void void_leaf_native_00500C40(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500C40u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000178u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500C40(void) { if(leaf_mode())void_leaf_native_00500C40();else sub_00500C40(); }

extern void sub_00500D30(void);

void void_leaf_native_00500D30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500D30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000230u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500D30(void) { if(leaf_mode())void_leaf_native_00500D30();else sub_00500D30(); }

extern void sub_00500D90(void);

void void_leaf_native_00500D90(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500D90u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000021Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500D90(void) { if(leaf_mode())void_leaf_native_00500D90();else sub_00500D90(); }

extern void sub_00500DE0(void);

void void_leaf_native_00500DE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500DE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000638u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500DE0(void) { if(leaf_mode())void_leaf_native_00500DE0();else sub_00500DE0(); }

extern void sub_00500DF0(void);

void void_leaf_native_00500DF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500DF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000067Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500DF0(void) { if(leaf_mode())void_leaf_native_00500DF0();else sub_00500DF0(); }

extern void sub_0050E140(void);

void void_leaf_native_0050E140(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0050E140u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000064u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0050E140(void) { if(leaf_mode())void_leaf_native_0050E140();else sub_0050E140(); }

extern void sub_00513250(void);

void void_leaf_native_00513250(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00513250u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00513250(void) { if(leaf_mode())void_leaf_native_00513250();else sub_00513250(); }

extern void sub_005AE110(void);

void void_leaf_native_005AE110(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x005AE110u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000002Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_005AE110(void) { if(leaf_mode())void_leaf_native_005AE110();else sub_005AE110(); }

extern void sub_005AE970(void);

void void_leaf_native_005AE970(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x005AE970u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000FCu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_005AE970(void) { if(leaf_mode())void_leaf_native_005AE970();else sub_005AE970(); }

extern void sub_0061F290(void);

void void_leaf_native_0061F290(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0061F290u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0061F290(void) { if(leaf_mode())void_leaf_native_0061F290();else sub_0061F290(); }

extern void sub_00620240(void);

void void_leaf_native_00620240(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00620240u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000A0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00620240(void) { if(leaf_mode())void_leaf_native_00620240();else sub_00620240(); }

extern void sub_00633CC0(void);

void void_leaf_native_00633CC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00633CC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000F8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00633CC0(void) { if(leaf_mode())void_leaf_native_00633CC0();else sub_00633CC0(); }

extern void sub_00720E90(void);

void void_leaf_native_00720E90(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00720E90u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000078u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00720E90(void) { if(leaf_mode())void_leaf_native_00720E90();else sub_00720E90(); }

extern void sub_00724930(void);

void void_leaf_native_00724930(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00724930u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000008u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00724930(void) { if(leaf_mode())void_leaf_native_00724930();else sub_00724930(); }

extern void sub_00724940(void);

void void_leaf_native_00724940(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00724940u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000018u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00724940(void) { if(leaf_mode())void_leaf_native_00724940();else sub_00724940(); }

extern void sub_0072BEE0(void);

void void_leaf_native_0072BEE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0072BEE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000000Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0072BEE0(void) { if(leaf_mode())void_leaf_native_0072BEE0();else sub_0072BEE0(); }

extern void sub_0076B5F0(void);

void void_leaf_native_0076B5F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0076B5F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000008u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0076B5F0(void) { if(leaf_mode())void_leaf_native_0076B5F0();else sub_0076B5F0(); }

extern void sub_00782CF0(void);

void void_leaf_native_00782CF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00782CF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00782CF0(void) { if(leaf_mode())void_leaf_native_00782CF0();else sub_00782CF0(); }

extern void sub_007D0600(void);

void void_leaf_native_007D0600(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x007D0600u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000005Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_007D0600(void) { if(leaf_mode())void_leaf_native_007D0600();else sub_007D0600(); }

extern void sub_007DD5A0(void);

void void_leaf_native_007DD5A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x007DD5A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x00F40214u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_007DD5A0(void) { if(leaf_mode())void_leaf_native_007DD5A0();else sub_007DD5A0(); }

extern void sub_00819270(void);

void void_leaf_native_00819270(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00819270u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000010u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00819270(void) { if(leaf_mode())void_leaf_native_00819270();else sub_00819270(); }

extern void sub_00819280(void);

void void_leaf_native_00819280(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00819280u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000018u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00819280(void) { if(leaf_mode())void_leaf_native_00819280();else sub_00819280(); }

extern void sub_0081AD10(void);

void void_leaf_native_0081AD10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0081AD10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0081AD10(void) { if(leaf_mode())void_leaf_native_0081AD10();else sub_0081AD10(); }

extern void sub_0081BF70(void);

void void_leaf_native_0081BF70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0081BF70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000000Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0081BF70(void) { if(leaf_mode())void_leaf_native_0081BF70();else sub_0081BF70(); }

extern void sub_008478A0(void);

void void_leaf_native_008478A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008478A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x00000061u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008478A0(void) { if(leaf_mode())void_leaf_native_008478A0();else sub_008478A0(); }

extern void sub_0087B9E0(void);

void void_leaf_native_0087B9E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087B9E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000002Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087B9E0(void) { if(leaf_mode())void_leaf_native_0087B9E0();else sub_0087B9E0(); }

extern void sub_0087B9F0(void);

void void_leaf_native_0087B9F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087B9F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000010u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087B9F0(void) { if(leaf_mode())void_leaf_native_0087B9F0();else sub_0087B9F0(); }

extern void sub_0087BA00(void);

void void_leaf_native_0087BA00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BA00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000014u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BA00(void) { if(leaf_mode())void_leaf_native_0087BA00();else sub_0087BA00(); }

extern void sub_0087BA10(void);

void void_leaf_native_0087BA10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BA10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    MEM8(ecx + 0x0000000Cu) = 0x1u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BA10(void) { if(leaf_mode())void_leaf_native_0087BA10();else sub_0087BA10(); }

extern void sub_0087BA20(void);

void void_leaf_native_0087BA20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BA20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000000Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BA20(void) { if(leaf_mode())void_leaf_native_0087BA20();else sub_0087BA20(); }

extern void sub_0087BA40(void);

void void_leaf_native_0087BA40(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BA40u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BA40(void) { if(leaf_mode())void_leaf_native_0087BA40();else sub_0087BA40(); }

extern void sub_0087BBE0(void);

void void_leaf_native_0087BBE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BBE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000028u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BBE0(void) { if(leaf_mode())void_leaf_native_0087BBE0();else sub_0087BBE0(); }

extern void sub_00882AC0(void);

void void_leaf_native_00882AC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00882AC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000040u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00882AC0(void) { if(leaf_mode())void_leaf_native_00882AC0();else sub_00882AC0(); }

extern void sub_00885BA0(void);

void void_leaf_native_00885BA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00885BA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x0000001Cu) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00885BA0(void) { if(leaf_mode())void_leaf_native_00885BA0();else sub_00885BA0(); }

extern void sub_00896CD0(void);

void void_leaf_native_00896CD0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00896CD0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00896CD0(void) { if(leaf_mode())void_leaf_native_00896CD0();else sub_00896CD0(); }

extern void sub_0089AD50(void);

void void_leaf_native_0089AD50(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089AD50u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000021u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089AD50(void) { if(leaf_mode())void_leaf_native_0089AD50();else sub_0089AD50(); }

extern void sub_0089B0C0(void);

void void_leaf_native_0089B0C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089B0C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000054u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089B0C0(void) { if(leaf_mode())void_leaf_native_0089B0C0();else sub_0089B0C0(); }

extern void sub_0089B110(void);

void void_leaf_native_0089B110(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089B110u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000097u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089B110(void) { if(leaf_mode())void_leaf_native_0089B110();else sub_0089B110(); }

extern void sub_0089B120(void);

void void_leaf_native_0089B120(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089B120u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000B0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089B120(void) { if(leaf_mode())void_leaf_native_0089B120();else sub_0089B120(); }

extern void sub_008B1E10(void);

void void_leaf_native_008B1E10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008B1E10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x00000001u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008B1E10(void) { if(leaf_mode())void_leaf_native_008B1E10();else sub_008B1E10(); }

extern void sub_0098C470(void);

void void_leaf_native_0098C470(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0098C470u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000088u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0098C470(void) { if(leaf_mode())void_leaf_native_0098C470();else sub_0098C470(); }

extern void sub_0098C490(void);

void void_leaf_native_0098C490(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0098C490u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000054u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0098C490(void) { if(leaf_mode())void_leaf_native_0098C490();else sub_0098C490(); }

extern void sub_0098C4C0(void);

void void_leaf_native_0098C4C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0098C4C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000184u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0098C4C0(void) { if(leaf_mode())void_leaf_native_0098C4C0();else sub_0098C4C0(); }

extern void sub_0098CF90(void);

void void_leaf_native_0098CF90(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0098CF90u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000124u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0098CF90(void) { if(leaf_mode())void_leaf_native_0098CF90();else sub_0098CF90(); }

extern void sub_0099E4C0(void);

void void_leaf_native_0099E4C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0099E4C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000174u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0099E4C0(void) { if(leaf_mode())void_leaf_native_0099E4C0();else sub_0099E4C0(); }

extern void sub_0099E4D0(void);

void void_leaf_native_0099E4D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0099E4D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000044u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0099E4D0(void) { if(leaf_mode())void_leaf_native_0099E4D0();else sub_0099E4D0(); }

extern void sub_0099E590(void);

void void_leaf_native_0099E590(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0099E590u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000D0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0099E590(void) { if(leaf_mode())void_leaf_native_0099E590();else sub_0099E590(); }

extern void sub_009DBD80(void);

void void_leaf_native_009DBD80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009DBD80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009DBD80(void) { if(leaf_mode())void_leaf_native_009DBD80();else sub_009DBD80(); }

extern void sub_009FB860(void);

void void_leaf_native_009FB860(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009FB860u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009FB860(void) { if(leaf_mode())void_leaf_native_009FB860();else sub_009FB860(); }

extern void sub_00A192B0(void);

void void_leaf_native_00A192B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A192B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x16130CC1u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A192B0(void) { if(leaf_mode())void_leaf_native_00A192B0();else sub_00A192B0(); }

extern void sub_00A19DB0(void);

void void_leaf_native_00A19DB0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A19DB0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1613250Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A19DB0(void) { if(leaf_mode())void_leaf_native_00A19DB0();else sub_00A19DB0(); }

extern void sub_00A19F80(void);

void void_leaf_native_00A19F80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A19F80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x16130CC3u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A19F80(void) { if(leaf_mode())void_leaf_native_00A19F80();else sub_00A19F80(); }

extern void sub_00A1A0E0(void);

void void_leaf_native_00A1A0E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A1A0E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x16130CC5u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A1A0E0(void) { if(leaf_mode())void_leaf_native_00A1A0E0();else sub_00A1A0E0(); }

extern void sub_00A367B0(void);

void void_leaf_native_00A367B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A367B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000024u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A367B0(void) { if(leaf_mode())void_leaf_native_00A367B0();else sub_00A367B0(); }

extern void sub_00A3A140(void);

void void_leaf_native_00A3A140(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A3A140u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x000000C4u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A3A140(void) { if(leaf_mode())void_leaf_native_00A3A140();else sub_00A3A140(); }

extern void sub_00A3D220(void);

void void_leaf_native_00A3D220(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A3D220u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A3D220(void) { if(leaf_mode())void_leaf_native_00A3D220();else sub_00A3D220(); }

extern void sub_00A44C70(void);

void void_leaf_native_00A44C70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A44C70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A44C70(void) { if(leaf_mode())void_leaf_native_00A44C70();else sub_00A44C70(); }

extern void sub_00A4D980(void);

void void_leaf_native_00A4D980(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A4D980u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x00000088u) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A4D980(void) { if(leaf_mode())void_leaf_native_00A4D980();else sub_00A4D980(); }

extern void sub_00A83AA0(void);

void void_leaf_native_00A83AA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A83AA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x00000002u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A83AA0(void) { if(leaf_mode())void_leaf_native_00A83AA0();else sub_00A83AA0(); }

extern void sub_00A951F0(void);

void void_leaf_native_00A951F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A951F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000C0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A951F0(void) { if(leaf_mode())void_leaf_native_00A951F0();else sub_00A951F0(); }

extern void sub_00AC1880(void);

void void_leaf_native_00AC1880(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AC1880u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000010Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AC1880(void) { if(leaf_mode())void_leaf_native_00AC1880();else sub_00AC1880(); }

extern void sub_00ACB380(void);
extern uint32_t void_ncf_creatures(void);

void void_leaf_native_00ACB380(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00ACB380u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    /* Retain the existing production New Creature Framework limit policy. */
    eax = void_ncf_creatures();
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00ACB380(void) { if(leaf_mode())void_leaf_native_00ACB380();else sub_00ACB380(); }

extern void sub_00AF7E80(void);

void void_leaf_native_00AF7E80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7E80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000A4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7E80(void) { if(leaf_mode())void_leaf_native_00AF7E80();else sub_00AF7E80(); }

extern void sub_00AF7F40(void);

void void_leaf_native_00AF7F40(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7F40u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000013Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7F40(void) { if(leaf_mode())void_leaf_native_00AF7F40();else sub_00AF7F40(); }

extern void sub_00AF8160(void);

void void_leaf_native_00AF8160(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF8160u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000140u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF8160(void) { if(leaf_mode())void_leaf_native_00AF8160();else sub_00AF8160(); }

extern void sub_00AFFEB0(void);

void void_leaf_native_00AFFEB0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AFFEB0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000002Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AFFEB0(void) { if(leaf_mode())void_leaf_native_00AFFEB0();else sub_00AFFEB0(); }

extern void sub_00AFFEC0(void);

void void_leaf_native_00AFFEC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AFFEC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000001Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AFFEC0(void) { if(leaf_mode())void_leaf_native_00AFFEC0();else sub_00AFFEC0(); }

extern void sub_00B24660(void);

void void_leaf_native_00B24660(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B24660u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000094u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B24660(void) { if(leaf_mode())void_leaf_native_00B24660();else sub_00B24660(); }

extern void sub_00B24670(void);

void void_leaf_native_00B24670(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B24670u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    MEM8(ecx + 0x00000094u) = 0x0u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B24670(void) { if(leaf_mode())void_leaf_native_00B24670();else sub_00B24670(); }

extern void sub_00B4C0F0(void);

void void_leaf_native_00B4C0F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C0F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000088u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C0F0(void) { if(leaf_mode())void_leaf_native_00B4C0F0();else sub_00B4C0F0(); }

extern void sub_00B4C370(void);

void void_leaf_native_00B4C370(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C370u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000002A4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C370(void) { if(leaf_mode())void_leaf_native_00B4C370();else sub_00B4C370(); }

extern void sub_00B4C420(void);

void void_leaf_native_00B4C420(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C420u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000017Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C420(void) { if(leaf_mode())void_leaf_native_00B4C420();else sub_00B4C420(); }

extern void sub_00B5A9D0(void);

void void_leaf_native_00B5A9D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5A9D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000108u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5A9D0(void) { if(leaf_mode())void_leaf_native_00B5A9D0();else sub_00B5A9D0(); }

extern void sub_00B5AA30(void);

void void_leaf_native_00B5AA30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AA30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000012Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AA30(void) { if(leaf_mode())void_leaf_native_00B5AA30();else sub_00B5AA30(); }

extern void sub_00B5AAD0(void);

void void_leaf_native_00B5AAD0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AAD0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000001D0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AAD0(void) { if(leaf_mode())void_leaf_native_00B5AAD0();else sub_00B5AAD0(); }

extern void sub_00B5AC10(void);

void void_leaf_native_00B5AC10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AC10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000248u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AC10(void) { if(leaf_mode())void_leaf_native_00B5AC10();else sub_00B5AC10(); }

extern void sub_00B5AC30(void);

void void_leaf_native_00B5AC30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AC30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000270u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AC30(void) { if(leaf_mode())void_leaf_native_00B5AC30();else sub_00B5AC30(); }

extern void sub_00B5ACA0(void);

void void_leaf_native_00B5ACA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5ACA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000128u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5ACA0(void) { if(leaf_mode())void_leaf_native_00B5ACA0();else sub_00B5ACA0(); }

extern void sub_00B5ACE0(void);

void void_leaf_native_00B5ACE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5ACE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000001D4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5ACE0(void) { if(leaf_mode())void_leaf_native_00B5ACE0();else sub_00B5ACE0(); }

extern void sub_00B5ACF0(void);

void void_leaf_native_00B5ACF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5ACF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000228u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5ACF0(void) { if(leaf_mode())void_leaf_native_00B5ACF0();else sub_00B5ACF0(); }

extern void sub_00B6BB00(void);

void void_leaf_native_00B6BB00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B6BB00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000014u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B6BB00(void) { if(leaf_mode())void_leaf_native_00B6BB00();else sub_00B6BB00(); }

extern void sub_00B7F240(void);

void void_leaf_native_00B7F240(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B7F240u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x000000B9u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B7F240(void) { if(leaf_mode())void_leaf_native_00B7F240();else sub_00B7F240(); }

extern void sub_00BA03D0(void);

void void_leaf_native_00BA03D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BA03D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000003Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BA03D0(void) { if(leaf_mode())void_leaf_native_00BA03D0();else sub_00BA03D0(); }

extern void sub_00BC2970(void);

void void_leaf_native_00BC2970(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BC2970u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000060u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BC2970(void) { if(leaf_mode())void_leaf_native_00BC2970();else sub_00BC2970(); }

extern void sub_00C2FD30(void);

void void_leaf_native_00C2FD30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C2FD30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000030u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C2FD30(void) { if(leaf_mode())void_leaf_native_00C2FD30();else sub_00C2FD30(); }

extern void sub_00C2FE30(void);

void void_leaf_native_00C2FE30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C2FE30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C2FE30(void) { if(leaf_mode())void_leaf_native_00C2FE30();else sub_00C2FE30(); }

extern void sub_00C2FE70(void);

void void_leaf_native_00C2FE70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C2FE70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C2FE70(void) { if(leaf_mode())void_leaf_native_00C2FE70();else sub_00C2FE70(); }

extern void sub_00C2FEF0(void);

void void_leaf_native_00C2FEF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C2FEF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C2FEF0(void) { if(leaf_mode())void_leaf_native_00C2FEF0();else sub_00C2FEF0(); }

extern void sub_00C37370(void);

void void_leaf_native_00C37370(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C37370u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x0000000Cu) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C37370(void) { if(leaf_mode())void_leaf_native_00C37370();else sub_00C37370(); }

extern void sub_00C3A590(void);

void void_leaf_native_00C3A590(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C3A590u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFF0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C3A590(void) { if(leaf_mode())void_leaf_native_00C3A590();else sub_00C3A590(); }

extern void sub_00C3A5A0(void);

void void_leaf_native_00C3A5A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C3A5A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFF8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C3A5A0(void) { if(leaf_mode())void_leaf_native_00C3A5A0();else sub_00C3A5A0(); }

extern void sub_00C3A5D0(void);

void void_leaf_native_00C3A5D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C3A5D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFECu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C3A5D0(void) { if(leaf_mode())void_leaf_native_00C3A5D0();else sub_00C3A5D0(); }

extern void sub_00C61A70(void);

void void_leaf_native_00C61A70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C61A70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000007Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C61A70(void) { if(leaf_mode())void_leaf_native_00C61A70();else sub_00C61A70(); }

extern void sub_00C61AB0(void);

void void_leaf_native_00C61AB0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C61AB0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000048u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C61AB0(void) { if(leaf_mode())void_leaf_native_00C61AB0();else sub_00C61AB0(); }

extern void sub_00C61B10(void);

void void_leaf_native_00C61B10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C61B10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000084u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C61B10(void) { if(leaf_mode())void_leaf_native_00C61B10();else sub_00C61B10(); }

extern void sub_00C68520(void);

void void_leaf_native_00C68520(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C68520u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000020u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C68520(void) { if(leaf_mode())void_leaf_native_00C68520();else sub_00C68520(); }

extern void sub_00C685C0(void);

void void_leaf_native_00C685C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C685C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C685C0(void) { if(leaf_mode())void_leaf_native_00C685C0();else sub_00C685C0(); }

extern void sub_00C98940(void);

void void_leaf_native_00C98940(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C98940u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C98940(void) { if(leaf_mode())void_leaf_native_00C98940();else sub_00C98940(); }

extern void sub_00CBC7E0(void);

void void_leaf_native_00CBC7E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBC7E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000100u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBC7E0(void) { if(leaf_mode())void_leaf_native_00CBC7E0();else sub_00CBC7E0(); }

extern void sub_00CBCA20(void);

void void_leaf_native_00CBCA20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBCA20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000020u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBCA20(void) { if(leaf_mode())void_leaf_native_00CBCA20();else sub_00CBCA20(); }

extern void sub_00CBE280(void);

void void_leaf_native_00CBE280(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBE280u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000044u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBE280(void) { if(leaf_mode())void_leaf_native_00CBE280();else sub_00CBE280(); }

extern void sub_00CBE290(void);

void void_leaf_native_00CBE290(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBE290u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000004Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBE290(void) { if(leaf_mode())void_leaf_native_00CBE290();else sub_00CBE290(); }

extern void sub_00CBE2A0(void);

void void_leaf_native_00CBE2A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBE2A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000018u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBE2A0(void) { if(leaf_mode())void_leaf_native_00CBE2A0();else sub_00CBE2A0(); }

extern void sub_00CBE390(void);

void void_leaf_native_00CBE390(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBE390u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000000Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBE390(void) { if(leaf_mode())void_leaf_native_00CBE390();else sub_00CBE390(); }

extern void sub_00CD8850(void);

void void_leaf_native_00CD8850(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CD8850u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000068u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CD8850(void) { if(leaf_mode())void_leaf_native_00CD8850();else sub_00CD8850(); }

extern void sub_00CE0810(void);

void void_leaf_native_00CE0810(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CE0810u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF90u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CE0810(void) { if(leaf_mode())void_leaf_native_00CE0810();else sub_00CE0810(); }

extern void sub_00CE6760(void);

void void_leaf_native_00CE6760(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CE6760u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000028u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CE6760(void) { if(leaf_mode())void_leaf_native_00CE6760();else sub_00CE6760(); }

extern void sub_00CECF10(void);

void void_leaf_native_00CECF10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CECF10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CECF10(void) { if(leaf_mode())void_leaf_native_00CECF10();else sub_00CECF10(); }

extern void sub_00CF2AA0(void);

void void_leaf_native_00CF2AA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CF2AA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000040u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CF2AA0(void) { if(leaf_mode())void_leaf_native_00CF2AA0();else sub_00CF2AA0(); }

extern void sub_00CF8A60(void);

void void_leaf_native_00CF8A60(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CF8A60u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x00000060u) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CF8A60(void) { if(leaf_mode())void_leaf_native_00CF8A60();else sub_00CF8A60(); }

extern void sub_00CFC430(void);

void void_leaf_native_00CFC430(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CFC430u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CFC430(void) { if(leaf_mode())void_leaf_native_00CFC430();else sub_00CFC430(); }

extern void sub_00D088A0(void);

void void_leaf_native_00D088A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00D088A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000114u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00D088A0(void) { if(leaf_mode())void_leaf_native_00D088A0();else sub_00D088A0(); }


extern void sub_0044D4E0(void);
void void_leaf_native_0044D4E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0044D4E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0044D4E0(void) { if(leaf_mode())void_leaf_native_0044D4E0();else sub_0044D4E0(); }

extern void sub_0048EB50(void);
void void_leaf_native_0048EB50(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0048EB50u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0xFFFFFF24u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0048EB50(void) { if(leaf_mode())void_leaf_native_0048EB50();else sub_0048EB50(); }

extern void sub_0048F160(void);
void void_leaf_native_0048F160(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0048F160u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000004Du);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0048F160(void) { if(leaf_mode())void_leaf_native_0048F160();else sub_0048F160(); }

extern void sub_004B1540(void);
void void_leaf_native_004B1540(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004B1540u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004B1540(void) { if(leaf_mode())void_leaf_native_004B1540();else sub_004B1540(); }

extern void sub_004BB090(void);
void void_leaf_native_004BB090(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004BB090u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004BB090(void) { if(leaf_mode())void_leaf_native_004BB090();else sub_004BB090(); }

extern void sub_004D8AD0(void);
void void_leaf_native_004D8AD0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004D8AD0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000034u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004D8AD0(void) { if(leaf_mode())void_leaf_native_004D8AD0();else sub_004D8AD0(); }

extern void sub_004D8F00(void);
void void_leaf_native_004D8F00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004D8F00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000000Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004D8F00(void) { if(leaf_mode())void_leaf_native_004D8F00();else sub_004D8F00(); }

extern void sub_004D8F50(void);
void void_leaf_native_004D8F50(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004D8F50u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000010u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004D8F50(void) { if(leaf_mode())void_leaf_native_004D8F50();else sub_004D8F50(); }

extern void sub_004D8F70(void);
void void_leaf_native_004D8F70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004D8F70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000018u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004D8F70(void) { if(leaf_mode())void_leaf_native_004D8F70();else sub_004D8F70(); }

extern void sub_004DDEE0(void);
void void_leaf_native_004DDEE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004DDEE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000064u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004DDEE0(void) { if(leaf_mode())void_leaf_native_004DDEE0();else sub_004DDEE0(); }

extern void sub_004DDF10(void);
void void_leaf_native_004DDF10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004DDF10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000036u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004DDF10(void) { if(leaf_mode())void_leaf_native_004DDF10();else sub_004DDF10(); }

extern void sub_004DDF20(void);
void void_leaf_native_004DDF20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004DDF20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x000000B0u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004DDF20(void) { if(leaf_mode())void_leaf_native_004DDF20();else sub_004DDF20(); }

extern void sub_004F8ED0(void);
void void_leaf_native_004F8ED0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004F8ED0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFDCu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004F8ED0(void) { if(leaf_mode())void_leaf_native_004F8ED0();else sub_004F8ED0(); }

extern void sub_004FB840(void);
void void_leaf_native_004FB840(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FB840u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000208u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FB840(void) { if(leaf_mode())void_leaf_native_004FB840();else sub_004FB840(); }

extern void sub_004FBA20(void);
void void_leaf_native_004FBA20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FBA20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_004FBA20(void) { if(leaf_mode())void_leaf_native_004FBA20();else sub_004FBA20(); }

extern void sub_00500BF0(void);
void void_leaf_native_00500BF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500BF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000198u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500BF0(void) { if(leaf_mode())void_leaf_native_00500BF0();else sub_00500BF0(); }

extern void sub_00500C00(void);
void void_leaf_native_00500C00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500C00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x000001FCu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500C00(void) { if(leaf_mode())void_leaf_native_00500C00();else sub_00500C00(); }

extern void sub_00500EE0(void);
void void_leaf_native_00500EE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00500EE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000001D8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00500EE0(void) { if(leaf_mode())void_leaf_native_00500EE0();else sub_00500EE0(); }

extern void sub_0050EFC0(void);
void void_leaf_native_0050EFC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0050EFC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF88u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0050EFC0(void) { if(leaf_mode())void_leaf_native_0050EFC0();else sub_0050EFC0(); }

extern void sub_0050FF50(void);
void void_leaf_native_0050FF50(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0050FF50u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF7Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0050FF50(void) { if(leaf_mode())void_leaf_native_0050FF50();else sub_0050FF50(); }

extern void sub_0053DBC0(void);
void void_leaf_native_0053DBC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0053DBC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x000002E0u) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0053DBC0(void) { if(leaf_mode())void_leaf_native_0053DBC0();else sub_0053DBC0(); }

extern void sub_00559C60(void);
void void_leaf_native_00559C60(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00559C60u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000000Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00559C60(void) { if(leaf_mode())void_leaf_native_00559C60();else sub_00559C60(); }

extern void sub_0055B7E0(void);
void void_leaf_native_0055B7E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0055B7E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0055B7E0(void) { if(leaf_mode())void_leaf_native_0055B7E0();else sub_0055B7E0(); }

extern void sub_007C32B0(void);
void void_leaf_native_007C32B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x007C32B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x0000000Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_007C32B0(void) { if(leaf_mode())void_leaf_native_007C32B0();else sub_007C32B0(); }

extern void sub_008478F0(void);
void void_leaf_native_008478F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008478F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008478F0(void) { if(leaf_mode())void_leaf_native_008478F0();else sub_008478F0(); }

extern void sub_00847920(void);
void void_leaf_native_00847920(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00847920u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00847920(void) { if(leaf_mode())void_leaf_native_00847920();else sub_00847920(); }

extern void sub_0087BBD0(void);
void void_leaf_native_0087BBD0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0087BBD0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000018u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0087BBD0(void) { if(leaf_mode())void_leaf_native_0087BBD0();else sub_0087BBD0(); }

extern void sub_00886CA0(void);
void void_leaf_native_00886CA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00886CA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000108u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00886CA0(void) { if(leaf_mode())void_leaf_native_00886CA0();else sub_00886CA0(); }

extern void sub_0089AD00(void);
void void_leaf_native_0089AD00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089AD00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000001Eu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089AD00(void) { if(leaf_mode())void_leaf_native_0089AD00();else sub_0089AD00(); }

extern void sub_0089B0A0(void);
void void_leaf_native_0089B0A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0089B0A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000007Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0089B0A0(void) { if(leaf_mode())void_leaf_native_0089B0A0();else sub_0089B0A0(); }

extern void sub_008ACDC0(void);
void void_leaf_native_008ACDC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008ACDC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF88u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008ACDC0(void) { if(leaf_mode())void_leaf_native_008ACDC0();else sub_008ACDC0(); }

extern void sub_008AE0C0(void);
void void_leaf_native_008AE0C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008AE0C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000044u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008AE0C0(void) { if(leaf_mode())void_leaf_native_008AE0C0();else sub_008AE0C0(); }

extern void sub_008AE2C0(void);
void void_leaf_native_008AE2C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008AE2C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0xFFFFFF74u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008AE2C0(void) { if(leaf_mode())void_leaf_native_008AE2C0();else sub_008AE2C0(); }

extern void sub_008AEAF0(void);
void void_leaf_native_008AEAF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008AEAF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF8Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008AEAF0(void) { if(leaf_mode())void_leaf_native_008AEAF0();else sub_008AEAF0(); }

extern void sub_008AEB30(void);
void void_leaf_native_008AEB30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008AEB30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF94u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008AEB30(void) { if(leaf_mode())void_leaf_native_008AEB30();else sub_008AEB30(); }

extern void sub_008AEB40(void);
void void_leaf_native_008AEB40(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008AEB40u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF90u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008AEB40(void) { if(leaf_mode())void_leaf_native_008AEB40();else sub_008AEB40(); }

extern void sub_008B77C0(void);
void void_leaf_native_008B77C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x008B77C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000038u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_008B77C0(void) { if(leaf_mode())void_leaf_native_008B77C0();else sub_008B77C0(); }

extern void sub_0093F960(void);
void void_leaf_native_0093F960(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0093F960u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0xB4513180u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0093F960(void) { if(leaf_mode())void_leaf_native_0093F960();else sub_0093F960(); }

extern void sub_0098CFA0(void);
void void_leaf_native_0098CFA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0098CFA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000013Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_0098CFA0(void) { if(leaf_mode())void_leaf_native_0098CFA0();else sub_0098CFA0(); }

extern void sub_009B19E0(void);
void void_leaf_native_009B19E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009B19E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009B19E0(void) { if(leaf_mode())void_leaf_native_009B19E0();else sub_009B19E0(); }

extern void sub_009B2B60(void);
void void_leaf_native_009B2B60(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009B2B60u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x500CBB00u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009B2B60(void) { if(leaf_mode())void_leaf_native_009B2B60();else sub_009B2B60(); }

extern void sub_009B30B0(void);
void void_leaf_native_009B30B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009B30B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x500CEC40u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009B30B0(void) { if(leaf_mode())void_leaf_native_009B30B0();else sub_009B30B0(); }

extern void sub_009B30F0(void);
void void_leaf_native_009B30F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009B30F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x16122B80u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009B30F0(void) { if(leaf_mode())void_leaf_native_009B30F0();else sub_009B30F0(); }

extern void sub_009D5060(void);
void void_leaf_native_009D5060(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x009D5060u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x00000030u) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_009D5060(void) { if(leaf_mode())void_leaf_native_009D5060();else sub_009D5060(); }

extern void sub_00A2D770(void);
void void_leaf_native_00A2D770(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A2D770u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000002Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A2D770(void) { if(leaf_mode())void_leaf_native_00A2D770();else sub_00A2D770(); }

extern void sub_00A69F00(void);
void void_leaf_native_00A69F00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A69F00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFF84u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A69F00(void) { if(leaf_mode())void_leaf_native_00A69F00();else sub_00A69F00(); }

extern void sub_00A6AB80(void);
void void_leaf_native_00A6AB80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A6AB80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0xFFFFFF98u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A6AB80(void) { if(leaf_mode())void_leaf_native_00A6AB80();else sub_00A6AB80(); }

extern void sub_00A6B060(void);
void void_leaf_native_00A6B060(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00A6B060u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00A6B060(void) { if(leaf_mode())void_leaf_native_00A6B060();else sub_00A6B060(); }

extern void sub_00AE67F0(void);
void void_leaf_native_00AE67F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AE67F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x9327DBC0u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AE67F0(void) { if(leaf_mode())void_leaf_native_00AE67F0();else sub_00AE67F0(); }

extern void sub_00AF7E70(void);
void void_leaf_native_00AF7E70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7E70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000094u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7E70(void) { if(leaf_mode())void_leaf_native_00AF7E70();else sub_00AF7E70(); }

extern void sub_00AF7EA0(void);
void void_leaf_native_00AF7EA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7EA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000ACu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7EA0(void) { if(leaf_mode())void_leaf_native_00AF7EA0();else sub_00AF7EA0(); }

extern void sub_00AF7EB0(void);
void void_leaf_native_00AF7EB0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7EB0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000B8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7EB0(void) { if(leaf_mode())void_leaf_native_00AF7EB0();else sub_00AF7EB0(); }

extern void sub_00AF7EC0(void);
void void_leaf_native_00AF7EC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7EC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000CCu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7EC0(void) { if(leaf_mode())void_leaf_native_00AF7EC0();else sub_00AF7EC0(); }

extern void sub_00AF7EE0(void);
void void_leaf_native_00AF7EE0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7EE0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000144u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7EE0(void) { if(leaf_mode())void_leaf_native_00AF7EE0();else sub_00AF7EE0(); }

extern void sub_00AF7F00(void);
void void_leaf_native_00AF7F00(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7F00u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000098u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7F00(void) { if(leaf_mode())void_leaf_native_00AF7F00();else sub_00AF7F00(); }

extern void sub_00AF7F30(void);
void void_leaf_native_00AF7F30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF7F30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000138u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF7F30(void) { if(leaf_mode())void_leaf_native_00AF7F30();else sub_00AF7F30(); }

extern void sub_00AF80E0(void);
void void_leaf_native_00AF80E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF80E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000088u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF80E0(void) { if(leaf_mode())void_leaf_native_00AF80E0();else sub_00AF80E0(); }

extern void sub_00AF80F0(void);
void void_leaf_native_00AF80F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF80F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000D4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF80F0(void) { if(leaf_mode())void_leaf_native_00AF80F0();else sub_00AF80F0(); }

extern void sub_00AF8100(void);
void void_leaf_native_00AF8100(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF8100u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000174u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF8100(void) { if(leaf_mode())void_leaf_native_00AF8100();else sub_00AF8100(); }

extern void sub_00AF8110(void);
void void_leaf_native_00AF8110(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF8110u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000DCu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF8110(void) { if(leaf_mode())void_leaf_native_00AF8110();else sub_00AF8110(); }

extern void sub_00AF8120(void);
void void_leaf_native_00AF8120(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF8120u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000190u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF8120(void) { if(leaf_mode())void_leaf_native_00AF8120();else sub_00AF8120(); }

extern void sub_00AF8150(void);
void void_leaf_native_00AF8150(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00AF8150u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000178u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00AF8150(void) { if(leaf_mode())void_leaf_native_00AF8150();else sub_00AF8150(); }

extern void sub_00B096E0(void);
void void_leaf_native_00B096E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B096E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFE4u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B096E0(void) { if(leaf_mode())void_leaf_native_00B096E0();else sub_00B096E0(); }

extern void sub_00B10A20(void);
void void_leaf_native_00B10A20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B10A20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x000000C0u) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B10A20(void) { if(leaf_mode())void_leaf_native_00B10A20();else sub_00B10A20(); }

extern void sub_00B14070(void);
void void_leaf_native_00B14070(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B14070u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x4E118380u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B14070(void) { if(leaf_mode())void_leaf_native_00B14070();else sub_00B14070(); }

extern void sub_00B26660(void);
void void_leaf_native_00B26660(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B26660u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B26660(void) { if(leaf_mode())void_leaf_native_00B26660();else sub_00B26660(); }

extern void sub_00B2A1F0(void);
void void_leaf_native_00B2A1F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B2A1F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000001Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B2A1F0(void) { if(leaf_mode())void_leaf_native_00B2A1F0();else sub_00B2A1F0(); }

extern void sub_00B4B5C0(void);
void void_leaf_native_00B4B5C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4B5C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000008Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4B5C0(void) { if(leaf_mode())void_leaf_native_00B4B5C0();else sub_00B4B5C0(); }

extern void sub_00B4C0D0(void);
void void_leaf_native_00B4C0D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C0D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000064u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C0D0(void) { if(leaf_mode())void_leaf_native_00B4C0D0();else sub_00B4C0D0(); }

extern void sub_00B4C0E0(void);
void void_leaf_native_00B4C0E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C0E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000084u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C0E0(void) { if(leaf_mode())void_leaf_native_00B4C0E0();else sub_00B4C0E0(); }

extern void sub_00B4C120(void);
void void_leaf_native_00B4C120(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4C120u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000194u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4C120(void) { if(leaf_mode())void_leaf_native_00B4C120();else sub_00B4C120(); }

extern void sub_00B4CE20(void);
void void_leaf_native_00B4CE20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B4CE20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000188u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B4CE20(void) { if(leaf_mode())void_leaf_native_00B4CE20();else sub_00B4CE20(); }

extern void sub_00B59EA0(void);
void void_leaf_native_00B59EA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B59EA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x00000003u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B59EA0(void) { if(leaf_mode())void_leaf_native_00B59EA0();else sub_00B59EA0(); }

extern void sub_00B5A9E0(void);
void void_leaf_native_00B5A9E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5A9E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x0000011Cu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5A9E0(void) { if(leaf_mode())void_leaf_native_00B5A9E0();else sub_00B5A9E0(); }

extern void sub_00B5A9F0(void);
void void_leaf_native_00B5A9F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5A9F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000200u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5A9F0(void) { if(leaf_mode())void_leaf_native_00B5A9F0();else sub_00B5A9F0(); }

extern void sub_00B5AA20(void);
void void_leaf_native_00B5AA20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AA20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x000001C4u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AA20(void) { if(leaf_mode())void_leaf_native_00B5AA20();else sub_00B5AA20(); }

extern void sub_00B5AA80(void);
void void_leaf_native_00B5AA80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5AA80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000060u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5AA80(void) { if(leaf_mode())void_leaf_native_00B5AA80();else sub_00B5AA80(); }

extern void sub_00B5ABA0(void);
void void_leaf_native_00B5ABA0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5ABA0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x000000D8u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5ABA0(void) { if(leaf_mode())void_leaf_native_00B5ABA0();else sub_00B5ABA0(); }

extern void sub_00B5ABF0(void);
void void_leaf_native_00B5ABF0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B5ABF0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000240u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B5ABF0(void) { if(leaf_mode())void_leaf_native_00B5ABF0();else sub_00B5ABF0(); }

extern void sub_00B72460(void);
void void_leaf_native_00B72460(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B72460u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B72460(void) { if(leaf_mode())void_leaf_native_00B72460();else sub_00B72460(); }

extern void sub_00B83860(void);
void void_leaf_native_00B83860(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B83860u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000002Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B83860(void) { if(leaf_mode())void_leaf_native_00B83860();else sub_00B83860(); }

extern void sub_00B8F4E0(void);
void void_leaf_native_00B8F4E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B8F4E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00B8F4E0(void) { if(leaf_mode())void_leaf_native_00B8F4E0();else sub_00B8F4E0(); }

extern void sub_00BC2940(void);
void void_leaf_native_00BC2940(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BC2940u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000020u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BC2940(void) { if(leaf_mode())void_leaf_native_00BC2940();else sub_00BC2940(); }

extern void sub_00BE6330(void);
void void_leaf_native_00BE6330(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BE6330u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x15084340u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BE6330(void) { if(leaf_mode())void_leaf_native_00BE6330();else sub_00BE6330(); }

extern void sub_00BE7B20(void);
void void_leaf_native_00BE7B20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BE7B20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x3027E380u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BE7B20(void) { if(leaf_mode())void_leaf_native_00BE7B20();else sub_00BE7B20(); }

extern void sub_00BE8400(void);
void void_leaf_native_00BE8400(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BE8400u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x17294C82u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BE8400(void) { if(leaf_mode())void_leaf_native_00BE8400();else sub_00BE8400(); }

extern void sub_00BEB6C0(void);
void void_leaf_native_00BEB6C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BEB6C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x11082C40u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BEB6C0(void) { if(leaf_mode())void_leaf_native_00BEB6C0();else sub_00BEB6C0(); }

extern void sub_00BEB700(void);
void void_leaf_native_00BEB700(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BEB700u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1106BC48u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BEB700(void) { if(leaf_mode())void_leaf_native_00BEB700();else sub_00BEB700(); }

extern void sub_00BEB880(void);
void void_leaf_native_00BEB880(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BEB880u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1106C3C2u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BEB880(void) { if(leaf_mode())void_leaf_native_00BEB880();else sub_00BEB880(); }

extern void sub_00BF0B90(void);
void void_leaf_native_00BF0B90(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BF0B90u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1107C380u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BF0B90(void) { if(leaf_mode())void_leaf_native_00BF0B90();else sub_00BF0B90(); }

extern void sub_00BF0D70(void);
void void_leaf_native_00BF0D70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BF0D70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1106C3C4u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BF0D70(void) { if(leaf_mode())void_leaf_native_00BF0D70();else sub_00BF0D70(); }

extern void sub_00BFF420(void);
void void_leaf_native_00BFF420(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BFF420u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0xFFFFFFC0u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00BFF420(void) { if(leaf_mode())void_leaf_native_00BFF420();else sub_00BFF420(); }

extern void sub_00C3FEC0(void);
void void_leaf_native_00C3FEC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C3FEC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000014Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C3FEC0(void) { if(leaf_mode())void_leaf_native_00C3FEC0();else sub_00C3FEC0(); }

extern void sub_00C419F0(void);
void void_leaf_native_00C419F0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C419F0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000130u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C419F0(void) { if(leaf_mode())void_leaf_native_00C419F0();else sub_00C419F0(); }

extern void sub_00C594A0(void);
void void_leaf_native_00C594A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C594A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(esp + 4); MEM32(ecx + 0x000000DCu) = eax;
    esp += 8; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C594A0(void) { if(leaf_mode())void_leaf_native_00C594A0();else sub_00C594A0(); }

extern void sub_00C594B0(void);
void void_leaf_native_00C594B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C594B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000104u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C594B0(void) { if(leaf_mode())void_leaf_native_00C594B0();else sub_00C594B0(); }

extern void sub_00C61AD0(void);
void void_leaf_native_00C61AD0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C61AD0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000078u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C61AD0(void) { if(leaf_mode())void_leaf_native_00C61AD0();else sub_00C61AD0(); }

extern void sub_00C752D0(void);
void void_leaf_native_00C752D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C752D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C752D0(void) { if(leaf_mode())void_leaf_native_00C752D0();else sub_00C752D0(); }

extern void sub_00C75300(void);
void void_leaf_native_00C75300(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C75300u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C75300(void) { if(leaf_mode())void_leaf_native_00C75300();else sub_00C75300(); }

extern void sub_00C75330(void);
void void_leaf_native_00C75330(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C75330u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C75330(void) { if(leaf_mode())void_leaf_native_00C75330();else sub_00C75330(); }

extern void sub_00C75360(void);
void void_leaf_native_00C75360(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C75360u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C75360(void) { if(leaf_mode())void_leaf_native_00C75360();else sub_00C75360(); }

extern void sub_00C7E7C0(void);
void void_leaf_native_00C7E7C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7E7C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B8Eu;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7E7C0(void) { if(leaf_mode())void_leaf_native_00C7E7C0();else sub_00C7E7C0(); }

extern void sub_00C7E810(void);
void void_leaf_native_00C7E810(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7E810u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B82u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7E810(void) { if(leaf_mode())void_leaf_native_00C7E810();else sub_00C7E810(); }

extern void sub_00C7EBC0(void);
void void_leaf_native_00C7EBC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7EBC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B80u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7EBC0(void) { if(leaf_mode())void_leaf_native_00C7EBC0();else sub_00C7EBC0(); }

extern void sub_00C7EFC0(void);
void void_leaf_native_00C7EFC0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7EFC0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1206A301u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7EFC0(void) { if(leaf_mode())void_leaf_native_00C7EFC0();else sub_00C7EFC0(); }

extern void sub_00C7F010(void);
void void_leaf_native_00C7F010(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F010u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B89u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F010(void) { if(leaf_mode())void_leaf_native_00C7F010();else sub_00C7F010(); }

extern void sub_00C7F0D0(void);
void void_leaf_native_00C7F0D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F0D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1206A2C1u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F0D0(void) { if(leaf_mode())void_leaf_native_00C7F0D0();else sub_00C7F0D0(); }

extern void sub_00C7F1B0(void);
void void_leaf_native_00C7F1B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F1B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x5014B340u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F1B0(void) { if(leaf_mode())void_leaf_native_00C7F1B0();else sub_00C7F1B0(); }

extern void sub_00C7F230(void);
void void_leaf_native_00C7F230(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F230u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x131A73C0u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F230(void) { if(leaf_mode())void_leaf_native_00C7F230();else sub_00C7F230(); }

extern void sub_00C7F4E0(void);
void void_leaf_native_00C7F4E0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F4E0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B85u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F4E0(void) { if(leaf_mode())void_leaf_native_00C7F4E0();else sub_00C7F4E0(); }

extern void sub_00C7F690(void);
void void_leaf_native_00C7F690(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C7F690u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B87u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C7F690(void) { if(leaf_mode())void_leaf_native_00C7F690();else sub_00C7F690(); }

extern void sub_00C82FB0(void);
void void_leaf_native_00C82FB0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C82FB0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B88u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C82FB0(void) { if(leaf_mode())void_leaf_native_00C82FB0();else sub_00C82FB0(); }

extern void sub_00C830A0(void);
void void_leaf_native_00C830A0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C830A0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B8Au;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C830A0(void) { if(leaf_mode())void_leaf_native_00C830A0();else sub_00C830A0(); }

extern void sub_00C831D0(void);
void void_leaf_native_00C831D0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C831D0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x1206A2C0u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C831D0(void) { if(leaf_mode())void_leaf_native_00C831D0();else sub_00C831D0(); }

extern void sub_00C83260(void);
void void_leaf_native_00C83260(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C83260u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = 0x12069B83u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C83260(void) { if(leaf_mode())void_leaf_native_00C83260();else sub_00C83260(); }

extern void sub_00C97C10(void);
void void_leaf_native_00C97C10(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C97C10u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000010u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C97C10(void) { if(leaf_mode())void_leaf_native_00C97C10();else sub_00C97C10(); }

extern void sub_00C97C20(void);
void void_leaf_native_00C97C20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C97C20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x00000011u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C97C20(void) { if(leaf_mode())void_leaf_native_00C97C20();else sub_00C97C20(); }

extern void sub_00C99920(void);
void void_leaf_native_00C99920(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C99920u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000040u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C99920(void) { if(leaf_mode())void_leaf_native_00C99920();else sub_00C99920(); }

extern void sub_00C99950(void);
void void_leaf_native_00C99950(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C99950u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000044u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C99950(void) { if(leaf_mode())void_leaf_native_00C99950();else sub_00C99950(); }

extern void sub_00C999B0(void);
void void_leaf_native_00C999B0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C999B0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000028u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C999B0(void) { if(leaf_mode())void_leaf_native_00C999B0();else sub_00C999B0(); }

extern void sub_00C99E70(void);
void void_leaf_native_00C99E70(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C99E70u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000002Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C99E70(void) { if(leaf_mode())void_leaf_native_00C99E70();else sub_00C99E70(); }

extern void sub_00C99E80(void);
void void_leaf_native_00C99E80(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C99E80u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000030u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00C99E80(void) { if(leaf_mode())void_leaf_native_00C99E80();else sub_00C99E80(); }

extern void sub_00CA6560(void);
void void_leaf_native_00CA6560(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CA6560u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    
    if (ecx) { eax = MEM32(ecx + 4); edx = MEM32(eax + 4); eax = edx + ecx + 4; }
    else { eax = 0;  }
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CA6560(void) { if(leaf_mode())void_leaf_native_00CA6560();else sub_00CA6560(); }

extern void sub_00CAB580(void);
void void_leaf_native_00CAB580(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CAB580u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000024u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CAB580(void) { if(leaf_mode())void_leaf_native_00CAB580();else sub_00CAB580(); }

extern void sub_00CB7F20(void);
void void_leaf_native_00CB7F20(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CB7F20u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = (eax & 0xFFFFFF00u) | MEM8(ecx + 0x0000004Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CB7F20(void) { if(leaf_mode())void_leaf_native_00CB7F20();else sub_00CB7F20(); }

extern void sub_00CB7F30(void);
void void_leaf_native_00CB7F30(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CB7F30u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000009Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CB7F30(void) { if(leaf_mode())void_leaf_native_00CB7F30();else sub_00CB7F30(); }

extern void sub_00CB94C0(void);
void void_leaf_native_00CB94C0(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CB94C0u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000184u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CB94C0(void) { if(leaf_mode())void_leaf_native_00CB94C0();else sub_00CB94C0(); }

extern void sub_00CBE380(void);
void void_leaf_native_00CBE380(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CBE380u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = ecx + 0x00000038u;
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CBE380(void) { if(leaf_mode())void_leaf_native_00CBE380();else sub_00CBE380(); }

extern void sub_00CE6750(void);
void void_leaf_native_00CE6750(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CE6750u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000024u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CE6750(void) { if(leaf_mode())void_leaf_native_00CE6750();else sub_00CE6750(); }

extern void sub_00CE6790(void);
void void_leaf_native_00CE6790(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CE6790u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x00000048u);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CE6790(void) { if(leaf_mode())void_leaf_native_00CE6790();else sub_00CE6790(); }

extern void sub_00CF2A90(void);
void void_leaf_native_00CF2A90(void) {
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00CF2A90u);
    (void)_cf; (void)_flag_k; (void)_flag_a; (void)_flag_b;
    eax = MEM32(ecx + 0x0000003Cu);
    esp += 4; RECOMP_EXIT_P(0x17u);
}

void void_leaf_dispatch_00CF2A90(void) { if(leaf_mode())void_leaf_native_00CF2A90();else sub_00CF2A90(); }
#endif
