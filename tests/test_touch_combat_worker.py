"""Exercise the production battle mailbox on real threads with a held solver."""
import unittest

from test_static_tls import ROOT, compile_probe


PTHREAD = r'''
#ifndef TEST_PTHREAD_H
#define TEST_PTHREAD_H
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdlib.h>
typedef SRWLOCK pthread_mutex_t;
typedef CONDITION_VARIABLE pthread_cond_t;
typedef HANDLE pthread_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
#define PTHREAD_COND_INITIALIZER CONDITION_VARIABLE_INIT
static LONG create_calls, fail_create;
static void pthread_mutex_lock(pthread_mutex_t *m) { AcquireSRWLockExclusive(m); }
static void pthread_mutex_unlock(pthread_mutex_t *m) { ReleaseSRWLockExclusive(m); }
static int pthread_mutex_trylock(pthread_mutex_t *m) { return !TryAcquireSRWLockExclusive(m); }
static void pthread_cond_wait(pthread_cond_t *c, pthread_mutex_t *m) {
    assert(SleepConditionVariableSRW(c,m,INFINITE,0));
}
static void pthread_cond_signal(pthread_cond_t *c) { WakeConditionVariable(c); }
typedef struct { void *(*entry)(void *); void *arg; } thread_start;
static DWORD WINAPI thread_entry(void *value) {
    thread_start start=*(thread_start *)value;
    free(value); start.entry(start.arg); return 0;
}
static int pthread_create(pthread_t *t, const void *attr, void *(*entry)(void *), void *arg) {
    (void)attr; InterlockedIncrement(&create_calls);
    if (InterlockedCompareExchange(&fail_create,0,0)) return 1;
    thread_start *start=(thread_start *)malloc(sizeof *start); assert(start);
    start->entry=entry; start->arg=arg;
    *t=CreateThread(NULL,0,thread_entry,start,0,NULL);
    if (!*t) { free(start); return 1; }
    return 0;
}
static void pthread_join(pthread_t t, void *unused) {
    (void)unused; assert(WaitForSingleObject(t,3000)==WAIT_OBJECT_0); CloseHandle(t);
}
#endif
'''

HOST = r'''
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include "pthread.h"
static uint64_t void_perf_now_ns(void) { return GetTickCount64()*1000000ull; }
static void void_log(const char *format, ...) { (void)format; }
#define VLOG(...) void_log(__VA_ARGS__)
'''

SOLVER_WRAPPER = r'''
static HANDLE solver_entered, solver_release;
static DWORD game_thread;
static LONG solve_calls;
static uint32_t solved_identity[32], captured_width[32];
int void_touch_battle_solve(void_touch_battle_grid *grid) {
    assert(GetCurrentThreadId()!=game_thread);
    LONG index=InterlockedIncrement(&solve_calls)-1; assert(index<32);
    solved_identity[index]=grid->max_cost; captured_width[index]=grid->width;
    SetEvent(solver_entered);
    assert(WaitForSingleObject(solver_release,3000)==WAIT_OBJECT_0);
    return actual_battle_solve(grid);
}
'''

