/* The adventure map's object highlight (Alt held, its fade 0x0058F850) without rebuilding it every
 * frame (3.1 addresses; 1.6 and 2.1 have the same update and map it in their patch contracts).
 * NUI::CSelectionRender's update (vtable 0x00E21F78 slot 0, 0x005A0DB0, reached
 * only virtually) releases each highlight handle it holds (+10, a vector of refcounted effects) and asks
 * its render set (+C, NRender::CSetRender +30 = 0x00B18F00) again for every entry of its two lists (+14/+18
 * with flag 1, +20/+24 with flag 0; 20-byte entries: object, colour). With the highlight on, every
 * highlightable object of the map is listed, and that rebuild (dynamic casts over each object's parts,
 * allocations, the scene registering each effect, then releasing them all again) took ~5.6 ms of a 64 ms
 * frame on a Mali-G51 phone. The entries change only with the objects or the fade's colour, so a frame
 * whose lists equal the last ones keeps last frame's handles, which are what the rebuild would make
 * again. Refresh stable handles in small batches across 30 frames; a cursor/colour change only
 * rebuilds the affected entries. A different owner, renderer or list shape uses the original rebuild. */
#include "host.h"
#include <stdlib.h>
#include <string.h>

static void_fn original_update;
static struct { uint32_t self, renderer, first, second, frames; uint8_t *entries; size_t capacity; } last;

static int same_entries(uint32_t a, uint32_t first, uint32_t b, uint32_t second)
{
    return first == last.first && second == last.second &&
           (!first || !memcmp(last.entries, GPTR(a), first)) && (!second || !memcmp(last.entries + first, GPTR(b), second));
}

static void selection_update(void)
{
    uint32_t self = g_ecx;
    if (!void_vm_readable(self, 0x2C)) { original_update(); return; }
    uint32_t a = MEM32(self + 0x14), a_end = MEM32(self + 0x18), b = MEM32(self + 0x20), b_end = MEM32(self + 0x24);
    uint32_t handles = MEM32(self + 0x10), first = a_end - a, second = b_end - b, held = UINT32_MAX;
    int lists = a_end >= a && b_end >= b && first % 20 == 0 && second % 20 == 0 && first + second <= (1u << 20) &&
                (!first || void_vm_readable(a, first)) && (!second || void_vm_readable(b, second));
    if (lists && void_vm_readable(handles, 8) && MEM32(handles + 4) >= MEM32(handles) &&
        (MEM32(handles + 4) - MEM32(handles)) % 4 == 0) held = (MEM32(handles + 4) - MEM32(handles)) / 4;
    uint32_t renderer = MEM32(self + 0xC), method = void_vm_readable(renderer, 4) &&
        void_vm_readable(MEM32(renderer), 0x34) ? MEM32(MEM32(renderer) + 0x30) : 0;
    if (lists && first + second && held == (first + second) / 20 && self == last.self &&
        renderer == last.renderer && first == last.first && second == last.second &&
        void_vm_writable(MEM32(handles), held * 4) && method && void_dispatch_find(method)) {
        uint32_t slots = MEM32(handles), batch = (held + 29) / 30;
        int valid = 1, unchanged = same_entries(a, first, b, second);
        for (uint32_t i = 0; i < held; ++i)
            if (MEM32(slots + i * 4) && !void_vm_writable(MEM32(slots + i * 4), 8)) { valid = 0; break; }
        if (valid) {
            void_regs saved;
            void_regs_save(&saved);
            for (uint32_t i = 0; i < held; ++i) {
                uint32_t offset = i * 20, entry = offset < first ? a + offset : b + offset - first;
                int refresh = (i + held - last.frames) % held < batch;
                if (!refresh && (unchanged || !memcmp(last.entries + offset, GPTR(entry), 20))) continue;
                uint32_t slot = slots + i * 4, old = MEM32(slot);
                MEM32(slot) = 0;
                if (old && !(--MEM32(old + 4) & 0xFFFFFu)) {
                    const uint32_t mask = 0xFFFFFu;
                    void_call_guest_this(0x008C61D0u, old, 1, &mask);
                }
                const uint32_t args[] = {MEM32(entry), entry + 4, offset < first};
                uint32_t handle = void_call_guest_this(method, renderer, 3, args);
                MEM32(slot) = handle;
                if (handle) ++MEM32(handle + 4);
                memcpy(last.entries + offset, GPTR(entry), 20);
            }
            last.frames = (last.frames + batch) % held;
            void_regs_load(&saved);
            g_esp += 4;
            return;
        }
    }
    last.self = 0;
    if (lists && first + second) {
        if (first + second > last.capacity) {
            uint8_t *grown = realloc(last.entries, first + second);
            if (grown) { last.entries = grown; last.capacity = first + second; }
        }
        if (first + second <= last.capacity) {
            if (first) memcpy(last.entries, GPTR(a), first);
            if (second) memcpy(last.entries + first, GPTR(b), second);
            last.self = self; last.renderer = renderer; last.first = first; last.second = second; last.frames = 0;
        }
    }
    original_update();
}

void void_highlight_init(void)
{
    if (original_update) return;
    original_update = void_dispatch_find(0x005A0DB0u);
    if (original_update) void_dispatch_add(0x005A0DB0u, selection_update);
}
