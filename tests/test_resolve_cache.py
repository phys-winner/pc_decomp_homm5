"""Execute the production dispatch hit/miss paths, diagnostics and invalidation."""
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define __builtin_expect(x,y) (x)
#ifdef _MSC_VER
#define __attribute__(x)
#endif
#ifndef _WIN32
#define _putenv_s(key,value) setenv(key,value,1)
#endif
typedef void (*void_fn)(void);
typedef void_fn recomp_func_t;
#define GUEST_THUNK_BASE 0x7FF00000u
#define RECOMP_RETADDR 0xDEAD0000u
#define MAX_THUNKS 16
static unsigned thunk_count = 2;
static int count_thunks = -1, trace_n = -1;
static uint32_t *thunk_calls;
static unsigned wraps, calls;
static uint32_t trace_target;
static jmp_buf trap;
static const char *reason;
static void void_fatal(const char *text) { reason=text; longjmp(trap,1); }
static void void_lift_trap(uint32_t va,const char *text) { (void)va; reason=text; longjmp(trap,1); }
static int in_image(uint32_t va) { return va>=0x400000u && va<0x600000u; }
static void first(void) { calls=1; }
static void second(void) { calls=2; }
static void traced(void) { calls=3; }
static void_fn trace_wrap(uint32_t va,void_fn fn) {
    ++wraps; if(trace_n<0)trace_n=0;
    return trace_n && va==trace_target ? traced : fn;
}
void void_dispatch_add(uint32_t va,void_fn fn);
#include "dispatch.h"
#include "resolve.h"
int main(void) {
    (void)image_lo;(void)image_hi;(void)image_count;
    assert(_putenv_s("VOID_COUNT_THUNKS","")==0);
    void_dispatch_add(0x401000,first);
    assert(void_resolve(0x401000)==first && count_thunks==0 && wraps==1);
    unsigned initial_wraps=wraps;
    for(unsigned i=0;i<10000;++i) { void_resolve(0x401000)(); assert(calls==1); }
    assert(wraps==initial_wraps);
    void_dispatch_add(0x401000,second);
    assert(void_resolve(0x401000)==second);
    uint32_t other=0x401001;
    while(resolve_slot(other)!=resolve_slot(0x401000)) ++other;
    assert(other<0x500000);
    void_dispatch_add(other,first);
    for(unsigned i=0;i<1000;++i) {
        assert(void_resolve(other)==first && void_resolve(0x401000)==second);
    }
    trace_n=1;trace_target=0x402000;
    void_dispatch_add(trace_target,first);
    assert(void_resolve(trace_target)==traced);
    initial_wraps=wraps;
    assert(void_resolve(trace_target)==traced && wraps==initial_wraps);
    void_dispatch_add(trace_target,second);
    assert(void_resolve(trace_target)==traced && wraps==initial_wraps+1);
    trace_n=0;
    assert(_putenv_s("VOID_COUNT_THUNKS","1")==0);count_thunks=-1;
    void_dispatch_add(GUEST_THUNK_BASE,first);
    void_dispatch_add(GUEST_THUNK_BASE+16,second);
    for(unsigned i=0;i<23;++i) assert(void_resolve(GUEST_THUNK_BASE)==first);
    for(unsigned i=0;i<7;++i) assert(void_resolve(GUEST_THUNK_BASE+16)==second);
    assert(count_thunks==1 && thunk_calls && thunk_calls[0]==23 && thunk_calls[1]==7);
    assert(void_resolve(0x401000)==second && thunk_calls[0]==23 && thunk_calls[1]==7);
    const uint32_t missing[]={0,0x1234,RECOMP_RETADDR,0x500000,0x600000};
    const char *messages[]={"null or low","null or low","return-address marker","unresolved guest","outside every"};
    for(unsigned i=0;i<5;++i) {
        reason=NULL;
        if(!setjmp(trap)) { void_resolve(missing[i]); assert(!"missing target returned"); }
        assert(reason && strstr(reason,messages[i]));
    }
    if(!setjmp(trap)) { void_dispatch_add(0,first);assert(!"VA zero registered"); }
    assert(strstr(reason,"VA 0"));
    free(thunk_calls);free(table);
    puts("PASS actual resolver: hits, collisions, re-registration, trace wrapping, thunk counting on cached hits and strict traps");
    return 0;
}
'''


def fixture(source):
    start = source.index("typedef struct { uint32_t va; void_fn fn; } slot_t;")
    end = source.index("void void_dispatch_add(uint32_t va, void_fn fn)\n{")
    dispatch = source[start:end] + function(source, "void void_dispatch_add(")
    dispatch += function(source, "void_fn void_dispatch_find(")
    resolve = function(source, "static __attribute__((noinline)) recomp_func_t resolve_slow(")
    resolve += function(source, "recomp_func_t void_resolve(")
    return {"dispatch.h": dispatch, "resolve.h": resolve}


class ResolveCacheTest(unittest.TestCase):
    def test_actual_resolver(self):
        source = (ROOT / "android/host/core.c").read_text()
        compile_probe("resolve_cache", HARNESS, fixture(source))

    def test_negative_controls(self):
        source = (ROOT / "android/host/core.c").read_text()
        invalidation = "resolve_cache[resolve_slot(va)].va = 0;"
        self.assertEqual(source.count(invalidation), 1)
        for name, mutant in (
            ("invalidation", source.replace(invalidation, "(void)va;")),
            ("counting", source.replace("count_thunks == 0, 1", "1, 1")),
        ):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                compile_probe("resolve_cache_negative_" + name, HARNESS, fixture(mutant))


if __name__ == "__main__":
    unittest.main()
