/* CObjectBase reference-vector archive traversal. Object lifetime and storage
 * allocation remain archive/vector callbacks; the typed walk is local. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_004FA1A0(void);
extern void sub_00720CC0(void);
extern void sub_00422F80(void);
extern void void_reference_native_object_dispatch(void);

typedef struct reference_vector { uint32_t begin, end, capacity; } reference_vector;
#define VECTOR(va) ((reference_vector *)GPTR(va))

#ifdef RECOMP_PROTOCOL_CHECK
#define VECTOR_CMP(a,b) do { _flag_a=(a);_flag_b=(b);_cf=_flag_a<_flag_b;_flag_k=FK_CMP; } while(0)
#define VECTOR_BYTE_TEST(a) do { _flag_a=_flag_b=(uint32_t)(uint8_t)(a)<<24;_cf=0;_flag_k=FK_NARROW(FK_TEST,24); } while(0)
#define VECTOR_ADD(a,b) do { _flag_a=(a);_flag_b=(b);_cf=(uint32_t)(_flag_a+_flag_b)<_flag_a;_flag_k=FK_ADD; } while(0)
#define VECTOR_SHIFT(a) do { _cf=((a)>>1)&1u;_flag_a=recomp_flags_pack((uint32_t)((int32_t)(a)>>2),_cf,0,0);_flag_b=0;_flag_k=FK_EFLAGS; } while(0)
#else
#define VECTOR_CMP(a,b) ((void)0)
#define VECTOR_BYTE_TEST(a) ((void)0)
#define VECTOR_ADD(a,b) ((void)0)
#define VECTOR_SHIFT(a) ((void)0)
#endif

static void vector_field(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FA250u);
    ecx=MEM32(esp+12);
    edx=MEM32(esp+8);
    PUSH32(esp,esi);
    esi=MEM32(esp+8);
    eax=MEM32(esi);
    PUSH32(esp,ecx);
    PUSH32(esp,edx);
    ecx=esi;
    RECOMP_ICALL_P(MEM32(eax+0x1C),0x17u,0x17u,0,0x004FA263u);
    RECOMP_FLAGS_IN();
    VECTOR_BYTE_TEST(eax);
    if((uint8_t)eax) {
        eax=MEM32(esp+0x14);
        PUSH32(esp,eax);
        ecx=esi;
        RECOMP_CALL_P(void_reference_native_object_dispatch,0x1Fu,0x17u,0,0x004FA271u);
        RECOMP_FLAGS_IN();
        edx=MEM32(esi);
        ecx=esi;
        esi=POP32_VAL(esp);
        RECOMP_ITAIL_P(MEM32(edx+0x20),0x1Fu,0);
        return;
    }
    esi=POP32_VAL(esp);
    esp+=4;
    RECOMP_EXIT_P(0x1Fu);
}

void void_vector_native_visit(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004FA1A0u);
    /* The first spill is also the mutable serialized count slot. */
    PUSH32(esp,ecx);
    PUSH32(esp,ebx);
    PUSH32(esp,esi);
    esi=ecx;
    eax=MEM32(esi);
    RECOMP_ICALL_P(MEM32(eax+0x3C),0x17u,0x17u,0,0x004FA1A7u);
    RECOMP_FLAGS_IN();
    VECTOR_BYTE_TEST(eax);
    int reading=(uint8_t)eax!=0;
    ebx=MEM32(esp+0x10);
    if(reading) {
        ecx=ebx;
        RECOMP_CALL_P(sub_00720CC0,0x1Fu,0x17u,0,0x004FA1B4u);
        RECOMP_FLAGS_IN();
        edx=MEM32(esi);
        ecx=esi;
        RECOMP_ICALL_P(MEM32(edx+0x44),0x17u,0x17u,0,0x004FA1BDu);
        RECOMP_FLAGS_IN();
        VECTOR_CMP(eax,2u);
        int modern=(int32_t)eax>=2;
        ecx=esi;
        PUSH32(esp,1);
        if(modern) {
            edx=MEM32(esi);
            PUSH32(esp,4);
            eax=esp+0x10;
            PUSH32(esp,eax);
            PUSH32(esp,2);
            RECOMP_ICALL_P(MEM32(edx+0x28),0x17u,0x17u,0,0x004FA1E9u);
            RECOMP_FLAGS_IN();
            ecx=MEM32(esp+8);
            PUSH32(esp,ecx);
            ecx=ebx;
            RECOMP_CALL_P(sub_00422F80,0x1Fu,0x17u,0,0x004FA1F3u);
            RECOMP_FLAGS_IN();
        } else {
            eax=MEM32(esi);
            RECOMP_ICALL_P(MEM32(eax+0x24),0x17u,0x17u,0,0x004FA1CBu);
            RECOMP_FLAGS_IN();
            ecx=eax;
            PUSH32(esp,ecx);
            ecx=ebx;
            MEM32(esp+0xC)=eax;
            RECOMP_CALL_P(sub_00422F80,0x1Fu,0x17u,0,0x004FA1D7u);
            RECOMP_FLAGS_IN();
        }
    } else {
        edx=VECTOR(ebx)->end;
        VECTOR_CMP(edx,VECTOR(ebx)->begin);
        edx-=VECTOR(ebx)->begin;
        eax=MEM32(esi);
        PUSH32(esp,1);
        PUSH32(esp,4);
        ecx=esp+0x10;
        PUSH32(esp,ecx);
        VECTOR_SHIFT(edx);
        edx=(uint32_t)((int32_t)edx>>2);
        PUSH32(esp,2);
        ecx=esi;
        MEM32(esp+0x18)=edx;
        RECOMP_ICALL_P(MEM32(eax+0x28),0x17u,0x17u,0,0x004FA215u);
        RECOMP_FLAGS_IN();
    }
    eax=0;
    VECTOR_CMP(MEM32(esp+8),eax);
    if((int32_t)MEM32(esp+8)>0) {
        PUSH32(esp,edi);
        int more;
        do {
            ecx=VECTOR(ebx)->begin;
            edx=esp+0x14;
            PUSH32(esp,edx);
            edx=ecx+eax*4u;
            PUSH32(esp,edx);
            edi=eax+1u;
            PUSH32(esp,edi);
            PUSH32(esp,1);
            PUSH32(esp,esi);
            RECOMP_CALL_P(vector_field,0x1Fu,0x17u,0,0x004FA233u);
            RECOMP_FLAGS_IN();
            eax=edi;
            VECTOR_ADD(esp,0x14u);
            esp+=0x14;
            VECTOR_CMP(eax,MEM32(esp+0xC));
            more=(int32_t)eax<(int32_t)MEM32(esp+0xC);
            RECOMP_BACKEDGE();
        } while(more);
        edi=POP32_VAL(esp);
    }
    esi=POP32_VAL(esp);
    ebx=POP32_VAL(esp);
    ecx=POP32_VAL(esp);
    esp+=8;
    RECOMP_EXIT_P(0xFFu);
}

void void_vector_native_dispatch(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-vector", "[vector-native] mode=%d (cached for this process)");
    if(mode)void_vector_native_visit();else sub_004FA1A0();
}
