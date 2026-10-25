/* Guest-visible COM objects implemented by the host.
 *
 * A guest object is 8 bytes of guest memory: the vtable VA (a table of
 * synthetic method VAs) and an index into the host object table. Methods are
 * stdcall with `this` as the first stack argument. */
#ifndef VOID_COM_H
#define VOID_COM_H
#include "host.h"

typedef struct void_com_class {
    const char *name;
    int count;
    const void_fn *methods;
    uint32_t vtable;      /* built on first use */
} void_com_class;

typedef struct void_com_object {
    void_com_class *cls;
    uint32_t guest;       /* the guest object VA */
    int refs;
    void (*destroy)(struct void_com_object *);
} void_com_object;

uint32_t void_com_vtable(void_com_class *cls);
/* Allocate the guest half of host object `object` (which must start with a
 * void_com_object header). extra_guest bytes follow the 8-byte header. */
uint32_t void_com_wrap(void_com_object *object, void_com_class *cls, uint32_t extra_guest);
void *void_com_host(uint32_t guest_this);
uint32_t void_com_addref(void_com_object *object);
uint32_t void_com_release(void_com_object *object);
int void_guid_equal(uint32_t guid_va, const uint8_t guid[16]);
void void_guid_format(uint32_t guid_va, char out[40]);

#define THIS_ ARG(0)

/* A COM method popping `nargs` dwords including `this`. */
#define COM_METHOD(prefix, name, nargs) \
    static uint32_t prefix##_##name##_impl(void); \
    static void prefix##_##name(void) { uint32_t _r = prefix##_##name##_impl(); g_eax = _r; g_esp += 4u + 4u * (nargs); } \
    static uint32_t prefix##_##name##_impl(void)

/* An unimplemented slot: traps with the interface and slot name. */
#define COM_TODO(prefix, name) \
    static void prefix##_##name(void) { \
        void_log("[com] %s::%s is not implemented (caller %08X)", #prefix, #name, g_cur_func); \
        void_lift_trap(g_cur_func, "unimplemented COM method"); }

#endif
