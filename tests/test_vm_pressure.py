"""Execute VM protection/release failures against a tracked host-page oracle."""
import re
import unittest

from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static unsigned char memory[0x1000000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define VOID_GUEST_SPAN 0x100000000ull
#define GUEST_USER_TOP 0x7FFE0000u
#define GUEST_THUNK_BASE 0x7FF00000u
#define GUEST_THUNK_LIMIT 0x7FFD0000u
#define GUEST_PAGE 0x1000u
#define GUEST_GRANULARITY 0x10000u
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_PRIVATE 1
#define MAP_ANONYMOUS 2
#define MAP_FIXED 4
#define MAP_NORESERVE 8
#define MAP_SHARED 16
#define MAP_FAILED ((void *)-1)
#define MADV_DONTNEED 1
#define _SC_PAGESIZE 1
#define ERROR_INVALID_PARAMETER_ 87u
#define ERROR_INVALID_ADDRESS_ 487u
#define ERROR_NOT_ENOUGH_MEMORY_ 8u
#define ERROR_ACCESS_DENIED_ 5u
typedef int64_t off_t;
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static unsigned char cpu_protect[1u<<20];
static unsigned page_size,protect_calls,fail_protect_at,fail_remap,last_error;
static int vm_locked;
static void void_log(const char *format,...){(void)format;}
static void void_fatal(const char *why,...){fprintf(stderr,"%s\n",why);abort();}
static void void_set_last_error(uint32_t error){assert(!vm_locked);last_error=error;}
static int pthread_mutex_lock(int *p){assert(!*p && !vm_locked);*p=vm_locked=1;return 0;}
static int pthread_mutex_unlock(int *p){assert(*p && vm_locked);*p=vm_locked=0;return 0;}
static long sysconf(int name){assert(name==_SC_PAGESIZE);return page_size;}
static int munmap(void *p,size_t n){(void)p;(void)n;return 0;}
static int mprotect(void *p,size_t n,int prot) {
    uint32_t address=(uint32_t)((unsigned char *)p-memory);
    assert(!(address%page_size) && !(n%page_size));++protect_calls;
    unsigned pages=(unsigned)(n/4096),first=address/4096;
    if(protect_calls==fail_protect_at){
        /* An OS failure may leave part of even the failed run changed. */
        for(unsigned i=0;i<page_size/4096 && i<pages;++i)cpu_protect[first+i]=(unsigned char)prot;
        errno=ENOMEM;return -1;
    }
    memset(cpu_protect+first,prot,pages);return 0;
}
static void *mmap(void *p,size_t n,int prot,int flags,int fd,off_t offset) {
    (void)fd;(void)offset;assert(prot==PROT_NONE);
    if(!(flags&MAP_FIXED)){assert(p==memory && n==VOID_GUEST_SPAN);return p;}
    if(fail_remap){--fail_remap;errno=ENOMEM;return MAP_FAILED;}
    uint32_t address=(uint32_t)((unsigned char *)p-memory);
    size_t rounded=(n+page_size-1)&~(size_t)(page_size-1);
    assert((uint64_t)address+rounded<=sizeof memory);
    memset(p,0,rounded);memset(cpu_protect+address/4096,0,rounded/4096);return p;
}
static int madvise(void *p,size_t n,int advice){assert(advice==MADV_DONTNEED);memset(p,0,n);return 0;}
int void_vm_free(uint32_t address,uint32_t size,uint32_t type);
int void_vm_writable(uint32_t address,uint32_t size);
#include "vm_actual.h"
static void check_host_map(uint32_t address,uint32_t size) {
    for(uint32_t page=address/4096;page<(address+size)/4096;++page)
        assert(cpu_protect[page]==host_page_prot(page,PAGES,PAGES,0));
}
static void check_protection_failure(void) {
    const uint32_t address=0x300000;
    assert(void_vm_alloc(address,0x10000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_)==address);
    uint32_t old;
    assert(void_vm_protect(address,4096,PAGE_READONLY_,&old));
    unsigned char before[0x10000];memset(GPTR(address),0xA5,sizeof before);memcpy(before,GPTR(address),sizeof before);
    protect_calls=0;fail_protect_at=page_size==16384?2:1;
    assert(!void_vm_protect(address+4096,8*4096,PAGE_READONLY_,&old));
    assert(last_error==ERROR_INVALID_PARAMETER_ && protect_calls>fail_protect_at);
    assert(page_protect[address/4096]==PAGE_READONLY_);
    for(unsigned i=1;i<16;++i)assert(page_protect[address/4096+i]==PAGE_READWRITE_);
    assert(!memcmp(before,GPTR(address),sizeof before));check_host_map(address,0x10000);
    fail_protect_at=0;assert(void_vm_free(address,0,MEM_RELEASE_));
    assert(void_vm_alloc(address,0x10000,MEM_RESERVE_,PAGE_READWRITE_)==address);
    assert(void_vm_alloc(address+9*4096,4096,MEM_COMMIT_,PAGE_READWRITE_)==address+9*4096);
    MEM32(address+9*4096)=0x12345678;
    protect_calls=0;fail_protect_at=page_size==16384?2:1;
    assert(!void_vm_alloc(address+4096,8*4096,MEM_COMMIT_,PAGE_READONLY_));
    assert(protect_calls>fail_protect_at && MEM32(address+9*4096)==0x12345678);
    for(unsigned i=1;i<=8;++i)assert(page_state[address/4096+i]==ST_RESERVE);
    check_host_map(address,0x10000);fail_protect_at=0;
    assert(void_vm_free(address,0,MEM_RELEASE_));
}
static void check_release_failure(void) {
    const uint32_t address=0x400000;
    uint32_t available=void_vm_available();
    assert(void_vm_alloc(address,0x10000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_)==address);
    MEM32(address)=0x89ABCDEF;fail_remap=1;
    assert(!void_vm_free(address,0,MEM_RELEASE_) && last_error==ERROR_NOT_ENOUGH_MEMORY_);
    assert(void_vm_available()==available-0x10000 && page_state[address/4096]==ST_COMMIT);
    assert(page_alloc[address/4096]==address/4096 && granule_used[address/0x10000]);
    assert(MEM32(address)==0x89ABCDEF && void_vm_writable(address,4));check_host_map(address,0x10000);
    assert(void_vm_free(address,0,MEM_RELEASE_) && void_vm_available()==available);
    assert(!MEM32(address));check_host_map(address,0x10000);
}
static void check_failed_commit_release(void) {
    for(unsigned claim=0;claim<2;++claim){
        uint32_t address=0x500000+claim*0x10000,available=void_vm_available();
        protect_calls=0;fail_protect_at=1;fail_remap=1;
        if(claim)assert(!void_vm_claim(address,0x10000,PAGE_READWRITE_));
        else assert(!void_vm_alloc(address,0x10000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_));
        assert(page_state[address/4096]==ST_RESERVE && granule_used[address/0x10000]);
        assert(void_vm_available()==available-0x10000);check_host_map(address,0x10000);
        fail_protect_at=0;
        assert(!void_vm_alloc(address,0x10000,MEM_RESERVE_,PAGE_READWRITE_));
        assert(void_vm_free(address,0,MEM_RELEASE_) && void_vm_available()==available);
    }
}
int main(void) {
    for(unsigned mode=0;mode<2;++mode){
        page_size=mode?16384:4096;
        memset(page_state,0,sizeof page_state);memset(page_protect,0,sizeof page_protect);
        memset(page_alloc,0,sizeof page_alloc);memset(granule_used,0,sizeof granule_used);
        memset(cpu_protect,0,sizeof cpu_protect);protect_calls=fail_protect_at=fail_remap=0;
        assert(void_guest_reserve());uint32_t available=void_vm_available();
        check_protection_failure();check_release_failure();check_failed_commit_release();
        assert(void_vm_available()==available && !vm_locked);
    }
    puts("PASS VM pressure: 4/16-KiB host pages, later/partially failed mprotect rollback with content preservation, existing-reservation commit rollback, failed remap preserves live/reserved metadata and retry succeeds");
    return 0;
}
'''


class VmPressureTest(unittest.TestCase):
    def test_failed_protection_and_release(self):
        source = (ROOT / "android/host/memory.c").read_text(encoding="utf8")
        start = source.index("#define PAGES")
        end = re.search(r"/\*\s*-+\s*heaps\s*\*/", source).start()
        vm = re.sub(r"^#include .*\n", "", source[start:end], flags=re.M)
        compile_probe("vm-pressure", HARNESS, {"vm_actual.h": vm})


if __name__ == "__main__":
    unittest.main()
