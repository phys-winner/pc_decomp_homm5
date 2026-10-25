"""Cached missing files must not release the VM or touch the filesystem."""
import unittest
from test_files_ansi import HARNESS
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body


MAIN = r'''
static unsigned slow_calls;
static uint32_t create_file(const char *path, uint32_t access, uint32_t disposition, uint32_t flags, uint32_t *error) {
    (void)access; (void)disposition; (void)flags;
    assert(released && path); ++slow_calls; *error=0; return 0x6000;
}
/* CREATE_FILE_GUEST */
static uint32_t probe(const char *path, uint32_t access, uint32_t disposition) {
    args[1]=access; args[4]=disposition; args[5]=0;
    return create_file_guest(strdup(path));
}
int main(void) {
    strcpy(overlay_root,"C:/overlay");
    /* Cold caches, positive files, and user data always take the original I/O path. */
    assert(probe("C:\\game\\missing",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    assert(slow_calls==1 && released_sections==1 && !opens[0] && !opens[1]);
    void_blocking_begin();
    assert(listing_get(game_root,1) && listing_get(overlay_root,1));
    void_blocking_end();
    unsigned sections=released_sections, stats=stat_calls;
    assert(probe("C:\\game\\missing",GENERIC_READ_,OPEN_EXISTING_)==UINT32_MAX && last_error==2);
    assert(probe("C:\\game\\absent\\child.xdb",GENERIC_READ_,OPEN_EXISTING_)==UINT32_MAX && last_error==3);
    assert(released_sections==sections && stat_calls==stats && slow_calls==1);
    assert(opens[0]==1 && opens[1]==1);
    assert(probe("c:\\GAME\\DATA.PAK",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    assert(probe("C:\\game\\extra.txt",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    /* A loaded parent cannot prove a miss in a directory not yet listed. */
    assert(probe("C:\\game\\ui\\port.xdb",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    assert(probe("C:\\profiles\\missing",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    assert(probe("C:\\game\\missing",GENERIC_WRITE_,OPEN_EXISTING_)==0x6000);
    assert(probe("C:\\game\\missing",GENERIC_READ_,CREATE_NEW_)==0x6000);
    assert(slow_calls==7 && released_sections==sections+6 && !opens[2] && !opens[3]);
    /* Invalidation cannot turn a stale absence into a fast failure. */
    listing_forget(game_root);
    assert(probe("C:\\game\\new.pak",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    listing_forget(overlay_root);
    assert(probe("C:\\game\\missing",GENERIC_READ_,OPEN_EXISTING_)==0x6000);
    assert(!released && !listing_lock && slow_calls==9);
    assert(archive_path("C:/game/DATA.PAK")&&archive_path("C:/overlay/extra.pak"));
    assert(!archive_path("C:/profiles/save.pak")&&!archive_path("C:/game2/data.pak")&&!archive_path("C:/game/data.pak.bak"));
    archive_changed("C:/profiles/save.pak");assert(!archive_cache_disabled);
    archive_changed("C:/game/data.pak");assert(archive_cache_disabled);
    puts("PASS cached probes: no I/O or VM handoff for proven misses, exact errors, overlay/case handling, cold cache and writes use original path, invalidation respected");
    return 0;
}
'''


