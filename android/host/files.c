/* Files: Windows paths over host directories, file handles, directory
 * enumeration and file mappings.
 *
 * The guest sees one drive. "C:\Games\HeroesV" is the read-mostly game
 * installation; profile folders and the rest of C: are writable directories
 * under the host data root. Every component is resolved case-insensitively,
 * as NTFS lookups are.
 *
 * Shared storage (/sdcard) is a FUSE file system: each lookup, open and
 * directory read is a round trip to the media provider, and a mapped page
 * fault is another. H5 probes every UI/data file as a loose file before it
 * reads its .pak archives (hundreds of misses per screen) and reads archive
 * entries through small mapped windows. Listings of the game's directories
 * are therefore kept in memory (they change only through this file), archive
 * windows are read in one call, and the guest machine is released while the
 * host waits on the file system, so FMOD keeps mixing. */
#define _GNU_SOURCE
#include "host.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <fnmatch.h>
#include <strings.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

#define WIN_MAX_PATH 260

typedef struct { const char *win; char host[1024]; } mount_t;
static mount_t mounts[8];
static int mount_count;
static char game_root[1024], data_root[1024], overlay_root[1024];
#ifndef HOMM5_BIN
#define HOMM5_BIN "bin"
#endif
static char cwd[WIN_MAX_PATH] = "C:\\Games\\HeroesV\\" HOMM5_BIN;
static pthread_mutex_t cwd_lock = PTHREAD_MUTEX_INITIALIZER;

const char *void_root_dir(void) { return game_root; }
const char *void_data_dir(void) { return data_root; }

/* ---------------------------------------------------- directory listings */
typedef struct {
    char *name;
    uint32_t folded;            /* hash of the ASCII-case-folded name */
    unsigned char kind;         /* DT_DIR, DT_REG or DT_UNKNOWN */
    unsigned char stat_valid;
    struct stat st;
} listed_entry;

typedef struct dir_listing {
    struct dir_listing *next;
    uint64_t key;
    char *path;
    int count;
    listed_entry *entries;
} dir_listing;

#define LISTING_BUCKETS 2048u
static dir_listing *listings[LISTING_BUCKETS];
static pthread_mutex_t listing_lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t listing_hits, listing_loads;

static uint64_t path_key(const char *path, size_t length)
{
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < length; ++i) h = (h ^ (uint8_t)path[i]) * 1099511628211ull;
    return h;
}

static uint32_t folded_hash(const char *name)
{
    uint32_t h = 2166136261u;
    for (const char *p = name; *p; ++p) {
        unsigned char c = (unsigned char)*p;
        if (c >= 'A' && c <= 'Z') c = (unsigned char)(c + 32);
        h = (h ^ c) * 16777619u;
    }
    return h;
}

static int under(const char *path, const char *root)
{
    size_t n = strlen(root);
    return n && !strncmp(path, root, n) && (path[n] == 0 || path[n] == '/');
}

/* Only the installation and the port's overlay: profiles and saves change
 * outside this cache's view (the game's own writes go there). */
static int cacheable(const char *dir)
{
    return under(dir, game_root) || under(dir, overlay_root);
}

/* Installation archives are immutable during normal play. A writer opts this
 * process out of read-ahead, including while writable mapped views stay open. */
static int archive_cache_disabled;
static int archive_path(const char *path)
{
    size_t n = path ? strlen(path) : 0;
    return n >= 4 && cacheable(path) && !strcasecmp(path + n - 4, ".pak");
}
static void archive_changed(const char *path)
{
    if (archive_path(path)) __atomic_store_n(&archive_cache_disabled, 1, __ATOMIC_RELEASE);
}

static void listing_free(dir_listing *l)
{
    for (int i = 0; i < l->count; ++i) free(l->entries[i].name);
    free(l->entries);
    free(l->path);
    free(l);
}

/* Caller holds listing_lock. NULL when the directory cannot be read. */
static dir_listing *listing_get(const char *dir, int load)
{
    size_t length = strlen(dir);
    uint64_t key = path_key(dir, length);
    dir_listing **slot = &listings[key % LISTING_BUCKETS];
    for (dir_listing *l = *slot; l; l = l->next)
        if (l->key == key && !strcmp(l->path, dir)) { ++listing_hits; return l; }
    if (!load) return NULL;
    DIR *d = opendir(length ? dir : "/");
    if (!d) return NULL;
    dir_listing *l = (dir_listing *)calloc(1, sizeof *l);
    int capacity = 0;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        if (l->count == capacity) {
            capacity = capacity ? capacity * 2 : 32;
            l->entries = (listed_entry *)realloc(l->entries, sizeof *l->entries * (size_t)capacity);
        }
        listed_entry *entry = &l->entries[l->count++];
        memset(entry, 0, sizeof *entry);
        entry->name = strdup(e->d_name);
        entry->folded = folded_hash(e->d_name);
        entry->kind = e->d_type == DT_DIR ? DT_DIR : e->d_type == DT_REG ? DT_REG : DT_UNKNOWN;
    }
    closedir(d);
    l->key = key;
    l->path = strdup(dir);
    l->next = *slot;
    *slot = l;
    ++listing_loads;
    return l;
}

static listed_entry *listing_find(dir_listing *l, const char *name)
{
    uint32_t folded = folded_hash(name);
    for (int i = 0; i < l->count; ++i)
        if (l->entries[i].folded == folded && !strcasecmp(l->entries[i].name, name)) return &l->entries[i];
    return NULL;
}

/* A directory's contents changed through this host (created, removed, renamed). */
static void listing_forget(const char *dir)
{
    size_t length = strlen(dir);
    uint64_t key = path_key(dir, length);
    pthread_mutex_lock(&listing_lock);
    for (dir_listing **slot = &listings[key % LISTING_BUCKETS]; *slot;) {
        dir_listing *l = *slot;
        if (l->key == key && !strcmp(l->path, dir)) { *slot = l->next; listing_free(l); }
        else slot = &l->next;
    }
    pthread_mutex_unlock(&listing_lock);
}

/* A file's parent listing; a removed or renamed directory also drops its subtree. */
static void listing_forget_parent(const char *path, int subtree)
{
    archive_changed(path);
    char parent[2048];
    snprintf(parent, sizeof parent, "%s", path);
    char *slash = strrchr(parent, '/');
    if (slash) *slash = 0;
    listing_forget(parent);
    if (!subtree) return;
    pthread_mutex_lock(&listing_lock);
    for (unsigned b = 0; b < LISTING_BUCKETS; ++b) {
        for (dir_listing **slot = &listings[b]; *slot;) {
            dir_listing *l = *slot;
            if (under(l->path, path)) { *slot = l->next; listing_free(l); }
            else slot = &l->next;
        }
    }
    pthread_mutex_unlock(&listing_lock);
}

/* 1 present (actual spelling and kind returned), 0 absent, -1 not answerable. */
static int listing_lookup(const char *dir, const char *name, char *actual, size_t cap, unsigned char *kind, int load)
{
    if (!cacheable(dir)) return -1;
    pthread_mutex_lock(&listing_lock);
    dir_listing *l = listing_get(dir, load);
    int result = -1;
    if (l) {
        listed_entry *entry = listing_find(l, name);
        result = entry != NULL;
        if (entry) {
            snprintf(actual, cap, "%s", entry->name);
            if (kind) *kind = entry->kind;
        }
    }
    pthread_mutex_unlock(&listing_lock);
    return result;
}

/* stat through the listing: archive enumeration stats every map file. */
static int cached_stat(const char *path, struct stat *out)
{
    char dir[2048];
    snprintf(dir, sizeof dir, "%s", path);
    char *slash = strrchr(dir, '/');
    if (!slash || !cacheable(path)) return stat(path, out);
    *slash = 0;
    const char *name = slash + 1;
    pthread_mutex_lock(&listing_lock);
    dir_listing *l = listing_get(dir, 1);
    listed_entry *entry = l ? listing_find(l, name) : NULL;
    int result;
    if (l && !entry) {
        errno = ENOENT;
        result = -1;
    } else if (entry && entry->stat_valid) {
        *out = entry->st;
        result = 0;
    } else {
        result = stat(path, out);
        int e = errno;
        if (!result && entry) { entry->st = *out; entry->stat_valid = 1; }
        errno = e;
    }
    pthread_mutex_unlock(&listing_lock);
    return result;
}

void void_files_set_overlay(const char *dir)
{
    snprintf(overlay_root, sizeof overlay_root, "%s", dir ? dir : "");
}

/* The app's private, fast storage for derived data (program binaries). */
static char cache_root[1024];
void void_files_set_cache(const char *dir) { snprintf(cache_root, sizeof cache_root, "%s", dir ? dir : ""); }
const char *void_cache_dir(void) { return cache_root[0] ? cache_root : NULL; }

/* "[files] ..." counters for the hitch log. */
void void_files_stats(uint64_t *hits, uint64_t *loads)
{
    pthread_mutex_lock(&listing_lock);
    *hits = listing_hits; *loads = listing_loads;
    pthread_mutex_unlock(&listing_lock);
}

static void mkdirs(const char *path)
{
    char tmp[1024];
    snprintf(tmp, sizeof tmp, "%s", path);
    for (char *p = tmp + 1; *p; ++p) {
        if (*p == '/') { *p = 0; mkdir(tmp, 0775); *p = '/'; }
    }
    mkdir(tmp, 0775);
}

static void add_mount(const char *win, const char *host_fmt, const char *base)
{
    mount_t *m = &mounts[mount_count++];
    m->win = win;
    snprintf(m->host, sizeof m->host, host_fmt, base);
    mkdirs(m->host);
}

int void_files_init(const char *game, const char *data)
{
    snprintf(game_root, sizeof game_root, "%s", game);
    snprintf(data_root, sizeof data_root, "%s", data);
    /* Longest prefixes first. */
    add_mount("C:\\Users\\Player\\AppData\\Local\\Temp", "%s/Temp", data);
    add_mount("C:\\Users\\Player\\Documents", "%s/Documents", data);
    add_mount("C:\\Users\\Player\\AppData", "%s/AppData", data);
    add_mount("C:\\Users\\Public\\Documents", "%s/PublicDocuments", data);
    add_mount("C:\\ProgramData", "%s/ProgramData", data);
    add_mount("C:\\Games\\HeroesV", "%s", game);
    add_mount("C:", "%s/drive_c", data);
    struct stat st;
    if (stat(game_root, &st) || !S_ISDIR(st.st_mode)) {
        void_log("[void] game root %s is missing", game_root);
        return 0;
    }
    return 1;
}

