"""User-data paths (profiles, saves): remembered folders keep NTFS case rules and notice outside changes."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#define strdup _strdup
#define strtok_r strtok_s
#define void_log(...) ((void)0)
#define RESOLVE_OVERLAY 1
#define RESOLVE_CACHED_ONLY 2
#define DT_UNKNOWN 0
#define DT_DIR 4
#define DT_REG 8
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m = 1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m = 0; return 0; }
static uint64_t void_perf_now_ns(void) { return 0; }
/* A fake shared storage: entries by exact host path. */
static const char *entries[64];
static int entry_dir[64], entry_count;
static unsigned lstat_calls, opendir_calls;
struct stat { uint32_t st_mode; };
#define S_ISDIR(m) ((m) == 0x4000)
static void add(const char *path, int dir) { entries[entry_count] = path; entry_dir[entry_count++] = dir; }
static int find_entry(const char *path) { for (int i = 0; i < entry_count; ++i) if (entries[i] && !strcmp(entries[i], path)) return i; return -1; }
static int lstat(const char *path, struct stat *st) {
    ++lstat_calls; int i = find_entry(path);
    if (i < 0) { errno = ENOENT; return -1; }
    st->st_mode = entry_dir[i] ? 0x4000 : 0x8000; return 0;
}
typedef struct { char path[512]; int next; } DIR;
struct dirent { char d_name[260]; unsigned char d_type; };
static DIR *opendir(const char *path) {
    ++opendir_calls; int i = find_entry(path);
    if (i < 0 || !entry_dir[i]) { errno = ENOENT; return NULL; }
    DIR *d = calloc(1, sizeof *d); assert(d); snprintf(d->path, sizeof d->path, "%s", path); return d;
}
static struct dirent *readdir(DIR *d) {
    static struct dirent e; size_t n = strlen(d->path);
    while (d->next < entry_count) {
        const char *p = entries[d->next++];
        if (p && !strncmp(p, d->path, n) && p[n] == '/' && !strchr(p + n + 1, '/')) {
            snprintf(e.d_name, sizeof e.d_name, "%s", p + n + 1); e.d_type = DT_UNKNOWN; return &e;
        }
    }
    return NULL;
}
static int closedir(DIR *d) { free(d); return 0; }
static char game_root[1024] = "C:/game", overlay_root[1024];
static char cwd[260] = "C:\\Games\\HeroesV\\bin";
static pthread_mutex_t cwd_lock;
typedef struct { const char *win; char host[1024]; } mount_t;
static mount_t mounts[] = {{"C:\\Users\\Player\\Documents", "C:/data/Documents"}, {"C:\\Games\\HeroesV", "C:/game"}};
static int mount_count = 2;
static int under(const char *path, const char *root) {
    size_t n = strlen(root);
    return n && !strncmp(path, root, n) && (path[n] == 0 || path[n] == '/');
}
static int cacheable(const char *dir) { return under(dir, game_root) || under(dir, overlay_root); }
/* No listing cache in this fixture: user data never has one. */
static int listing_lookup(const char *dir, const char *name, char *actual, size_t cap, unsigned char *kind, int load) {
    (void)dir; (void)name; (void)actual; (void)cap; (void)kind; (void)load; return -1;
}
/* PRODUCTION */
static char *resolve(const char *path, int *parent, int *leaf) {
    *parent = *leaf = -7;
    return to_host_ex(path, 0, parent, leaf, NULL);
}
#define SAVES "C:\\Users\\Player\\Documents\\My Games\\Heroes V\\Profiles\\Player\\Saves"
int main(void) {
    add("C:/data/Documents", 1); add("C:/data/Documents/My Games", 1);
    add("C:/data/Documents/My Games/Heroes V", 1); add("C:/data/Documents/My Games/Heroes V/Profiles", 1);
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player", 1);
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/saves", 1);   /* lower case on disk */
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/save_1.sav", 0);
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/save_2.sav", 0);
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/Save_3.sav", 0);
    int parent, leaf;
    /* First access resolves every folder (and scans the one spelled differently). */
    char *host = resolve(SAVES "\\save_1.sav", &parent, &leaf);
    assert(!strcmp(host, "C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/save_1.sav") && parent == 1 && leaf == 1);
    assert(lstat_calls == 6 && opendir_calls == 1 && folder_count == 1); free(host);
    /* Then one lstat per existing file. */
    unsigned stats = lstat_calls, scans = opendir_calls;
    host = resolve(SAVES "\\save_2.sav", &parent, &leaf);
    assert(!strcmp(host, "C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/save_2.sav") && parent == 1 && leaf == 1);
    assert(lstat_calls == stats + 1 && opendir_calls == scans); free(host);
    /* Other letter case of folder and file, as NTFS allows. */
    host = resolve("c:\\USERS\\player\\documents\\MY GAMES\\heroes v\\PROFILES\\player\\SAVES\\SAVE_3.SAV", &parent, &leaf);
    assert(!strcmp(host, "C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/Save_3.sav") && parent == 1 && leaf == 1);
    assert(lstat_calls == stats + 2 && opendir_calls == scans + 1); free(host);
    /* A free save name: absent, in an existing folder (FILE_NOT_FOUND, not PATH_NOT_FOUND). */
    host = resolve(SAVES "\\save_9.sav", &parent, &leaf);
    assert(parent == 1 && leaf == 0 && !strcmp(host, "C:/data/Documents/My Games/Heroes V/Profiles/Player/saves/save_9.sav"));
    free(host);
    /* The player renames the folder outside the game: the next lookup notices and resolves again. */
    entries[5] = "C:/data/Documents/My Games/Heroes V/Profiles/Player/OldSaves";
    for (int i = 6; i < 9; ++i) entries[i] = NULL;
    host = resolve(SAVES "\\save_1.sav", &parent, &leaf);
    assert(parent == 0 && leaf == 0 && folder_count == 0); free(host);   /* PATH_NOT_FOUND, nothing stale */
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/Saves", 1);
    add("C:/data/Documents/My Games/Heroes V/Profiles/Player/Saves/save_1.sav", 0);
    host = resolve(SAVES "\\save_1.sav", &parent, &leaf);
    assert(!strcmp(host, "C:/data/Documents/My Games/Heroes V/Profiles/Player/Saves/save_1.sav") && leaf == 1 && folder_count == 1);
    free(host);
    /* A folder change through the host forgets everything. */
    folder_forget_all(); assert(folder_count == 0);
    /* The folder itself as the leaf (FindFirstFile resolves it), and the mount root's direct child. */
    host = resolve(SAVES, &parent, &leaf); assert(leaf == 1 && parent == 1); free(host);
    host = resolve("C:\\Users\\Player\\Documents\\desktop.ini", &parent, &leaf); assert(leaf == 0 && parent == 1); free(host);
    /* The installation keeps its own (listing) path; the folder cache is user data only. */
    unsigned remembered = folder_count;
    host = resolve("C:\\Games\\HeroesV\\data\\data.pak", &parent, &leaf); free(host);
    assert(folder_count == remembered);
    /* Off (A/B): every access walks every folder again. */
    folder_cache_off = 1; folder_forget_all(); stats = lstat_calls;
    host = resolve(SAVES "\\save_1.sav", &parent, &leaf); free(host);
    host = resolve(SAVES "\\save_1.sav", &parent, &leaf); free(host);
    assert(lstat_calls == stats + 12 && folder_count == 0);
    puts("PASS user-data folders: one lstat per save after the first, NTFS case, free names, outside renames and invalidation, A/B switch");
    return 0;
}
'''


class FilesFoldersTest(unittest.TestCase):
    def test_remembered_folders(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        production = text[text.index("/* ---------------------------------------------------- user-data folders */"):
                          text.index("/* Append component `name` to host path")]
        production += body(text, "static int normalize(")
        for name in ("static int resolve_component(", "static int resolve_below(", "static char *to_host_ex("):
            production += body(text, name)
        compile_probe("files_folders", HARNESS.replace("/* PRODUCTION */", production), {})


if __name__ == "__main__":
    unittest.main()
