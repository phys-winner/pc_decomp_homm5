/* Full creature and hero models on the adventure map (port_lod_fix).
 *
 * The adventure map draws monsters and heroes with separate "_LOD" models
 * (about half the polygons, often half-size textures) that the data names:
 * AdvMapMonsterShared.Model, and the Model/ColourModels of the character a
 * hero's HeroCharacterAdventure points to. Combat draws the full models of
 * the same creatures and heroes. The engine has no switch between the two,
 * so with port_lod_fix on, its href readers resolve a LOD model, a hero's
 * per-player colour model or a LOD-bound animation set to the full one listed
 * in lod_models_table.h (seams, ToE: the typed reference reader 0x00C47F10
 * before it builds an absolute reference at 0x00C48230 and a relative one at
 * 0x00C482B0, and the reader 0x00B9D3A0 before 0x00B9D612; the vanilla and hof
 * patch contracts map them to 1.6/2.1),
 * which tools/lod_models.py derives from each edition's own records. The
 * engine then loads the same objects combat uses (no second copy).
 *
 * A reference resolves when its record is first read, and the hero and
 * creature records are read at startup, before the game applies the
 * profile's variables (port_lod_fix still holds its default then). So the
 * choice is taken once per run from the profile the game will select (the
 * last chosen one, Profiles/global*.cfg: setvar profile_name, and its
 * user*.cfg: setvar port_lod_fix), or the variable's default when the profile
 * has none; a change of the option applies after a restart of the game.
 *
 * <userdata>/lod_trace (checked at the first reference) logs every
 * reference to a LOD file and what became of it. */
#include "host.h"
#include <stdlib.h>
#include <string.h>
#include <strings.h>

typedef struct { const char *lod, *full; } lod_redirect;
#include "lod_models_table.h"

int void_port_lod_fix(void);

#ifdef HOMM5_EDITION
#define LOD_EDITION HOMM5_EDITION
#else
#define LOD_EDITION "toe"
#endif

static const lod_redirect *lod_table;
static size_t lod_count;
static int lod_ready, lod_trace, lod_on;
static unsigned lod_references, lod_resolved;

static int lod_compare(const void *a, const void *b)
{
    return strcmp(((const lod_redirect *)a)->lod, ((const lod_redirect *)b)->lod);
}

/* ---------------------------------------------------- profile choice */
/* `value` of the last `setvar <name> = value` line of cfg `text` (quotes and
 * surrounding blanks removed). 1 found, 0 not. */
static int lod_cfg_value(const char *text, size_t length, const char *name, char *value, size_t cap)
{
    size_t n = strlen(name);
    int found = 0;
    for (size_t at = 0; at < length;) {
        size_t end = at, i = at;
        while (end < length && text[end] != '\n') ++end;
        while (i < end && (text[i] == ' ' || text[i] == '\t')) ++i;
        if (end - i > 7 && !strncasecmp(text + i, "setvar", 6) && (text[i + 6] == ' ' || text[i + 6] == '\t')) {
            i += 7;
            while (i < end && (text[i] == ' ' || text[i] == '\t')) ++i;
            if (end - i > n && !strncasecmp(text + i, name, n)) {
                size_t j = i + n, k = end;
                while (j < end && (text[j] == ' ' || text[j] == '\t')) ++j;
                if (j < end && text[j] == '=') {
                    ++j;
                    while (j < end && (text[j] == ' ' || text[j] == '\t')) ++j;
                    while (k > j && (text[k - 1] == '\r' || text[k - 1] == ' ' || text[k - 1] == '\t')) --k;
                    if (k - j >= 2 && text[j] == '"' && text[k - 1] == '"') { ++j; --k; }
                    if (k - j < cap) { memcpy(value, text + j, k - j); value[k - j] = 0; found = 1; }
                }
            }
        }
        at = end + 1;
    }
    return found;
}

/* A profile cfg by its Windows path (as the game names it), up to 1 MiB. */
static char *lod_cfg_read(const char *windows, size_t *length)
{
    char *host = void_path_to_host(windows);
    FILE *file = host ? fopen(host, "rb") : NULL;
    free(host);
    if (!file) return NULL;
    char *text = malloc((1u << 20) + 1);
    size_t n = text ? fread(text, 1, 1u << 20, file) : 0;
    fclose(file);
    if (text) text[n] = 0;
    *length = n;
    return text;
}

/* The game's ANSI (CP1251) profile name as UTF-8, as the host spells paths. */
static void lod_ansi_utf8(const char *in, char *out, size_t cap)
{
    size_t n = 0;
    for (const unsigned char *p = (const unsigned char *)in; *p && n + 4 < cap; ++p) {
        unsigned u = *p < 0x80 ? *p : void_ansi_to_u16(*p);
        if (u < 0x80) out[n++] = (char)u;
        else if (u < 0x800) { out[n++] = (char)(0xC0 | u >> 6); out[n++] = (char)(0x80 | (u & 0x3F)); }
        else { out[n++] = (char)(0xE0 | u >> 12); out[n++] = (char)(0x80 | ((u >> 6) & 0x3F)); out[n++] = (char)(0x80 | (u & 0x3F)); }
    }
    out[n] = 0;
}

/* port_lod_fix as the profile the game will select stores it: 1 or 0, -1 none.
 * Profile folders and cfg suffixes per edition as in Games.java. */