/* Normalize a Windows path to "C:\a\b" (no trailing separator, no . or ..).
 * Returns 0 if it cannot be represented. */
static int normalize(const char *in, char *out, size_t cap)
{
    char work[1024];
    size_t n = 0;
    const char *p = in;
    if (!strncmp(p, "\\\\?\\", 4)) p += 4;
    if (((p[0] | 0x20) >= 'a' && (p[0] | 0x20) <= 'z') && p[1] == ':') {
        if (p[2] == '\\' || p[2] == '/') {
            snprintf(work, sizeof work, "C:%s", p + 2);
        } else {
            pthread_mutex_lock(&cwd_lock);
            snprintf(work, sizeof work, "%s\\%s", cwd, p + 2);
            pthread_mutex_unlock(&cwd_lock);
        }
    } else if (p[0] == '\\' || p[0] == '/') {
        snprintf(work, sizeof work, "C:%s", p);
    } else {
        pthread_mutex_lock(&cwd_lock);
        snprintf(work, sizeof work, "%s\\%s", cwd, p);
        pthread_mutex_unlock(&cwd_lock);
    }
    /* Split and rebuild. */
    char *parts[128];
    int count = 0;
    for (char *s = work; *s; ++s) if (*s == '/') *s = '\\';
    char *save = NULL;
    char *tok = strtok_r(work + 2, "\\", &save);
    while (tok) {
        if (!strcmp(tok, ".") || !*tok) {
        } else if (!strcmp(tok, "..")) {
            if (count) --count;
        } else {
            /* Windows strips trailing dots and spaces from components. */
            size_t len = strlen(tok);
            while (len > 1 && (tok[len - 1] == '.' || tok[len - 1] == ' ')) tok[--len] = 0;
            if (count == 128) return 0;
            parts[count++] = tok;
        }
        tok = strtok_r(NULL, "\\", &save);
    }
    n = (size_t)snprintf(out, cap, "C:");
    for (int i = 0; i < count; ++i) {
        n += (size_t)snprintf(out + n, n < cap ? cap - n : 0, "\\%s", parts[i]);
        if (n >= cap) return 0;
    }
    if (count == 0) snprintf(out, cap, "C:\\");
    return 1;
}

/* Append component `name` to host path `base`, matching an existing entry
 * case-insensitively. Returns 1 if the entry exists, 0 if it does not. */
static int resolve_component(char *base, size_t cap, const char *name, unsigned char *kind, int cache_only)
{
    size_t len = strlen(base);
    char actual[512];
    int listed = listing_lookup(base, name, actual, sizeof actual, kind, !cache_only);
    if (listed >= 0) {
        snprintf(base + len, cap - len, "/%s", listed ? actual : name);
        return listed;
    }
    if (cache_only) return -1;
    if (kind) *kind = DT_UNKNOWN;
    snprintf(base + len, cap - len, "/%s", name);
    struct stat st;
    if (!lstat(base, &st)) {
        if (kind) *kind = S_ISDIR(st.st_mode) ? DT_DIR : DT_REG;
        return 1;
    }
    base[len] = 0;
    DIR *d = opendir(len ? base : "/");
    int found = 0;
    if (d) {
        struct dirent *e;
        while ((e = readdir(d))) {
            if (!strcasecmp(e->d_name, name)) {
                snprintf(base + len, cap - len, "/%s", e->d_name);
                found = 1;
                break;
            }
        }
        closedir(d);
    }
    if (!found) snprintf(base + len, cap - len, "/%s", name);
    return found;
}

/* Resolution flags: the port's overlay shadows game files for reading. */
#define RESOLVE_OVERLAY 1
#define RESOLVE_CACHED_ONLY 2

/* The path below a mount, resolved component by component under `root`.
 * Returns 1 if the leaf exists, 0 if not, with *parent_ok as below. */
static int resolve_below(char *host, size_t cap, const char *root, const char *rest, int *parent_ok,
                         unsigned char *leaf_kind, int cache_only)
{
    snprintf(host, cap, "%s", root);
    int ok = 1, leaf = 1;
    char component[512];
    if (leaf_kind) *leaf_kind = DT_DIR;
    while (*rest) {
        while (*rest == '\\') ++rest;
        if (!*rest) break;
        size_t k = 0;
        while (rest[k] && rest[k] != '\\' && k < sizeof component - 1) { component[k] = rest[k]; ++k; }
        component[k] = 0;
        rest += k;
        int last = !*rest || (rest[0] == '\\' && !rest[1]);
        if (!ok) {
            size_t len = strlen(host);
            snprintf(host + len, cap - len, "/%s", component);
            leaf = 0;
        } else {
            unsigned char kind = DT_UNKNOWN;
            int exists = resolve_component(host, cap, component, &kind, cache_only);
            if (exists < 0) return -1;
            if (!exists && !last) ok = 0;
            if (last) { leaf = exists; if (leaf_kind) *leaf_kind = kind; }
        }
    }
    if (parent_ok) *parent_ok = ok;
    return ok && leaf;
}

/* Windows path (UTF-8) -> host path. *exists_parent reports whether every
 * component but the last exists (ERROR_PATH_NOT_FOUND vs FILE_NOT_FOUND);
 * *leaf reports the last one: 1 present, 0 absent. */
static char *to_host_ex(const char *windows_path, int flags, int *parent_exists, int *leaf, char *normalized_out)
{
    char norm[1024];
    if (!windows_path || !normalize(windows_path, norm, sizeof norm)) return NULL;
    if (normalized_out) snprintf(normalized_out, 1024, "%s", norm);
    const mount_t *best = NULL;
    size_t best_len = 0;
    for (int i = 0; i < mount_count; ++i) {
        size_t l = strlen(mounts[i].win);
        if (!strncasecmp(norm, mounts[i].win, l) && (norm[l] == 0 || norm[l] == '\\') && l > best_len) {
            best = &mounts[i];
            best_len = l;
        }
    }
    if (!best) return NULL;
    int cache_only = (flags & RESOLVE_CACHED_ONLY) != 0;
    if (cache_only && !cacheable(best->host)) return NULL;
    char *host = (char *)malloc(2048);
    const char *rest = norm + best_len;
    /* A regular file of the overlay replaces the installation's for reading. */
    if ((flags & RESOLVE_OVERLAY) && overlay_root[0] && !strcmp(best->host, game_root) && *rest) {
        int overlay_parent = 0;
        unsigned char kind = DT_UNKNOWN;
        int present = resolve_below(host, 2048, overlay_root, rest, &overlay_parent, &kind, cache_only);
        if (present < 0) { free(host); return NULL; }
        if (present && kind != DT_DIR) {
            if (parent_exists) *parent_exists = 1;
            if (leaf) *leaf = 1;
            return host;
        }
    }
    int ok = 1;
    int present = resolve_below(host, 2048, best->host, rest, &ok, NULL, cache_only);
    if (present < 0) { free(host); return NULL; }
    if (parent_exists) *parent_exists = ok;
    if (leaf) *leaf = present;
    return host;
}

static char *to_host(const char *windows_path, int *parent_exists, char *normalized_out)
{
    return to_host_ex(windows_path, 0, parent_exists, NULL, normalized_out);
}

char *void_path_to_host(const char *windows_path) { return to_host(windows_path, NULL, NULL); }

/* The overlay's twin of an installation directory, for merged listings. */
static char *overlay_dir(const char *windows_dir)
{
    char norm[1024];
    if (!overlay_root[0] || !normalize(windows_dir, norm, sizeof norm)) return NULL;
    static const char game_mount[] = "C:\\Games\\HeroesV";
    size_t l = sizeof game_mount - 1;
    if (strncasecmp(norm, game_mount, l) || (norm[l] && norm[l] != '\\')) return NULL;
    char *host = (char *)malloc(2048);
    int parent_ok = 0;
    unsigned char kind = DT_UNKNOWN;
    if (!resolve_below(host, 2048, overlay_root, norm + l, &parent_ok, &kind, 0) || kind == DT_REG) {
        free(host);
        return NULL;
    }
    return host;
}

uint32_t void_cwd_get(char *out, uint32_t cap)
{
    pthread_mutex_lock(&cwd_lock);
    uint32_t n = (uint32_t)snprintf(out, cap, "%s", cwd);
    pthread_mutex_unlock(&cwd_lock);
    return n;
}

int void_cwd_set(const char *windows_path)
{
    char norm[1024];
    if (!normalize(windows_path, norm, sizeof norm)) return 0;
    char *host = to_host(norm, NULL, NULL);
    struct stat st;
    int ok = host && !stat(host, &st) && S_ISDIR(st.st_mode);
    free(host);
    if (!ok) return 0;
    pthread_mutex_lock(&cwd_lock);
    snprintf(cwd, sizeof cwd, "%s", norm);
    pthread_mutex_unlock(&cwd_lock);
    return 1;
}

uint32_t void_errno_to_win32(int e)
{
    switch (e) {
    case ENOENT: return ERROR_FILE_NOT_FOUND_;
    case ENOTDIR: return ERROR_PATH_NOT_FOUND_;
    case EACCES: case EPERM: case EROFS: return ERROR_ACCESS_DENIED_;
    case EEXIST: return ERROR_FILE_EXISTS_;
    case ENOMEM: return ERROR_NOT_ENOUGH_MEMORY_;
    case EBADF: return ERROR_INVALID_HANDLE_;
    case EINVAL: return ERROR_INVALID_PARAMETER_;
    case ENOSPC: return 112u;          /* ERROR_DISK_FULL */
    case ENOTEMPTY: return 145u;       /* ERROR_DIR_NOT_EMPTY */
    default: return ERROR_ACCESS_DENIED_;
    }
}

