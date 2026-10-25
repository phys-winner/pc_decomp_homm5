/* DirectInput 8: the system keyboard and mouse, fed by input.c. */
#include "com.h"
#include "input.h"

static const uint8_t IID_IDirectInput8A[16] = {0x30,0x80,0x79,0xBF,0x3A,0x48,0xA2,0x4D,0xAA,0x99,0x5D,0x64,0xED,0x36,0x97,0x00};
static const uint8_t IID_IDirectInput8W[16] = {0x31,0x80,0x79,0xBF,0x3A,0x48,0xA2,0x4D,0xAA,0x99,0x5D,0x64,0xED,0x36,0x97,0x00};
static const uint8_t IID_IDirectInputDevice8A[16] = {0x80,0x10,0xD4,0x54,0x15,0xDC,0x33,0x48,0xA4,0x1B,0x74,0x8F,0x73,0xA3,0x81,0x79};
static const uint8_t IID_IDirectInputDevice8W[16] = {0x81,0x10,0xD4,0x54,0x15,0xDC,0x33,0x48,0xA4,0x1B,0x74,0x8F,0x73,0xA3,0x81,0x79};
static const uint8_t IID_IUnknown[16] = {0,0,0,0,0,0,0,0,0xC0,0,0,0,0,0,0,0x46};
static const uint8_t GUID_SysMouse[16] = {0x60,0x2B,0x1D,0x6F,0xA0,0xD5,0xCF,0x11,0xBF,0xC7,0x44,0x45,0x53,0x54,0x00,0x00};
static const uint8_t GUID_SysKeyboard[16] = {0x61,0x2B,0x1D,0x6F,0xA0,0xD5,0xCF,0x11,0xBF,0xC7,0x44,0x45,0x53,0x54,0x00,0x00};

#define DI_OK 0u
#define DI_NOEFFECT 1u
#define DIERR_NOTACQUIRED 0x8007000Cu
#define DIERR_DEVICENOTREG 0x80040154u
#define DIERR_INVALIDPARAM 0x80070057u
#define DIERR_UNSUPPORTED 0x80004001u

enum { DEV_KEYBOARD, DEV_MOUSE };

typedef struct {
    void_com_object com;
    int kind;
    int wide;
    int acquired;
    uint32_t data_size;      /* from SetDataFormat */
    uint32_t buffer_size;    /* DIPROP_BUFFERSIZE */
    uint32_t event;          /* SetEventNotification */
} device_t;

typedef struct { void_com_object com; int wide; } dinput_t;

/* ------------------------------------------------------------ device */
static void_com_class device_class;

COM_METHOD(dev, QueryInterface, 3)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    if (void_guid_equal(ARG(1), IID_IDirectInputDevice8A) || void_guid_equal(ARG(1), IID_IDirectInputDevice8W) ||
        void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&d->com);
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    char g[40];
    void_guid_format(ARG(1), g);
    void_log("[dinput] device QueryInterface(%s): unsupported", g);
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(dev, AddRef, 1) { return void_com_addref(&((device_t *)void_com_host(THIS_))->com); }
COM_METHOD(dev, Release, 1) { return void_com_release(&((device_t *)void_com_host(THIS_))->com); }

COM_METHOD(dev, GetCapabilities, 2)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    uint32_t caps = ARG(1);
    uint32_t size = MEM32(caps);
    memset(GPTR(caps + 4), 0, size > 4 ? size - 4 : 0);
    MEM32(caps + 4) = 1;                                   /* DIDC_ATTACHED */
    if (d->kind == DEV_KEYBOARD) { MEM32(caps + 8) = 0x0413u; MEM32(caps + 16) = 128; }
    else { MEM32(caps + 8) = 0x0212u; MEM32(caps + 12) = 3; MEM32(caps + 16) = 3; }
    return DI_OK;
}

COM_METHOD(dev, EnumObjects, 4) { return DI_OK; }

