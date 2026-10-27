/* Legacy CutScene cameras need Hor+; DialogScene already applies it itself. */
#include "host.h"
#include <math.h>

static uint32_t cutscene_read32(uint32_t address)
{
    return void_vm_readable(address, 4) ? MEM32(address) : 0;
}

uint32_t void_cutscene_fov(uint32_t camera, uint32_t viewport, uint32_t fov, uint32_t stack)
{
    if (!camera || !void_vm_readable(viewport, 8) ||
        !isfinite(MEMF(viewport)) || !isfinite(MEMF(viewport + 4)) ||
        MEMF(viewport + 4) <= 0 || MEMF(viewport) <= MEMF(viewport + 4) * (4.0f / 3.0f) ||
        !cutscene_read32(0x00FE719Cu) || !void_dispatch_find(0x008385A0u) ||
        !void_dispatch_find(0x00D119FCu)
#ifndef HOMM5_LEGACY_UI
        || !void_dispatch_find(0x00CF64F0u)
#endif
        ) return fov;
    void_regs saved;
    void_regs_save(&saved);
    /* The caller keeps ESP in a local; nested calls must stay below its live frame. */
    g_esp = stack;
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1);
    uint32_t table = cutscene_read32(interface + 4);
    uint32_t base = interface && table ? interface + 4 + cutscene_read32(table + 4) : 0;
    if (base && void_vm_readable(base, 4)) {
        const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
        uint32_t screen = void_call_guest(0x00D119FCu, 5, args, 0);
        if (cutscene_read32(screen) == 0x00E3261Cu && cutscene_read32(screen + 0x18C) == camera) {
#ifdef HOMM5_LEGACY_UI
            float original;
            memcpy(&original, &fov, sizeof original);
            /* ToE's CF6490 wide branch, with its exact float degree constants.
               The old engines have no viewport-to-Hor+ helper to call. */
            double angle = (double)original * 0x1.1df46ap-6 * .5;
            double ratio = (double)MEMF(viewport + 4) / MEMF(viewport);
            float adjusted = fp_f32(atan(tan(angle) * (.75 / ratio)) * 2.0 * 0x1.ca5dc0p+5);
#else
            void_call_guest_this(0x00CF64F0u, viewport, 1, &fov);
            float adjusted = fp_f32(g_st[0]);
#endif
            if (isfinite(adjusted) && adjusted > 0 && adjusted < 180) memcpy(&fov, &adjusted, sizeof fov);
        }
    }
    void_regs_load(&saved);
    return fov;
}
