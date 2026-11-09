/* Private typed archive-reference processing. Destruction queues and RTTI
 * graph search remain opaque original callbacks. Not routed or admitted. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_004FA280(void),sub_00C05AC0(void);
extern void sub_008C61D0(void),sub_00D119FC(void);

typedef struct object_base { uint32_t vtable, references; } object_base;
typedef struct complete_locator { uint32_t signature,offset,cd_offset,type; } complete_locator;
#define BASE(va) ((object_base *)GPTR(va))
#define LOCATOR(va) ((complete_locator *)GPTR(va))
#define REF_TEST(a,b) do{_flag_a=(a);_flag_b=(b);_cf=0;_flag_k=FK_TEST;}while(0)
#define REF_CMP(a,b) do{_flag_a=(a);_flag_b=(b);_cf=_flag_a<_flag_b;_flag_k=FK_CMP;}while(0)
#define REF_ADD(a,b) do{_flag_a=(a);_flag_b=(b);_cf=(uint32_t)(_flag_a+_flag_b)<_flag_a;_flag_k=FK_ADD;}while(0)
#define REF_BYTE(a) do{_flag_a=_flag_b=(uint32_t)(uint8_t)(a)<<24;_cf=0;_flag_k=FK_NARROW(FK_TEST,24);}while(0)
#define REF_LOCALS uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0; RECOMP_REGS_LOCALS (void)_cf;(void)_flag_k;(void)_flag_a;(void)_flag_b;

static void reference_release(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x00611AA0u);
    ecx=MEM32(esp+4);
    REF_TEST(ecx,ecx);
    if(ecx) {
        REF_ADD(BASE(ecx)->references,UINT32_MAX);
        BASE(ecx)->references--;
        eax=BASE(ecx)->references;
        REF_TEST(eax,0x000FFFFFu);
        if(!(eax&0x000FFFFFu)) {
            MEM32(esp+4)=0x000FFFFFu;
            RECOMP_TAIL_P(sub_008C61D0,0x1Fu,0);
            return;
        }
    }
    esp+=8;
    RECOMP_EXIT_P(0x17u);
}

static void reference_tile_cast(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x00C05B10u);
    REF_TEST(ecx,ecx);
    if(!ecx) {
        eax=0;REF_TEST(0,0);
    } else {
        eax=MEM32(MEM32(ecx)-4);
        edx=LOCATOR(eax)->offset;
        REF_TEST(edx,edx);
        eax=ecx;
        if(edx) {
            REF_CMP(eax,edx);
            eax-=edx;
            edx=MEM32(MEM32(eax)-4);
            REF_TEST(edx,edx);
            int compatible=0;
            if(edx) {
                REF_CMP(LOCATOR(edx)->type,0x00F78FC0u);
                compatible=LOCATOR(edx)->type==0x00F78FC0u;
            }
            if(!compatible) {
                PUSH32(esp,0);
                PUSH32(esp,0x00F78FC0u);
                PUSH32(esp,0x00F272C0u);
                PUSH32(esp,0);
                PUSH32(esp,ecx);
                RECOMP_CALL_P(sub_00D119FC,0x17u,0x17u,0,0x00C05B4Au);
                RECOMP_FLAGS_IN();
                REF_ADD(esp,20u);esp+=20u;
            }
        }
    }
    esp+=8;
    RECOMP_EXIT_P(0x17u);
}

static void reference_tile_assign(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x00731290u);
    edx=MEM32(esp+4);
    REF_TEST(edx,edx);
    eax=MEM32(ecx);
    MEM32(ecx)=edx;
    /* The slot may alias new/old object metadata: read after the store. */
    if(edx) {
        ecx=MEM32(MEM32(edx+4)+4);
        REF_ADD(MEM32(ecx+edx+8),1u);
        MEM32(ecx+edx+8)++;
        ecx+=edx+4;
    }
    REF_TEST(eax,eax);
    if(eax) {
        edx=MEM32(eax+4);
        ecx=MEM32(edx+4);
        REF_ADD(MEM32(ecx+eax+8),UINT32_MAX);
        MEM32(ecx+eax+8)--;
        ecx+=eax+4;
        eax=MEM32(ecx+4);
        REF_TEST(eax,0x000FFFFFu);
        if(!(eax&0x000FFFFFu)) {
            MEM32(esp+4)=0x000FFFFFu;
            RECOMP_TAIL_P(sub_008C61D0,0x1Fu,0);
            return;
        }
    }
    esp+=8;
    RECOMP_EXIT_P(0x17u);
}

