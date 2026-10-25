"""Execute shared A/W find and metadata bodies against a deterministic directory."""
import re
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define strdup _strdup
#define strcasecmp _stricmp
static uint8_t memory[0x10000];
#define GPTR(va) (memory + (va))
#define MEM8(va) (*(uint8_t *)GPTR(va))
#define MEM16(va) (*(uint16_t *)GPTR(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
#define MEM64(va) (*(uint64_t *)GPTR(va))
static uint32_t args[8], last_error;
#define ARG(n) args[n]
#define WINAPI_EXPORT(dll, name, nargs) uint32_t name##_impl(void)
#define ERROR_INVALID_HANDLE_ 6
#define ERROR_PATH_NOT_FOUND_ 3
#define ERROR_FILE_NOT_FOUND_ 2
#define ERROR_INVALID_PARAMETER_ 87
#define ERROR_NO_MORE_FILES_ 18
#define WIN_INVALID_HANDLE UINT32_MAX
#define VOID_OBJ_FIND 4
#define RESOLVE_OVERLAY 1
#define VLOG(...) ((void)0)
#define __ATOMIC_ACQUIRE 2
#define __ATOMIC_RELEASE 3
#define __atomic_load_n(p, order) (*(p))
#define __atomic_store_n(p, value, order) (*(p) = (value))
/* ACTUAL_PERF_KINDS */
static void void_set_last_error(uint32_t value) { last_error = value; }
static int void_vm_writable(uint32_t va, uint32_t size) { return va >= 0x100 && (uint64_t)va + size <= sizeof memory; }
#include "strings.h"
/* The guest machine lock: host file-system work runs with it released. */
static int released;
static unsigned released_sections, find_perf_calls;
static void void_blocking_begin(void) { assert(!released); released = 1; ++released_sections; }
static void void_blocking_end(void) { assert(released); released = 0; }
static uint64_t void_perf_now_ns(void) { return 0; }
static void void_perf_add(int kind, uint64_t ns, uint64_t bytes) { assert(!released && kind == VOID_PERF_FIND && !ns && !bytes); ++find_perf_calls; }
/* Non-recursive host mutex: a nested listing lock would deadlock. */
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m = 1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m = 0; return 0; }
struct stamp { time_t tv_sec; long tv_nsec; };
struct stat { uint32_t st_mode; int64_t st_size; struct stamp st_ctim, st_atim, st_mtim; uint64_t st_dev, st_ino; uint32_t st_nlink; };
#define S_ISDIR(mode) ((mode) == 0x4000)
/* Host paths: "C:/..." (the guest's backslashes become slashes). The
 * installation is C:/game, the port's overlay C:/overlay, profiles uncached. */