/* ----------------------------------------------------------- file objects */
typedef struct {
    int fd;
    uint32_t granted_access;
    int std_stream;       /* 0 none, 1 stdin, 2 stdout, 3 stderr */
    int is_dir;
    char *host_path;
    int delete_on_close;
    char line[512];       /* buffered guest console output */
    size_t line_len;
    unsigned keep_times;
    struct timespec kept_times[2]; /* SetFileTime(-1) suppresses this handle's updates */
} file_t;

static int file_restore_kept_times(file_t *f)
{
    if (!f->keep_times) return 0;
    struct timespec times[2] = { {0, UTIME_OMIT}, {0, UTIME_OMIT} };
    for (unsigned i = 0; i < 2; ++i) if (f->keep_times & (1u << i)) times[i] = f->kept_times[i];
    int result;
    do { result = futimens(f->fd, times); } while (result && errno == EINTR);
    return result;
}

static void listing_forget_parent(const char *path, int subtree);

static void file_destroy(void_object *o)
{
    file_t *f = (file_t *)o->data;
    if (f->fd >= 0 && !f->std_stream) { file_restore_kept_times(f); close(f->fd); }
    if (f->delete_on_close && f->host_path) unlink(f->host_path);
    /* A written file's size and times changed under its cached listing. */
    if (f->host_path && (f->delete_on_close || (f->granted_access & 0x50000006u)))
        listing_forget_parent(f->host_path, 0);
    free(f->host_path);
}

static uint32_t file_handle(int fd, const char *host_path, int std_stream)
{
    void_object *o = void_object_new(VOID_OBJ_FILE, sizeof(file_t));
    file_t *f = (file_t *)o->data;
    f->fd = fd;
    f->std_stream = std_stream;
    f->host_path = host_path ? strdup(host_path) : NULL;
    o->destroy = file_destroy;
    o->signaled = 1;
    return void_handle_new(o);
}

static file_t *file_get(uint32_t h)
{
    void_object *o = void_handle_get(h, VOID_OBJ_FILE);
    return o ? (file_t *)o->data : NULL;
}

int void_file_host_fd(uint32_t h)
{
    file_t *f = file_get(h);
    return f ? f->fd : -1;
}

static uint32_t std_handles[3];

void void_files_std_init(void)
{
    std_handles[0] = file_handle(0, NULL, 1);
    std_handles[1] = file_handle(1, NULL, 2);
    std_handles[2] = file_handle(2, NULL, 3);
}

#define GENERIC_READ_ 0x80000000u
#define GENERIC_WRITE_ 0x40000000u
#define FILE_WRITE_DATA_ 0x0002u
#define FILE_APPEND_DATA_ 0x0004u
#define CREATE_NEW_ 1u
#define CREATE_ALWAYS_ 2u
#define OPEN_EXISTING_ 3u
#define OPEN_ALWAYS_ 4u
#define TRUNCATE_EXISTING_ 5u
#define FILE_FLAG_DELETE_ON_CLOSE_ 0x04000000u
#define FILE_FLAG_BACKUP_SEMANTICS_ 0x02000000u

/* Host side of CreateFile: runs with the guest machine released, so it only
 * touches host state; *error is the thread's next last-error value. */
static uint32_t create_file(const char *path, uint32_t access, uint32_t disposition, uint32_t flags, uint32_t *error)
{
    *error = 0;
    if (!path || !*path) { *error = ERROR_PATH_NOT_FOUND_; return WIN_INVALID_HANDLE; }
    if (!strncasecmp(path, "\\\\.\\", 4) || !strcasecmp(path, "CONOUT$") || !strcasecmp(path, "CONIN$")) {
        void_log("[void] CreateFile(%s): device paths are not supported", path);
        *error = ERROR_FILE_NOT_FOUND_;
        return WIN_INVALID_HANDLE;
    }
    int write = (access & (GENERIC_WRITE_ | FILE_WRITE_DATA_ | FILE_APPEND_DATA_ | 0x10000000u)) != 0;
    int read = (access & (GENERIC_READ_ | 0x0001u | 0x10000000u)) != 0 || !write;
    int oflags = O_CLOEXEC | (write ? (read ? O_RDWR : O_WRONLY) : O_RDONLY);
    switch (disposition) {
    case CREATE_NEW_: oflags |= O_CREAT | O_EXCL; break;
    case CREATE_ALWAYS_: oflags |= O_CREAT | O_TRUNC; break;
    case OPEN_EXISTING_: break;
    case OPEN_ALWAYS_: oflags |= O_CREAT; break;
    case TRUNCATE_EXISTING_: oflags |= O_TRUNC; break;
    default:
        *error = ERROR_INVALID_PARAMETER_;
        return WIN_INVALID_HANDLE;
    }
    int parent_ok = 0, leaf = -1;
    int plain_read = !write && disposition == OPEN_EXISTING_;
    char *host = to_host_ex(path, plain_read ? RESOLVE_OVERLAY : 0, &parent_ok, &leaf, NULL);
    if (!host) { *error = ERROR_PATH_NOT_FOUND_; return WIN_INVALID_HANDLE; }
    if (write || (oflags & (O_CREAT | O_TRUNC))) archive_changed(host);
    /* A listed directory answers the loose-file probes without a lookup. */
    char parent[2048];
    snprintf(parent, sizeof parent, "%s", host);
    char *slash = strrchr(parent, '/');
    if (slash) *slash = 0;
    int listed = slash && cacheable(parent);
    if (listed && (!parent_ok || (!leaf && !(oflags & O_CREAT)))) {
        *error = parent_ok ? ERROR_FILE_NOT_FOUND_ : ERROR_PATH_NOT_FOUND_;
        VLOG("[void] CreateFile(%s -> %s) failed: not listed", path, host);
        free(host);
        return WIN_INVALID_HANDLE;
    }
    if ((oflags & O_CREAT) && !write) oflags = (oflags & ~O_ACCMODE) | O_RDWR;
    /* Open first: OPEN_ALWAYS/CREATE_ALWAYS still report an existing file. */
    int existed = 0, created = 0, fd = -1;
    if (oflags & O_CREAT) {
        if (!(oflags & O_EXCL)) {
            fd = open(host, oflags & ~(O_CREAT | O_TRUNC), 0664);
            if (fd >= 0) {
                existed = 1;
                if ((oflags & O_TRUNC) && ftruncate(fd, 0)) { int e = errno; close(fd); fd = -1; errno = e; }
            } else if (errno == ENOENT) {
                fd = open(host, oflags | O_EXCL, 0664);
                created = fd >= 0;
            }
        } else {
            fd = open(host, oflags, 0664);
            created = fd >= 0;
        }
    } else {
        fd = open(host, oflags, 0664);
    }
    if (fd < 0 && (errno == EISDIR || errno == EACCES) && (flags & FILE_FLAG_BACKUP_SEMANTICS_))
        fd = open(host, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) {
        int e = errno;
        uint32_t code = void_errno_to_win32(e);
        if (e == ENOENT && !parent_ok) code = ERROR_PATH_NOT_FOUND_;
        if (e == EISDIR) code = ERROR_ACCESS_DENIED_;
        VLOG("[void] CreateFile(%s -> %s) failed: %s", path, host, strerror(e));
        free(host);
        *error = code;
        return WIN_INVALID_HANDLE;
    }
    struct stat st;
    int is_dir = !fstat(fd, &st) && S_ISDIR(st.st_mode);
    if (is_dir && !(flags & FILE_FLAG_BACKUP_SEMANTICS_)) {
        close(fd);
        free(host);
        *error = ERROR_ACCESS_DENIED_;
        return WIN_INVALID_HANDLE;
    }
    if (write || created) listing_forget(parent);
    uint32_t h = file_handle(fd, host, 0);
    file_t *f = file_get(h);
    f->granted_access = access;
    f->is_dir = is_dir;
    if (flags & FILE_FLAG_DELETE_ON_CLOSE_) f->delete_on_close = 1;
    VLOG("[void] CreateFile(%s) -> %s handle %08X", path, host, h);
    free(host);
    *error = (existed && (disposition == CREATE_ALWAYS_ || disposition == OPEN_ALWAYS_)) ? ERROR_ALREADY_EXISTS_ : 0;
    return h;
}

#define K32 "kernel32.dll"

static uint32_t create_file_guest(char *path)
{
    uint32_t access = ARG(1), disposition = ARG(4), flags = ARG(5), error = 0;
    uint64_t start = void_perf_now_ns();
    /* Cached loose-file misses do no I/O; do not hand the whole guest to another thread for each probe. */
    if (path && *path && strncasecmp(path, "\\\\.\\", 4) &&
        strcasecmp(path, "CONOUT$") && strcasecmp(path, "CONIN$") &&
        disposition == OPEN_EXISTING_ && !(access & (GENERIC_WRITE_ | FILE_WRITE_DATA_ | FILE_APPEND_DATA_ | 0x10000000u))) {
        int parent_ok = 0, leaf = 1;
        char *known = to_host_ex(path, RESOLVE_OVERLAY | RESOLVE_CACHED_ONLY, &parent_ok, &leaf, NULL);
        int missing = known && !leaf;
        free(known);
        if (missing) {
            free(path);
            void_set_last_error(parent_ok ? ERROR_FILE_NOT_FOUND_ : ERROR_PATH_NOT_FOUND_);
            void_perf_add(VOID_PERF_FILE_OPEN, void_perf_now_ns() - start, 0);
            return WIN_INVALID_HANDLE;
        }
    }
    void_blocking_begin();
    uint32_t h = create_file(path, access, disposition, flags, &error);
    void_blocking_end();
    void_perf_add(VOID_PERF_FILE_OPEN, void_perf_now_ns() - start, 0);
    free(path);
    void_set_last_error(error);
    return h;
}

WINAPI_EXPORT(K32, CreateFileA, 7) { return create_file_guest(void_astr_utf8(ARG(0))); }
WINAPI_EXPORT(K32, CreateFileW, 7) { return create_file_guest(void_wstr_utf8(ARG(0))); }