static void reference_virtual_base(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x0061F290u);
    REF_TEST(ecx,ecx);
    if(ecx) {
        eax=MEM32(ecx+4);
        edx=MEM32(eax+4);
        eax=edx+ecx+4;
    } else {eax=0;REF_TEST(0,0);}
    esp+=4;
    RECOMP_EXIT_P(0x17u);
}

/* HOF_BASE_HELPER */

void void_reference_native_object(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x004FA280u);
    PUSH32(esp,esi);
    esi=ecx;
    eax=MEM32(esi);
    RECOMP_ICALL_P(MEM32(eax+0x3C),0x17u,0x17u,0,0x004FA285u);
    RECOMP_FLAGS_IN();REF_BYTE(eax);
    if((uint8_t)eax) {
        edx=MEM32(esi);ecx=esi;
        RECOMP_ICALL_P(MEM32(edx+0x38),0x17u,0x17u,0,0x004FA290u);
        RECOMP_FLAGS_IN();
        /* BASE_CONVERSION_BEGIN */
        REF_TEST(eax,eax);
        if(eax) {
            ecx=MEM32(MEM32(eax)-4);
            edx=LOCATOR(ecx)->offset;
            REF_TEST(edx,edx);
            if(edx) {
                ecx=eax;REF_CMP(ecx,edx);ecx-=edx;
                edx=MEM32(MEM32(ecx)-4);
                REF_TEST(edx,edx);
                if(edx) {
                    REF_CMP(LOCATOR(edx)->type,0x00F272C0u);
                    if(LOCATOR(edx)->type==0x00F272C0u)eax=ecx;
                }
            }
        }
        /* BASE_CONVERSION_END */
        REF_TEST(eax,eax);
        ecx=MEM32(esp+8);edx=MEM32(ecx);MEM32(ecx)=eax;
        if(eax) {REF_ADD(BASE(eax)->references,1u);BASE(eax)->references++;}
        esi=POP32_VAL(esp);MEM32(esp+4)=edx;
        RECOMP_TAIL_P(reference_release,0x1Fu,0);
        return;
    }
    ecx=MEM32(esp+8);edx=MEM32(ecx);eax=MEM32(esi);
    PUSH32(esp,edx);ecx=esi;
    RECOMP_ICALL_P(MEM32(eax+0x34),0x17u,0x17u,0,0x004FA2E0u);
    RECOMP_FLAGS_IN();
    esi=POP32_VAL(esp);esp+=8;
    RECOMP_EXIT_P(0x17u);
}

void void_reference_native_tile(void)
{
    REF_LOCALS
    RECOMP_ENTER(0x00C05AC0u);
    PUSH32(esp,esi);esi=ecx;eax=MEM32(esi);
    RECOMP_ICALL_P(MEM32(eax+0x3C),0x17u,0x17u,0,0x00C05AC5u);
    RECOMP_FLAGS_IN();REF_BYTE(eax);
    if((uint8_t)eax) {
        edx=MEM32(esi);ecx=esi;
        RECOMP_ICALL_P(MEM32(edx+0x38),0x17u,0x17u,0,0x00C05AD0u);
        RECOMP_FLAGS_IN();
        PUSH32(esp,0);edx=0;REF_TEST(0,0);ecx=eax;
        RECOMP_CALL_P(reference_tile_cast,0x17u,0x17u,0,0x00C05AD9u);
        RECOMP_FLAGS_IN();
        ecx=MEM32(esp+8);PUSH32(esp,eax);
        RECOMP_CALL_P(reference_tile_assign,0x1Fu,0x17u,0,0x00C05AE3u);
        RECOMP_FLAGS_IN();
    } else {
        eax=MEM32(esp+8);ecx=MEM32(eax);
        PUSH32(esp,edi);edi=MEM32(esi);
        RECOMP_CALL_P(reference_virtual_base,0x17u,0x17u,0,0x00C05AF5u);
        RECOMP_FLAGS_IN();
        PUSH32(esp,eax);ecx=esi;
        RECOMP_ICALL_P(MEM32(edi+0x34),0x17u,0x17u,0,0x00C05AFDu);
        RECOMP_FLAGS_IN();edi=POP32_VAL(esp);
    }
    esi=POP32_VAL(esp);esp+=8;
    RECOMP_EXIT_P(0x1Fu);
}

static void_native_mode_cache reference_mode = VOID_NATIVE_MODE_CACHE_INIT;
static int reference_enabled(void)
{
    return void_native_mode_get(&reference_mode, "native-references", "[native] archive references mode %d");
}
void void_reference_native_object_dispatch(void)
{if(reference_enabled())void_reference_native_object();else sub_004FA280();}
void void_reference_native_tile_dispatch(void)
{if(reference_enabled())void_reference_native_tile();else sub_00C05AC0();}
