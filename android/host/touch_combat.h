#ifndef VOID_TOUCH_COMBAT_H
#define VOID_TOUCH_COMBAT_H
#include <stdint.h>

typedef struct {
    uint32_t width, height, mode, max_cost;
    int32_t start_x, start_y;
    uint32_t cells[4096][2];
} void_touch_battle_grid;

int void_touch_battle_solve(void_touch_battle_grid *grid);
/* Submit/poll never wait for the worker. -1 means failure, 0 busy, 1 success. */
int void_touch_battle_submit(uint32_t ticket, const void_touch_battle_grid *grid);
int void_touch_battle_poll(uint32_t ticket, void_touch_battle_grid *grid);
void void_touch_battle_cancel(void);
void void_touch_battle_shutdown(void);
#endif