static void console_write(file_t *f, const uint8_t *data, uint32_t n)
{
    for (uint32_t i = 0; i < n; ++i) {
        char c = (char)data[i];
        if (c == '\n' || f->line_len == sizeof f->line - 1) {
            f->line[f->line_len] = 0;
            void_log("[guest-%s] %s", f->std_stream == 3 ? "stderr" : "stdout", f->line);
            f->line_len = 0;
            if (c == '\n') continue;
        }
        if (c != '\r') f->line[f->line_len++] = c;
    }
}

WINAPI_EXPORT(K32, ReadFile, 5)
{
    uint32_t h = ARG(0), buffer = ARG(1), size = ARG(2), read_out = ARG(3), overlapped = ARG(4);
    file_t *f = file_get(h);
    if (read_out) MEM32(read_out) = 0;
    if (!f || f->is_dir) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (f->std_stream) return 1;
    if (size && !void_vm_writable(buffer, size)) { void_set_last_error(998u); return 0; }  /* ERROR_NOACCESS */
    ssize_t got;
    /* Shared storage answers each read through FUSE: let other threads run. The
       read uses its own descriptor (sharing the file position), so a CloseHandle
       from another thread meanwhile cannot free or reuse what it reads from. */
    int fd = f->fd, blocking = size >= 16384;
    if (blocking) {
        fd = dup(f->fd);
        if (fd < 0) { fd = f->fd; blocking = 0; }
    }
    uint64_t start = void_perf_now_ns();
    if (blocking) void_blocking_begin();
    if (overlapped) {
        off_t offset = (off_t)MEM32(overlapped + 8) | ((off_t)MEM32(overlapped + 12) << 32);
        got = pread(fd, GPTR(buffer), size, offset);
    } else {
        size_t total = 0;
        got = 0;
        while (total < size) {
            ssize_t r = read(fd, (uint8_t *)GPTR(buffer) + total, size - total);
            if (r < 0) { if (errno == EINTR) continue; got = -1; break; }
            if (r == 0) break;
            total += (size_t)r;
        }
        if (got >= 0) got = (ssize_t)total;
    }
    int e = errno;
    if (blocking) {
        void_blocking_end();
        close(fd);
        f = file_get(h);              /* closed meanwhile: the read itself still happened */
    }
    if (f && file_restore_kept_times(f) && got >= 0) { got = -1; e = errno; }
    void_perf_add(VOID_PERF_FILE_READ, void_perf_now_ns() - start, got > 0 ? (uint64_t)got : 0);
    if (got < 0) { void_set_last_error(void_errno_to_win32(e)); return 0; }
    if (read_out) MEM32(read_out) = (uint32_t)got;
    if (overlapped) { MEM32(overlapped) = 0; MEM32(overlapped + 4) = (uint32_t)got; }
    return 1;
}

WINAPI_EXPORT(K32, WriteFile, 5)
{
    uint32_t h = ARG(0), buffer = ARG(1), size = ARG(2), written_out = ARG(3), overlapped = ARG(4);
    file_t *f = file_get(h);
    if (written_out) MEM32(written_out) = 0;
    if (!f || f->is_dir) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (f->std_stream) {
        console_write(f, (const uint8_t *)GPTR(buffer), size);
        if (written_out) MEM32(written_out) = size;
        return 1;
    }
    ssize_t put;
    if (overlapped) {
        off_t offset = (off_t)MEM32(overlapped + 8) | ((off_t)MEM32(overlapped + 12) << 32);
        put = pwrite(f->fd, GPTR(buffer), size, offset);
    } else {
        put = write(f->fd, GPTR(buffer), size);
    }
    int e = errno;
    if (file_restore_kept_times(f) && put >= 0) { put = -1; e = errno; }
    if (put < 0) { void_set_last_error(void_errno_to_win32(e)); return 0; }
    if (written_out) MEM32(written_out) = (uint32_t)put;
    return 1;
}

WINAPI_EXPORT(K32, SetFilePointer, 4)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0xFFFFFFFFu; }
    int64_t distance = ARG(2) ? (int64_t)(((uint64_t)MEM32(ARG(2)) << 32) | ARG(1)) : (int64_t)(int32_t)ARG(1);
    int whence = ARG(3) == 0 ? SEEK_SET : ARG(3) == 1 ? SEEK_CUR : SEEK_END;
    if (f->std_stream) return 0;
    off_t pos = lseek(f->fd, (off_t)distance, whence);
    if (pos < 0) { void_set_last_error(131u); return 0xFFFFFFFFu; }   /* ERROR_NEGATIVE_SEEK */
    if (ARG(2)) MEM32(ARG(2)) = (uint32_t)((uint64_t)pos >> 32);
    void_set_last_error(0);
    return (uint32_t)pos;
}

WINAPI_EXPORT(K32, SetFilePointerEx, 5)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    int64_t distance = (int64_t)(((uint64_t)ARG(2) << 32) | ARG(1));
    int whence = ARG(4) == 0 ? SEEK_SET : ARG(4) == 1 ? SEEK_CUR : SEEK_END;
    off_t pos = lseek(f->fd, (off_t)distance, whence);
    if (pos < 0) { void_set_last_error(131u); return 0; }
    if (ARG(3)) { MEM32(ARG(3)) = (uint32_t)pos; MEM32(ARG(3) + 4) = (uint32_t)((uint64_t)pos >> 32); }
    return 1;
}