static unsigned stat_calls;
static int stat(const char *path, struct stat *out) {
    ++stat_calls;
    if (strstr(path, "vanished") || strstr(path, "missing") || strstr(path, "nogame")) { errno = ENOENT; return -1; }
    *out = (struct stat){0x81A4, 0x123456789ll, {1, 100}, {2, 200}, {3, 300}, 7, 0x123456789ABull, 2};   /* rw-r--r-- */
    static const char *const directories[] = {"C:/", "C:", "C:/game", "C:/game/", "C:/profiles", "C:/overlay", "C:/overlay/ui"};
    for (unsigned i = 0; i < sizeof directories / sizeof *directories; ++i) if (!_stricmp(path, directories[i])) out->st_mode = 0x4000;
    if (!strncmp(path, "C:/overlay/", 11) && out->st_mode != 0x4000) out->st_size = 0x55;
    if (!strncmp(path, "C:/profiles/", 12)) out->st_mode = 0x81B6;   /* rw-rw-rw- */
    if (strstr(path, "readonly")) out->st_mode = 0x8124;             /* r--r--r-- */
    return 0;
}
struct statvfs { uint64_t f_bsize, f_frsize, f_blocks, f_bavail, f_bfree; };
static struct statvfs fixture_space = {4096, 4096, 0x100000005ull, 0x80000003ull, 0x8000000Bull};
static int statvfs(const char *path, struct statvfs *out) { assert(path && *path); *out = fixture_space; return 0; }
static int fstat(int fd, struct stat *out) { assert(fd == 9); return stat("data.pak", out); }
typedef struct { int fd; } file_t;
static file_t fixture_file = {9};
static file_t *file_get(uint32_t handle) { return handle == 0x6000 ? &fixture_file : NULL; }
static uint32_t void_errno_to_win32(int error) { assert(error == ENOENT); return 2; }
static char *host_path(const char *path) {
    char *out = strdup(path); assert(out);
    for (char *p = out; *p; ++p) if (*p == '\\') *p = '/';
    return out;
}
static char *to_host(const char *path, int *parent, char *normalized) {
    (void)normalized; if (parent) *parent = 1; return path ? host_path(path) : NULL;
}
static unsigned resolved_paths;
static char *to_host_ex(const char *path, int flags, int *parent, int *leaf, char *normalized) {
    assert(released && path && flags == RESOLVE_OVERLAY && parent && leaf && !normalized);
    ++resolved_paths; *parent = !strstr(path, "nodir\\"); *leaf = -1;
    return host_path(path);
}
static int normalize(const char *in, char *out, size_t cap) { return snprintf(out, cap, "%s", in) > 0; }
static char game_root[1024] = "C:/game", overlay_root[1024];
/* The overlay's twin of an installation directory (files.c's overlay_dir). */
static char *overlay_dir(const char *windows_dir) {
    assert(released);
    if (!overlay_root[0]) return NULL;
    if (!_stricmp(windows_dir, "C:\\game")) return strdup("C:/overlay");
    if (!_stricmp(windows_dir, "C:\\nogame")) return strdup("C:/overlay/ui");
    return NULL;
}
typedef struct { void *data; void (*destroy)(void *); } unused_t;
typedef struct void_object { void *data; void (*destroy)(struct void_object *); } void_object;
static void_object *objects[32];
static uint32_t next_handle;
static void_object *void_object_new(int kind, size_t size) {
    assert(kind == VOID_OBJ_FIND); void_object *o = calloc(1, sizeof *o); assert(o); o->data = calloc(1, size); assert(o->data); return o;
}
static void void_object_release(void_object *o) { if (o->destroy) o->destroy(o); free(o->data); free(o); }
static uint32_t void_handle_new(void_object *o) { assert(next_handle < 32); objects[next_handle] = o; return 0x1000 + 4 * next_handle++; }
static void_object *void_handle_get(uint32_t h, int kind) {
    assert(kind == VOID_OBJ_FIND); return h >= 0x1000 && h < 0x1000 + next_handle * 4 && !(h & 3) ? objects[(h - 0x1000) / 4] : NULL;
}
static int void_handle_close(uint32_t h) { uint32_t i = (h - 0x1000) / 4; void_object_release(objects[i]); objects[i] = NULL; return 1; }
/* Host directories; readdir reports "." and ".." as Linux does. */
#define DT_UNKNOWN 0
#define DT_DIR 4
#define DT_REG 8
typedef struct { const char *path; const char *names[10]; } fixture_dir;
static fixture_dir directories[] = {
    {"C:/game", {".", "..", "data.pak", "vanished.pak", "\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA.pak", "Shared.pak"}},
    {"C:/overlay", {".", "..", "SHARED.PAK", "extra.txt", "ui"}},
    {"C:/overlay/ui", {".", "..", "port.xdb"}},
    {"C:/profiles", {".", "..", "save1.sav"}},
};
static unsigned opens[4];
typedef struct { unsigned dir, next; } DIR;
struct dirent { char d_name[260]; unsigned char d_type; };
static DIR *opendir(const char *path) {
    assert(released);
    for (unsigned i = 0; i < 4; ++i) if (!strcmp(path, directories[i].path)) {
        ++opens[i]; DIR *d = calloc(1, sizeof *d); assert(d); d->dir = i; return d;
    }
    errno = ENOENT; return NULL;
}
static struct dirent *readdir(DIR *d) {
    static struct dirent entry;
    const char *name = directories[d->dir].names[d->next];
    if (!name) return NULL;
    ++d->next; strcpy(entry.d_name, name);
    entry.d_type = (unsigned char)(name[0] == '.' || !strcmp(name, "ui") ? DT_DIR : DT_REG);
    return &entry;
}
static int closedir(DIR *d) { free(d); return 0; }
/* fnmatch(FNM_CASEFOLD) for '*' and '?'. */
#define FNM_CASEFOLD 16
static int glob(const char *p, const char *s) {
    if (!*p) return !*s;
    if (*p == '*') return glob(p + 1, s) || (*s && glob(p, s + 1));
    if (!*s || (*p != '?' && tolower((unsigned char)*p) != tolower((unsigned char)*s))) return 0;
    return glob(p + 1, s + 1);
}
static int fnmatch(const char *pattern, const char *name, int flags) { assert(flags == FNM_CASEFOLD); return !glob(pattern, name); }
#include "listings.h"
#include "metadata.h"
#include "drives.h"
#include "find.h"
static uint32_t find_a(const char *pattern) { strcpy((char *)GPTR(0x100), pattern); args[0] = 0x100; args[1] = 0x2000; return FindFirstFileA_impl(); }
static const char *found_a(void) { return (const char *)GPTR(0x202C); }
static void expect_rest(uint32_t h, const char *const *names, unsigned count) {
    args[0] = h; args[1] = 0x2000;
    for (unsigned i = 0; i < count; ++i) { assert(FindNextFileA_impl() == 1); assert(!strcmp(found_a(), names[i])); }
    assert(FindNextFileA_impl() == 0 && last_error == 18 && FindClose_impl() == 1);
}
static uint32_t attributes(const char *path) { strcpy((char *)GPTR(0x100), path); args[0] = 0x100; return GetFileAttributesA_impl(); }
int main(void) {
    /* The installation directory is listed once (machine released); "." and ".."
       come first, as on Windows below a drive root, with the directory's attributes. */
    memset(GPTR(0x2000), 0xCC, 640);
    uint32_t h = find_a("C:\\game\\*.*"); assert(h != UINT32_MAX);
    assert(!released && released_sections == 1 && find_perf_calls == 1 && opens[0] == 1 && listing_loads == 1);
    assert(!strcmp(found_a(), ".") && MEM32(0x2000) == 0x10);
    args[0] = h; assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), "..") && MEM32(0x2000) == 0x10);
    assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), "data.pak"));
    assert(MEM32(0x2000) == 0x20 && MEM32(0x201C) == 1 && MEM32(0x2020) == 0x23456789);
    assert(MEM64(0x2004) == 116444736010000001ull);
    for (uint32_t i = 320; i < 640; ++i) assert(MEM8(0x2000 + i) == 0xCC);
    args[0] = h; assert(FindNextFileA_impl() == 1);
    assert(!strcmp(found_a(), "\xC8\xE3\xF0\xEE\xEA.pak"));
    assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), "Shared.pak"));
    assert(FindNextFileA_impl() == 0 && last_error == 18);
    assert(FindClose_impl() == 1);
    assert(FindNextFileA_impl() == 0 && last_error == 6);
    /* Served from the listing: entries' stats are cached, a vanished entry is re-checked. */
    unsigned stats = stat_calls;
    void_utf8_to_gw("C:\\game\\*", 0x400, 260);
    args[0] = 0x400; args[1] = 0x3000; memset(GPTR(0x3000), 0xCC, 640);
    h = FindFirstFileW_impl(); assert(h != UINT32_MAX && MEM16(0x302C) == '.' && !MEM16(0x302E));
    args[0] = h; assert(FindNextFileW_impl() == 1 && MEM16(0x302C) == '.' && MEM16(0x302E) == '.');
    assert(FindNextFileW_impl() == 1 && MEM16(0x302C) == 'd');
    /* Plus one stat of the installation directory itself, for "." and "..". */
    assert(opens[0] == 1 && listing_loads == 1 && stat_calls == stats + 3);
    for (uint32_t i = 592; i < 640; ++i) assert(MEM8(0x3000 + i) == 0xCC);
    args[0] = h; assert(FindNextFileW_impl() == 1 && MEM16(0x302C) == 0x0418 && MEM16(0x302C + 8) == 0x043A);
    assert(FindClose_impl() == 1);
    h = find_a("C:\\game\\s*"); assert(h != UINT32_MAX && !strcmp(found_a(), "Shared.pak"));
    expect_rest(h, NULL, 0);
    assert(find_a("C:\\game\\*.none") == UINT32_MAX && last_error == 2);
    args[0] = 0x100; args[1] = sizeof memory - 319; assert(FindFirstFileA_impl() == UINT32_MAX && last_error == 87);
    args[1] = 0x2000; MEM8(0x100) = 0; assert(FindFirstFileA_impl() == UINT32_MAX);
    assert(find_a("C:\\game\\") == UINT32_MAX && last_error == 2);
    /* A file created through this host is seen once its directory is forgotten. */
    directories[0].names[6] = "new.pak";
    assert(find_a("C:\\game\\new.pak") == UINT32_MAX && last_error == 2 && opens[0] == 1);
    listing_forget_parent("C:/game/new.pak", 0);
    h = find_a("C:\\game\\new.pak"); assert(h != UINT32_MAX && !strcmp(found_a(), "new.pak") && opens[0] == 2);
    expect_rest(h, NULL, 0);
    char actual[64]; unsigned char kind = DT_UNKNOWN;
    released = 1;
    assert(listing_lookup("C:/game", "DATA.PAK", actual, sizeof actual, &kind, 1) == 1 && !strcmp(actual, "data.pak") && kind == DT_REG);
    assert(listing_lookup("C:/game", "absent.pak", actual, sizeof actual, &kind, 1) == 0);
    assert(listing_lookup("C:/profiles", "save1.sav", actual, sizeof actual, &kind, 1) == -1 && !opens[3]);
    released = 0;
    /* Profiles are read directly every time: the game writes there behind the cache. */
    h = find_a("C:\\profiles\\*.sav"); assert(h != UINT32_MAX && !strcmp(found_a(), "save1.sav") && opens[3] == 1);
    expect_rest(h, NULL, 0);
    directories[3].names[3] = "save2.sav";
    h = find_a("C:\\profiles\\*.sav"); assert(h != UINT32_MAX && opens[3] == 2);
    static const char *const saves[] = {"save2.sav"};
    expect_rest(h, saves, 1);
    /* The overlay's entries come first and shadow the installation's, ignoring case. */
    strcpy(overlay_root, "C:/overlay");
    h = find_a("C:\\game\\*.*"); assert(h != UINT32_MAX && opens[1] == 1 && opens[0] == 2);
    assert(!strcmp(found_a(), ".") && MEM32(0x2000) == 0x10);
    args[0] = h; assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), ".."));
    assert(FindNextFileA_impl() == 1);
    assert(!strcmp(found_a(), "SHARED.PAK") && MEM32(0x201C) == 0 && MEM32(0x2020) == 0x55);
    static const char *const merged[] = {"extra.txt", "ui", "data.pak", "\xC8\xE3\xF0\xEE\xEA.pak", "new.pak"};
    expect_rest(h, merged, 5);
    /* A directory only the overlay has. */
    h = find_a("C:\\nogame\\*"); assert(h != UINT32_MAX && !strcmp(found_a(), ".") && opens[2] == 1);
    args[0] = h; assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), ".."));
    assert(FindNextFileA_impl() == 1 && !strcmp(found_a(), "port.xdb") && MEM32(0x2020) == 0x55);
    expect_rest(h, NULL, 0);
    assert(find_a("C:\\nogame\\*.none") == UINT32_MAX && last_error == 3);
    /* A removed directory drops its parent's listing and its own subtree. */
    listing_forget_parent("C:/overlay/ui", 1);
    h = find_a("C:\\nogame\\*"); assert(h != UINT32_MAX && opens[2] == 2);
    static const char *const reloaded[] = {"..", "port.xdb"};
    expect_rest(h, reloaded, 2);
    h = find_a("C:\\game\\*.txt"); assert(h != UINT32_MAX && !strcmp(found_a(), "extra.txt") && opens[1] == 2 && opens[0] == 2);
    expect_rest(h, NULL, 0);
    overlay_root[0] = 0;
    assert(find_a("C:\\nogame\\*") == UINT32_MAX && last_error == 3);
    /* Metadata: resolved and stat'ed with the machine released, through the listing. */
    unsigned sections = released_sections, resolved = resolved_paths;
    strcpy((char *)GPTR(0x100), "C:\\game\\data.pak");
    args[0] = 0x100; args[1] = 0; args[2] = 0x4000; stats = stat_calls;
    assert(GetFileAttributesExA_impl() == 1 && MEM32(0x4000) == 0x20 && MEM32(0x401C) == 1 && MEM32(0x4020) == 0x23456789);
    assert(stat_calls == stats && released_sections == sections + 1 && resolved_paths == resolved + 1);
    args[1] = 1; assert(GetFileAttributesExA_impl() == 0 && last_error == 87 && resolved_paths == resolved + 1);
    assert(attributes("C:\\game\\data.pak") == 0x20);
    /* No write permission: read-only, the same through every query. */
    assert(attributes("C:\\profiles\\readonly.sav") == 0x21);
    strcpy((char *)GPTR(0x100), "C:\\profiles\\readonly.sav");
    args[0] = 0x100; args[1] = 0; args[2] = 0x4000;
    assert(GetFileAttributesExA_impl() == 1 && MEM32(0x4000) == 0x21);
    assert(attributes("C:\\profiles\\save1.sav") == 0x20);
    assert(attributes("C:\\game") == 0x10);
    stats = stat_calls;
    assert(attributes("C:\\game\\missing.pak") == UINT32_MAX && last_error == 2 && stat_calls == stats);  /* the listing answers */
    assert(attributes("C:\\nodir\\x.pak") == UINT32_MAX && last_error == 3);
    args[0] = 0; sections = released_sections;
    assert(GetFileAttributesA_impl() == UINT32_MAX && last_error == 3 && released_sections == sections);
    args[0] = 0x6000; args[1] = 0x5000;
    assert(GetFileInformationByHandle_impl() == 1 && MEM32(0x501C) == 7 && MEM32(0x5020) == 1);
    assert(MEM32(0x5024) == 0x23456789 && MEM32(0x5028) == 2 && MEM32(0x502C) == 0x123 && MEM32(0x5030) == 0x456789AB);
    args[1] = 0x5100; args[2] = 0; args[3] = 0x5200;
    assert(GetFileTime_impl() == 1 && MEM64(0x5100) == 116444736010000001ull && MEM64(0x5200) == 116444736030000003ull);
    args[0] = 0; assert(GetFileTime_impl() == 0 && last_error == 6);
    strcpy((char *)GPTR(0x100), "C:\\"); args[0] = 0x100; assert(GetDriveTypeA_impl() == 3);
    strcpy((char *)GPTR(0x100), "C:"); assert(GetDriveTypeA_impl() == 3);
    strcpy((char *)GPTR(0x100), "Q:\\"); assert(GetDriveTypeA_impl() == 1 && last_error == 3);
    strcpy((char *)GPTR(0x100), "C:\\game"); assert(GetDriveTypeA_impl() == 1);
    strcpy((char *)GPTR(0x100), "C:\\game\\"); assert(GetDriveTypeA_impl() == 3);
    args[0] = 0; assert(GetDriveTypeA_impl() == 3 && GetLogicalDrives_impl() == 4);
    args[1] = 0x6000; MEM8(0x6000) = 0xCC; assert(GetLogicalDriveStringsA_impl() == 5 && MEM8(0x6000) == 0xCC);
    args[0] = 4; assert(GetLogicalDriveStringsA_impl() == 5 && MEM8(0x6000) == 0xCC);
    args[0] = 5; MEM8(0x6005) = 0xCC;
    assert(GetLogicalDriveStringsA_impl() == 4 && !memcmp(GPTR(0x6000), "C:\\\0\0", 5) && MEM8(0x6005) == 0xCC);
    MEM16(0x600A) = 0xCCCC;
    assert(GetLogicalDriveStringsW_impl() == 4 && MEM16(0x6000) == 'C' && MEM16(0x6006) == 0 && MEM16(0x6008) == 0 && MEM16(0x600A) == 0xCCCC);
    args[0] = 0; args[1] = 0x6000; args[2] = 0x6010; args[3] = 0x6020; args[4] = 0x6030;
    assert(GetDiskFreeSpaceA_impl() == 1 && MEM32(0x6000) == 16 && MEM32(0x6010) == 512);
    assert(MEM32(0x6020) == 0x40000001 && MEM32(0x6030) == 0x80000002);
    assert(GetDiskFreeSpaceExA_impl() == 1);
    assert(MEM64(0x6000) == 0x80000003ull * 4096 && MEM64(0x6010) == 0x100000005ull * 4096 && MEM64(0x6020) == 0x8000000Bull * 4096);
    void_utf8_to_gw("c:\\game", 0x800, 260); args[0] = 0x800; assert(GetDiskFreeSpaceExW_impl() == 1);
    fixture_space.f_frsize = 0; assert(GetDiskFreeSpaceExW_impl() == 1 && MEM64(0x6010) == 0x100000005ull * 4096);
    fixture_space.f_bsize = 0; assert(GetDiskFreeSpaceExW_impl() == 0 && last_error == 534);
    fixture_space.f_bsize = 4096;
    strcpy((char *)GPTR(0x100), "Q:\\"); args[0] = 0x100; MEM64(0x6000) = 0x1234;
    assert(GetDiskFreeSpaceExA_impl() == 0 && last_error == 3 && MEM64(0x6000) == 0x1234);
    strcpy((char *)GPTR(0x100), "C:\\game\\data.pak"); assert(GetDiskFreeSpaceExA_impl() == 0 && last_error == 267);
    args[0] = 0; args[1] = sizeof memory - 3; assert(GetDiskFreeSpaceA_impl() == 0 && last_error == 87);
    args[1] = 0; args[2] = 0; args[3] = 0; assert(GetDiskFreeSpaceExA_impl() == 1);
    assert(!released && !listing_lock);
    puts("PASS file/drive A/W helpers: struct bounds, names, metadata, 64-bit space, cluster scaling, optional outputs, invalid paths/handles; cached installation/overlay listings (released machine, cached stats, misses without stat, invalidation incl. subtree), uncached profiles, overlay-first merge, read-only attribute");
    return 0;
}
'''


class FilesAnsiTest(unittest.TestCase):
    def test_find_and_metadata(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        listings = text[text.index("/* ---------------------------------------------------- directory listings */"):
                        text.index("void void_files_set_overlay(const char *dir)")]
        metadata = text[text.index("static uint64_t unix_to_filetime"):text.index("static uint32_t delete_file")]
        find = text[text.index("/* ------------------------------------------------------------ find files */"):
                    text.index("/* ------------------------------------------------------------- mappings */")]
        drives = text[text.index("static char *volume_path"):text.index("/* ------------------------------------------------------------ find files */")]
        strings = (ROOT / "android/host/strings.c").read_text(encoding="utf-8").replace('#include "host.h"', "")
        host = (ROOT / "android/host/host.h").read_text(encoding="utf-8")
        perf_kinds = re.search(r"enum \{\s*VOID_PERF_FILE_OPEN\b.*?\};", host, re.S).group()
        compile_probe("files_ansi", HARNESS.replace("/* ACTUAL_PERF_KINDS */", perf_kinds),
                      {"listings.h": listings, "metadata.h": metadata, "find.h": find, "drives.h": drives, "strings.h": strings})


if __name__ == "__main__":
    unittest.main()
