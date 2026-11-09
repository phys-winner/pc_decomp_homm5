/* CSetRender's command maintenance loop. Opaque resource/destructor callbacks
 * keep their original protocol; the three MOV-only getters are local reads.
 * The machine owner also owns the cached per-process choice. */
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#include "host.h"
#include <stdio.h>
#include "native_mode.h"

extern void sub_00B1C300(void);
extern void sub_008C6150(void);
extern void sub_008790B0(void);
extern void sub_0087BD50(void);
extern void sub_00B1BB90(void);

typedef struct scene_link {
    uint32_t next, previous, command;
} scene_link;

typedef struct scene_command {
    uint32_t methods;
    uint8_t references[4];
    uint32_t weak_references;
    uint8_t ready, reserved[3];
    uint32_t eligible_at, expires_at;
    uint8_t data[0x44 - 0x18];
    uint32_t generation;
} scene_command;

_Static_assert(sizeof(scene_link) == 12, "original command-list node");
_Static_assert(offsetof(scene_command, generation) == 0x44, "original command layout");
#define SCENE_LINK(va) ((scene_link *)GPTR(va))
#define SCENE_COMMAND(va) ((scene_command *)GPTR(va))

/* Production callbacks do not consume flags. Protocol-check builds publish
 * them all, so retain the original lazy representation at those boundaries. */
#ifdef RECOMP_PROTOCOL_CHECK
#define SCENE_CMP(a, b) do { _flag_a = (a); _flag_b = (b); \
    _cf = _flag_a < _flag_b; _flag_k = FK_CMP; } while (0)
#define SCENE_TEST(a, b) do { _flag_a = (a); _flag_b = (b); \
    _cf = 0; _flag_k = FK_TEST; } while (0)
#define SCENE_BYTE_TEST(a, b) do { _flag_a = (uint32_t)(a) << 24; \
    _flag_b = (uint32_t)(b) << 24; _cf = 0; _flag_k = FK_NARROW(FK_TEST, 24); } while (0)
#define SCENE_ADD(a, b) do { _flag_a = (a); _flag_b = (b); \
    _cf = (uint32_t)(_flag_a + _flag_b) < _flag_a; _flag_k = FK_ADD; } while (0)
#define SCENE_LEAF_PUBLISH() do { RECOMP_FLAGS_OUT(); RECOMP_PUBLISH(0xFFu); } while (0)
#define SCENE_LEAF_EXIT() RECOMP_PUBLISH(0xFFu)
#else
#define SCENE_CMP(a, b) ((void)0)
#define SCENE_TEST(a, b) ((void)0)
#define SCENE_BYTE_TEST(a, b) ((void)0)
#define SCENE_ADD(a, b) ((void)0)
#define SCENE_LEAF_PUBLISH() ((void)0)
#define SCENE_LEAF_EXIT() ((void)0)
#endif

/* Keep the guest return-slot write and trace entry. No observer runs between
 * a MOV-only getter and its return; the next opaque call publishes its inputs. */
#define SCENE_READ(va, value) do { \
    PUSH32(esp, RECOMP_RETADDR); \
    SCENE_LEAF_PUBLISH(); RECOMP_ENTER(va); \
    eax = (value); esp += 4; SCENE_LEAF_EXIT(); RECOMP_FLAGS_IN(); \
} while (0)