HARNESS = r'''
#include "touch_combat.c"
static void wait_event(HANDLE event) { assert(WaitForSingleObject(event,3000)==WAIT_OBJECT_0); }
static void join_thread(HANDLE thread) { wait_event(thread); CloseHandle(thread); }
static void_touch_battle_grid make_grid(uint32_t identity) {
    void_touch_battle_grid grid={0};
    grid.width=3; grid.height=3; grid.start_x=1; grid.start_y=1; grid.max_cost=identity;
    for (unsigned y=0;y<3;++y) for (unsigned x=0;x<3;++x) grid.cells[y*3+x][1]=(y<<6)|x;
    return grid;
}
static void submit(uint32_t ticket, const void_touch_battle_grid *grid) {
    ULONGLONG end=GetTickCount64()+2000;
    int result;
    while (!(result=void_touch_battle_submit(ticket,grid))) { assert(GetTickCount64()<end); Sleep(0); }
    assert(result==1);
}
static int poll(uint32_t ticket, void_touch_battle_grid *grid) {
    ULONGLONG end=GetTickCount64()+2000;
    int result;
    while (!(result=void_touch_battle_poll(ticket,grid))) { assert(GetTickCount64()<end); Sleep(0); }
    return result;
}
static HANDLE mailbox_locked, mailbox_release;
static DWORD WINAPI hold_mailbox(void *unused) {
    (void)unused; pthread_mutex_lock(&battle_lock); SetEvent(mailbox_locked);
    wait_event(mailbox_release); pthread_mutex_unlock(&battle_lock); return 0;
}
static DWORD WINAPI stop_worker(void *unused) { (void)unused; void_touch_battle_shutdown(); return 0; }
int main(void) {
    game_thread=GetCurrentThreadId();
    solver_entered=CreateEvent(NULL,FALSE,FALSE,NULL); solver_release=CreateEvent(NULL,FALSE,FALSE,NULL);
    mailbox_locked=CreateEvent(NULL,FALSE,FALSE,NULL); mailbox_release=CreateEvent(NULL,FALSE,FALSE,NULL);
    assert(solver_entered && solver_release && mailbox_locked && mailbox_release);
    void_touch_battle_grid first=make_grid(101), second=make_grid(102), latest=make_grid(103), output={0};
    assert(void_touch_battle_submit(0,&first)==-1 && void_touch_battle_submit(1,NULL)==-1);
    assert(!void_touch_battle_poll(0,&output) && !void_touch_battle_poll(1,NULL));
    assert(!create_calls && !solve_calls);

    /* Real mutex contention cannot stall submit, poll, or cancel. The owner only
       releases after all three return, so a blocking implementation deadlocks. */
    HANDLE holder=CreateThread(NULL,0,hold_mailbox,NULL,0,NULL); wait_event(mailbox_locked);
    assert(!void_touch_battle_submit(1,&first)); assert(!void_touch_battle_poll(1,&output));
    void_touch_battle_cancel(); assert(!create_calls); SetEvent(mailbox_release); join_thread(holder);

    submit(1,&first); wait_event(solver_entered);
    first.width=64; first.cells[0][1]=0xDEADBEEFu;
    assert(captured_width[0]==3 && solved_identity[0]==101);
    /* The worker is held before calculation; the game can replace its queued
       request twice, and can poll repeatedly without waiting for computation. */
    submit(2,&second); submit(3,&latest); latest.width=0;
    for (unsigned i=0;i<1000;++i) assert(!void_touch_battle_poll(3,&output));
    assert(solve_calls==1 && create_calls==1);
    SetEvent(solver_release); wait_event(solver_entered);
    assert(solve_calls==2 && solved_identity[1]==103 && captured_width[1]==3);
    assert(!void_touch_battle_poll(1,&output) && !void_touch_battle_poll(2,&output));
    pthread_mutex_lock(&battle_lock); assert(!battle_ready); pthread_mutex_unlock(&battle_lock);
    SetEvent(solver_release); assert(poll(3,&output)==1);
    assert(output.max_cost==103 && output.width==3 && (output.cells[0][1]&0x1000u));
    assert(!void_touch_battle_poll(3,&output));
    Sleep(10); assert(solve_calls==2); /* An empty mailbox does no repeated search. */

    /* Cancellation drops both the running result and the waiting replacement. */
    first=make_grid(104); second=make_grid(105);
    submit(4,&first); wait_event(solver_entered); submit(5,&second); void_touch_battle_cancel();
    SetEvent(solver_release);
    first=make_grid(106); submit(6,&first); wait_event(solver_entered);
    assert(solve_calls==4 && solved_identity[3]==106);
    assert(!void_touch_battle_poll(4,&output) && !void_touch_battle_poll(5,&output));
    SetEvent(solver_release); assert(poll(6,&output)==1 && output.max_cost==106);

    /* A solver rejection is consumed exactly once and leaves output untouched. */
    first=make_grid(107); first.width=0; submit(7,&first); wait_event(solver_entered);
    SetEvent(solver_release); assert(poll(7,&output)==-1 && output.max_cost==106);
    assert(!void_touch_battle_poll(7,&output));

    /* A different generation cannot consume a completed valid result. */
    first=make_grid(108); submit(8,&first); wait_event(solver_entered); SetEvent(solver_release);
    ULONGLONG deadline=GetTickCount64()+2000;
    for (;;) {
        pthread_mutex_lock(&battle_lock); int ready=battle_ready; pthread_mutex_unlock(&battle_lock);
        if (ready) break; assert(GetTickCount64()<deadline); Sleep(0);
    }
    assert(!void_touch_battle_poll(7,&output)); assert(poll(8,&output)==1 && output.max_cost==108);

    /* Shutdown joins the actual worker, rejects new work, and suppresses its
       eventual completion. This blocking operation is outside the game loop. */
    first=make_grid(109); submit(9,&first); wait_event(solver_entered);
    HANDLE stopper=CreateThread(NULL,0,stop_worker,NULL,0,NULL);
    deadline=GetTickCount64()+2000;
    for (;;) {
        pthread_mutex_lock(&battle_lock); int stopping=battle_stopping; pthread_mutex_unlock(&battle_lock);
        if (stopping) break; assert(GetTickCount64()<deadline); Sleep(0);
    }
    assert(WaitForSingleObject(stopper,0)==WAIT_TIMEOUT);
    int accepted;
    do { accepted=void_touch_battle_submit(10,&first); } while (!accepted);
    assert(accepted==-1); SetEvent(solver_release); join_thread(stopper);
    assert(!battle_started && !battle_ready && !void_touch_battle_poll(9,&output));

    /* Thread creation failures are cached until shutdown, then retry succeeds. */
    InterlockedExchange(&fail_create,1); LONG attempts=create_calls;
    assert(void_touch_battle_submit(11,&first)==-1 && create_calls==attempts+1);
    assert(void_touch_battle_submit(12,&first)==-1 && create_calls==attempts+1);
    void_touch_battle_shutdown(); InterlockedExchange(&fail_create,0);
    first=make_grid(113); submit(13,&first); wait_event(solver_entered); SetEvent(solver_release);
    assert(poll(13,&output)==1 && output.max_cost==113 && create_calls==attempts+2);
    void_touch_battle_shutdown(); void_touch_battle_shutdown();
    CloseHandle(solver_entered); CloseHandle(solver_release); CloseHandle(mailbox_locked); CloseHandle(mailbox_release);
    puts("PASS real battle worker: nonblocking contention, copied input, latest wins, cancel, one-shot result, failure, shutdown/restart");
    return 0;
}
'''