WINAPI_EXPORT(K32, GetFileSize, 2)
{
    file_t *f = file_get(ARG(0));
    struct stat st;
    if (!f || fstat(f->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0xFFFFFFFFu; }
    if (ARG(1)) MEM32(ARG(1)) = (uint32_t)((uint64_t)st.st_size >> 32);
    void_set_last_error(0);
    return (uint32_t)st.st_size;
}

WINAPI_EXPORT(K32, GetFileSizeEx, 2)
{
    file_t *f = file_get(ARG(0));
    struct stat st;
    if (!f || fstat(f->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    MEM32(ARG(1)) = (uint32_t)st.st_size;
    MEM32(ARG(1) + 4) = (uint32_t)((uint64_t)st.st_size >> 32);
    return 1;
}

WINAPI_EXPORT(K32, GetFileType, 1)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    return f->std_stream ? 2u : 1u;    /* FILE_TYPE_CHAR / FILE_TYPE_DISK */
}

WINAPI_EXPORT(K32, FlushFileBuffers, 1) { return file_get(ARG(0)) ? 1u : 0u; }

WINAPI_EXPORT(K32, SetEndOfFile, 1)
{
    file_t *f = file_get(ARG(0));
    if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    off_t pos = lseek(f->fd, 0, SEEK_CUR);
    if (pos < 0 || ftruncate(f->fd, pos)) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    if (file_restore_kept_times(f)) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    return 1;
}

WINAPI_EXPORT(K32, LockFile, 5) { return 1; }
WINAPI_EXPORT(K32, UnlockFile, 5) { return 1; }
WINAPI_EXPORT(K32, LockFileEx, 6) { return 1; }

WINAPI_EXPORT(K32, GetStdHandle, 1)
{
    switch (ARG(0)) {
    case 0xFFFFFFF6u: return std_handles[0];
    case 0xFFFFFFF5u: return std_handles[1];
    case 0xFFFFFFF4u: return std_handles[2];
    default: void_set_last_error(ERROR_INVALID_HANDLE_); return WIN_INVALID_HANDLE;
    }
}

WINAPI_EXPORT(K32, SetStdHandle, 2)
{
    switch (ARG(0)) {
    case 0xFFFFFFF6u: std_handles[0] = ARG(1); return 1;
    case 0xFFFFFFF5u: std_handles[1] = ARG(1); return 1;
    case 0xFFFFFFF4u: std_handles[2] = ARG(1); return 1;
    default: return 0;
    }
}

static uint64_t unix_to_filetime(time_t t, long ns)
{
    return (uint64_t)t * 10000000ull + (uint64_t)ns / 100u + 116444736000000000ull;
}

/* The first 36 bytes are shared by GET_FILEEX_INFO_STANDARD and find data. */
static void fill_file_metadata(const struct stat *st, uint32_t out)
{
    /* As GetFileAttributes reports them: ARCHIVE, READONLY without write bits. */
    MEM32(out) = S_ISDIR(st->st_mode) ? 0x10u : (st->st_mode & 0222) ? 0x20u : 0x21u;
    MEM64(out + 4) = unix_to_filetime(st->st_ctim.tv_sec, st->st_ctim.tv_nsec);
    MEM64(out + 12) = unix_to_filetime(st->st_atim.tv_sec, st->st_atim.tv_nsec);
    MEM64(out + 20) = unix_to_filetime(st->st_mtim.tv_sec, st->st_mtim.tv_nsec);
    MEM32(out + 28) = S_ISDIR(st->st_mode) ? 0 : (uint32_t)((uint64_t)st->st_size >> 32);
    MEM32(out + 32) = S_ISDIR(st->st_mode) ? 0 : (uint32_t)st->st_size;
}

/* The host stat of a guest path, with the machine released; 0 on success,
 * else the Win32 error. */
static uint32_t stat_guest_path(const char *path, struct stat *st)
{
    if (!path) return ERROR_PATH_NOT_FOUND_;
    void_blocking_begin();
    int parent_ok = 0, leaf = -1;
    char *host = to_host_ex(path, RESOLVE_OVERLAY, &parent_ok, &leaf, NULL);
    uint32_t error = 0;
    if (!host) error = ERROR_PATH_NOT_FOUND_;
    else if (!parent_ok) error = ERROR_PATH_NOT_FOUND_;
    else if (cached_stat(host, st)) error = errno == ENOENT ? ERROR_FILE_NOT_FOUND_ : void_errno_to_win32(errno);
    free(host);
    void_blocking_end();
    return error;
}

static uint32_t attributes_of(const char *path)
{
    struct stat st;
    uint32_t error = stat_guest_path(path, &st);
    if (error) {
        void_set_last_error(error);
        VLOG("[void] GetFileAttributes(%s): missing", path ? path : "(null)");
        return 0xFFFFFFFFu;
    }
    if (S_ISDIR(st.st_mode)) return 0x10u;
    return (st.st_mode & 0222) ? 0x20u : 0x21u;   /* FILE_ATTRIBUTE_ARCHIVE (| READONLY) */
}

WINAPI_EXPORT(K32, GetFileAttributesA, 1)
{
    char *path = void_astr_utf8(ARG(0));
    uint32_t r = attributes_of(path);
    free(path);
    return r;
}

WINAPI_EXPORT(K32, GetFileAttributesW, 1)
{
    char *path = void_wstr_utf8(ARG(0));
    uint32_t r = attributes_of(path);
    free(path);
    return r;
}

static uint32_t attributes_ex(int wide)
{
    if (ARG(1) != 0 || !void_vm_writable(ARG(2), 36)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    char *path = wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0));
    struct stat st;
    uint32_t error = stat_guest_path(path, &st);
    if (!error) fill_file_metadata(&st, ARG(2));
    else void_set_last_error(error);
    free(path);
    return !error;
}
WINAPI_EXPORT(K32, GetFileAttributesExA, 3) { return attributes_ex(0); }
WINAPI_EXPORT(K32, GetFileAttributesExW, 3) { return attributes_ex(1); }

WINAPI_EXPORT(K32, GetFileTime, 4)
{
    file_t *file = file_get(ARG(0));
    struct stat st;
    if (!file || fstat(file->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    for (uint32_t i = 1; i < 4; ++i) {
        if (ARG(i) && !void_vm_writable(ARG(i), 8)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    }
    if (ARG(1)) MEM64(ARG(1)) = unix_to_filetime(st.st_ctim.tv_sec, st.st_ctim.tv_nsec);
    if (ARG(2)) MEM64(ARG(2)) = unix_to_filetime(st.st_atim.tv_sec, st.st_atim.tv_nsec);
    if (ARG(3)) MEM64(ARG(3)) = unix_to_filetime(st.st_mtim.tv_sec, st.st_mtim.tv_nsec);
    return 1;
}

WINAPI_EXPORT(K32, GetFileInformationByHandle, 2)
{
    file_t *file = file_get(ARG(0));
    uint32_t out = ARG(1);
    struct stat st;
    if (!file || fstat(file->fd, &st)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (!void_vm_writable(out, 52)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    MEM32(out) = S_ISDIR(st.st_mode) ? 0x10u : 0x20u;
    MEM64(out + 4) = unix_to_filetime(st.st_ctim.tv_sec, st.st_ctim.tv_nsec);
    MEM64(out + 12) = unix_to_filetime(st.st_atim.tv_sec, st.st_atim.tv_nsec);
    MEM64(out + 20) = unix_to_filetime(st.st_mtim.tv_sec, st.st_mtim.tv_nsec);
    MEM32(out + 28) = (uint32_t)st.st_dev;
    MEM32(out + 32) = S_ISDIR(st.st_mode) ? 0 : (uint32_t)((uint64_t)st.st_size >> 32);
    MEM32(out + 36) = S_ISDIR(st.st_mode) ? 0 : (uint32_t)st.st_size;
    MEM32(out + 40) = (uint32_t)st.st_nlink;
    MEM32(out + 44) = (uint32_t)((uint64_t)st.st_ino >> 32);
    MEM32(out + 48) = (uint32_t)st.st_ino;
    return 1;
}

static uint32_t delete_file(const char *path)
{
    char *host = to_host(path, NULL, NULL);
    int ok = host && !unlink(host);
    if (!ok) void_set_last_error(host ? void_errno_to_win32(errno) : ERROR_PATH_NOT_FOUND_);
    if (host) listing_forget_parent(host, 0);
    free(host);
    return ok;
}

WINAPI_EXPORT(K32, DeleteFileA, 1) { char *p = void_astr_utf8(ARG(0)); uint32_t r = delete_file(p); free(p); return r; }
WINAPI_EXPORT(K32, DeleteFileW, 1) { char *p = void_wstr_utf8(ARG(0)); uint32_t r = delete_file(p); free(p); return r; }

/* The random map generator removes its working folder after saving a map. */
static uint32_t remove_directory(const char *path)
{
    char *host = path ? to_host(path, NULL, NULL) : NULL;
    int ok = host && !rmdir(host);
    if (!ok) void_set_last_error(host ? void_errno_to_win32(errno) : ERROR_PATH_NOT_FOUND_);
    if (host) listing_forget_parent(host, 1);
    VLOG("[void] RemoveDirectory(%s) = %d", path ? path : "(null)", ok);
    free(host);
    return ok;
}

WINAPI_EXPORT(K32, RemoveDirectoryA, 1) { char *p = void_astr_utf8(ARG(0)); uint32_t r = remove_directory(p); free(p); return r; }
WINAPI_EXPORT(K32, RemoveDirectoryW, 1) { char *p = void_wstr_utf8(ARG(0)); uint32_t r = remove_directory(p); free(p); return r; }

/* Only READONLY has a representation here (the owner write bit); other
 * attributes are accepted for an existing file, as on FAT-like volumes. */
static uint32_t set_file_attributes(const char *path, uint32_t attributes)
{
    char *host = path ? to_host(path, NULL, NULL) : NULL;
    struct stat st;
    if (!host || stat(host, &st)) {
        void_set_last_error(host ? void_errno_to_win32(errno) : ERROR_PATH_NOT_FOUND_);
        free(host);
        return 0;
    }
    if (!S_ISDIR(st.st_mode)) {
        mode_t mode = (attributes & 1u) ? (st.st_mode & ~(mode_t)0222) : (st.st_mode | 0200);
        /* Shared storage may refuse chmod; the attribute is advisory there. */
        if ((mode & 07777) != (st.st_mode & 07777) && chmod(host, mode & 07777))
            VLOG("[void] SetFileAttributes(%s): chmod: %s", path, strerror(errno));
    }
    listing_forget_parent(host, 0);
    free(host);
    return 1;
}

WINAPI_EXPORT(K32, SetFileAttributesA, 2) { char *p = void_astr_utf8(ARG(0)); uint32_t r = set_file_attributes(p, ARG(1)); free(p); return r; }
WINAPI_EXPORT(K32, SetFileAttributesW, 2) { char *p = void_wstr_utf8(ARG(0)); uint32_t r = set_file_attributes(p, ARG(1)); free(p); return r; }

/* CopyFile uses the same virtual drive/mount resolution as CreateFile. Never
 * pass a guest path directly to POSIX, even when it resembles a host path. */
static uint32_t copy_file(const char *from, const char *to, int fail_if_exists)
{
    int source_parent = 0, dest_parent = 0, in = -1, out = -1;
    uint32_t error = 0;
    char *a = to_host(from, &source_parent, NULL);
    char *b = to_host(to, &dest_parent, NULL);
    struct stat source, dest;
    if (!a || !b) { error = ERROR_PATH_NOT_FOUND_; goto done; }
    do { in = open(a, O_RDONLY | O_NONBLOCK | O_CLOEXEC); } while (in < 0 && errno == EINTR);
    if (in < 0) {
        error = errno == ENOENT && !source_parent ? ERROR_PATH_NOT_FOUND_ : void_errno_to_win32(errno);
        goto done;
    }
    if (fstat(in, &source)) { error = void_errno_to_win32(errno); goto done; }
    if (!S_ISREG(source.st_mode)) { error = ERROR_ACCESS_DENIED_; goto done; }
    /* O_EXCL makes fail-if-exists atomic. Without it, defer truncation until
     * identity and read-only checks have accepted the opened destination. */
    do { out = open(b, O_WRONLY | O_CREAT | O_CLOEXEC | (fail_if_exists ? O_EXCL : 0), 0664); }
    while (out < 0 && errno == EINTR);
    if (out < 0) {
        error = errno == ENOENT && !dest_parent ? ERROR_PATH_NOT_FOUND_ : void_errno_to_win32(errno);
        goto done;
    }
    if (fstat(out, &dest)) { error = void_errno_to_win32(errno); goto done; }
    if (!S_ISREG(dest.st_mode) || !(dest.st_mode & 0222)) { error = ERROR_ACCESS_DENIED_; goto done; }
    if (source.st_dev == dest.st_dev && source.st_ino == dest.st_ino) {
        error = 32u;                   /* ERROR_SHARING_VIOLATION (also hard links) */
        goto done;
    }
    int result;
    do { result = ftruncate(out, 0); } while (result < 0 && errno == EINTR);
    if (result) { error = void_errno_to_win32(errno); goto done; }
    uint8_t buffer[16384];
    for (;;) {
        ssize_t got;
        do { got = read(in, buffer, sizeof buffer); } while (got < 0 && errno == EINTR);
        if (got < 0) { error = void_errno_to_win32(errno); goto done; }
        if (!got) break;
        ssize_t offset = 0;
        while (offset < got) {
            ssize_t put = write(out, buffer + offset, (size_t)(got - offset));
            if (put < 0 && errno == EINTR) continue;
            if (put <= 0) { error = put ? void_errno_to_win32(errno) : 29u; goto done; } /* ERROR_WRITE_FAULT */
            offset += put;
        }
    }
    /* POSIX permissions represent the supported read-only attribute. Preserve
     * timestamps too; Windows security descriptors/alternate streams have no
     * representation in this host's file model. */
    if ((source.st_mode & 0777) != (dest.st_mode & 0777) && fchmod(out, source.st_mode & 0777)) {
        error = void_errno_to_win32(errno); goto done;
    }
    struct timespec times[2] = { source.st_atim, source.st_mtim };
    if (futimens(out, times)) { error = void_errno_to_win32(errno); goto done; }
done:
    /* Linux/Android close releases the descriptor even on EINTR: do not retry. */
    if (out >= 0 && close(out) && !error) error = void_errno_to_win32(errno);
    if (in >= 0) close(in);
    if (b) listing_forget_parent(b, 0);
    VLOG("[void] CopyFile(%s -> %s, fail_if_exists=%d): %s (%u)",
         from ? from : "(null)", to ? to : "(null)", fail_if_exists, error ? "failed" : "copied", error);
    free(a); free(b);
    if (error) void_set_last_error(error);
    return !error;
}

/* Validate before the shared converters read guest memory. This host supports
 * MAX_PATH paths; longer names fail rather than truncating into another file. */
static int copy_path_valid(uint32_t address, int wide)
{
    if (!address) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return 0; }
    uint32_t unit = wide ? 2u : 1u;
    for (uint32_t i = 0; i < WIN_MAX_PATH; ++i) {
        uint64_t at = (uint64_t)address + i * unit;
        if (at + unit > UINT64_C(0x100000000) || !void_vm_readable((uint32_t)at, unit)) {
            void_set_last_error(998u); return 0; /* ERROR_NOACCESS */
        }
        if (!(wide ? MEM16((uint32_t)at) : MEM8((uint32_t)at))) {
            if (!i) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return 0; }
            return 1;
        }
    }
    void_set_last_error(206u); return 0; /* ERROR_FILENAME_EXCED_RANGE */
}

static uint32_t copy_file_guest(int wide)
{
    if (!copy_path_valid(ARG(0), wide) || !copy_path_valid(ARG(1), wide)) return 0;
    char *a = wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0));
    char *b = wide ? void_wstr_utf8(ARG(1)) : void_astr_utf8(ARG(1));
    uint32_t result = 0;
    if (!a || !b) void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_);
    else result = copy_file(a, b, ARG(2) != 0);
    free(a); free(b);
    return result;
}

WINAPI_EXPORT(K32, CopyFileA, 3) { return copy_file_guest(0); }
WINAPI_EXPORT(K32, CopyFileW, 3) { return copy_file_guest(1); }

static uint32_t move_file(const char *from, const char *to)
{
    char *a = to_host(from, NULL, NULL), *b = to_host(to, NULL, NULL);
    struct stat st;
    int ok = 0;
    if (a && b) {
        if (!stat(b, &st)) void_set_last_error(ERROR_ALREADY_EXISTS_);
        else if (rename(a, b)) void_set_last_error(void_errno_to_win32(errno));
        else ok = 1;
        listing_forget_parent(a, 1);
        listing_forget_parent(b, 1);
    }
    free(a); free(b);
    return ok;
}

WINAPI_EXPORT(K32, MoveFileA, 2)
{
    char *a = void_astr_utf8(ARG(0)), *b = void_astr_utf8(ARG(1));
    uint32_t r = move_file(a, b);
    free(a); free(b);
    return r;
}

WINAPI_EXPORT(K32, MoveFileW, 2)
{
    char *a = void_wstr_utf8(ARG(0)), *b = void_wstr_utf8(ARG(1));
    uint32_t r = move_file(a, b);
    free(a); free(b);
    return r;
}

static uint32_t create_directory(const char *path)
{
    char *host = path ? to_host(path, NULL, NULL) : NULL;
    uint32_t ok = 0;
    if (host) {
        if (!mkdir(host, 0775)) ok = 1;
        else void_set_last_error(errno == EEXIST ? ERROR_ALREADY_EXISTS_ : void_errno_to_win32(errno));
        listing_forget_parent(host, 0);
    } else {
        void_set_last_error(ERROR_PATH_NOT_FOUND_);
    }
    VLOG("[void] CreateDirectory(%s) = %u", path ? path : "(null)", ok);
    free(host);
    return ok;
}

WINAPI_EXPORT(K32, CreateDirectoryW, 2) { char *p = void_wstr_utf8(ARG(0)); uint32_t r = create_directory(p); free(p); return r; }
WINAPI_EXPORT(K32, CreateDirectoryA, 2) { char *p = void_astr_utf8(ARG(0)); uint32_t r = create_directory(p); free(p); return r; }

/* GetFullPathName: the normalized absolute Windows path. */
static uint32_t full_path(const char *in, uint32_t buffer, uint32_t capacity, uint32_t file_part, int wide)
{
    char norm[1024];
    if (!in || !normalize(in, norm, sizeof norm)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    /* Keep a trailing separator the caller supplied. */
    size_t in_len = strlen(in);
    if (in_len && (in[in_len - 1] == '\\' || in[in_len - 1] == '/') && strlen(norm) > 3) strcat(norm, "\\");
    uint32_t written = wide ? void_utf8_to_gw(norm, buffer, capacity) : void_utf8_to_ga(norm, buffer, capacity);
    uint32_t units = 0;
    if (wide) { if (written + 1 > capacity) return written; units = written; }
    else { if (written + 1 > capacity) return written; units = written; }
    if (file_part) {
        uint32_t last = 0;
        for (uint32_t i = 0; i < units; ++i) {
            uint32_t c = wide ? MEM16(buffer + 2 * i) : MEM8(buffer + i);
            if (c == '\\') last = i + 1;
        }
        MEM32(file_part) = last < units ? buffer + (wide ? 2 * last : last) : 0;
    }
    return units;
}

WINAPI_EXPORT(K32, GetFullPathNameA, 4)
{
    char *p = void_astr_utf8(ARG(0));
    uint32_t r = full_path(p, ARG(2), ARG(1), ARG(3), 0);
    free(p);
    return r;
}

WINAPI_EXPORT(K32, GetFullPathNameW, 4)
{
    char *p = void_wstr_utf8(ARG(0));
    uint32_t r = full_path(p, ARG(2), ARG(1), ARG(3), 1);
    free(p);
    return r;
}

static const char temp_dir[] = "C:\\Users\\Player\\AppData\\Local\\Temp\\";

WINAPI_EXPORT(K32, GetTempPathA, 2)
{
    uint32_t n = void_utf8_to_ga(temp_dir, ARG(1), ARG(0));
    return n;
}

WINAPI_EXPORT(K32, GetTempPathW, 2)
{
    uint32_t n = void_utf8_to_gw(temp_dir, ARG(1), ARG(0));
    return n;
}

static uint32_t temp_file_name(const char *dir, const char *prefix, uint32_t unique, char *out, size_t cap)
{
    static uint32_t counter;
    uint32_t number = unique ? unique : (uint32_t)(void_tick_ms() + ++counter) & 0xFFFFu;
    for (int attempt = 0; attempt < 65536; ++attempt) {
        if (!number) number = 1;
        snprintf(out, cap, "%s%s%.3s%X.tmp", dir, (dir[0] && dir[strlen(dir) - 1] == '\\') ? "" : "\\", prefix ? prefix : "", number);
        if (unique) return number;
        char *host = to_host(out, NULL, NULL);
        int fd = host ? open(host, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0664) : -1;
        if (fd >= 0) listing_forget_parent(host, 0);
        free(host);
        if (fd >= 0) { close(fd); return number; }
        number = (number + 1) & 0xFFFFu;
    }
    return 0;
}

WINAPI_EXPORT(K32, GetTempFileNameA, 4)
{
    char *dir = void_astr_utf8(ARG(0)), *prefix = void_astr_utf8(ARG(1));
    char name[1024];
    uint32_t r = temp_file_name(dir ? dir : "", prefix, ARG(2), name, sizeof name);
    if (r) void_utf8_to_ga(name, ARG(3), WIN_MAX_PATH);
    free(dir); free(prefix);
    return r;
}

WINAPI_EXPORT(K32, GetTempFileNameW, 4)
{
    char *dir = void_wstr_utf8(ARG(0)), *prefix = void_wstr_utf8(ARG(1));
    char name[1024];
    uint32_t r = temp_file_name(dir ? dir : "", prefix, ARG(2), name, sizeof name);
    if (r) void_utf8_to_gw(name, ARG(3), WIN_MAX_PATH);
    free(dir); free(prefix);
    return r;
}

/* ----------------------------------------------------------- drive space */
static char *volume_path(const char *path)
{
    if (!path) path = "C:\\";
    if (!*path || (path[1] == ':' && (path[0] | 0x20) != 'c')) {
        void_set_last_error(ERROR_PATH_NOT_FOUND_); return NULL;
    }
    if (path[0] == '\\' && path[1] == '\\') { void_set_last_error(53u); return NULL; } /* ERROR_BAD_NETPATH */
    char *host = to_host(path, NULL, NULL);
    struct stat st;
    if (!host || stat(host, &st)) {
        void_set_last_error(host ? void_errno_to_win32(errno) : ERROR_PATH_NOT_FOUND_);
        free(host); return NULL;
    }
    if (!S_ISDIR(st.st_mode)) { void_set_last_error(267u); free(host); return NULL; } /* ERROR_DIRECTORY */
    return host;
}

static uint32_t drive_type(int wide)
{
    char *path = ARG(0) ? (wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0))) : NULL;
    size_t length = path ? strlen(path) : 0;
    if (path && length > 2 && path[length - 1] != '\\' && path[length - 1] != '/') { free(path); return 1; }
    char *host = volume_path(path);
    uint32_t result = host ? 3 : 1;     /* DRIVE_FIXED / DRIVE_NO_ROOT_DIR */
    free(host); free(path);
    return result;
}
WINAPI_EXPORT(K32, GetDriveTypeA, 1) { return drive_type(0); }
WINAPI_EXPORT(K32, GetDriveTypeW, 1) { return drive_type(1); }
WINAPI_EXPORT(K32, GetLogicalDrives, 0) { return 1u << 2; }

