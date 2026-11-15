"""Profiles and saves: parked read handles skip repeated opens and closes on shared storage (files.c)."""
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define strdup _strdup
#ifndef SEEK_SET
#define SEEK_SET 0
#endif
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m = 1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m = 0; return 0; }
static uint64_t now_ns;
static uint64_t void_perf_now_ns(void) { return now_ns; }
static int folder_cache_off;
static uint64_t parked_reused, parked_stale;
/* A fake shared storage: one file per path, descriptors pointing at a file. */
struct timespec_ { long long tv_sec; long tv_nsec; };
struct stat { unsigned st_mode; unsigned long long st_dev, st_ino; long long st_size; struct timespec_ st_mtim, st_ctim; };
#define S_IFREG_ 0x8000u
#define S_ISREG(m) (((m) & 0xF000u) == S_IFREG_)
static struct stat files[8];
static const char *names[8];
static int file_count;
static int fd_file[64], fd_open[64];
static long long fd_offset[64];
static unsigned stat_calls, close_calls, lseek_calls;
static int find_file(const char *path) { for (int i = 0; i < file_count; ++i) if (names[i] && !strcmp(names[i], path)) return i; return -1; }
static int stat(const char *path, struct stat *st) {
    ++stat_calls; int i = find_file(path);
    if (i < 0) { errno = ENOENT; return -1; }
    *st = files[i]; return 0;
}
static int fstat(int fd, struct stat *st) { assert(fd >= 0 && fd < 64 && fd_open[fd]); *st = files[fd_file[fd]]; return 0; }
static long long lseek(int fd, long long offset, int whence) {
    assert(fd_open[fd] && whence == SEEK_SET); ++lseek_calls; fd_offset[fd] = offset; return offset;
}
static int close(int fd) { assert(fd >= 0 && fd < 64 && fd_open[fd]); fd_open[fd] = 0; ++close_calls; return 0; }
static int next_fd = 10;
static int open_file(int file) { int fd = next_fd++; assert(fd < 64); fd_open[fd] = 1; fd_file[fd] = file; fd_offset[fd] = 12345; return fd; }
static int add(const char *path, long long size) {
    names[file_count] = path;
    files[file_count] = (struct stat){ S_IFREG_ | 0644u, 66, 1000u + (unsigned)file_count, size, {1700000000, 5}, {1700000000, 5} };
    return file_count++;
}
static int open_count(void) { int n = 0; for (int i = 0; i < 64; ++i) n += fd_open[i]; return n; }
/* PRODUCTION */
int main(void) {
    int save = add("/data/Saves/save_1.sav", 4967695), cfg = add("/data/user_a2.cfg", 4036);
    /* Nothing parked: the caller opens. */
    assert(parked_take("/data/Saves/save_1.sav") == -1 && !stat_calls);
    /* The game closes a read handle: kept, and the next read open takes it back at offset 0. */
    int fd = open_file(save);
    assert(parked_put("/data/Saves/save_1.sav", fd) == 1 && parked_count == 1 && !close_calls);
    assert(parked_take("/data/Saves/save_1.sav") == fd && fd_offset[fd] == 0 && parked_reused == 1 && !parked_count);
    assert(parked_take("/data/Saves/save_1.sav") == -1);              /* one taker per descriptor */
    /* The list pattern: open, close, open, close... one real open per file. */
    for (int round = 0; round < 5; ++round) {
        int got = parked_take("/data/user_a2.cfg");
        if (got < 0) got = open_file(cfg);
        assert(parked_put("/data/user_a2.cfg", got) == 1);
    }
    assert(parked_reused == 5 && next_fd == 12 && parked_count == 1);
    /* A file changed in place (size, times) or replaced (inode) is opened again. */
    assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    files[save].st_mtim.tv_nsec = 6;
    unsigned closes = close_calls;
    assert(parked_take("/data/Saves/save_1.sav") == -1 && close_calls == closes + 1 && parked_stale == 1 && !fd_open[fd]);
    fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    files[save].st_ino = 77777;
    assert(parked_take("/data/Saves/save_1.sav") == -1 && parked_stale == 2 && !fd_open[fd]);
    fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    files[save].st_size = 1;
    assert(parked_take("/data/Saves/save_1.sav") == -1 && parked_stale == 3);
    fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    names[save] = NULL;                                                  /* deleted outside the game */
    assert(parked_take("/data/Saves/save_1.sav") == -1 && parked_stale == 4);
    names[save] = "/data/Saves/save_1.sav";
    /* Writes, deletes and renames through the host drop the path (or everything). */
    fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    parked_drop("/data/Saves/save_1.sav");
    assert(!fd_open[fd] && parked_count == 1 && parked_take("/data/Saves/save_1.sav") == -1);
    fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1 && parked_count == 2);
    parked_drop(NULL);
    assert(!parked_count && open_count() == 0);
    /* Not regular files: never parked. */
    fd = open_file(save); files[save].st_mode = 0x4000u;
    assert(parked_put("/data/Saves/save_1.sav", fd) == 0 && fd_open[fd]); close(fd);
    files[save].st_mode = S_IFREG_ | 0644u;
    /* Unused for a minute: closed by the next park. */
    now_ns = 1000; fd = open_file(save); assert(parked_put("/data/Saves/save_1.sav", fd) == 1);
    now_ns += 61ull * 1000000000ull; int other = open_file(cfg);
    assert(parked_put("/data/user_a2.cfg", other) == 1 && !fd_open[fd] && parked_count == 1);
    parked_drop(NULL);
    assert(!parked_count && open_count() == 0);
    /* Off (A/B): nothing parked, nothing taken. */
    folder_cache_off = 1; fd = open_file(save);
    assert(parked_put("/data/Saves/save_1.sav", fd) == 0 && parked_take("/data/Saves/save_1.sav") == -1); close(fd);
    folder_cache_off = 0;
    puts("PASS parked read handles: one open per file across a list, offset 0, changed/replaced/deleted files reopened, host writes drop, expiry, A/B");
    return 0;
}
'''

CAPACITY = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define strdup _strdup
#define SEEK_SET_ 0
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m = 1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m = 0; return 0; }
static uint64_t now_ns;
static uint64_t void_perf_now_ns(void) { return now_ns; }
static int folder_cache_off;
static uint64_t parked_reused, parked_stale;
struct timespec_ { long long tv_sec; long tv_nsec; };
struct stat { unsigned st_mode; unsigned long long st_dev, st_ino; long long st_size; struct timespec_ st_mtim, st_ctim; };
#define S_ISREG(m) (((m) & 0xF000u) == 0x8000u)
static unsigned char closed[1000];
static int stat(const char *path, struct stat *st) { (void)path; memset(st, 0, sizeof *st); st->st_mode = 0x8000u; return 0; }
static int fstat(int fd, struct stat *st) { (void)fd; memset(st, 0, sizeof *st); st->st_mode = 0x8000u; return 0; }
static long long lseek(int fd, long long offset, int whence) { (void)fd; (void)whence; return offset; }
static int close(int fd) { assert(fd >= 0 && fd < 1000 && !closed[fd]); closed[fd] = 1; return 0; }
/* PRODUCTION */
int main(void) {
    char path[64];
    for (int fd = 0; fd < (int)PARKED_SLOTS + 3; ++fd) {
        now_ns += 1;
        snprintf(path, sizeof path, "/data/Saves/save_%d.sav", fd);
        assert(parked_put(path, fd) == 1);
    }
    /* 256 kept; the three oldest closed to make room. */
    assert(parked_count == PARKED_SLOTS && closed[0] && closed[1] && closed[2] && !closed[3]);
    assert(parked_take("/data/Saves/save_0.sav") == -1 && parked_take("/data/Saves/save_258.sav") == 258);
    parked_drop(NULL);
    for (int fd = 3; fd < (int)PARKED_SLOTS + 2; ++fd) assert(closed[fd]);
    puts("PASS parked read handles: 256 descriptors at most, the oldest closed first");
    return 0;
}
'''

