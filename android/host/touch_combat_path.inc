/* B5F0D0's eight-bucket search over a copied native grid. No guest state. */
typedef struct {
    uint32_t (*cells)[2];
    unsigned head, end, capacity;
} combat_path_bucket;

static int combat_path_push(combat_path_bucket *bucket, const uint32_t cell[2])
{
    if (bucket->end == bucket->capacity) {
        unsigned capacity = bucket->capacity ? bucket->capacity * 2 : 32;
        if (capacity > 32768) return 0;
        void *cells = realloc(bucket->cells, capacity * sizeof *bucket->cells);
        if (!cells) return 0;
        bucket->cells = cells;
        bucket->capacity = capacity;
    }
    memcpy(bucket->cells[bucket->end++], cell, sizeof *bucket->cells);
    return 1;
}

int void_touch_battle_solve(void_touch_battle_grid *grid)
{
    if (!grid || !grid->width || grid->width > 64 || !grid->height || grid->height > 64 ||
        grid->mode > 2 || grid->start_x < 0 || grid->start_y < 0 ||
        (uint32_t)grid->start_x >= grid->width || (uint32_t)grid->start_y >= grid->height) return 0;
    for (unsigned y = 0; y < grid->height; ++y) for (unsigned x = 0; x < grid->width; ++x)
        if ((grid->cells[y * grid->width + x][1] & 0xFFFu) != ((y << 6) | x)) return 0;
    uint32_t *start = grid->cells[(unsigned)grid->start_y * grid->width + (unsigned)grid->start_x];
    if (start[1] & 0x800000u) return 1;
    combat_path_bucket buckets[8] = {{0}};
    unsigned pending = 0, bucket_index = 0;
    int ok = 0;
    /* The native seed is ignored if an existing zero-cost visit already owns it. */
    if (!(start[1] & 0x1000u) || (start[0] >> 16)) {
        start[0] = 0;
        start[1] = (start[1] & 0xFF801FFFu) | 0x1000u;
        if (!combat_path_push(&buckets[0], start)) goto done;
        pending = 1;
    }
    static const int offsets[8][2] = {{0,-1},{0,1},{-1,0},{1,0},{1,-1},{1,1},{-1,-1},{-1,1}};
    while (pending) {
        while (buckets[bucket_index].head == buckets[bucket_index].end)
            bucket_index = (bucket_index + 1) & 7;
        combat_path_bucket *bucket = &buckets[bucket_index];
        uint32_t entry[2]; memcpy(entry, bucket->cells[bucket->head++], sizeof entry);
        --pending;
        if (bucket->head == bucket->end) {
            bucket->head = bucket->end = 0;
            bucket_index = (bucket_index + 1) & 7;
        }
        int x = (int)(entry[1] & 63), y = (int)((entry[1] >> 6) & 63);
        if (grid->mode == 2 && (entry[1] & 0x1000000u) &&
            (x != grid->start_x || y != grid->start_y)) continue;
        for (unsigned direction = 0; direction < 8; ++direction) {
            int nx = x + offsets[direction][0], ny = y + offsets[direction][1];
            if (nx < 0 || ny < 0 || (unsigned)nx >= grid->width || (unsigned)ny >= grid->height) continue;
            uint32_t *cell = grid->cells[(unsigned)ny * grid->width + (unsigned)nx];
            unsigned step = direction < 4 ? 2 : 3;
            unsigned distance = (entry[0] & 0xFFFFu) + step, cost = (entry[0] >> 16) + step;
            if ((cell[1] & 0x800000u) || ((int32_t)grid->max_cost >= 0 && distance > grid->max_cost) ||
                ((cell[1] & 0x1000u) && (cell[0] >> 16) <= cost)) continue;
            cell[0] = (distance & 0xFFFFu) | ((cost & 0xFFFFu) << 16);
            cell[1] = (cell[1] & 0xFF801FFFu) | ((direction | (entry[1] >> 17 & 63) * 16) << 13) | 0x1000u;
            if (!combat_path_push(&buckets[distance & 7], cell)) goto done;
            ++pending;
        }
    }
    ok = 1;
done:
    for (unsigned i = 0; i < 8; ++i) free(buckets[i].cells);
    return ok;
}