static uint32_t logical_drive_strings(int wide)
{
    if (ARG(0) < 5) return 5;
    if (!void_vm_writable(ARG(1), wide ? 10 : 5)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    if (wide) { void_utf8_to_gw("C:\\", ARG(1), ARG(0)); MEM16(ARG(1) + 8) = 0; }
    else { void_utf8_to_ga("C:\\", ARG(1), ARG(0)); MEM8(ARG(1) + 4) = 0; }
    return 4;
}
WINAPI_EXPORT(K32, GetLogicalDriveStringsA, 2) { return logical_drive_strings(0); }
WINAPI_EXPORT(K32, GetLogicalDriveStringsW, 2) { return logical_drive_strings(1); }

static int volume_space(int wide, struct statvfs *space)
{
    char *path = ARG(0) ? (wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0))) : NULL;
    char *host = volume_path(path);
    int ok = host && !statvfs(host, space);
    if (host && !ok) void_set_last_error(void_errno_to_win32(errno));
    free(host); free(path);
    return ok;
}

static uint32_t disk_free_space(int wide)
{
    for (uint32_t i = 1; i < 5; ++i) {
        if (!void_vm_writable(ARG(i), 4)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    }
    struct statvfs space;
    if (!volume_space(wide, &space)) return 0;
    uint64_t unit = space.f_frsize ? space.f_frsize : space.f_bsize;
    uint64_t total = space.f_blocks, available = space.f_bavail;
    /* A larger virtual cluster keeps the legacy DWORD counts representable. */
    while ((total > UINT32_MAX || available > UINT32_MAX) && unit <= UINT32_MAX / 2u) {
        unit *= 2; total /= 2; available /= 2;
    }
    if (!unit || unit > UINT32_MAX || total > UINT32_MAX || available > UINT32_MAX) {
        void_set_last_error(534u); return 0;        /* ERROR_ARITHMETIC_OVERFLOW */
    }
    uint32_t sector = unit >= 512 && !(unit % 512) ? 512 : (uint32_t)unit;
    MEM32(ARG(1)) = (uint32_t)unit / sector;
    MEM32(ARG(2)) = sector;
    MEM32(ARG(3)) = (uint32_t)available;
    MEM32(ARG(4)) = (uint32_t)total;
    return 1;
}
WINAPI_EXPORT(K32, GetDiskFreeSpaceA, 5) { return disk_free_space(0); }
WINAPI_EXPORT(K32, GetDiskFreeSpaceW, 5) { return disk_free_space(1); }

static uint32_t disk_free_space_ex(int wide)
{
    for (uint32_t i = 1; i < 4; ++i) {
        if (ARG(i) && !void_vm_writable(ARG(i), 8)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    }
    struct statvfs space;
    if (!volume_space(wide, &space)) return 0;
    uint64_t unit = space.f_frsize ? space.f_frsize : space.f_bsize;
    if (!unit || space.f_blocks > UINT64_MAX / unit || space.f_bavail > UINT64_MAX / unit || space.f_bfree > UINT64_MAX / unit) {
        void_set_last_error(534u); return 0;
    }
    if (ARG(1)) MEM64(ARG(1)) = (uint64_t)space.f_bavail * unit;
    if (ARG(2)) MEM64(ARG(2)) = (uint64_t)space.f_blocks * unit;
    if (ARG(3)) MEM64(ARG(3)) = (uint64_t)space.f_bfree * unit;
    return 1;
}
WINAPI_EXPORT(K32, GetDiskFreeSpaceExA, 4) { return disk_free_space_ex(0); }
WINAPI_EXPORT(K32, GetDiskFreeSpaceExW, 4) { return disk_free_space_ex(1); }

/* ------------------------------------------------------------ find files */
/* Matches with their metadata, gathered once (machine released) by FindFirst. */
typedef struct {
    char *name;
    struct stat st;
} found_t;

typedef struct {
    found_t *found;
    int count, next;
} find_t;

static void find_destroy(void_object *o)
{
    find_t *f = (find_t *)o->data;
    for (int i = 0; i < f->count; ++i) free(f->found[i].name);
    free(f->found);
}

static void fill_find_data(const found_t *found, uint32_t out, int wide)
{
    memset(GPTR(out), 0, wide ? 592 : 320);
    fill_file_metadata(&found->st, out);
    if (wide) void_utf8_to_gw(found->name, out + 44, 260);
    else void_utf8_to_ga(found->name, out + 44, 260);
}

static int find_matches(const char *pattern, const char *name)
{
    /* "*.*" matches every name, as on Windows; "x." matches extensionless names. */
    if (!strcmp(pattern, "*") || !strcmp(pattern, "*.*")) return 1;
    if (!fnmatch(pattern, name, FNM_CASEFOLD)) return 1;
    size_t n = strlen(pattern);
    return n && pattern[n - 1] == '.' && !strchr(name, '.');
}

/* Names of one host directory matching the pattern, skipping ones already
 * gathered (the overlay's come first). Below a drive root Windows lists "."
 * and ".." first, as readdir does for uncached directories. */
static void find_gather(find_t *f, const char *dir, const char *pattern, int dots)
{
    char **names = NULL;
    int count = 0;
    if (cacheable(dir)) {
        pthread_mutex_lock(&listing_lock);
        dir_listing *l = listing_get(dir, 1);
        if (l) {
            names = (char **)malloc(sizeof *names * (size_t)(l->count + 3));
            static const char *const dot_names[] = {".", ".."};
            for (int i = 0; i < 2 && dots; ++i)
                if (find_matches(pattern, dot_names[i])) names[count++] = strdup(dot_names[i]);
            for (int i = 0; i < l->count; ++i)
                if (find_matches(pattern, l->entries[i].name)) names[count++] = strdup(l->entries[i].name);
        }
        pthread_mutex_unlock(&listing_lock);
    } else {
        DIR *d = opendir(dir);
        if (d) {
            int capacity = 0;
            struct dirent *e;
            while ((e = readdir(d))) {
                if (!find_matches(pattern, e->d_name)) continue;
                if (!dots && (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))) continue;
                if (count == capacity) {
                    capacity = capacity ? capacity * 2 : 32;
                    names = (char **)realloc(names, sizeof *names * (size_t)capacity);
                }
                names[count++] = strdup(e->d_name);
            }
            closedir(d);
        }
    }
    struct stat dot_st = {0};
    int dot_state = 0;                            /* the directory's own stat: 1 ok, -1 failed */
    for (int i = 0; i < count; ++i) {
        int duplicate = 0;
        for (int j = 0; j < f->count && !duplicate; ++j) duplicate = !strcasecmp(f->found[j].name, names[i]);
        char host[4096];
        snprintf(host, sizeof host, "%s/%s", dir, names[i]);
        struct stat st;
        /* "." and ".." are no listing entries: they report the directory itself. */
        if (!strcmp(names[i], ".") || !strcmp(names[i], "..")) {
            if (!duplicate && !dot_state) dot_state = cached_stat(dir, &dot_st) ? -1 : 1;
            if (duplicate || dot_state < 0) { free(names[i]); continue; }
            st = dot_st;
        } else if (duplicate || cached_stat(host, &st)) { free(names[i]); continue; }
        f->found = (found_t *)realloc(f->found, sizeof *f->found * (size_t)(f->count + 1));
        f->found[f->count].name = names[i];
        f->found[f->count++].st = st;
    }
    free(names);
}

static uint32_t find_first(int wide)
{
    char *pattern_path = wide ? void_wstr_utf8(ARG(0)) : void_astr_utf8(ARG(0));
    uint32_t out = ARG(1);
    if (!pattern_path) { void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    if (!void_vm_writable(out, wide ? 592 : 320)) { free(pattern_path); void_set_last_error(ERROR_INVALID_PARAMETER_); return WIN_INVALID_HANDLE; }
    size_t input_length = strlen(pattern_path);
    if (!input_length || pattern_path[input_length - 1] == '\\' || pattern_path[input_length - 1] == '/') {
        free(pattern_path); void_set_last_error(ERROR_FILE_NOT_FOUND_); return WIN_INVALID_HANDLE;
    }
    char norm[1024];
    if (!normalize(pattern_path, norm, sizeof norm)) { free(pattern_path); void_set_last_error(ERROR_PATH_NOT_FOUND_); return WIN_INVALID_HANDLE; }
    char *slash = strrchr(norm, '\\');
    char pattern[512];
    snprintf(pattern, sizeof pattern, "%s", slash ? slash + 1 : norm);
    if (slash) *slash = 0;
    if (strlen(norm) == 2) strcat(norm, "\\");
    uint64_t start = void_perf_now_ns();
    void_blocking_begin();
    int parent_ok = 0;
    char *host_dir = to_host(norm, &parent_ok, NULL);
    char *extra_dir = overlay_dir(norm);
    struct stat dir_st;
    int dir_ok = host_dir && parent_ok && !cached_stat(host_dir, &dir_st) && S_ISDIR(dir_st.st_mode);
    find_t gathered = {0};
    int dots = strlen(norm) > 3;                  /* not "c:\\" */
    if (extra_dir) find_gather(&gathered, extra_dir, pattern, dots);
    if (dir_ok) find_gather(&gathered, host_dir, pattern, dots);
    free(host_dir); free(extra_dir);
    void_blocking_end();
    void_perf_add(VOID_PERF_FIND, void_perf_now_ns() - start, 0);
    if (!dir_ok && !gathered.count) {
        VLOG("[void] FindFirstFile(%s): no directory", pattern_path);
        free(pattern_path);
        void_set_last_error(ERROR_PATH_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    VLOG("[void] FindFirstFile(%s): %d matches", pattern_path, gathered.count);
    free(pattern_path);
    if (!gathered.count) {
        void_set_last_error(ERROR_FILE_NOT_FOUND_);
        return WIN_INVALID_HANDLE;
    }
    void_object *o = void_object_new(VOID_OBJ_FIND, sizeof(find_t));
    find_t *f = (find_t *)o->data;
    o->destroy = find_destroy;
    *f = gathered;
    fill_find_data(&f->found[f->next++], out, wide);
    return void_handle_new(o);
}
WINAPI_EXPORT(K32, FindFirstFileA, 2) { return find_first(0); }
WINAPI_EXPORT(K32, FindFirstFileW, 2) { return find_first(1); }

static uint32_t find_next(int wide)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_FIND);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (!void_vm_writable(ARG(1), wide ? 592 : 320)) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    find_t *f = (find_t *)o->data;
    if (f->next < f->count) {
        fill_find_data(&f->found[f->next++], ARG(1), wide);
        return 1;
    }
    void_set_last_error(ERROR_NO_MORE_FILES_);
    return 0;
}
WINAPI_EXPORT(K32, FindNextFileA, 2) { return find_next(0); }
WINAPI_EXPORT(K32, FindNextFileW, 2) { return find_next(1); }

WINAPI_EXPORT(K32, FindClose, 1)
{
    if (!void_handle_get(ARG(0), VOID_OBJ_FIND)) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    void_handle_close(ARG(0));
    return 1;
}

/* ------------------------------------------------------------- mappings */
typedef struct {
    int fd; uint64_t size; uint32_t protect;
    int archive;
    uint64_t identity, cached_offset;
    uint32_t cached_size;
    uint8_t *cached;
} mapping_t;
static uint64_t mapping_identity;
#define ARCHIVE_READ_AHEAD 65536u

static void mapping_destroy(void_object *o)
{
    mapping_t *m = (mapping_t *)o->data;
    if (m->fd >= 0) close(m->fd);
    free(m->cached);
}

WINAPI_EXPORT(K32, CreateFileMappingA, 6)
{
    uint32_t file = ARG(0), protect = ARG(2);
    uint64_t size = ((uint64_t)ARG(3) << 32) | ARG(4);
    int fd, archive = 0;
    if (file == WIN_INVALID_HANDLE) {
        char path[1100];
        snprintf(path, sizeof path, "%s/Temp/.mapping-XXXXXX", data_root);
        fd = mkstemp(path);
        if (fd < 0 || !size) { if (fd >= 0) close(fd); void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
        unlink(path);
        if (ftruncate(fd, (off_t)size)) { close(fd); void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_); return 0; }
    } else {
        file_t *f = file_get(file);
        if (!f) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
        archive = archive_path(f->host_path);
        if (archive && (protect & 0xFFu) != 0x02u) archive_changed(f->host_path);
        fd = dup(f->fd);
        struct stat st;
        fstat(fd, &st);
        if (!size) size = (uint64_t)st.st_size;
        else if (size > (uint64_t)st.st_size && (protect & 0xFFu) == 0x04u) {
            if (ftruncate(fd, (off_t)size)) { close(fd); void_set_last_error(ERROR_ACCESS_DENIED_); return 0; }
        }
    }
    void_object *o = void_object_new(VOID_OBJ_MAPPING, sizeof(mapping_t));
    mapping_t *m = (mapping_t *)o->data;
    m->fd = fd;
    m->size = size;
    m->protect = protect;
    m->archive = archive;
    m->identity = ++mapping_identity;
    o->destroy = mapping_destroy;
    void_set_last_error(0);
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, OpenFileMappingA, 3)
{
    void_set_last_error(ERROR_FILE_NOT_FOUND_);
    return 0;
}

WINAPI_EXPORT(K32, MapViewOfFile, 5)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_MAPPING);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    mapping_t *m = (mapping_t *)o->data;
    uint32_t access = ARG(1);
    uint64_t offset = ((uint64_t)ARG(2) << 32) | ARG(3);
    uint64_t size = ARG(4) ? ARG(4) : m->size - offset;
    if (offset > m->size || size > 0x7FFF0000u || !size) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    int writable = (access & 2u) != 0 || (access & 1u) != 0;
    /* FILE_MAP_ALL_ACCESS (0xF001F) includes the COPY bit as well as WRITE.
     * Windows defines it as FILE_MAP_WRITE, so WRITE takes precedence: treating
     * every bit-0 request as private silently loses H5's mapped save payload. */
    int shared = !(access & 1u) || (access & 2u);
    if (m->archive && writable && shared)
        __atomic_store_n(&archive_cache_disabled, 1, __ATOMIC_RELEASE);
    uint64_t start = void_perf_now_ns();
    uint32_t va = 0;
    int read_fd = -1;
    /* A read-only window of a read-only mapping (the .pak archives) is read
     * in one call: on shared storage each page fault of a file mapping is a
     * separate FUSE round trip taken with the guest machine held. */
    if (!writable && (m->protect & 0xFFu) == 0x02u && size <= (16u << 20)) {
        int cached = m->archive && size <= ARCHIVE_READ_AHEAD &&
            !__atomic_load_n(&archive_cache_disabled, __ATOMIC_ACQUIRE);
        if (cached && m->cached && offset >= m->cached_offset &&
            offset - m->cached_offset <= m->cached_size && size <= m->cached_size - (offset - m->cached_offset)) {
            va = void_vm_alloc(0, (uint32_t)size, 0x3000u, 0x04u);
            if (va) memcpy(GPTR(va), m->cached + (offset - m->cached_offset), (size_t)size);
        }
        if (!va) {
            /* Its own descriptor: the mapping may be closed by another thread meanwhile. */
            read_fd = dup(m->fd);
            va = read_fd >= 0 ? void_vm_alloc(0, (uint32_t)size, 0x3000u, 0x04u) : 0;
            if (va) {
                uint64_t identity = m->identity;
                uint32_t handle = ARG(0);
                uint64_t read_size = cached ? (m->size - offset < ARCHIVE_READ_AHEAD ? m->size - offset : ARCHIVE_READ_AHEAD) : size;
                if (read_size < size) read_size = size;
                uint8_t *block = cached ? malloc((size_t)read_size) : NULL;
                if (!block) read_size = size;
                uint8_t *target = block ? block : GPTR(va);
                void_blocking_begin();
                uint64_t done = 0;
                int failed = 0;
                while (done < read_size) {
                    ssize_t got = pread(read_fd, target + done, (size_t)(read_size - done), (off_t)(offset + done));
                    if (got < 0 && errno == EINTR) continue;
                    if (got < 0) { failed = 1; break; }
                    if (got == 0) break;          /* past the end: zero-filled, as a mapping */
                    done += (uint64_t)got;
                }
                void_blocking_end();
                if (block && !failed) {
                    memset(block + done, 0, (size_t)(read_size - done));
                    memcpy(GPTR(va), block, (size_t)size);
                    /* The original handle can have been closed and reused during I/O. */
                    void_object *current = void_handle_get(handle, VOID_OBJ_MAPPING);
                    mapping_t *live = current ? current->data : NULL;
                    if (live && live->identity == identity && !__atomic_load_n(&archive_cache_disabled, __ATOMIC_ACQUIRE)) {
                        free(live->cached); live->cached = block; block = NULL;
                        live->cached_offset = offset; live->cached_size = (uint32_t)read_size;
                    }
                }
                free(block);
                if (failed) {
                    /* A read error is not data: let the real mapping report it. */
                    void_vm_free(va, 0, 0x8000u);
                    va = 0;
                }
            }
        }
        if (va) {
            uint32_t old = 0;
            void_vm_protect(va, (uint32_t)size, 0x02u, &old);
        }
    }
    if (!va) va = void_vm_map_file(read_fd >= 0 ? read_fd : m->fd, offset, (uint32_t)size, writable, shared);
    if (read_fd >= 0) close(read_fd);
    void_perf_add(VOID_PERF_FILE_MAP, void_perf_now_ns() - start, size);
    VLOG("[void] MapViewOfFile(%08X, off %llX, %llX) = %08X", ARG(0), (unsigned long long)offset,
        (unsigned long long)size, va);
    return va;
}