COM_METHOD(dev, GetProperty, 3)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    uint32_t guid = ARG(1), header = ARG(2);
    if (guid == 1) { MEM32(header + 16) = d->buffer_size; return DI_OK; }   /* DIPROP_BUFFERSIZE */
    if (guid == 2) { MEM32(header + 16) = 0; return DI_OK; }                /* DIPROP_AXISMODE: relative */
    return DIERR_UNSUPPORTED;
}

COM_METHOD(dev, SetProperty, 3)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    uint32_t guid = ARG(1), header = ARG(2);
    if (guid == 1) d->buffer_size = MEM32(header + 16);
    VLOG("[dinput] SetProperty(%u) = %u", guid, guid < 0x10000u ? MEM32(header + 16) : 0);
    return DI_OK;
}

COM_METHOD(dev, Acquire, 1)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    if (d->acquired) return DI_NOEFFECT;
    d->acquired = 1;
    return DI_OK;
}

COM_METHOD(dev, Unacquire, 1)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    if (!d->acquired) return DI_NOEFFECT;
    d->acquired = 0;
    return DI_OK;
}

COM_METHOD(dev, GetDeviceState, 3)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    uint32_t size = ARG(1), out = ARG(2);
    if (!d->acquired) return DIERR_NOTACQUIRED;
    if (d->kind == DEV_KEYBOARD) {
        uint8_t keys[256];
        void_input_keyboard_snapshot(keys);
        memcpy(GPTR(out), keys, size < 256 ? size : 256);
        return DI_OK;
    }
    int32_t dx, dy, dz;
    uint8_t buttons[8];
    void_input_mouse_snapshot(&dx, &dy, &dz, buttons);
    memset(GPTR(out), 0, size);
    if (size >= 12) { MEM32(out) = (uint32_t)dx; MEM32(out + 4) = (uint32_t)dy; MEM32(out + 8) = (uint32_t)dz; }
    for (uint32_t i = 0; i < 8 && 12 + i < size; ++i) MEM8(out + 12 + i) = buttons[i];
    return DI_OK;
}

COM_METHOD(dev, GetDeviceData, 5)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    uint32_t object_size = ARG(1), out = ARG(2), inout = ARG(3), flags = ARG(4);
    if (!d->acquired) return DIERR_NOTACQUIRED;
    uint32_t want = MEM32(inout);
    void_input_event events[256];
    int max = want > 256 ? 256 : (int)want;
    int peek = (flags & 1u) != 0;
    int n = out ? (d->kind == DEV_KEYBOARD ? void_input_keyboard_events(events, max, peek)
                                           : void_input_mouse_events(events, max, peek))
                : (d->kind == DEV_KEYBOARD ? void_input_keyboard_events(events, max, 0)
                                           : void_input_mouse_events(events, max, 0));
    if (out) {
        for (int i = 0; i < n; ++i) {
            uint32_t e = out + (uint32_t)i * object_size;
            MEM32(e) = events[i].ofs; MEM32(e + 4) = events[i].data;
            MEM32(e + 8) = events[i].time; MEM32(e + 12) = events[i].seq;
            if (object_size >= 20) MEM32(e + 16) = 0;
        }
    }
    MEM32(inout) = (uint32_t)n;
    return DI_OK;
}

COM_METHOD(dev, SetDataFormat, 2)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    d->data_size = MEM32(ARG(1) + 12);
    VLOG("[dinput] SetDataFormat(%s): %u bytes, %u objects", d->kind == DEV_KEYBOARD ? "keyboard" : "mouse",
        d->data_size, MEM32(ARG(1) + 16));
    return DI_OK;
}

COM_METHOD(dev, SetEventNotification, 2) { ((device_t *)void_com_host(THIS_))->event = ARG(1); return DI_OK; }
COM_METHOD(dev, SetCooperativeLevel, 3) { return DI_OK; }
COM_METHOD(dev, GetObjectInfo, 4) { return DIERR_UNSUPPORTED; }