USER_VIEW = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int folder_cache_off;
struct stat { unsigned st_mode; long long st_size; };
#define S_ISREG(m) (((m) & 0xF000u) == 0x8000u)
static long long file_size = 4967695;
static unsigned file_mode = 0x8000u;
static int fstat(int fd, struct stat *st) { assert(fd == 5); st->st_mode = file_mode; st->st_size = file_size; return 0; }
/* MAPPING */
int main(void) {
    mapping_t m; memset(&m, 0, sizeof m); m.fd = 5; m.user_data = 1;
    /* A whole save: mapped, not read. */
    assert(user_view_mapped(&m, 0, 4967695));
    /* Small views (profiles, headers read alone) and installation files: read as before. */
    assert(!user_view_mapped(&m, 0, 1u << 20) && user_view_mapped(&m, 0, (1u << 20) + 1));
    m.user_data = 0; assert(!user_view_mapped(&m, 0, 4967695)); m.user_data = 1;
    /* Past the end of the file (a view the file does not cover): read, zero-filled. */
    assert(!user_view_mapped(&m, 65536, 4967695) && user_view_mapped(&m, 65536, 4967695 - 65536));
    file_mode = 0x4000u; assert(!user_view_mapped(&m, 0, 4967695)); file_mode = 0x8000u;
    folder_cache_off = 1; assert(!user_view_mapped(&m, 0, 4967695));
    puts("PASS mapped save views: user-data views over 1 MiB inside the file are mapped; small, installation, past-end and A/B views are read");
    return 0;
}
'''


def block(text):
    return text[text.index("/* -------------------------------------------------- parked read handles */"):
                text.index("/* ----------------------------------------------------------- file objects */")]


class ParkedHandlesTest(unittest.TestCase):
    def test_parked_handles(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        compile_probe("files_parked", HARNESS.replace("/* PRODUCTION */", block(text)), {})
        # A replaced file (another inode) must not hand out the old descriptor.
        broken = block(text).replace("a->st_ino == b->st_ino && ", "", 1)
        self.assertNotEqual(broken, block(text))
        with self.assertRaises(AssertionError):
            compile_probe("files_parked_negative", HARNESS.replace("/* PRODUCTION */", broken), {})

    def test_capacity(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        compile_probe("files_parked_capacity", CAPACITY.replace("/* PRODUCTION */", block(text)), {})

    def test_mapped_save_views(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        start = text.index("/* ------------------------------------------------------------- mappings */")
        code = text[start:text.index("static void mapping_destroy(")]
        code = code.replace("static uint64_t mapping_identity;", "")
        compile_probe("files_user_views", USER_VIEW.replace("/* MAPPING */", code), {})


if __name__ == "__main__":
    unittest.main()
