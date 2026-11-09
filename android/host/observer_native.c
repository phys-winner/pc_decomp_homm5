/* CChunklessSerializer's forwarding and virtual-base/buffer fast paths.
 * Growth keeps the original advance body, including merged legacy tails. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00C48A30(void);
extern void sub_004033B0(void);

typedef struct serializer_forwarder {
    uint32_t data[4], source, output;
} serializer_forwarder;
typedef struct serializer_stream {
    uint32_t methods, begin, capacity, high_water, position, flags;
} serializer_stream;
#define FORWARDER(va) ((serializer_forwarder *)GPTR(va))
#define STREAM(va) ((serializer_stream *)GPTR(va))
_Static_assert(offsetof(serializer_forwarder,output)==0x14,"original serializer output");
_Static_assert(offsetof(serializer_stream,position)==0x10,"original stream position");

#ifdef RECOMP_PROTOCOL_CHECK
#define OBSERVER_TEST(a, b) do { _flag_a=(a);_flag_b=(b);_cf=0;_flag_k=FK_TEST; } while(0)
#define OBSERVER_BYTE_TEST(a, b) do { _flag_a=(uint32_t)(a)<<24; \
    _flag_b=(uint32_t)(b)<<24;_cf=0;_flag_k=FK_NARROW(FK_TEST,24); } while(0)
#define OBSERVER_ADD(a, b) do { _flag_a=(a);_flag_b=(b); \
    _cf=(uint32_t)(_flag_a+_flag_b)<_flag_a;_flag_k=FK_ADD; } while(0)
#else
#define OBSERVER_TEST(a, b) ((void)0)
#define OBSERVER_BYTE_TEST(a, b) ((void)0)
#define OBSERVER_ADD(a, b) ((void)0)
#endif

static void observer_base(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x0061F290u);
    (void)_flag_k;
    if (ecx) {
        edx=MEM32(MEM32(ecx+4)+4);
        eax=ecx+edx+4;
    } else eax=0;
    esp+=4;
    RECOMP_EXIT_P(0x17u);
}

static void observer_advance(void)
{
    /* Check without touching registers, memory or TRACE. The original entry
     * then sees exactly its original frame on every allocating slow path. */
    uint32_t requested=MEM32(g_esp+4),buffer=g_ecx;
    if (requested>STREAM(buffer)->high_water && requested>STREAM(buffer)->capacity) {
        sub_004033B0();
        return;
    }
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x004033B0u);
    (void)_flag_k;
    edx=MEM32(esp+4);
    eax=STREAM(ecx)->high_water;
    STREAM(ecx)->position=edx;
    if (edx>eax) STREAM(ecx)->high_water=edx;
    eax=(eax&0xFFFFFF00u)|1u;
    esp+=8;
    RECOMP_EXIT_P(0x17u);
}

void void_observer_native_forward(void)
{
    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00C48A30u);
    PUSH32(esp,esi);
    esi=ecx;
    ecx=FORWARDER(esi)->source;
    OBSERVER_TEST(ecx,ecx);
    if (ecx) {
        RECOMP_CALL_P(observer_base,0x17u,0x17u,0,0x00C48A3Au);
        RECOMP_FLAGS_IN();
        OBSERVER_BYTE_TEST(MEM8(eax+7),0x80u);
        if (!(MEM8(eax+7)&0x80u)) {
            ecx=FORWARDER(esi)->source;
            edx=MEM32(esp+8);
            eax=MEM32(ecx);
            PUSH32(esp,edi);
            PUSH32(esp,edx);
            RECOMP_ICALL_P(MEM32(eax),0x17u,0x17u,0,0x00C48A50u);
            RECOMP_FLAGS_IN();
            /* The observer may change its output target during the callback. */
            esi=FORWARDER(esi)->output;
            OBSERVER_TEST(esi,esi);
            edi=eax;
            if (esi) {
                eax=STREAM(esi)->position;
                OBSERVER_ADD(eax,4u);
                eax+=4;
                PUSH32(esp,eax);
                ecx=esi;
                RECOMP_CALL_P(observer_advance,0x17u,0x17u,0,0x00C48A64u);
                RECOMP_FLAGS_IN();
                if ((uint8_t)eax) {
                    ecx=STREAM(esi)->position-4;
                    MEM32(ecx)=edi;
                }
            }
            edi=POP32_VAL(esp);
        }
    }
    esi=POP32_VAL(esp);
    esp+=8;
    RECOMP_EXIT_P(0x17u);
}

void void_observer_native_dispatch(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-observer", "[observer-native] mode=%d (cached for this process)");
    if (mode) void_observer_native_forward();
    else sub_00C48A30();
}