static void fill_instance(uint32_t out, int kind, int wide)
{
    uint32_t size = MEM32(out);
    memset(GPTR(out + 4), 0, size > 4 ? size - 4 : 0);
    const uint8_t *guid = kind == DEV_KEYBOARD ? GUID_SysKeyboard : GUID_SysMouse;
    memcpy(GPTR(out + 4), guid, 16);
    memcpy(GPTR(out + 20), guid, 16);
    MEM32(out + 36) = kind == DEV_KEYBOARD ? 0x0413u : 0x0212u;
    const char *name = kind == DEV_KEYBOARD ? "Keyboard" : "Mouse";
    if (wide) { void_utf8_to_gw(name, out + 40, 260); void_utf8_to_gw(name, out + 560, 260); }
    else { void_utf8_to_ga(name, out + 40, 260); void_utf8_to_ga(name, out + 300, 260); }
}

COM_METHOD(dev, GetDeviceInfo, 2)
{
    device_t *d = (device_t *)void_com_host(THIS_);
    fill_instance(ARG(1), d->kind, d->wide);
    return DI_OK;
}

COM_METHOD(dev, RunControlPanel, 3) { return DI_OK; }
COM_METHOD(dev, Initialize, 4) { return DI_OK; }
COM_METHOD(dev, CreateEffect, 5) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, EnumEffects, 4) { return DI_OK; }
COM_METHOD(dev, GetEffectInfo, 3) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, GetForceFeedbackState, 2) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, SendForceFeedbackCommand, 2) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, EnumCreatedEffectObjects, 4) { return DI_OK; }
COM_METHOD(dev, Escape, 2) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, Poll, 1) { return DI_NOEFFECT; }
COM_METHOD(dev, SendDeviceData, 5) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, EnumEffectsInFile, 5) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, WriteEffectToFile, 5) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, BuildActionMap, 4) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, SetActionMap, 4) { return DIERR_UNSUPPORTED; }
COM_METHOD(dev, GetImageInfo, 2) { return DIERR_UNSUPPORTED; }

static const void_fn device_methods[] = {
    dev_QueryInterface, dev_AddRef, dev_Release, dev_GetCapabilities, dev_EnumObjects, dev_GetProperty,
    dev_SetProperty, dev_Acquire, dev_Unacquire, dev_GetDeviceState, dev_GetDeviceData, dev_SetDataFormat,
    dev_SetEventNotification, dev_SetCooperativeLevel, dev_GetObjectInfo, dev_GetDeviceInfo, dev_RunControlPanel,
    dev_Initialize, dev_CreateEffect, dev_EnumEffects, dev_GetEffectInfo, dev_GetForceFeedbackState,
    dev_SendForceFeedbackCommand, dev_EnumCreatedEffectObjects, dev_Escape, dev_Poll, dev_SendDeviceData,
    dev_EnumEffectsInFile, dev_WriteEffectToFile, dev_BuildActionMap, dev_SetActionMap, dev_GetImageInfo,
};
static void_com_class device_class = { "IDirectInputDevice8", 32, device_methods, 0 };