class FileProbeTest(unittest.TestCase):
    def test_truncating_read_handle_disables_archive_cache_before_open(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#define strdup _strdup
#define __atomic_store_n(p,v,o) (*(p)=(v))
#define VLOG(...) ((void)0)
#define void_log(...) ((void)0)
#define RESOLVE_OVERLAY 1
#define WIN_INVALID_HANDLE UINT32_MAX
enum { ERROR_PATH_NOT_FOUND_=3,ERROR_FILE_NOT_FOUND_=2,ERROR_INVALID_PARAMETER_=87,
       ERROR_ACCESS_DENIED_=5,ERROR_ALREADY_EXISTS_=183 };
enum { O_RDONLY=0,O_WRONLY=1,O_RDWR=2,O_ACCMODE=3,O_CREAT=64,O_EXCL=128,
       O_TRUNC=512,O_DIRECTORY=65536,O_CLOEXEC=524288 };
static char game_root[]="C:/game",overlay_root[]="C:/overlay";
static int seen_flags,archive_cache_disabled,expected_disabled;
static int open(const char *path,int flags,...) {
    assert(path && archive_cache_disabled==expected_disabled);seen_flags=flags;errno=ENOENT;return -1;
}
struct stat { int st_mode; };
#define S_ISDIR(mode) ((mode)==1)
static int fstat(int fd,struct stat *st) {(void)fd;st->st_mode=0;return 0;}
static int ftruncate(int fd,int size) {(void)fd;(void)size;return 0;}
static int close(int fd) {(void)fd;return 0;}
static uint32_t void_errno_to_win32(int error) {(void)error;return 2;}
static char *to_host_ex(const char *path,int flags,int *parent,int *leaf,char *norm) {
    (void)flags;(void)norm;*parent=*leaf=1;return strdup(path);
}
static void listing_forget(const char *parent) {(void)parent;}
typedef struct {uint32_t granted_access;int is_dir,delete_on_close;} file_t;
static file_t file;
static uint32_t file_handle(int fd,const char *path,int stream) {(void)fd;(void)path;(void)stream;return 1;}
static file_t *file_get(uint32_t handle) {(void)handle;return &file;}
/* PRODUCTION */
int main(void) {
    uint32_t error=0;
    assert(create_file("C:/game/data.pak",GENERIC_READ_,OPEN_EXISTING_,0,&error)==WIN_INVALID_HANDLE);
    assert(!archive_cache_disabled && !(seen_flags&O_TRUNC));
    /* Even an unsuccessful truncating open must invalidate before host I/O.
       The existing host accepts O_RDONLY|O_TRUNC; access flags alone miss it. */
    expected_disabled=1;
    assert(create_file("C:/game/data.pak",GENERIC_READ_,TRUNCATE_EXISTING_,0,&error)==WIN_INVALID_HANDLE);
    assert(archive_cache_disabled && (seen_flags&O_TRUNC) && !(seen_flags&O_ACCMODE));
    archive_cache_disabled=expected_disabled=0;
    assert(create_file("C:/profiles/save.pak",GENERIC_READ_,TRUNCATE_EXISTING_,0,&error)==WIN_INVALID_HANDLE);
    assert(!archive_cache_disabled && (seen_flags&O_TRUNC));
    puts("PASS archive invalidation: readonly truncation disables before open, ordinary reads and profile paths do not");
    return 0;
}
'''
        production = "\n".join(body(text, name) for name in (
            "static int under(", "static int cacheable(", "static int archive_path(", "static void archive_changed("))
        production += text[text.index("#define GENERIC_READ_"):text.index("/* Host side of CreateFile:")]
        production += body(text, "static uint32_t create_file(")
        fixture = fixture.replace("/* PRODUCTION */", production)
        compile_probe("file_probe_truncate", fixture, {})
        broken = fixture.replace("(oflags & (O_CREAT | O_TRUNC))", "(oflags & O_CREAT)")
        self.assertNotEqual(broken, fixture)
        with self.assertRaisesRegex(AssertionError, "Assertion failed"):
            compile_probe("file_probe_truncate_bad", broken, {})

    def test_cached_probe(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        fixture = HARNESS[:HARNESS.index('#include "listings.h"')].replace('#include "strings.h"', '')
        # Replace fixture path resolution with the actual shared resolver.
        first = fixture.index("static char *to_host(")
        last = fixture.index("static int normalize(")
        fixture = fixture[:first] + fixture[last:]
        fixture = fixture.replace("kind == VOID_PERF_FIND", "kind == VOID_PERF_FILE_OPEN")
        fixture = fixture.replace("/* ACTUAL_PERF_KINDS */", "enum { VOID_PERF_FILE_OPEN };")
        fixture += r'''
#define strncasecmp _strnicmp
#define lstat stat
#define RESOLVE_CACHED_ONLY 2
typedef struct { const char *win; char host[1024]; } mount_t;
static mount_t mounts[]={{"C:\\game","C:/game"},{"C:\\profiles","C:/profiles"}};
static int mount_count=2;
'''
        listings = text[text.index("/* ---------------------------------------------------- directory listings */"):
                        text.index("void void_files_set_overlay(const char *dir)")]
        fixture += listings
        for name in ("static int resolve_component(", "static int resolve_below(", "static char *to_host_ex("):
            fixture += body(text, name)
        fixture += text[text.index("#define GENERIC_READ_"):text.index("/* Host side of CreateFile:")]
        fixture += MAIN.replace("/* CREATE_FILE_GUEST */", body(text, "static uint32_t create_file_guest("))
        compile_probe("file_probe", fixture, {})


if __name__ == "__main__":
    unittest.main()
