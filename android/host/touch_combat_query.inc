/* Construct the native movement grid, without performing path search. */
static int combat_grid_capture(uint32_t screen, uint32_t actor, void_touch_battle_grid *grid)
{
    if (!grid) return 0;
    grid->width = grid->height = 0;
    uint32_t base = virtual_base(actor, 4), position = object_method(actor, 0x40);
    if (!read32(screen + 0x2A0) || !base || !position || !void_vm_readable(base, 8) ||
        (MEM8(base + 7) & 0x80u)) return 0;
    void_regs saved;
    void_regs_save(&saved);
    int ok = 0;
    uint32_t workspace = void_galloc(32);
    if (!workspace || !void_vm_writable(workspace, 32)) goto done;
    memset((void *)ADDR(workspace), 0, 32);
    MEM32(workspace + 16) = 2; MEM32(workspace + 20) = UINT32_MAX;
    const uint32_t args[] = {0, 0};
    g_edx = actor;
    void_call_guest_this(0x00C52CC0u, workspace, 2, args);
    uint32_t width = read32(workspace + 8), height = read32(workspace + 12);
    uint32_t rows = read32(workspace + 4), mode = read32(workspace + 16), start = workspace + 24;
    if (!width || width > 64 || !height || height > 64 || mode > 2 ||
        !void_vm_readable(rows, 4 * height) ||
        void_call_guest_this(position, actor, 1, &start) != start ||
        read32(start) >= width || read32(start + 4) >= height) goto release_grid;
    for (unsigned y = 0; y < height; ++y) {
        uint32_t row = read32(rows + 4 * y);
        if (!void_vm_readable(row, 8 * width)) goto release_grid;
        memcpy(grid->cells[y * width], (const void *)ADDR(row), 8 * width);
    }
    grid->width = width; grid->height = height; grid->mode = mode;
    grid->max_cost = read32(workspace + 20);
    grid->start_x = (int32_t)read32(start); grid->start_y = (int32_t)read32(start + 4);
    ok = 1;
release_grid:
    for (unsigned offset = 0; offset < 8; offset += 4) {
        uint32_t allocation = read32(workspace + offset);
        if (allocation) void_call_guest(0x00879240u, 1, &allocation, 0);
    }
done:
    if (workspace) void_gfree(workspace);
    void_regs_load(&saved);
    return ok;
}

/* Read-only native MoveAttack validation. The caller saves/restores guest registers. */
static unsigned combat_alternative_path(uint32_t arena, uint32_t actor, uint32_t target,
        uint32_t cell, uint32_t path, uint32_t pathfinder)
{
    const uint32_t args[] = {path, 0, path + 12, arena, 0, 0, pathfinder};
    g_ebx = cell; g_esi = actor; g_edi = target;
    if (!(void_call_guest(0x00C53F60u, 7, args, 1) & 0xFFu)) return 0;
    uint32_t begin = read32(path), end = read32(path + 4), capacity = read32(path + 8);
    if (!begin || end < begin || capacity < end || (end - begin) % 12 ||
        end - begin > 4096u * 12 || !void_vm_readable(begin, end - begin)) return 0;
    return (end - begin) / 12;
}

/* Consume a completed copied-grid search; the original validator skips its search.
 * Original validators still supply target, landing and special battlefield rules. */
