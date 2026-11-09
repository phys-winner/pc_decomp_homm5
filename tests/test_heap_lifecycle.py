"""Execute production heap-handle lifecycle with a bounded mspace oracle."""
import unittest

from test_static_tls import ROOT, compile_probe
from test_mmx_packed import CLANG


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x20000];
#define GPTR(p) (memory+(uint32_t)(p))
#define GVA(p) ((uint32_t)((unsigned char *)(p)-memory))
#define MEM32(p) (*(uint32_t *)GPTR(p))
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int locked;
static int pthread_mutex_lock(pthread_mutex_t *p){assert(!*p);*p=1;++locked;return 0;}
static int pthread_mutex_unlock(pthread_mutex_t *p){assert(*p && locked);*p=0;--locked;return 0;}
typedef struct {int alive,descriptor;} mock_space;
typedef mock_space *mspace;
static mock_space spaces[256];
static unsigned live_spaces,creates,destroys;
static int fail_create,fail_descriptor;
static mspace create_mspace(size_t initial,int locks) {
    assert(locked && !initial && locks==1);++creates;
    if(fail_create){fail_create=0;return NULL;}
    for(unsigned i=0;i<256;++i)if(!spaces[i].alive){
        spaces[i].alive=1;spaces[i].descriptor=0;++live_spaces;return &spaces[i];
    }
    assert(!"mspace leak");return NULL;
}
static int mspace_track_large_chunks(mspace space,int enable) {
    assert(locked && space->alive && enable==1);return 0;
}
static void *mspace_calloc(mspace space,size_t count,size_t size) {
    assert(locked && space->alive && !space->descriptor && count==1 && size==64);
    if(fail_descriptor){fail_descriptor=0;return NULL;}
    space->descriptor=1;
    unsigned index=(unsigned)(space-spaces);uint32_t address=0x10000+64*index;
    memset(GPTR(address),0,64);return GPTR(address);
}
static size_t destroy_mspace(mspace space) {
    assert(locked && space->alive);space->alive=space->descriptor=0;
    --live_spaces;++destroys;return 64;
}
#include "heaps_actual.h"
int main(void) {
    fail_create=1;assert(!void_heap_create(0,0) && !heap_count && !live_spaces);
    fail_descriptor=1;assert(!void_heap_create(0,0) && !heap_count && !live_spaces && destroys==1);
    uint32_t process=void_process_heap();assert(process && heap_count==1 && live_spaces==1);
    assert(void_process_heap()==process && !void_heap_destroy(process));
    for(unsigned i=0;i<4096;++i){
        uint32_t handle=void_heap_create(0,0);
        assert(handle && handle!=process && MEM32(handle)==0xEEFFEEFF && heap_space(handle));
        assert(void_heap_destroy(handle) && !heap_space(handle));
        assert(!void_heap_destroy(handle) && heap_count==2 && live_spaces==1);
    }
    uint32_t handles[255];
    for(unsigned i=0;i<255;++i){handles[i]=void_heap_create(0,0);assert(handles[i]);}
    assert(live_spaces==256 && heap_count==256);
    unsigned before=creates;assert(!void_heap_create(0,0) && creates==before);
    for(unsigned i=0;i<255;i+=2)assert(void_heap_destroy(handles[i]));
    unsigned expected=live_spaces;
    fail_descriptor=1;assert(!void_heap_create(0,0) && live_spaces==expected && heap_count==256);
    for(unsigned i=0;i<255;i+=2){handles[i]=void_heap_create(0,0);assert(handles[i]);}
    assert(live_spaces==256 && !void_heap_create(0,0));
    for(unsigned i=0;i<255;++i)assert(void_heap_destroy(handles[i]));
    assert(live_spaces==1 && !locked && heap_space(process));
    printf("PASS heap lifetime: 4096 create/destroy cycles, 256 simultaneous slots, reuse under saturation, process heap protected, mspace/descriptor OOM rollback (%u creates/%u destroys)\n",creates,destroys);
    return 0;
}
'''


class HeapLifecycleTest(unittest.TestCase):
    def helpers(self):
        source = (ROOT / "android/host/memory.c").read_text(encoding="utf8")
        start = source.index("#define MAX_HEAPS")
        end = source.index("uint32_t void_heap_alloc(", start)
        return source[start:end]

    def test_reuse_and_creation_rollback(self):
        compile_probe("heap-lifecycle", HARNESS, {"heaps_actual.h": self.helpers()}, compiler_override=CLANG)

    def test_concurrent_process_init_and_custom_heap_reuse(self):
        source = HARNESS[:HARNESS.index("int main(void)")]
        source = '#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#undef GPTR\n' + source
        old = '''typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int locked;
