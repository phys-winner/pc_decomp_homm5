/* Map loads free render-list nodes in scene order. The original LIFO pool
 * then scatters replacement nodes across thousands of pages. Reorder only
 * free 16-byte blocks after the original list clear, before it is rebuilt. */
#include "host.h"
#include <stdlib.h>

static int scene_pool_address_compare(const void *left, const void *right)
{
    uint32_t a = *(const uint32_t *)left, b = *(const uint32_t *)right;
    return (a > b) - (a < b);
}

static uint32_t scene_pool_order_free16(uint32_t pool, uint32_t head_address,
        const uint32_t *starts, const uint32_t *cursors, const uint8_t *classes)
{
    enum { SLOT_BYTES = 0x100000u, COMMIT_BYTES = 0x10000u, SLOTS = 512u };
    uint32_t committed[SLOTS] = {0}, capacity = 0;
    if (!starts || !cursors || !classes || pool < COMMIT_BYTES ||
        (pool & (COMMIT_BYTES - 1u)) ||
        (uint64_t)pool + (uint64_t)SLOTS * SLOT_BYTES > 0xFFFE0000ull ||
        !void_vm_readable(head_address, 4) || !void_vm_writable(head_address, 4)) return 0;
    uint32_t head = MEM32(head_address);
    if (!head) return 0;
    for (uint32_t i = 0; i < SLOTS; ++i) {
        if (classes[i] != 1u) continue;
        uint32_t start = pool + i * SLOT_BYTES;
        uint64_t end = cursors[i] ? cursors[i] : (uint64_t)start + SLOT_BYTES;
        if (starts[i] != start || end < start || end > (uint64_t)start + SLOT_BYTES ||
            ((end - start) & (COMMIT_BYTES - 1u))) return 0;
        uint32_t bytes = (uint32_t)(end - start);
        if (bytes && (!void_vm_readable(start, bytes) || !void_vm_writable(start, bytes))) return 0;
        committed[i] = bytes;
        capacity += bytes / 16u;
    }
    if (!capacity) return 0;
    uint32_t *blocks = malloc((size_t)capacity * sizeof *blocks);
    if (!blocks) return 0;
    uint32_t at = head, slow = head, count = 0;
    while (at) {
        uint32_t offset = at - pool, slot = offset / SLOT_BYTES;
        if (at < pool || (uint64_t)at >= (uint64_t)pool + (uint64_t)SLOTS * SLOT_BYTES ||
            (offset & 15u) || slot >= SLOTS ||
            offset % SLOT_BYTES >= committed[slot] || count == capacity) {
            free(blocks); return 0;
        }
        blocks[count++] = at;
        at = MEM32(at);
        /* The half-speed pointer only visits previously validated blocks. */
        if (!(count & 1u)) slow = MEM32(slow);
        if (at && at == slow) { free(blocks); return 0; }
    }
    qsort(blocks, count, sizeof *blocks, scene_pool_address_compare);
    for (uint32_t i = 1; i < count; ++i)
        if (blocks[i - 1] == blocks[i]) { free(blocks); return 0; }
    if (MEM32(head_address) != head) { free(blocks); return 0; }
    /* Validate and allocate everything before changing any guest byte. */
    for (uint32_t i = 0; i < count; ++i)
        MEM32(blocks[i]) = i + 1 < count ? blocks[i + 1] : 0;
    MEM32(head_address) = blocks[0];
    free(blocks);
    return count;
}

void void_scene_pool_reorder(uint32_t list)
{
    if (list < 104) return;
    uint32_t root = list - 104;
    if (!void_vm_readable(root, 0x118) || MEM32(root) != 0x00E7B68Cu ||
        MEM32(root + 12) != 0x00E7B64Cu || MEM32(root + 268) != 0x00E7B62Cu) return;
    uint32_t sentinel = MEM32(list);
    if (!void_vm_readable(sentinel, 12) || MEM32(sentinel) != sentinel ||
        MEM32(sentinel + 4) != sentinel || !void_vm_readable(g_fs_base, 0x30) ||
        !void_vm_readable(0x010E5674u, 4) || !void_vm_readable(0x00FEAB20u, 4) ||
        !void_vm_readable(0x00FEAB28u, 4)) return;
    uint32_t index = MEM32(0x010E5674u), tls = MEM32(g_fs_base + 0x2C);
    if (index >= 64 || !void_vm_readable(tls, (index + 1) * 4)) return;
    uint32_t thread = MEM32(tls + index * 4);
    if (!void_vm_readable(thread, 8) || !MEM32(thread + 4) || MEM32(0x00FEAB20u) ||
        !void_vm_readable(0x00FE9740u, 2048) || !void_vm_readable(0x00FE9F40u, 2048) ||
        !void_vm_readable(0x00FEA740u, 512)) return;
    /* The caller owns the guest machine; no callback or yield may run here. */
    uint32_t count = scene_pool_order_free16(MEM32(0x00FEAB28u), 0x00FEA944u,
        (const uint32_t *)GPTR(0x00FE9740u), (const uint32_t *)GPTR(0x00FE9F40u),
        (const uint8_t *)GPTR(0x00FEA740u));
    if (count > 1) void_log("[memory] scene free16 locality: reordered %u blocks", count);
}
