"""Adventure-map LOD -> full model references (android/host/lod_models.c, tools/lod_models.py)."""
import re
import sys
import unittest
from pathlib import Path

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import lod_models  # noqa: E402

TABLE = ROOT / "android/host/lod_models_table.h"
ROW = re.compile(r'^    \{"([^"]*)", "([^"]*)"\},$')


def table_rows(text):
    arrays, current = {}, None
    for line in text.splitlines():
        m = re.match(r"static const lod_redirect lod_(\w+)\[\] = \{", line)
        if m:
            current = arrays.setdefault(m[1], [])
            continue
        m = ROW.match(line)
        if m and current is not None:
            current.append((m[1], m[2]))
    return arrays


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x20000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM8(p) (*(uint8_t*)GPTR(p))
#define MEM32(p) (*(uint32_t*)GPTR(p))
static uint32_t g_eax=0xAAAA,g_ecx=0xCCCC,g_edx=0xDDDD;
static int option=1,logs,assigns;
static uint32_t next_alloc=0x8000,freed;
static int void_vm_readable(uint32_t va,uint32_t size) {return va>=0x100 && (uint64_t)va+size<=sizeof memory;}
static void void_log(const char *format,...) {(void)format;++logs;}
static const char *void_data_dir(void) {return "no-such-userdata";}
static int void_port_lod_fix(void) {return option;}
/* No profile here: the choice is the variable's default. */
static char *void_path_to_host(const char *windows) {(void)windows;return NULL;}
static uint16_t void_ansi_to_u16(uint8_t c) {return c;}
#define strncasecmp _strnicmp
static uint32_t void_galloc(uint32_t size) {uint32_t a=next_alloc;next_alloc+=(size+15)&~15u;return a;}
static void void_gfree(uint32_t va) {freed=va;}
/* The engine's assign 0x00404150 on a {begin, end, capacity} string: grows the storage. */
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int nargs,const uint32_t *args) {
    assert(va==0x00404150u && nargs==2);
    ++assigns;g_eax=g_ecx=g_edx=0;                       /* a guest call clobbers these */
    uint32_t length=args[1]-args[0],buffer=0x4000+0x400*(uint32_t)assigns;
    memcpy(GPTR(buffer),GPTR(args[0]),length);MEM8(buffer+length)=0;
    MEM32(self)=buffer;MEM32(self+4)=buffer+length;MEM32(self+8)=buffer+length+1;
    return self;
}
#include "lod_models_body.h"
static uint32_t make(uint32_t object,uint32_t buffer,const char *text,uint32_t capacity) {
    uint32_t length=(uint32_t)strlen(text);
    memcpy(GPTR(buffer),text,length+1);
    MEM32(object)=buffer;MEM32(object+4)=buffer+length;MEM32(object+8)=buffer+capacity;
    return object;
}
static const char *value(uint32_t object) {
    assert(MEM8(MEM32(object+4))==0);
    return (const char *)GPTR(MEM32(object));
}
int main(void) {
    /* A non-LOD reference is left alone (and costs no lookup). */
    uint32_t s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Peasant.(Model).xdb",64);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant.(Model).xdb") && !lod_references);
    /* Absolute LOD path, other case and slashes: resolved in place, "/" kept. */
    s=make(0x100,0x1000,"/_(Model)/Creatures/HAVEN\\Peasant_LOD.(Model).xdb",64);
    void_lod_reference(s);
    assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant.(Model).xdb") && MEM32(s)==0x1000 && !assigns);
    /* A relative reference arrives joined, without the leading slash. */
    s=make(0x100,0x1000,"Characters/Heroes/Wizard_LOD_White.xdb",64);
    void_lod_reference(s);assert(!strcmp(value(s),"Characters/Heroes/Wizard_White.xdb"));
    /* A longer full path than the storage holds: the engine's assign grows it;
       the registers the following guest call needs are kept. */
    s=make(0x100,0x1000,"/characters/heroes/ilaya_lod.xdb",34);
    void_lod_reference(s);
    assert(assigns==1 && !strcmp(value(s),"/Characters/Heroes/DS/Shadwin_DS_M.xdb") && freed==0x8000);
    assert(g_eax==0xAAAA && g_ecx==0xCCCC && g_edx==0xDDDD);
    /* No table entry: kept. Option off: kept. */
    s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Unknown_LOD.(Model).xdb",64);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Unknown_LOD.(Model).xdb"));
    /* The choice is made once per run (at the first reference), not per reference. */
    option=0;s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Peasant_LOD.(Model).xdb",64);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant.(Model).xdb"));
    lod_on=0;s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Peasant_LOD.(Model).xdb",64);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant_LOD.(Model).xdb"));
    option=1;lod_on=1;
    /* An absolute href keeps its "#xpointer(...)" part (the typed-reference reader's form). */
    s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Peasant_LOD.(Model).xdb#xpointer(/Model)",80);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant.(Model).xdb#xpointer(/Model)"));
    s=make(0x100,0x1000,"/_(Model)/Creatures/Haven/Peasant.(Model).xdb#xpointer(/Peasant_LOD)",80);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(Model)/Creatures/Haven/Peasant.(Model).xdb#xpointer(/Peasant_LOD)"));
    /* Animation sets resolve the same way. */
    s=make(0x100,0x1000,"/_(AnimSet)/Creatures/Academy/MasterGenie_LOD-adv.(AnimSet).xdb",80);
    void_lod_reference(s);assert(!strcmp(value(s),"/_(AnimSet)/Creatures/Academy/MasterGenie-arena.(AnimSet).xdb"));
    /* Unreadable or inconsistent strings are ignored. */
    void_lod_reference(0);void_lod_reference(0x1FFF8);
    MEM32(0x200)=0x1000;MEM32(0x204)=0x0FFF;MEM32(0x208)=0x1100;void_lod_reference(0x200);
    assert(lod_resolved==6 && assigns==1);
    puts("PASS LOD references: non-LOD untouched, case/slash-insensitive lookup, in-place and engine-grown rewrite, option off, unknown kept");
    return 0;
}
'''

TEST_TABLE = r'''
static const lod_redirect lod_toe[] = {
    {"_(animset)/creatures/academy/mastergenie_lod-adv.(animset).xdb", "_(AnimSet)/Creatures/Academy/MasterGenie-arena.(AnimSet).xdb"},
    {"_(model)/creatures/haven/peasant_lod.(model).xdb", "_(Model)/Creatures/Haven/Peasant.(Model).xdb"},
    {"characters/heroes/ilaya_lod.xdb", "Characters/Heroes/DS/Shadwin_DS_M.xdb"},
    {"characters/heroes/wizard_lod_white.xdb", "Characters/Heroes/Wizard_White.xdb"},
};
static const lod_redirect lod_vanilla[] = {{"a_lod", "a"}};
static const lod_redirect lod_hof[] = {{"b_lod", "b"}};
'''


PROFILE_HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define strncasecmp _strnicmp
#define LOD_EDITION EDITION_NAME
static const char *base = FIXTURE_DIR;
static char requests[16][1024];
static int request_count;
/* The host's path translation, onto the fixture folder (ASCII names: the
   UTF-8 profile name and the em dash of the ToE folder are checked, then
   spelled "Igrok" and "-" on this Windows disk). */
static char *void_path_to_host(const char *windows) {
    snprintf(requests[request_count++ & 15], 1024, "%s", windows);
    const char *prefix = "C:\\Users\\Player\\Documents\\";
    assert(!strncmp(windows, prefix, strlen(prefix)));
    char *out = malloc(2048);
    assert(out);
    snprintf(out, 2048, "%s/%s", base, windows + strlen(prefix));
    for (char *p = out; *p; ++p) if (*p == '\\') *p = '/';
    char *at = strstr(out, "\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA");
    if (at) { memmove(at + 5, at + 10, strlen(at + 10) + 1); memcpy(at, "Igrok", 5); }
    at = strstr(out, "\xE2\x80\x94");
    if (at) { memmove(at + 1, at + 3, strlen(at + 3) + 1); *at = '-'; }
    return out;
}
/* STRINGS */
/* PROFILE_BLOCK */
static void put(const char *folder, const char *name, const char *text) {
    char path[1024];
    snprintf(path, sizeof path, "%s/%s/%s", base, folder, name);
    if (!text) { remove(path); return; }
    FILE *file = fopen(path, "wb");
    assert(file);
    fputs(text, file);
    fclose(file);
}
static const char *last(void) { return requests[(request_count - 1) & 15]; }
int main(void) {
    const char *profiles = PROFILES_FOLDER, *global = GLOBAL_NAME, *user = USER_NAME;
    char player[512];
    snprintf(player, sizeof player, "%s/Igrokqa", profiles);
    put(profiles, global, NULL);
    put(player, user, NULL);
    /* No profile chosen yet (first start): no choice, the variable's default applies. */
    assert(lod_profile_choice() == -1 && request_count == 1 && !strcmp(last(), GLOBAL_WINDOWS));
    /* The game's own global file (header comments, CRLF), CP1251 name "Igrok" in Cyrillic. */
    put(profiles, global, "//====\r\n// generated by the game, please do not modify\r\n//====\r\n"
                          "setvar net_game_port = 8888\r\nsetvar profile_name = \xC8\xE3\xF0\xEE\xEAqa\r\n");
    /* A profile that never changed the option has no line (port_lod_fix2 is another name). */
    put(player, user, "setvar adv_camera_mode = 0\r\nsetvar port_lod_fix2 = 0\r\n");
    assert(lod_profile_choice() == -1);
    assert(strstr(last(), "\\\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBAqa\\") && strstr(last(), USER_NAME));
    put(player, user, "setvar adv_camera_mode = 0\r\nsetvar port_lod_fix = 0\r\nsetvar port_fog = 1\r\n");
    assert(lod_profile_choice() == 0);
    /* The last line wins; any letter case and blanks. */
    put(player, user, "setvar port_lod_fix = 0\nSETVAR\tPORT_LOD_FIX\t=\t1.000000\n");
    assert(lod_profile_choice() == 1);
    put(player, user, "setvar port_lod_fix = \"0\"\n");
    assert(lod_profile_choice() == 0);
    put(player, user, "setvar port_lod_fix = off\n");
    assert(lod_profile_choice() == -1);
    /* Java's single-profile seed (LF, no header). */
    put(profiles, global, "setvar profile_name = \xC8\xE3\xF0\xEE\xEAqa\n");
    put(player, user, "setvar port_lod_fix = 0\n");
    assert(lod_profile_choice() == 0);
    /* The selected profile has no folder: no choice. */
    put(profiles, global, "setvar profile_name = Nobody\n");
    assert(lod_profile_choice() == -1);
    put(profiles, global, "setvar profile_name =\n");
    assert(lod_profile_choice() == -1);
    char value[8];
    assert(!lod_cfg_value("setvar port_lod_fix = 123456789", 31, "port_lod_fix", value, sizeof value));
    assert(lod_cfg_value("setvar a = 1\nsetvar b = 2\n", 26, "b", value, sizeof value) && !strcmp(value, "2"));
    put(profiles, global, NULL);
    put(player, user, NULL);
    printf("PASS LOD profile choice (%s): first start, game and launcher global files, CP1251 name, last line, quotes, case, missing\n", EDITION_NAME);
    return 0;
}
"""

EDITIONS = {
    "toe": ("My Games/Heroes of Might and Magic V - Tribes of the East/Profiles", "_a2",
            "C:\\\\Users\\\\Player\\\\Documents\\\\My Games\\\\Heroes of Might and Magic V \\xE2\\x80\\x94 Tribes of the East\\\\Profiles\\\\global_a2.cfg"),
    "vanilla": ("My Games/Heroes of Might and Magic V/Profiles", "",
                "C:\\\\Users\\\\Player\\\\Documents\\\\My Games\\\\Heroes of Might and Magic V\\\\Profiles\\\\global.cfg"),
    "hof": ("My Games/Heroes of Might and Magic V/Hammers of Fate/Profiles", "_a1",
            "C:\\\\Users\\\\Player\\\\Documents\\\\My Games\\\\Heroes of Might and Magic V\\\\Hammers of Fate\\\\Profiles\\\\global_a1.cfg"),
}


def profile_block():
    source = (ROOT / "android/host/lod_models.c").read_text(encoding="utf-8")
    return source[source.index("/* ---------------------------------------------------- profile choice */"):
                  source.index("/* ---------------------------------------------------- end of profile choice */")]


def strings_block():
    source = (ROOT / "android/host/strings.c").read_text(encoding="utf-8")
    return source[source.index("static const uint16_t cp1251_high[128]"):source.index("int void_u16_to_ansi(")]


def host_body():
    source = (ROOT / "android/host/lod_models.c").read_text(encoding="utf-8")
    for include in ('#include "host.h"\n', "#include <stdlib.h>\n", "#include <string.h>\n", "#include <strings.h>\n"):
        assert include in source, include
        source = source.replace(include, "", 1)
    return source.replace("int void_port_lod_fix(void);\n", "")


class LodModelsTest(unittest.TestCase):
    def test_reference_rewrite(self):
        compile_probe("lod-models", HARNESS, {"lod_models_body.h": host_body(), "lod_models_table.h": TEST_TABLE})

    def test_profile_choice(self):
        """The hero and creature records are read before the profile applies: the choice comes from the profile files."""
        for edition, (folder, suffix, global_windows) in EDITIONS.items():
            with self.subTest(edition=edition):
                base = ROOT / "build/tests" / ("lod-profile-" + edition) / "data"
                (base / folder / "Igrokqa").mkdir(parents=True, exist_ok=True)
                harness = (PROFILE_HARNESS.replace("EDITION_NAME", '"%s"' % edition)
                           .replace("FIXTURE_DIR", '"%s"' % base.as_posix())
                           .replace("PROFILES_FOLDER", '"%s"' % folder)
                           .replace("GLOBAL_NAME", '"global%s.cfg"' % suffix)
                           .replace("USER_NAME", '"user%s.cfg"' % suffix)
                           .replace("GLOBAL_WINDOWS", '"%s"' % global_windows)
                           .replace("/* STRINGS */", strings_block())
                           .replace("/* PROFILE_BLOCK */", profile_block()))
                compile_probe("lod-profile-" + edition, harness, {})

    def test_generated_table_compiles(self):
        harness = HARNESS[:HARNESS.index("static uint32_t make(")] + r'''