class TouchCombatWorkerTest(unittest.TestCase):
    def test_real_thread_mailbox(self):
        worker = (ROOT / "android/host/touch_combat.c").read_text(encoding="utf-8")
        solver = (ROOT / "android/host/touch_combat_path.inc").read_text(encoding="utf-8")
        headers = {
            "host.h": HOST,
            "pthread.h": PTHREAD,
            "touch_combat.h": (ROOT / "android/host/touch_combat.h").read_text(encoding="utf-8"),
            "touch_combat.c": worker,
            "touch_combat_path.inc": solver.replace("int void_touch_battle_solve(", "static int actual_battle_solve(") + SOLVER_WRAPPER,
        }
        compile_probe("touch_combat_worker", HARNESS, headers, extra_flags=("/I.",))
        # These deliberately broken publication/copy implementations must fail
        # the same real-thread scenario, rather than only a source-text check.
        for name, old, new in (
            ("stale", "!battle_stopping && battle_wanted == ticket", "!battle_stopping"),
            ("copy", "battle_input = *grid;", "battle_input = *grid; battle_input.width = 0;"),
        ):
            self.assertEqual(worker.count(old), 1)
            headers["touch_combat.c"] = worker.replace(old, new)
            with self.subTest(negative_control=name):
                with self.assertRaises(AssertionError):
                    compile_probe("touch_combat_worker_" + name, HARNESS, headers, extra_flags=("/I.",))


if __name__ == "__main__":
    unittest.main()