WINAPI_EXPORT(K32, UnmapViewOfFile, 1) { return (uint32_t)void_vm_unmap_file(ARG(0)); }

/* Shared views write through the page cache; msync only orders the write-back. */
WINAPI_EXPORT(K32, FlushViewOfFile, 2)
{
    uint32_t address = ARG(0), size = ARG(1);
    if (!address || !void_vm_readable(address, 1)) { void_set_last_error(487u); return 0; }  /* ERROR_INVALID_ADDRESS */
    uint32_t page = address & ~(GUEST_PAGE - 1);
    uint32_t span = size ? size + (address - page) : GUEST_PAGE;
    span = (span + GUEST_PAGE - 1) & ~(GUEST_PAGE - 1);
    if (msync(GPTR(page), span, MS_ASYNC)) VLOG("[void] FlushViewOfFile(%08X): %s", address, strerror(errno));
    return 1;
}

static int filetime_to_unix(uint64_t value, struct timespec *out)
{
    /* The high bit denotes negative NT relative times, not an absolute FILETIME.
     * The documented -1 sentinel is handled by SetFileTime before conversion. */
    if (value > INT64_MAX) return 0;
    int64_t seconds = (int64_t)(value / 10000000u) - INT64_C(11644473600);
    out->tv_sec = (time_t)seconds;
    out->tv_nsec = (long)(value % 10000000u) * 100;
    return (int64_t)out->tv_sec == seconds;
}