int main(void) {
    lod_init();
    assert(lod_table==lod_toe && lod_count==sizeof lod_toe/sizeof *lod_toe && lod_count>100);
    for(size_t i=1;i<lod_count;i++) assert(strcmp(lod_table[i-1].lod,lod_table[i].lod)<0);
    puts("PASS generated LOD table: sorted unique keys for bsearch");
    return 0;
}
'''
        compile_probe("lod-models-table", harness, {"lod_models_body.h": host_body(),
                                                     "lod_models_table.h": TABLE.read_text(encoding="utf-8")})

    def test_table_shape(self):
        arrays = table_rows(TABLE.read_text(encoding="utf-8"))
        self.assertEqual(set(arrays), {"toe", "vanilla", "hof"})
        for edition, rows in arrays.items():
            keys = [k for k, _ in rows]
            self.assertGreater(len(rows), 100, edition)
            self.assertEqual(keys, sorted(keys, key=lambda k: k.encode()), edition)
            self.assertEqual(len(keys), len(set(keys)), edition)
            for lod, full in rows:
                self.assertEqual(lod, lod.lower())
                self.assertFalse(lod.startswith("/") or full.startswith("/"))
                self.assertIn("_lod", lod)
                self.assertNotIn("_lod", full.lower().rsplit("/", 1)[-1], (edition, lod, full))
            # The generic knight and RuneMage keep their adventure models (see KEEP).
            self.assertNotIn("_(model)/heroes/knight_lod.(model).xdb", keys)
            self.assertFalse(any(k.startswith("characters/heroes/runemage-model-lod") for k in keys))

    def test_rules_on_synthetic_records(self):
        self.assertEqual(lod_models.stem("_(Model)/Creatures/Haven/Peasant_LOD.(Model).xdb"), "peasant")
        self.assertEqual(lod_models.stem("Characters/Creatures/Preserve/BladeJuggler_LOD_.xdb"), "bladejuggler")
        self.assertEqual(lod_models.stem("_(Model)/Creatures/Preserve/Unicorn_LOD______6596.(Model).xdb"), "unicorn")
        self.assertEqual(lod_models.choose("x/Peasant_LOD.xdb", {"y/Wolf.xdb", "x/Peasant.xdb"}), "x/Peasant.xdb")
        self.assertIsNone(lod_models.choose("x/Peasant_LOD.xdb", {"y/Wolf.xdb", "z/Bear.xdb"}))
        self.assertEqual(lod_models.resolve("Characters/Heroes/Duncan_LOD.(Character).xdb", "Duncan_LOD.xdb#xpointer(/Model)"),
                         "Characters/Heroes/Duncan_LOD.xdb")
        self.assertEqual(lod_models.resolve("a/b.xdb", "/_(Model)/C/D.xdb#xpointer(/Model)"), "_(Model)/C/D.xdb")

    def test_committed_table_matches_the_game_data(self):
        try:
            tables = {}
            for edition in lod_models.EDITIONS:
                archives = lod_models.archives(edition, lod_models.game_directory(edition))
                if not archives:
                    raise FileNotFoundError(edition)
                tables[edition] = lod_models.build(lod_models.Data(archives))
        except (FileNotFoundError, ValueError, OSError) as missing:
            self.skipTest("game data not available: " + str(missing))
        self.assertEqual(lod_models.c_table(tables), TABLE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
