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

#ifdef HOMM5_LEGACY_UI
/* The legacy spellbook camera (1.6 0x0063CFD0, 2.1 0x00641F10) projects a fixed 50-degree horizontal FOV,
   so wide screens crop the book's top and bottom. ToE's 0x006832D0 passes it through CF64F0/CF6490 with
   the screen size; this is that conversion for the viewport the caller has just filled. */
uint32_t void_book_fov(uint32_t viewport, uint32_t fov)
{
    float original;
    memcpy(&original, &fov, sizeof original);
    if (!void_vm_readable(viewport, 8) || !isfinite(original)) return fov;
    float width = MEMF(viewport), height = MEMF(viewport + 4);
    float ratio = height == 0 || width == 0 ? .75f : height / width;
    if (!isfinite(ratio) || ratio <= 0) return fov;
    double half = tan((double)original * 0x1.1df46ap-6 * .5);
    double angle = ratio <= .75f ? atan(half / ratio * .75) : atan(half * ratio * (double)1.3333334f);
    float adjusted = fp_f32((angle + angle) * 0x1.ca5dc0p+5);
    if (isfinite(adjusted) && adjusted > 0 && adjusted < 180) memcpy(&fov, &adjusted, sizeof fov);
    return fov;
}

/* The book's 4:3 frame (its 1024x768 design units) in the UI canvas, as void_book_fov projects it:
   the canvas height when the canvas is wider than 4:3, its width when taller. */
static int book_frame(double *scale, double *left, double *top)
{
    if (!void_vm_readable(0x00F74BE0u, 8)) return 0;
    float width = MEMF(0x00F74BE0u), height = MEMF(0x00F74BE4u);
    if (!isfinite(width) || !isfinite(height) || width <= 0 || height <= 0) return 0;
    *scale = height / width <= .75f ? height / 768.0 : width / 1024.0;
    *left = (width - 1024 * *scale) * .5;
    *top = (height - 768 * *scale) * .5;
    return 1;
}

/* Spell icons are fixed rects of that frame (MB_CastSpell parts; the pickers 0x00642070 / 0x0063D130 test
   them against the pick point), so the point moves into the frame first. */
uint32_t void_book_point(uint32_t point)
{
    static uint32_t frame_point;
    double scale, left, top;
    if (!void_vm_readable(point, 8) || !book_frame(&scale, &left, &top)) return point;
    if (!frame_point) frame_point = void_galloc(8);
    if (!frame_point || !void_vm_writable(frame_point, 8)) return point;
    MEMF(frame_point) = (float)((MEMF(point) - left) / scale);
    MEMF(frame_point + 4) = (float)((MEMF(point + 4) - top) / scale);
    return frame_point;
}

/* 0x00642870 / 0x0063D930 anchor a spell's tooltip at its rect: centre and half size, back to the canvas. */
void void_book_anchor(uint32_t anchor)
{
    double scale, left, top;
    if (!void_vm_writable(anchor, 16) || !book_frame(&scale, &left, &top)) return;
    for (unsigned i = 0; i < 4; ++i)
        MEM32(anchor + 4 * i) = (uint32_t)(int32_t)lround((int32_t)MEM32(anchor + 4 * i) * scale +
                                                          (i == 0 ? left : i == 1 ? top : 0));
}
#endif
