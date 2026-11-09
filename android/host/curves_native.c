/* Packed particle-key curves. Preserve the archive's packed layout and x87
 * precision/rounding helpers while expressing search/interpolation directly. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00BF5F30(void);
extern void sub_00BF60E0(void);

static inline uint32_t curve_status(uint32_t eax,int compare)
{
    uint32_t status=compare>=0x10000?(uint32_t)compare&0x4700u:
        compare==2?0x4500u:compare<0?0x0100u:compare==0?0x4000u:0;
    return (eax&0xFFFF0000u)|status;
}

void void_curve_native_word(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BF5F30u);
    (void)_cf;(void)_flag_k;(void)_flag_a;(void)_flag_b;
    X87_CHECK_ENTER();
    PUSH32(esp,ecx);
    eax=(eax&0xFFFF0000u)|MEM16(ecx);
    if((uint16_t)eax==1) {
        eax=MEM32(ecx+2);
        ecx=(ecx&0xFFFF0000u)|MEM16(eax+2);
        edx=MEM32(esp+0xC);
        MEM16(edx)=(uint16_t)ecx;
        ecx=POP32_VAL(esp);
    } else {
        double time=MEMF(esp+8);
        PUSH32(esp,esi);
        time=fp_pc(time-(double)MEMF(0x00E0AB70u));
        esi=(uint32_t)(int32_t)(int16_t)eax;
        PUSH32(esp,edi);
        edi=0;
        MEMF(esp+0x10)=fp_f32(time);
        --esi;
        MEM32(esp+8)=(uint32_t)(int32_t)fp_to_int((double)MEMF(esp+0x10));
        if((int32_t)esi>1) {
            PUSH32(esp,ebx);
            ebx=MEM32(ecx+2);
            PUSH32(esp,ebp);
            ebp=MEM32(esp+0x10);
            int more;
            do {
                eax=esi+edi;
                edx=(int32_t)eax<0?UINT32_MAX:0;
                eax=(uint32_t)((int32_t)(eax-edx)>>1);
                if((int16_t)MEM16(ebx+eax*4u)>(int16_t)ebp)esi=eax;
                else edi=eax;
                eax=esi-edi;
                more=(int32_t)eax>1;
                RECOMP_BACKEDGE();
            } while(more);
            ebp=POP32_VAL(esp);
            ebx=POP32_VAL(esp);
        }
        ecx=MEM32(ecx+2);
        edx=(edx&0xFFFF0000u)|MEM16(ecx+edi*4u+2);
        eax=MEM32(esp+0x14);
        edi=POP32_VAL(esp);
        MEM16(eax)=(uint16_t)edx;
        esi=POP32_VAL(esp);
        ecx=POP32_VAL(esp);
    }
    X87_CHECK_EXIT(0x00BF5F30u,0,0,0);
    esp+=12;
    RECOMP_EXIT_P(0xFFu);
}

void void_curve_native_scalar(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00BF60E0u);
    (void)_cf;(void)_flag_k;(void)_flag_a;(void)_flag_b;
    X87_CHECK_ENTER();
    eax=(eax&0xFFFF0000u)|MEM16(ecx);
    esp-=8;
    if((uint16_t)eax==1) {
        eax=MEM32(ecx+2);
        ecx=MEM32(eax+2);
        edx=MEM32(esp+0x10);
        MEM32(edx)=ecx;
        esp+=8;
    } else {
        double time=MEMF(esp+0xC);
        PUSH32(esp,esi);
        time=fp_pc(time-(double)MEMF(0x00E0AB70u));
        esi=(uint32_t)(int32_t)(int16_t)eax;
        PUSH32(esp,edi);
        edi=0;
        MEMF(esp+8)=fp_f32(time);
        --esi;
        MEM32(esp+0xC)=(uint32_t)(int32_t)fp_to_int((double)MEMF(esp+8));
        if((int32_t)esi>1) {
            PUSH32(esp,ebx);
            ebx=MEM32(ecx+2);
            PUSH32(esp,ebp);
            ebp=MEM32(esp+0x14);
            int more;
            do {
                eax=esi+edi;
                edx=(int32_t)eax<0?UINT32_MAX:0;
                eax=(uint32_t)((int32_t)(eax-edx)>>1);
                edx=eax*3u;
                if((int16_t)MEM16(ebx+edx*2u)>(int16_t)ebp)esi=eax;
                else edi=eax;
                eax=esi-edi;
                more=(int32_t)eax>1;
                RECOMP_BACKEDGE();
            } while(more);
            ebp=POP32_VAL(esp);
            ebx=POP32_VAL(esp);
        }
        eax=MEM32(ecx+2);
        edx=esi*3u;
        esi=(uint32_t)(int32_t)(int16_t)MEM16(eax+edx*2u);
        ecx=eax+edi*6u;
        edx=eax+edx*2u;
        eax=(uint32_t)(int32_t)(int16_t)MEM16(ecx);
        MEM32(esp+0xC)=eax;
        esi-=eax;
        double ratio=(double)(int32_t)MEM32(esp+0xC);
        edi=POP32_VAL(esp);
        ratio=fp_pc((double)MEMF(esp+0x10)-ratio);
        MEM32(esp+0x10)=esi;
        esi=POP32_VAL(esp);
        ratio=fp_pc(ratio/(double)(int32_t)MEM32(esp+0xC));
        void_fpu_cmp=FPU_CMP(ratio,(double)MEMF(0x00E0A7E4u));
        eax=curve_status(eax,void_fpu_cmp);
        if(!((eax>>8)&0x41u))ratio=MEMF(0x00E0A7E4u);
        else {
            void_fpu_cmp=FPU_CMP(ratio,(double)MEMF(0x00E0BE10u));
            eax=curve_status(eax,void_fpu_cmp);
            if(!RECOMP_PF(((eax>>8)&5u)<<24,24))ratio=MEMF(0x00E0BE10u);
        }
        double low=fp_pc((double)MEMF(0x00E0A7E4u)-ratio);
        eax=MEM32(esp+0x10);
        low=fp_pc(low*(double)MEMF(ecx+2));
        double high=fp_pc(ratio*(double)MEMF(edx+2));
        MEMF(eax)=fp_f32(fp_pc(low+high));
        esp+=8;
    }
    X87_CHECK_EXIT(0x00BF60E0u,0,0,0);
    esp+=12;
    RECOMP_EXIT_P(0xFFu);
}

static int curve_mode(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-curves", "[curve-native] mode=%d (cached for this process)");
    return mode;
}
void void_curve_native_word_dispatch(void)
{
    if(curve_mode())void_curve_native_word();else sub_00BF5F30();
}
void void_curve_native_scalar_dispatch(void)
{
    if(curve_mode())void_curve_native_scalar();else sub_00BF60E0();
}