static int combat_alternative_available_grid(uint32_t screen, uint32_t actor, int capabilities,
        const void_touch_battle_grid *grid)
{
    capabilities &= 3;
    if (!capabilities || !grid || !grid->width || grid->width > 64 || !grid->height ||
        grid->height > 64 || grid->mode > 2) return 0;
    uint32_t arena = read32(screen + 0x2A0), base = virtual_base(actor, 4);
    if (!base || !void_vm_readable(base, 8) || (MEM8(base + 7) & 0x80u)) return 0;
    uint32_t context_owner = virtual_base(arena, 8);
    uint32_t context_method = object_method(context_owner, 0x40);
    uint32_t position = object_method(actor, 0x40), size_method = object_method(actor, 0x44);
    uint32_t speed_method = object_method(actor, 0x48);
    if (!context_method || !position || !size_method || !speed_method) return 0;
    void_regs saved;
    void_regs_save(&saved);
    int result = 0;
    unsigned bytes = 88 + 4 * grid->height + 8 * grid->width * grid->height;
    uint32_t workspace = void_galloc(bytes);
    if (!workspace || !void_vm_writable(workspace, bytes)) goto done;
    memset((void *)ADDR(workspace), 0, 88);
    uint32_t pathfinder = workspace + 64, rows = workspace + 88, cells = rows + 4 * grid->height;
    MEM32(pathfinder) = cells; MEM32(pathfinder + 4) = rows;
    MEM32(pathfinder + 8) = grid->width; MEM32(pathfinder + 12) = grid->height;
    MEM32(pathfinder + 16) = grid->mode; MEM32(pathfinder + 20) = grid->max_cost;
    memcpy((void *)ADDR(cells), grid->cells, 8 * grid->width * grid->height);
    for (unsigned row = 0; row < grid->height; ++row) MEM32(rows + 4 * row) = cells + 8 * grid->width * row;
    uint32_t units = workspace, perimeter = workspace + 12, path = workspace + 24;
    uint32_t start = workspace + 40, target_cell = workspace + 48;
    uint32_t context = void_call_guest_this(context_method, context_owner, 0, NULL);
    unsigned size = void_call_guest_this(size_method, actor, 0, NULL);
    int speed = (int32_t)void_call_guest_this(speed_method, actor, 0, NULL);
    if (!size || size > 2 || speed < 0 ||
        void_call_guest_this(position, actor, 1, &start) != start ||
        read32(start) >= 64 || read32(start + 4) >= 64 ||
        (int32_t)read32(start) != grid->start_x || (int32_t)read32(start + 4) != grid->start_y ||
        (uint32_t)speed * 2u != grid->max_cost) goto release_vectors;
    g_edx = units;
    void_call_guest_this(0x00AF4450u, arena, 0, NULL);
    uint32_t begin = read32(units), end = read32(units + 4), capacity = read32(units + 8);
    if (end < begin || capacity < end || (end - begin) % 4 ||
        end - begin > 4096u * 4 || !void_vm_readable(begin, end - begin)) goto release_vectors;
    for (uint32_t entry = begin; entry < end && result != capabilities; entry += 4) {
        uint32_t target = read32(entry), target_base = virtual_base(target, 4);
        if (!target || target == actor || !target_base || !void_vm_readable(target_base, 8) ||
            (MEM8(target_base + 7) & 0x80u) || object_query(target, 0x74)) continue;
        uint32_t visible = object_method(target, 0x50), target_position = object_method(target, 0x40);
        uint32_t target_size_method = object_method(target, 0x44);
        if (!visible || !target_position || !target_size_method ||
            !(void_call_guest_this(visible, target, 1, &context) & 0xFFu)) continue;
        /* Vanilla's equivalent uses ESI; ToE/HoF use EDX. */
        g_edx = target; g_esi = target;
        if (!(void_call_guest_this(0x004E5790u, actor, 0, NULL) & 0xFFu)) continue;
        unsigned target_size = void_call_guest_this(target_size_method, target, 0, NULL);
        if (!target_size || target_size > 2 ||
            void_call_guest_this(target_position, target, 1, &target_cell) != target_cell ||
            read32(target_cell) >= 64 || read32(target_cell + 4) >= 64) continue;
        /* Minimum distance to the entire attack-anchor rectangle is a lower bound:
         * no reachable large/flying creature can be rejected by this prefilter. */
        int too_far = 0;
        for (unsigned axis = 0; axis < 2; ++axis) {
            int origin = (int)read32(start + 4*axis), at = (int)read32(target_cell + 4*axis);
            int lo = at - (int)target_size, hi = at + (int)size;
            if ((origin < lo && lo - origin > speed) ||
                (origin > hi && origin - hi > speed)) too_far = 1;
        }
        if (too_far) continue;
        unsigned points = combat_alternative_path(arena, actor, target, target_cell, path, pathfinder);
        if (!points) continue;
        result |= capabilities & 1;
        if (!(capabilities & 2)) continue;
        if (points > 1) { result |= 2; continue; }
        /* An adjacent target may still allow moving to another attack direction. */
        g_edx = actor;
        void_call_guest_this(0x00B3F2F0u, perimeter, 1, &target);
        uint32_t first = read32(perimeter), last = read32(perimeter + 4), limit = read32(perimeter + 8);
        if (last < first || limit < last || (last - first) % 8 ||
            last - first > 16u * 8 || !void_vm_readable(first, last - first)) continue;
        for (uint32_t cell = first; cell < last; cell += 8) {
            if (read32(cell) >= 64 || read32(cell + 4) >= 64 ||
                (read32(cell) == read32(start) && read32(cell + 4) == read32(start + 4))) continue;
            if (combat_alternative_path(arena, actor, target, cell, path, pathfinder) > 1) { result |= 2; break; }
        }
    }
release_vectors:
    for (unsigned offset = 0; offset < 36; offset += 12) {
        uint32_t allocation = read32(workspace + offset);
        if (allocation) void_call_guest(0x00879240u, 1, &allocation, 0);
    }
done:
    if (workspace) void_gfree(workspace);
    void_regs_load(&saved);
    return result;
}