static int lod_profile_choice(void)
{
    const char *profiles = "C:\\Users\\Player\\Documents\\My Games\\Heroes of Might and Magic V \xE2\x80\x94 Tribes of the East\\Profiles";
    const char *suffix = "_a2";
    if (!strcmp(LOD_EDITION, "vanilla")) { profiles = "C:\\Users\\Player\\Documents\\My Games\\Heroes of Might and Magic V\\Profiles"; suffix = ""; }
    else if (!strcmp(LOD_EDITION, "hof")) {
        profiles = "C:\\Users\\Player\\Documents\\My Games\\Heroes of Might and Magic V\\Hammers of Fate\\Profiles";
        suffix = "_a1";
    }
    char path[1024], value[256], name[768];
    size_t length = 0;
    snprintf(path, sizeof path, "%s\\global%s.cfg", profiles, suffix);
    char *text = lod_cfg_read(path, &length);
    int found = text && lod_cfg_value(text, length, "profile_name", value, sizeof value) && *value;
    free(text);
    if (!found) return -1;
    lod_ansi_utf8(value, name, sizeof name);
    if (snprintf(path, sizeof path, "%s\\%s\\user%s.cfg", profiles, name, suffix) >= (int)sizeof path) return -1;
    text = lod_cfg_read(path, &length);
    found = text && lod_cfg_value(text, length, "port_lod_fix", value, sizeof value);
    free(text);
    if (!found) return -1;
    char *end;
    float number = strtof(value, &end);
    return end == value ? -1 : number >= 0.5f;
}
/* ---------------------------------------------------- end of profile choice */

static void lod_init(void)
{
    lod_ready = 1;
    const char *edition = LOD_EDITION;
    if (!strcmp(edition, "vanilla")) { lod_table = lod_vanilla; lod_count = sizeof lod_vanilla / sizeof *lod_vanilla; }
    else if (!strcmp(edition, "hof")) { lod_table = lod_hof; lod_count = sizeof lod_hof / sizeof *lod_hof; }
    else { lod_table = lod_toe; lod_count = sizeof lod_toe / sizeof *lod_toe; }
    char path[1200];
    snprintf(path, sizeof path, "%s/lod_trace", void_data_dir());
    FILE *flag = fopen(path, "r");
    if (flag) { lod_trace = 1; fclose(flag); }
    int choice = lod_profile_choice();
    lod_on = choice >= 0 ? choice : void_port_lod_fix();
    void_log("[lod] %s: %u LOD references have a full model; full models %s (%s)%s", edition, (unsigned)lod_count,
             lod_on ? "on" : "off", choice >= 0 ? "player profile" : "default", lod_trace ? ", trace on" : "");
}

/* The full reference for a path ("/" first or not, either slash, any case). */
static const lod_redirect *lod_find(const char *text, uint32_t length)
{
    uint32_t at = 0;
    while (at + 4 <= length && !(text[at] == '_' && (text[at + 1] | 0x20) == 'l' &&
                                 (text[at + 2] | 0x20) == 'o' && (text[at + 3] | 0x20) == 'd')) ++at;
    if (at + 4 > length) return NULL;          /* the usual case: not a LOD file */
    char key[512];
    uint32_t n = 0;
    for (uint32_t i = text[0] == '/' || text[0] == '\\'; i < length; ++i) {
        char c = text[i] == '\\' ? '/' : text[i];
        if (n == sizeof key - 1) return NULL;
        key[n++] = (char)(c >= 'A' && c <= 'Z' ? c + 32 : c);
    }
    key[n] = 0;
    const lod_redirect probe = { key, NULL };
    ++lod_references;
    const lod_redirect *hit = bsearch(&probe, lod_table, lod_count, sizeof *lod_table, lod_compare);
    if (lod_trace) void_log("[lod] %.*s -> %s", (int)length, text, hit ? hit->full : "(kept: no full model)");
    return hit;
}

/* Seams: `string` is the guest {begin, end, capacity} reference the engine
 * is about to resolve: an absolute href ("/path#xpointer(...)") or a path
 * already joined to its record's folder; the "#..." part is kept. */
void void_lod_reference(uint32_t string)
{
    if (!lod_ready) lod_init();
    if (!string || !void_vm_readable(string, 12)) return;
    uint32_t begin = MEM32(string), end = MEM32(string + 4), capacity = MEM32(string + 8);
    if (!begin || end <= begin || end - begin > 480 || capacity < end || !void_vm_readable(begin, end - begin)) return;
    const char *text = (const char *)GPTR(begin);
    uint32_t total = end - begin, path = 0;
    while (path < total && text[path] != '#') ++path;
    const lod_redirect *hit = lod_find(text, path);
    if (!hit) return;
    if (!lod_on) {
        if (lod_trace) void_log("[lod] option off: kept");
        return;
    }
    char full[1024];
    int slash = text[0] == '/' || text[0] == '\\';
    uint32_t length = (uint32_t)snprintf(full, sizeof full, "%s%s%.*s", slash ? "/" : "", hit->full,
                                         (int)(total - path), text + path);
    if (length >= sizeof full) return;
    if (++lod_resolved <= 3 || !(lod_resolved & 63))
        void_log("[lod] %u references resolved to full models (last %s)", lod_resolved, hit->full);
    if ((uint64_t)begin + length < capacity) {
        memcpy(GPTR(begin), full, length);
        MEM8(begin + length) = 0;
        MEM32(string + 4) = begin + length;
        return;
    }
    /* Longer than the storage: the engine's own assign (0x00404150) grows it. */
    uint32_t copy = void_galloc(length + 1);
    if (!copy) return;
    memcpy(GPTR(copy), full, (size_t)length + 1);
    uint32_t eax = g_eax, ecx = g_ecx, edx = g_edx;
    const uint32_t args[2] = { copy, copy + length };
    void_call_guest_this(0x00404150u, string, 2, args);
    g_eax = eax; g_ecx = ecx; g_edx = edx;
    void_gfree(copy);
}
