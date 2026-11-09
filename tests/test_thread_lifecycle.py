"""Execute production thread/TLS teardown, handle retention and create failure."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CreateThread HostCreateThread
#define GetExitCodeThread HostGetExitCodeThread
#include <windows.h>
#undef CreateThread
#undef GetExitCodeThread
#define STATIC_TLS_MODULES 64
#define INLINE_DEPTH 8
#define GUEST_STACK_DEFAULT (1u<<20)
typedef struct void_object {
    int refs,signaled,count;void *data;void (*destroy)(struct void_object *);
} void_object;
typedef struct void_thread {
    uint32_t tib,stack_lo,stack_hi,static_tls,static_tls_alloc[STATIC_TLS_MODULES];
    uint32_t start,param,exit_code,id;int suspended,guest_owned,pt;
    void_object *object;struct void_thread *next_thread;
} void_thread;
typedef int pthread_key_t,pthread_once_t,pthread_attr_t;
typedef void (*d3d_rt_fn)(void *);
static void_thread *all_threads,*t_self;
static int threads_lock,handle_lock,wait_lock,wait_cond;
static pthread_key_t thread_key;
static pthread_once_t thread_key_once;
static void (*native_exit)(void *);
static void *native_value;
static unsigned broadcasts,host_alive,host_freed,guest_alive,vm_alive;
static void *host_allocations[20000];static unsigned host_count;
static void *checked_calloc(size_t n,size_t size) {
    void *p=calloc(n,size);assert(p && host_count<20000);
    host_allocations[host_count++]=p;++host_alive;return p;
}
static void checked_free(void *p) {
    if(!p)return;
    for(unsigned i=host_count;i;--i)if(host_allocations[i-1]==p){
        host_allocations[i-1]=NULL;--host_alive;++host_freed;free(p);return;
    }
    assert(!"untracked or double free");
}
#define free checked_free
static unsigned char guest_live[20000],vm_live[10000];
static unsigned guest_count,vm_count;
static unsigned char *vm_memory;
static uint32_t fail_release;
static unsigned self_error_writes;
static void void_set_last_error(uint32_t error);
static uint32_t guest_new(void) {
    assert(guest_count<20000);guest_live[guest_count]=1;++guest_alive;
    return 0x1000+16*guest_count++;
}
static uint32_t vm_new(void) {
    assert(vm_count<10000);vm_live[vm_count]=1;++vm_alive;
    assert(VirtualAlloc(vm_memory+0x10000*vm_count,4096,MEM_COMMIT,PAGE_READWRITE));
    return 0x100000+0x10000*vm_count++;
}
static void void_gfree(uint32_t p) {
    if(!p)return;
    assert(p>=0x1000 && !(p&15));unsigned i=(p-0x1000)/16;
    assert(i<guest_count && guest_live[i]);guest_live[i]=0;--guest_alive;
}
static int void_vm_free(uint32_t p,uint32_t size,uint32_t flags) {
    assert(p>=0x100000 && !(p&0xffff) && !size && flags==0x8000);
    unsigned i=(p-0x100000)/0x10000;assert(i<vm_count && vm_live[i]);
    if(p==fail_release){fail_release=0;void_set_last_error(8);return 0;}
    DWORD previous;assert(VirtualProtect(vm_memory+0x10000*i,4096,PAGE_NOACCESS,&previous));
    vm_live[i]=0;--vm_alive;return 1;
}
static int pthread_mutex_lock(int *p){assert(!*p);*p=1;return 0;}
static int pthread_mutex_unlock(int *p){assert(*p);*p=0;return 0;}
static int pthread_cond_broadcast(int *p){assert(p==&wait_cond && wait_lock);++broadcasts;return 0;}
static void void_fatal(const char *why,...){fprintf(stderr,"%s\n",why);abort();}
static int pthread_key_create(pthread_key_t *key,void (*cleanup)(void *)) {
    assert(key==&thread_key && !native_exit);native_exit=cleanup;*key=1;return 0;
}
static int pthread_once(pthread_once_t *once,void (*init)(void)) {
    if(!*once){*once=1;init();}return 0;
}
static int pthread_setspecific(pthread_key_t key,void *value){assert(key==1);native_value=value;return 0;}
static uint32_t address_text,host_entry;
static uint8_t *inline_payload[INLINE_DEPTH];
static size_t inline_cap[INLINE_DEPTH];static int inline_depth;
static void thread_native_exit(void *arg);
#include "object_release.h"
#include "cleanup.h"
#include "binding.h"
static void_thread *thread_new(uint32_t stack) {
    (void)stack;void_thread *t=checked_calloc(1,sizeof *t);
    t->tib=vm_new();t->stack_lo=vm_new();t->stack_hi=t->stack_lo+GUEST_STACK_DEFAULT;
    t->static_tls=guest_new();t->static_tls_alloc[0]=guest_new();t->static_tls_alloc[5]=guest_new();
    t->next_thread=all_threads;all_threads=t;return t;
}
static void_object *void_object_new(int kind,size_t size) {
    assert(kind==7 && !size);void_object *o=checked_calloc(1,sizeof *o);o->refs=1;return o;
}
static void_object *new_thread_object(void_thread *t,int refs) {
    void_object *o=void_object_new(7,0);o->refs=refs;o->data=t;o->destroy=thread_object_destroy;
    t->object=o;return o;
}
static void_object *handle_object;
static uint32_t void_handle_new(void_object *o){assert(!handle_object);handle_object=o;return 0x1234;}
static void_object *void_handle_get(uint32_t h,int kind){assert(kind==7);return h==0x1234?handle_object:NULL;}
static int void_handle_close(uint32_t h){assert(h==0x1234 && handle_object);void_object *o=handle_object;handle_object=NULL;void_object_release(o);return 1;}
static void *thread_main(void *p){(void)p;assert(!"failure must not start thread");return NULL;}
static int pthread_attr_init(pthread_attr_t *p){*p=1;return 0;}
static int pthread_attr_setstacksize(pthread_attr_t *p,unsigned n){assert(*p && n==(32u<<20));return 0;}
static int pthread_attr_setdetachstate(pthread_attr_t *p,int state){assert(*p && state==1);return 0;}
static int pthread_attr_destroy(pthread_attr_t *p){assert(*p);*p=0;return 0;}
static int pthread_create(int *pt,const pthread_attr_t *attr,void *(*fn)(void *),void *p){(void)pt;assert(*attr && fn==thread_main && p);return 1;}
static int last_error;
static void void_set_last_error(uint32_t error){
    last_error=(int)error;
    if(t_self){
        assert(t_self->tib>=0x100000);
        unsigned char *tib=vm_memory+0x10000*((t_self->tib-0x100000)/0x10000);
        MEMORY_BASIC_INFORMATION info;
        assert(VirtualQuery(tib,&info,sizeof info)==sizeof info);
        assert(info.Protect==PAGE_READWRITE && "TIB must remain writable while reporting cleanup failure");
        *(uint32_t *)(tib+0x34)=error;++self_error_writes;
    }
}
static uint32_t args[6],scratch[8];
#define MEM32(p) scratch[(p)/4]
#define ARG(i) args[i]
#define WINAPI_EXPORT(dll,name,n) static uint32_t name(void)
#define VOID_OBJ_THREAD 7
#define HOST_STACK_SIZE (32u<<20)
#define PTHREAD_CREATE_DETACHED 1
#define ERROR_NOT_ENOUGH_MEMORY_ 8
#define ERROR_INVALID_HANDLE_ 6
#define VLOG(...) ((void)0)
static int pthread_self(void){return 19;}
static void pin_guest_thread(void){}
#include "create_thread.h"
static void thread_buffers(void) {
    address_text=guest_new();host_entry=guest_new();
    inline_payload[0]=checked_calloc(1,4096);inline_cap[0]=4096;
    inline_payload[7]=checked_calloc(1,128);inline_cap[7]=128;
}
static void exit_bound_thread(void_thread *t) {
    thread_bind(t);assert(native_value==t && t_self==t);
    native_value=NULL;native_exit(t);assert(!t_self);
    assert(!address_text && !host_entry && !inline_depth);
    for(int i=0;i<INLINE_DEPTH;++i)assert(!inline_payload[i] && !inline_cap[i]);
}
int main(void) {
    vm_memory=VirtualAlloc(NULL,sizeof vm_live*0x10000ull,MEM_RESERVE,PAGE_NOACCESS);assert(vm_memory);
    void_thread anchor={0};all_threads=&anchor;
    for(unsigned i=0;i<1024;++i) {
        void_thread *t=thread_new(0);void_object *o=new_thread_object(t,3);
        handle_object=o;args[0]=0x1234;args[1]=4;
        assert(GetExitCodeThread() && MEM32(4)==259);
        t->exit_code=23;thread_buffers();
        void_object_release(o); /* original handle closed, duplicate retained */
        exit_bound_thread(t);
        assert(all_threads==&anchor && !guest_alive && !vm_alive);
        assert(o->refs==1 && o->signaled && o->count==23 && o->data==t);
        assert(GetExitCodeThread() && MEM32(4)==23);
        assert(!t->tib && !t->stack_lo && !t->static_tls && host_alive==2);
        void_handle_close(0x1234);assert(!host_alive);
    }
    void_thread *t=thread_new(0);void_object *o=new_thread_object(t,2);
    void_object_release(o);exit_bound_thread(t);assert(!host_alive && !vm_alive && !guest_alive);
    t=void_thread_self();assert(t->pt==19 && native_value==t && t->object->data==t);
    exit_bound_thread(t); /* real host attachment owns one running reference */
    assert(!host_alive && !vm_alive && !guest_alive && broadcasts==1026);
    for(unsigned failed=0;failed<2;++failed){
        t=thread_new(0);new_thread_object(t,1);
        uint32_t retained=failed?t->tib:t->stack_lo;
        fail_release=retained;unsigned writes=self_error_writes;
        exit_bound_thread(t);
        assert(last_error==8 && self_error_writes==writes+1 && !fail_release);
        assert(all_threads==&anchor && !host_alive && !guest_alive && vm_alive==1);
        assert(vm_live[(retained-0x100000)/0x10000]);
        assert(void_vm_free(retained,0,0x8000) && !vm_alive); /* retry retained reservation outside exit */
    }
    void_thread caller={0};caller.tib=vm_new();t_self=&caller;
    args[1]=GUEST_STACK_DEFAULT;args[2]=0x401000;args[4]=4;
    assert(!CreateThread() && last_error==8 && !handle_object);
    assert(all_threads==&anchor && !host_alive && vm_alive==1 && !guest_alive);
    assert(*(uint32_t *)(vm_memory+0x10000*((caller.tib-0x100000)/0x10000)+0x34)==8);
    t_self=NULL;assert(void_vm_free(caller.tib,0,0x8000) && !vm_alive);
    assert(!threads_lock && !handle_lock && !wait_lock);
    assert(VirtualFree(vm_memory,0,MEM_RELEASE));
    printf("PASS thread lifetime: 1024 TLS/stack/TIB/host cleanup cycles, duplicate handles, close before exit, host attachment, self stack/TIB release failures with protected TIBs, create failure preserves caller TIB (%u host frees)\n",host_freed);
    return 0;
}
'''


class ThreadLifecycleTest(unittest.TestCase):
    def test_teardown_and_failed_start(self):
        threads = (ROOT / "android/host/threads.c").read_text(encoding="utf8")
        network = (ROOT / "android/host/network.c").read_text(encoding="utf8")
        render = (ROOT / "android/host/d3d9_thread.c").read_text(encoding="utf8")
        cleanup = function(network, "void void_network_thread_cleanup(")
        cleanup += function(render, "void d3d_rt_thread_cleanup(")
        cleanup += function(threads, "static void thread_object_destroy(void_object *o) {")
        cleanup += function(threads, "static void thread_storage_release(")
        cleanup += function(threads, "static void thread_native_exit(void *arg)\n{")
        binding = function(threads, "static void thread_key_init(")
        binding += function(threads, "static void thread_bind(")
        compile_probe("thread-lifecycle", HARNESS, {
            "object_release.h": function(threads, "void void_object_release("),
            "cleanup.h": cleanup,
            "binding.h": binding,
            "create_thread.h": function(threads, "void_thread *void_thread_self(")
                               + function(threads, "WINAPI_EXPORT(K32, CreateThread,")
                               + function(threads, "WINAPI_EXPORT(K32, GetExitCodeThread,"),
        })


if __name__ == "__main__":
    unittest.main()