WINAPI_EXPORT(K32, SetFileTime, 4)
{
    file_t *f = file_get(ARG(0));
    if (!f || f->fd < 0 || f->std_stream) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    /* GENERIC_WRITE and GENERIC_ALL include FILE_WRITE_ATTRIBUTES (0x100). */
    if (!(f->granted_access & (GENERIC_WRITE_ | 0x10000000u | 0x100u))) {
        void_set_last_error(ERROR_ACCESS_DENIED_); return 0;
    }
    uint64_t requested[3] = {0, 0, 0};
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t address = ARG(i + 1);
        if (address) {
            if (!void_vm_readable(address, 8)) { void_set_last_error(998u); return 0; } /* ERROR_NOACCESS */
            memcpy(&requested[i], GPTR(address), 8);
        }
    }
    struct stat st;
    if (fstat(f->fd, &st)) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    /* POSIX cannot change creation time. H5's saving path passes the unchanged
     * GetFileTime creation value; accept that, and report other requests rather
     * than claiming to have changed an unrelated ctime field. */
    if (requested[0] && requested[0] != UINT64_MAX &&
        requested[0] != unix_to_filetime(st.st_ctim.tv_sec, st.st_ctim.tv_nsec)) {
        void_set_last_error(ERROR_NOT_SUPPORTED_); return 0;
    }
    struct timespec times[2] = { {0, UTIME_OMIT}, {0, UTIME_OMIT} };
    struct timespec kept[2] = { f->kept_times[0], f->kept_times[1] };
    unsigned mask = f->keep_times;
    int update = 0;
    for (unsigned i = 0; i < 2; ++i) {
        uint64_t value = requested[i + 1];
        if (!value) continue;          /* NULL and a zero FILETIME leave it alone. */
        if (value == UINT64_MAX) {
            kept[i] = i ? st.st_mtim : st.st_atim;
            mask |= 1u << i;
        } else {
            if (!filetime_to_unix(value, &times[i])) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
            mask &= ~(1u << i);
            update = 1;
        }
    }
    if (update) {
        int result;
        do { result = futimens(f->fd, times); } while (result && errno == EINTR);
        if (result) { void_set_last_error(void_errno_to_win32(errno)); return 0; }
    }
    f->kept_times[0] = kept[0]; f->kept_times[1] = kept[1]; f->keep_times = mask;
    return 1;
}
