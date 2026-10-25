/* Guest COM object plumbing. */
#include "com.h"

#define MAX_OBJECTS 65536
static void *objects[MAX_OBJECTS];
static uint32_t object_hint = 1;
static pthread_mutex_t com_lock = PTHREAD_MUTEX_INITIALIZER;

uint32_t void_com_vtable(void_com_class *cls)
{
    if (cls->vtable) return cls->vtable;
    uint32_t vt = void_galloc(4u * (uint32_t)cls->count);
    for (int i = 0; i < cls->count; ++i) {
        char *name = (char *)malloc(96);
        snprintf(name, 96, "%s#%d", cls->name, i);
        MEM32(vt + 4u * (uint32_t)i) = void_thunk(cls->methods[i], name);
    }
    cls->vtable = vt;
    return vt;
}

uint32_t void_com_wrap(void_com_object *object, void_com_class *cls, uint32_t extra_guest)
{
    pthread_mutex_lock(&com_lock);
    uint32_t index = 0;
    for (uint32_t n = 0; n < MAX_OBJECTS; ++n) {
        uint32_t i = (object_hint + n) % MAX_OBJECTS;
        if (i && !objects[i]) { index = i; break; }
    }
    if (!index) void_fatal("COM object table full");
    objects[index] = object;
    object_hint = index + 1;
    pthread_mutex_unlock(&com_lock);
    uint32_t guest = void_galloc(8u + extra_guest);
    MEM32(guest) = void_com_vtable(cls);
    MEM32(guest + 4) = index;
    object->cls = cls;
    object->guest = guest;
    object->refs = 1;
    return guest;
}

void *void_com_host(uint32_t guest)
{
    if (!guest || !void_vm_readable(guest, 8)) void_lift_trap(g_cur_func, "COM call on an invalid object");
    uint32_t index = MEM32(guest + 4);
    void *object = index && index < MAX_OBJECTS ? objects[index] : NULL;
    if (!object || ((void_com_object *)object)->guest != guest) void_lift_trap(g_cur_func, "COM call on a released object");
    return object;
}

uint32_t void_com_addref(void_com_object *object) { return (uint32_t)++object->refs; }

uint32_t void_com_release(void_com_object *object)
{
    int refs = --object->refs;
    if (refs > 0) return (uint32_t)refs;
    uint32_t guest = object->guest;
    pthread_mutex_lock(&com_lock);
    objects[MEM32(guest + 4)] = NULL;
    pthread_mutex_unlock(&com_lock);
    MEM32(guest) = 0;
    MEM32(guest + 4) = 0;
    void_gfree(guest);
    if (object->destroy) object->destroy(object);
    else free(object);
    return 0;
}

int void_guid_equal(uint32_t guid_va, const uint8_t guid[16])
{
    return guid_va && !memcmp(GPTR(guid_va), guid, 16);
}

void void_guid_format(uint32_t g, char out[40])
{
    if (!g) { strcpy(out, "(null)"); return; }
    snprintf(out, 40, "{%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}", MEM32(g), MEM16(g + 4), MEM16(g + 6),
        MEM8(g + 8), MEM8(g + 9), MEM8(g + 10), MEM8(g + 11), MEM8(g + 12), MEM8(g + 13), MEM8(g + 14), MEM8(g + 15));
}