static int pthread_mutex_lock(pthread_mutex_t *p){assert(!*p);*p=1;++locked;return 0;}
static int pthread_mutex_unlock(pthread_mutex_t *p){assert(*p && locked);*p=0;--locked;return 0;}'''
        replacement = r'''
typedef struct {INIT_ONCE once;CRITICAL_SECTION lock;} pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER {INIT_ONCE_STATIC_INIT,{0}}
static volatile LONG locked,measuring,measured_locks;
static BOOL CALLBACK lock_init(PINIT_ONCE once,PVOID parameter,PVOID *context){
    (void)once;(void)context;InitializeCriticalSection(&((pthread_mutex_t *)parameter)->lock);return TRUE;
}
static int pthread_mutex_lock(pthread_mutex_t *p){
    assert(InitOnceExecuteOnce(&p->once,lock_init,p,NULL));EnterCriticalSection(&p->lock);
    InterlockedIncrement(&locked);if(measuring)InterlockedIncrement(&measured_locks);return 0;
}
static int pthread_mutex_unlock(pthread_mutex_t *p){
    assert(locked>0);InterlockedDecrement(&locked);LeaveCriticalSection(&p->lock);return 0;
}
'''
        self.assertIn(old, source)
        source = source.replace(old, replacement)
        source += r'''
static HANDLE start_event;
static DWORD WINAPI heap_worker(void *unused){
    (void)unused;assert(WaitForSingleObject(start_event,INFINITE)==WAIT_OBJECT_0);
    uint32_t process=void_process_heap();assert(process);
    for(unsigned i=0;i<2000;++i){
        assert(void_process_heap()==process && heap_space(process));
        uint32_t custom=void_heap_create(0,0);assert(custom && custom!=process && heap_space(custom));
        assert(void_heap_destroy(custom));
    }
    return 0;
}
int main(void){
    HANDLE workers[8];start_event=CreateEventA(NULL,TRUE,FALSE,NULL);assert(start_event);
    for(unsigned i=0;i<8;++i){workers[i]=CreateThread(NULL,0,heap_worker,NULL,0,NULL);assert(workers[i]);}
    assert(SetEvent(start_event));
    assert(WaitForMultipleObjects(8,workers,TRUE,INFINITE)==WAIT_OBJECT_0);
    for(unsigned i=0;i<8;++i)assert(CloseHandle(workers[i]));assert(CloseHandle(start_event));
    uint32_t process=void_process_heap();assert(process && live_spaces==1 && creates==16001 && destroys==16000 && heap_count<=9);
    measuring=1;
    for(unsigned i=0;i<10000;++i)assert(void_process_heap()==process && heap_space(process));
    assert(!measured_locks && !locked && !void_heap_destroy(process));
    puts("PASS concurrent heaps: 8 native threads, one process heap, 16000 custom create/lookup/destroy cycles, slot reuse, process lookup/initialization fast path takes no mutex");
    return 0;
}
'''
        compile_probe("heap-concurrent", source, {"heaps_actual.h": self.helpers()}, compiler_override=CLANG)


if __name__ == "__main__":
    unittest.main()
