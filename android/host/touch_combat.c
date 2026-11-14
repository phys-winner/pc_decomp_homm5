#define _GNU_SOURCE
#include "host.h"
#include "touch_combat.h"
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#ifdef __ANDROID__
#include <sched.h>
#include <sys/resource.h>
#include <unistd.h>
#endif

#include "touch_combat_path.inc"

static pthread_mutex_t battle_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t battle_wake = PTHREAD_COND_INITIALIZER;
static pthread_t battle_thread;
static int battle_started, battle_failed, battle_stopping, battle_pending, battle_ready;
static uint32_t battle_wanted, battle_request, battle_result;
static void_touch_battle_grid battle_input, battle_output;

static void *battle_worker(void *unused)
{
    (void)unused;
#ifdef __ANDROID__
    /* Do not inherit the game thread's single-core affinity or elevated priority. */
    cpu_set_t cores;
    CPU_ZERO(&cores);
    long count = sysconf(_SC_NPROCESSORS_CONF);
    for (long i = 0; i < count && i < CPU_SETSIZE; ++i) CPU_SET(i, &cores);
    if (count > 0) sched_setaffinity(0, sizeof cores, &cores);
    setpriority(PRIO_PROCESS, 0, 5);
#endif
    void_touch_battle_grid grid;
    pthread_mutex_lock(&battle_lock);
    for (;;) {
        while (!battle_pending && !battle_stopping) pthread_cond_wait(&battle_wake, &battle_lock);
        if (battle_stopping) break;
        uint32_t ticket = battle_request;
        grid = battle_input;
        battle_pending = 0;
        pthread_mutex_unlock(&battle_lock);
        uint64_t start = void_perf_now_ns();
        int ok = void_touch_battle_solve(&grid);
        VLOG("[touch] battle-worker ticket=%u cells=%u solved=%d query_us=%llu", ticket,
             grid.width * grid.height, ok, (unsigned long long)((void_perf_now_ns() - start) / 1000));
        pthread_mutex_lock(&battle_lock);
        if (!battle_stopping && battle_wanted == ticket) {
            if (ok) battle_output = grid;
            battle_result = ticket;
            battle_ready = ok ? 1 : -1;
        }
    }
    pthread_mutex_unlock(&battle_lock);
    return NULL;
}

int void_touch_battle_submit(uint32_t ticket, const void_touch_battle_grid *grid)
{
    if (!ticket || !grid) return -1;
    if (pthread_mutex_trylock(&battle_lock)) return 0;
    int result = -1;
    if (!battle_stopping && !battle_failed) {
        if (!battle_started) {
            if (pthread_create(&battle_thread, NULL, battle_worker, NULL)) {
                battle_failed = 1;
                void_log("[touch] battle worker unavailable");
            } else battle_started = 1;
        }
        if (battle_started) {
            battle_wanted = battle_request = ticket;
            battle_input = *grid;
            battle_pending = 1;
            battle_ready = 0;
            pthread_cond_signal(&battle_wake);
            result = 1;
        }
    }
    pthread_mutex_unlock(&battle_lock);
    return result;
}

int void_touch_battle_poll(uint32_t ticket, void_touch_battle_grid *grid)
{
    if (!ticket || !grid || pthread_mutex_trylock(&battle_lock)) return 0;
    int result = 0;
    if (battle_wanted == ticket && battle_result == ticket && battle_ready) {
        result = battle_ready;
        if (result > 0) *grid = battle_output;
        battle_ready = 0;
    }
    pthread_mutex_unlock(&battle_lock);
    return result;
}

void void_touch_battle_cancel(void)
{
    /* The caller also advances its ticket, so a busy mailbox cannot revive old work. */
    if (pthread_mutex_trylock(&battle_lock)) return;
    battle_wanted = 0;
    battle_pending = battle_ready = 0;
    pthread_mutex_unlock(&battle_lock);
}

void void_touch_battle_shutdown(void)
{
    pthread_mutex_lock(&battle_lock);
    int started = battle_started;
    battle_stopping = 1;
    battle_wanted = 0;
    battle_pending = battle_ready = 0;
    pthread_cond_signal(&battle_wake);
    pthread_mutex_unlock(&battle_lock);
    if (started) pthread_join(battle_thread, NULL);
    pthread_mutex_lock(&battle_lock);
    battle_started = battle_failed = battle_stopping = 0;
    pthread_mutex_unlock(&battle_lock);
}