void void_scene_native_commands(void)
{
    uint32_t _cf = 0, _flag_k = FK_NONE, _flag_a = 0, _flag_b = 0;
    RECOMP_REGS_LOCALS
    RECOMP_ENTER(0x00B1C300u);

    PUSH32(esp, ebx);
    ebx = ecx;
    eax = MEM32(ebx + 0x68);
    PUSH32(esp, edi);
    edi = SCENE_LINK(eax)->next;
    SCENE_CMP(edi, eax);
    if (edi != eax) {
        PUSH32(esp, ebp);
        ebp = MEM32(esp + 0x10);
        PUSH32(esp, esi);
        int more;
        do {
            esi = SCENE_LINK(edi)->command;
            SCENE_TEST(esi, esi);
            if (esi) SCENE_BYTE_TEST(SCENE_COMMAND(esi)->references[3], 0x80u);
            if (!esi || (SCENE_COMMAND(esi)->references[3] & 0x80u)) {
                /* Unlink before releasing the weak reference. Destruction may
                 * mutate the list; the original keeps this captured successor. */
                esi = SCENE_LINK(edi)->next;
                eax = SCENE_LINK(edi)->previous;
                SCENE_LINK(eax)->next = esi;
                SCENE_LINK(esi)->previous = eax;
                ecx = SCENE_LINK(edi)->command;
                SCENE_TEST(ecx, ecx);
                if (ecx) {
                    SCENE_ADD(SCENE_COMMAND(ecx)->weak_references, UINT32_MAX);
                    if (--SCENE_COMMAND(ecx)->weak_references == 0) {
                        RECOMP_CALL_P(sub_008C6150, 0x1Fu, 0x17u, 0, 0x00B1C33Bu);
                        RECOMP_FLAGS_IN();
                    }
                }
                PUSH32(esp, edi);
                RECOMP_CALL_P(sub_008790B0, 0x17u, 0x17u, 0, 0x00B1C341u);
                RECOMP_FLAGS_IN();
                SCENE_ADD(esp, 4u);
                esp += 4;
                edi = esi;
            } else {
                eax = SCENE_COMMAND(esi)->generation;
                SCENE_CMP(eax, UINT32_MAX);
                if (eax != UINT32_MAX) {
                    SCENE_CMP(eax, MEM32(ebx + 0xA4));
                    if (eax != MEM32(ebx + 0xA4)) {
                        ecx = esi;
                        RECOMP_CALL_P(sub_0087BD50, 0x1Fu, 0x17u, 0, 0x00B1C35Fu);
                        RECOMP_FLAGS_IN();
                        PUSH32(esp, esi);
                        ecx = ebx;
                        RECOMP_CALL_P(sub_00B1BB90, 0x57u, 0x17u, 0, 0x00B1C367u);
                        RECOMP_FLAGS_IN();
                    }
                }
                ecx = esi;
                SCENE_READ(0x0087BA00u, SCENE_COMMAND(ecx)->expires_at);
                SCENE_TEST(eax, eax);
                int expired = 0;
                if (eax) {
                    ecx = esi;
                    SCENE_READ(0x0087BA00u, SCENE_COMMAND(ecx)->expires_at);
                    SCENE_CMP(eax, ebp);
                    expired = eax < ebp;
                }
                if (expired) {
                    ecx = esi;
                    RECOMP_CALL_P(sub_0087BD50, 0x1Fu, 0x17u, 0, 0x00B1C384u);
                    RECOMP_FLAGS_IN();
                } else {
                    ecx = esi;
                    SCENE_READ(0x0087BA20u, (eax & 0xFFFFFF00u) | SCENE_COMMAND(ecx)->ready);
                    SCENE_BYTE_TEST((uint8_t)eax, (uint8_t)eax);
                    if (!(uint8_t)eax) {
                        ecx = esi;
                        SCENE_READ(0x0087B9F0u, SCENE_COMMAND(ecx)->eligible_at);
                        SCENE_CMP(eax, ebp);
                        if (eax <= ebp) {
                            eax = SCENE_COMMAND(esi)->methods;
                            ecx = esi;
                            RECOMP_ICALL_P(MEM32(eax + 0x20), 0x17u, 0x17u, 0, 0x00B1C3A5u);
                            RECOMP_FLAGS_IN();
                            SCENE_CMP(eax, MEM32(esp + 0x18));
                            if (eax == MEM32(esp + 0x18)) {
                                PUSH32(esp, esi);
                                ecx = ebx;
                                RECOMP_CALL_P(sub_00B1BB90, 0x57u, 0x17u, 0, 0x00B1C3B1u);
                                RECOMP_FLAGS_IN();
                            }
                        }
                    }
                }
                edi = SCENE_LINK(edi)->next;
            }
            /* The yield may change registers/memory. The pending comparison
             * remains the one made before that hand-over, as in the original. */
            SCENE_CMP(edi, MEM32(ebx + 0x68));
            more = edi != MEM32(ebx + 0x68);
            RECOMP_BACKEDGE();
        } while (more);
        esi = POP32_VAL(esp);
        ebp = POP32_VAL(esp);
    }
    edi = POP32_VAL(esp);
    ebx = POP32_VAL(esp);
    esp += 12;
    RECOMP_EXIT_P(0xFFu);
}

void void_scene_native_dispatch(void)
{
    static void_native_mode_cache cache = VOID_NATIVE_MODE_CACHE_INIT;
    int mode = void_native_mode_get(&cache, "native-scene", "[scene-native] mode=%d (cached for this process)");
    if (mode) void_scene_native_commands();
    else sub_00B1C300();
}