/* ------------------------------------------------------------ IDirectInput8 */
COM_METHOD(di, QueryInterface, 3)
{
    dinput_t *d = (dinput_t *)void_com_host(THIS_);
    if (void_guid_equal(ARG(1), IID_IDirectInput8A) || void_guid_equal(ARG(1), IID_IDirectInput8W) ||
        void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&d->com);
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(di, AddRef, 1) { return void_com_addref(&((dinput_t *)void_com_host(THIS_))->com); }
COM_METHOD(di, Release, 1) { return void_com_release(&((dinput_t *)void_com_host(THIS_))->com); }

COM_METHOD(di, CreateDevice, 4)
{
    dinput_t *di = (dinput_t *)void_com_host(THIS_);
    int kind;
    if (void_guid_equal(ARG(1), GUID_SysKeyboard)) kind = DEV_KEYBOARD;
    else if (void_guid_equal(ARG(1), GUID_SysMouse)) kind = DEV_MOUSE;
    else {
        char g[40];
        void_guid_format(ARG(1), g);
        void_log("[dinput] CreateDevice(%s): no such device", g);
        MEM32(ARG(2)) = 0;
        return DIERR_DEVICENOTREG;
    }
    device_t *d = (device_t *)calloc(1, sizeof *d);
    d->kind = kind;
    d->wide = di->wide;
    MEM32(ARG(2)) = void_com_wrap(&d->com, &device_class, 0);
    void_log("[dinput] created %s device %08X", kind == DEV_KEYBOARD ? "keyboard" : "mouse", MEM32(ARG(2)));
    return DI_OK;
}

COM_METHOD(di, EnumDevices, 5)
{
    dinput_t *di = (dinput_t *)void_com_host(THIS_);
    uint32_t type = ARG(1), callback = ARG(2), ref = ARG(3);
    uint32_t inst = void_galloc(1100);
    int kinds[2] = { DEV_KEYBOARD, DEV_MOUSE };
    for (int i = 0; i < 2; ++i) {
        int k = kinds[i];
        int match = type == 0 || type == 1 || (type == 2 && k == DEV_MOUSE) || (type == 3 && k == DEV_KEYBOARD) ||
            (type == 0x13 && k == DEV_KEYBOARD) || (type == 0x12 && k == DEV_MOUSE);
        if (!match) continue;
        MEM32(inst) = di->wide ? 1100u : 580u;
        fill_instance(inst, k, di->wide);
        uint32_t args[2] = { inst, ref };
        if (!void_call_guest(callback, 2, args, 1)) break;
    }
    void_gfree(inst);
    return DI_OK;
}

COM_METHOD(di, GetDeviceStatus, 2)
{
    return (void_guid_equal(ARG(1), GUID_SysKeyboard) || void_guid_equal(ARG(1), GUID_SysMouse)) ? DI_OK : DIERR_DEVICENOTREG;
}
COM_METHOD(di, RunControlPanel, 3) { return DI_OK; }
COM_METHOD(di, Initialize, 3) { return DI_OK; }
COM_METHOD(di, FindDevice, 4) { return DIERR_DEVICENOTREG; }
COM_METHOD(di, EnumDevicesBySemantics, 6) { return DI_OK; }
COM_METHOD(di, ConfigureDevices, 5) { return DIERR_UNSUPPORTED; }

static const void_fn dinput_methods[] = {
    di_QueryInterface, di_AddRef, di_Release, di_CreateDevice, di_EnumDevices, di_GetDeviceStatus,
    di_RunControlPanel, di_Initialize, di_FindDevice, di_EnumDevicesBySemantics, di_ConfigureDevices,
};
static void_com_class dinput_class = { "IDirectInput8", 11, dinput_methods, 0 };

WINAPI_EXPORT("dinput8.dll", DirectInput8Create, 5)
{
    uint32_t riid = ARG(2), out = ARG(3);
    int wide = void_guid_equal(riid, IID_IDirectInput8W);
    if (!wide && !void_guid_equal(riid, IID_IDirectInput8A)) {
        char g[40];
        void_guid_format(riid, g);
        void_log("[dinput] DirectInput8Create(%s): unsupported interface", g);
        return E_NOINTERFACE_;
    }
    dinput_t *d = (dinput_t *)calloc(1, sizeof *d);
    d->wide = wide;
    MEM32(out) = void_com_wrap(&d->com, &dinput_class, 0);
    void_log("[dinput] DirectInput8Create(version %08X, %s) = %08X", ARG(1), wide ? "W" : "A", MEM32(out));
    return DI_OK;
}
