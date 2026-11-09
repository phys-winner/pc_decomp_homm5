"""Execute the actual startup selection of live and timed native input scripts."""
import json
import re
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body


HARNESS = r'''
#include <assert.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define F_OK 0
#define strdup _strdup
static char data[2048] = DATA_PATH;
static const char *live_env, *timed_env;
static unsigned live_starts, timed_starts, access_calls;
static char *captured_live;
/* EVENT_TYPE */
static script_event *captured_timed;
static const char *void_data_dir(void) { return data; }
static char *fake_getenv(const char *name) {
    assert(!strcmp(name, "VOID_INPUT_LIVE") || !strcmp(name, "VOID_INPUT"));
    return (char *)(!strcmp(name, "VOID_INPUT_LIVE") ? live_env : timed_env);
}
#define getenv fake_getenv
static int counted_access(const char *path, int mode) { ++access_calls; return _access(path, mode); }
#define access counted_access
static void void_log(const char *format, ...) { (void)format; }
static void *live_thread(void *arg) { (void)arg; return NULL; }
static void *script_thread(void *arg) { (void)arg; return NULL; }
static void start_detached(void *(*fn)(void *), void *arg) {
    if (fn == live_thread) { ++live_starts; captured_live = arg; }
    else { assert(fn == script_thread); ++timed_starts; captured_timed = arg; }
}
/* PARSE_LINE */
/* SCRIPT_START */
static void reset(void) {
    free(captured_live); free(captured_timed); captured_live = NULL; captured_timed = NULL;
    live_starts = timed_starts = access_calls = 0; live_env = timed_env = NULL;
}
static void write_file(const char *path, const char *contents) {
    FILE *f = fopen(path, "wb"); assert(f); assert(fputs(contents, f) >= 0); assert(!fclose(f));
}
int main(void) {
    char live[4096], timed[4096];
    snprintf(live, sizeof live, "%s/input.live", data);
    snprintf(timed, sizeof timed, "%s/input.txt", data);
    remove(live); remove(timed);
    void_input_script_start(); assert(!live_starts && !timed_starts && access_calls == 1);
    reset(); write_file(live, "");
    void_input_script_start(); assert(live_starts == 1 && !timed_starts && access_calls == 1);
    assert(captured_live && !strcmp(captured_live, live));
    reset(); live_env = "explicit-live-file-that-does-not-yet-exist";
    void_input_script_start(); assert(live_starts == 1 && !access_calls && !strcmp(captured_live, live_env));
    reset(); live_env = "";
    void_input_script_start(); assert(!live_starts && !access_calls);
    reset(); write_file(timed, "0 key 41\n1 click 10 20\n");
    void_input_script_start(); assert(live_starts == 1 && timed_starts == 1);
    assert(!strcmp(captured_timed[0].action, "key") && captured_timed[0].a == 0x41);
    assert(!strcmp(captured_timed[1].action, "click") && captured_timed[1].a == 10 && captured_timed[1].b == 20);
    assert(!captured_timed[2].action[0]);
    reset(); assert(!remove(live) && !remove(timed));
    memset(data, 'x', sizeof data - 1); data[sizeof data - 1] = 0;
    void_input_script_start(); assert(!live_starts && !access_calls);
    reset();
    puts("PASS native input startup: opt-in file presence, explicit path/empty priority, timed coexistence, bounded fallback path");
    return 0;
}
'''


class InputLiveTest(unittest.TestCase):
    def test_default_presence_and_explicit_environment_priority(self):
        source = (ROOT / "android/host/script.c").read_text(encoding="utf-8")
        event = re.search(r"typedef struct \{[^\n]*\} script_event;", source).group()
        data = ROOT / "build/tests/script_live_start/profile"
        data.mkdir(parents=True, exist_ok=True)
        harness = HARNESS.replace("DATA_PATH", json.dumps(str(data)))
        harness = harness.replace("/* EVENT_TYPE */", event)
        harness = harness.replace("/* PARSE_LINE */", body(source, "static int parse_line("))
        harness = harness.replace("/* SCRIPT_START */", body(source, "void void_input_script_start("))
        compile_probe("script_live_start", harness, {})


if __name__ == "__main__":
    unittest.main()
