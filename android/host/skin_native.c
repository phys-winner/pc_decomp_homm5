/* CVBCombiner's indexed packed-attribute weight selection. Allocation and
 * submission keep their boundaries; MMX math has an independent selector. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00C6B0B0(void);
extern void sub_00C6AEF0(void);
extern void sub_00C6A930(void);
extern void void_skin_math_one_dispatch(void);
extern void void_skin_math_two_dispatch(void);
extern void void_skin_math_three_dispatch(void);
extern void sub_00BA3B00(void);
extern void sub_00CF9BE0(void);

typedef struct skin_weight_record {
    uint8_t vertex[16], weight[3], reserved, bone[3], padding;
} skin_weight_record;
_Static_assert(sizeof(skin_weight_record)==24,"original weight-record stride");
#define WEIGHTS(va) ((skin_weight_record *)GPTR(va))

#ifdef RECOMP_PROTOCOL_CHECK
#define SKIN_CMP(a,b) do {_flag_a=(a);_flag_b=(b);_cf=_flag_a<_flag_b;_flag_k=FK_CMP;}while(0)
#define SKIN_TEST(a) do {_flag_a=_flag_b=(a);_cf=0;_flag_k=FK_TEST;}while(0)
#define SKIN_BYTE_TEST(a) do {_flag_a=_flag_b=(uint32_t)(uint8_t)(a)<<24;_cf=0;_flag_k=FK_NARROW(FK_TEST,24);}while(0)
#define SKIN_ADD(a,b) do {_flag_a=(a);_flag_b=(b);_cf=(uint32_t)(_flag_a+_flag_b)<_flag_a;_flag_k=FK_ADD;}while(0)
#else
#define SKIN_CMP(a,b) ((void)0)
#define SKIN_TEST(a) ((void)0)
#define SKIN_BYTE_TEST(a) ((void)0)
#define SKIN_ADD(a,b) ((void)0)
#endif

void void_skin_native_combine(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C6B0B0u);
    SKIN_CMP(esp,0x14u);
    esp-=0x14;
    eax=MEM32(esp+0x34);
    PUSH32(esp,edi);
    edi=ecx;
    ecx=MEM32(eax);
    SKIN_CMP(ecx,MEM32(eax+4));
    MEM32(esp+4)=edi;
    if(ecx==MEM32(eax+4)) {
        edx=MEM32(esp+0x40);
        eax=MEM32(esp+0x30);
        ecx=MEM32(esp+0x2C);
        PUSH32(esp,edx);
        edx=MEM32(esp+0x2C);
        PUSH32(esp,eax);
        eax=MEM32(esp+0x2C);
        PUSH32(esp,ecx);
        ecx=MEM32(esp+0x28);
        PUSH32(esp,edx);
        PUSH32(esp,eax);
        PUSH32(esp,ecx);
        ecx=edi;
        RECOMP_CALL_P(sub_00C6AEF0,0x17u,0x17u,0,0x00C6B0E5u);
        RECOMP_FLAGS_IN();
        edi=POP32_VAL(esp);
        esp+=0x14+44;
        RECOMP_EXIT_P(0xFFu);
        return;
    }

    PUSH32(esp,ebx);
    ebx=MEM32(esp+0x20);
    edx=MEM32(ebx+0x34)-MEM32(ebx+0x30);
    ebx+=0x30;
    eax=0xFFFF8000u;
    PUSH32(esp,ebp);
    PUSH32(esp,esi);
    MEM16(esp+0x14)=MEM16(esp+0x16)=MEM16(esp+0x18)=0x8000;
    eax=0xFFFF8080u;
    edx=(uint32_t)((int32_t)edx>>1);
    esi=0;
    SKIN_TEST(esi);
    PUSH32(esp,edx);
    ecx=0x010D9E34u;
    MEM16(esp+0x1E)=0;
    MEM16(esp+0x24)=MEM16(esp+0x22)=MEM16(esp+0x20)=0x8080;
    MEM16(esp+0x26)=0;
    /* These original argument slots are reused as observable local storage. */
    MEM32(esp+0x48)=ebx;
    RECOMP_CALL_P(sub_00C6A930,0x17u,0x17u,0,0x00C6B141u);
    RECOMP_FLAGS_IN();
    eax=MEM32(0x010D9E38u);
    ebp=MEM32(0x010D9E34u);
    eax=(uint32_t)((int32_t)(eax-ebp)>>2);
    MEM32(esp+0x34)=eax;
    SKIN_CMP(eax,esi);
    if((int32_t)eax>(int32_t)esi) {
        edi=MEM32(esp+0x30);
        SKIN_ADD(edi,8u);
        edi+=8;
        int more;
        do {
            uint32_t index=(uint32_t)MEM16(MEM32(ebx)+esi*2u);
            edx=MEM32(esp+0x40);
            ecx=index*3u;
            ebx=(ebx&0xFFFFFF00u)|WEIGHTS(edx+ecx*8u)->weight[1];
            SKIN_BYTE_TEST(ebx);
            eax=edx+ecx*8u;
            if(!(uint8_t)ebx) {
                eax=WEIGHTS(eax)->bone[0];
                ecx=MEM32(esp+0x48);
                edx=MEM32(ecx);
                eax=edx+eax*24u;
                PUSH32(esp,eax);
                ecx=esp+0x18;
                PUSH32(esp,ecx);
                ecx=ebp+esi*4u;
                edx=edi;
                RECOMP_CALL_P(void_skin_math_one_dispatch,0x17u,0x17u,0,0x00C6B1A5u);
                RECOMP_FLAGS_IN();
            } else {
                edx=(edx&0xFFFFFF00u)|WEIGHTS(eax)->weight[2];
                SKIN_BYTE_TEST(edx);
                if(!(uint8_t)edx) {
                    edx=MEM32(esp+0x48);
                    ecx=MEM32(edx);
                    edx=ecx+(uint32_t)WEIGHTS(eax)->bone[1]*24u;
                    PUSH32(esp,ebx);
                    PUSH32(esp,edx);
                    /* Original DWORD arguments retain pointer bits above AL. */
                    edx=(edx&0xFFFFFF00u)|WEIGHTS(eax)->weight[0];
                    eax=(uint32_t)WEIGHTS(eax)->bone[0]*3u;
                    ecx+=eax*8u;
                    PUSH32(esp,edx);
                    PUSH32(esp,ecx);
                    edx=esp+0x24;
                    PUSH32(esp,edx);
                    ecx=ebp+esi*4u;
                    edx=edi;
                    RECOMP_CALL_P(void_skin_math_two_dispatch,0x17u,0x17u,0,0x00C6B1DFu);
                    RECOMP_FLAGS_IN();
                } else {
                    ecx=MEM32(MEM32(esp+0x48));
                    PUSH32(esp,edx);
                    edx=ecx+(uint32_t)WEIGHTS(eax)->bone[2]*24u;
                    PUSH32(esp,edx);
                    edx=ecx+(uint32_t)WEIGHTS(eax)->bone[1]*24u;
                    PUSH32(esp,ebx);
                    PUSH32(esp,edx);
                    edx=(edx&0xFFFFFF00u)|WEIGHTS(eax)->weight[0];
                    eax=(uint32_t)WEIGHTS(eax)->bone[0]*3u;
                    ecx+=eax*8u;
                    PUSH32(esp,edx);
                    PUSH32(esp,ecx);
                    edx=esp+0x2C;
                    PUSH32(esp,edx);
                    ecx=ebp+esi*4u;
                    edx=edi;
                    RECOMP_CALL_P(void_skin_math_three_dispatch,0x17u,0x17u,0,0x00C6B21Eu);
                    RECOMP_FLAGS_IN();
                }
            }
            ebx=MEM32(esp+0x44);
            SKIN_ADD(esi,1u);
            esi++;
            SKIN_ADD(edi,0x14u);
            edi+=0x14;
            SKIN_CMP(esi,MEM32(esp+0x34));
            more=(int32_t)esi<(int32_t)MEM32(esp+0x34);
            RECOMP_BACKEDGE();
            if(more)ebp=MEM32(0x010D9E34u);
        } while(more);
        edi=MEM32(esp+0x10);
    }
    /* EMMS is intentionally a no-op in this runtime's explicit FP model. */
    ecx=MEM32(esp+0x3C);
    edx=MEM32(esp+0x38);
    eax=MEM32(edi);
    PUSH32(esp,1);
    PUSH32(esp,ecx);
    ecx=MEM32(esp+0x30);
    PUSH32(esp,edx);
    PUSH32(esp,eax);
    PUSH32(esp,0xD);
    RECOMP_CALL_P(sub_00BA3B00,0x17u,0x17u,0,0x00C6B252u);
    RECOMP_FLAGS_IN();
    edx=MEM32(esp+0x3C);
    ecx=MEM32(esp+0x5C);
    PUSH32(esp,eax);
    eax=MEM32(esp+0x44);
    PUSH32(esp,0x010D9E34u);
    PUSH32(esp,ebx);
    PUSH32(esp,eax);
    RECOMP_CALL_P(sub_00CF9BE0,0x17u,0x17u,0,0x00C6B26Bu);
    RECOMP_FLAGS_IN();
    esi=POP32_VAL(esp);
    ebp=POP32_VAL(esp);
    ebx=POP32_VAL(esp);
    edi=POP32_VAL(esp);
    esp+=0x14+44;
    RECOMP_EXIT_P(0xFFu);
}

void void_skin_native_dispatch(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-skin", "[skin-native] mode=%d (cached for this process)");
    if(mode)void_skin_native_combine();else sub_00C6B0B0();
}
