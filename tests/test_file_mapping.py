"""Execute the actual mapping API body; verify shared/COW/read-copy results on a real file."""
import json
import re
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

HARNESS = r'''
#include <windows.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <io.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
typedef SSIZE_T ssize_t;
static uint32_t args[5],last_error;
#define ARG(i) args[i]
#define WINAPI_EXPORT(dll,name,nargs) uint32_t name##_impl(void)
#define ERROR_INVALID_HANDLE_ 6u
#define ERROR_INVALID_PARAMETER_ 87u
#define VOID_OBJ_MAPPING 5
#define VLOG(...) ((void)0)
#define __ATOMIC_ACQUIRE 2
#define __ATOMIC_RELEASE 3
#define __atomic_load_n(p, order) (*(p))
#define __atomic_store_n(p, value, order) (*(p) = (value))
static int archive_cache_disabled;
#define ARCHIVE_READ_AHEAD 65536u
/* ACTUAL_PERF_KINDS */
/* ACTUAL_MAPPING_TYPE */
typedef struct { void *data; } void_object;
static mapping_t mapping;
static void_object object={&mapping};
static void_object *void_handle_get(uint32_t handle,int type) { assert(type==5);return handle==0x6000?&object:NULL; }
static void void_set_last_error(uint32_t value) { last_error=value; }
/* Host clock: only backend work advances it, so a recorded duration is the
 * work done between the body's two clock reads. */
static uint64_t perf_clock=1000000;
static unsigned perf_calls;
static int perf_kind=-1;
static uint64_t perf_ns,perf_bytes;
static uint64_t void_perf_now_ns(void) { return perf_clock; }
static void void_perf_add(int kind,uint64_t ns,uint64_t bytes) { ++perf_calls;perf_kind=kind;perf_ns=ns;perf_bytes=bytes; }
/* The guest machine lock: released only around the host's file reads. */
static int blocking;
static unsigned blocking_sections;
static int replace_mapping;
static void void_blocking_begin(void) { assert(!blocking);blocking=1;++blocking_sections; }
static void void_blocking_end(void) {
    assert(blocking);blocking=0;
    if(replace_mapping) { ++mapping.identity;mapping.fd=-1;free(mapping.cached);mapping.cached=NULL;replace_mapping=0; }
}
/* Guest window for VirtualAlloc'ed read views. */
#define WINDOW_SIZE (0x200000u+(16u<<20)+0x10000u)
static uint8_t *guest;
#undef GPTR    /* winbase.h: GlobalAlloc flags */
#define GPTR(va) ((void *)(guest+(uint32_t)(va)))
static uint32_t alloc_va,alloc_size;
static unsigned alloc_calls,protect_calls,release_calls;
static int fail_alloc;
static uint32_t void_vm_alloc(uint32_t address,uint32_t size,uint32_t type,uint32_t protect) {
    assert(!blocking&&!alloc_va&&address==0&&type==0x3000u&&protect==0x04u);
    ++alloc_calls;if(fail_alloc)return 0;
    assert(size&&size<=WINDOW_SIZE-0x200000u-0x1000u);
    alloc_va=0x200000;alloc_size=size;
    memset(GPTR(alloc_va),0,size);                  /* fresh committed pages */
    memset((uint8_t *)GPTR(alloc_va)+size,0xCC,0x1000);  /* canary past the view */
    return alloc_va;
}
static int void_vm_protect(uint32_t address,uint32_t size,uint32_t protect,uint32_t *old) {
    assert(!blocking&&address==alloc_va&&size==alloc_size&&protect==0x02u&&old);
    ++protect_calls;*old=0x04u;return 1;
}
/* The view reads through its own descriptor, closed once read. */
static int dup_fd=-1,fail_read;
static unsigned dup_calls,close_calls,free_calls;
static int mock_dup(int fd) { assert(!blocking&&fd==mapping.fd&&dup_fd<0);++dup_calls;dup_fd=_dup(fd);return dup_fd; }
static int mock_close(int fd) { assert(!blocking&&fd==dup_fd);++close_calls;dup_fd=-1;return _close(fd); }
#define dup(fd) mock_dup(fd)
#define close(fd) mock_close(fd)
static int void_vm_free(uint32_t address,uint32_t size,uint32_t type) {
    assert(!blocking&&address==alloc_va&&size==0&&type==0x8000u);++free_calls;alloc_va=0;return 1;
}
/* pread on the real fixture file, with injected EINTR and short reads. */
static unsigned pread_calls,pread_eintr,pread_eof;
static size_t pread_chunk;
static int fail_cache_alloc;
static void *cache_malloc(size_t size) { return fail_cache_alloc ? NULL : malloc(size); }
static void *freed_cache;
static void counted_free(void *pointer) { freed_cache=pointer;free(pointer); }
static ssize_t pread(int fd,void *buffer,size_t count,off_t offset) {
    assert(blocking&&fd==dup_fd&&fd!=mapping.fd&&alloc_va&&offset>=0&&count);
    if(fail_read) { errno=EIO;return -1; }
    if((uintptr_t)buffer>=(uintptr_t)guest&&(uintptr_t)buffer<(uintptr_t)guest+WINDOW_SIZE)
        assert((uint8_t *)buffer>=(uint8_t *)GPTR(alloc_va)&&(uint8_t *)buffer+count<=(uint8_t *)GPTR(alloc_va)+alloc_size);
    else assert(mapping.archive&&count<=ARCHIVE_READ_AHEAD);
    ++pread_calls;perf_clock+=1000;
    if(pread_eintr) { --pread_eintr;errno=EINTR;return -1; }
    if(pread_chunk&&count>pread_chunk)count=pread_chunk;
    assert(_lseeki64(fd,offset,SEEK_SET)==offset);
    int got=_read(fd,buffer,(unsigned)count);assert(got>=0);
    pread_eof+=!got;return got;
}
static void *view;
static int seen_writable,seen_shared;
static unsigned backend_calls;
/* Native Windows mapping supplies the POSIX backend's shared/private contract
 * while the access classification is the unmodified actual Android API body. */
static uint32_t void_vm_map_file(int fd,uint64_t offset,uint32_t size,int writable,int shared) {
    assert(!view&&!blocking);++backend_calls;seen_writable=writable!=0;seen_shared=shared!=0;perf_clock+=7000;
    HANDLE section=CreateFileMappingW((HANDLE)_get_osfhandle(fd),NULL,writable?PAGE_READWRITE:PAGE_READONLY,0,0,NULL);
    assert(section);
    view=MapViewOfFile(section,writable?(shared?FILE_MAP_WRITE:FILE_MAP_COPY):FILE_MAP_READ,
        (DWORD)(offset>>32),(DWORD)offset,size);
    assert(view);assert(CloseHandle(section));return 0x10000;
}
static int void_vm_unmap_file(uint32_t address) {
    if(alloc_va&&address==alloc_va) { alloc_va=0;++release_calls;return 1; }
    assert(address==0x10000&&view);
    if(seen_shared&&seen_writable)assert(FlushViewOfFile(view,0));
    assert(UnmapViewOfFile(view));view=NULL;return 1;
}
#define malloc cache_malloc
/* ACTUAL_BODIES */
#undef malloc
static uint8_t file_bytes[3*65536];
/* A read-only view of a read-only mapping: one guest allocation filled by
 * pread with the machine released, then protected read-only. */
static void read_view(uint32_t access,uint32_t offset,uint32_t size,uint32_t expected_size,unsigned eof_reads) {
    unsigned allocs=alloc_calls,backend=backend_calls,sections=blocking_sections,reads=pread_calls,protects=protect_calls;
    unsigned perfs=perf_calls,eofs=pread_eof;uint64_t clock=perf_clock;
    args[0]=0x6000;args[1]=access;args[2]=0;args[3]=offset;args[4]=size;
    assert(MapViewOfFile_impl()==0x200000&&!blocking);
    assert(alloc_calls==allocs+1&&alloc_size==expected_size&&backend_calls==backend&&!view);
    assert(blocking_sections==sections+1&&pread_calls>reads&&protect_calls==protects+1&&pread_eof==eofs+eof_reads);
    assert(perf_calls==perfs+1&&perf_kind==VOID_PERF_FILE_MAP&&perf_bytes==expected_size);
    assert(perf_ns==perf_clock-clock&&perf_ns==1000ull*(pread_calls-reads));
    /* File bytes at the window's offset; zero past the fixture pattern and past EOF. */
    const uint8_t *data=(const uint8_t *)GPTR(0x200000);
    for(size_t i=0;i<expected_size;++i) {
        size_t at=offset+i;
        assert(data[i]==(at<sizeof file_bytes?file_bytes[at]:0));
    }
    for(size_t i=0;i<0x1000;++i)assert(data[expected_size+i]==0xCC);
    unsigned releases=release_calls;args[0]=0x200000;
    assert(UnmapViewOfFile_impl()==1&&release_calls==releases+1&&!alloc_va);
}
int main(void) {
    guest=(uint8_t *)VirtualAlloc(NULL,WINDOW_SIZE,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);assert(guest);
    int fd=_open(FIXTURE_PATH,_O_BINARY|_O_RDWR|_O_CREAT|_O_TRUNC,_S_IREAD|_S_IWRITE);assert(fd>=0);
    static uint8_t zero[65536],observed[8193],pattern[8193];
    for(unsigned i=0;i<sizeof pattern;++i)pattern[i]=(uint8_t)(i%251+1);
    mapping=(mapping_t){fd,sizeof zero,PAGE_READWRITE};
    const uint32_t access[]={FILE_MAP_ALL_ACCESS,FILE_MAP_WRITE,FILE_MAP_READ|FILE_MAP_WRITE,FILE_MAP_COPY,FILE_MAP_COPY|FILE_MAP_READ};
    for(unsigned i=0;i<sizeof access/sizeof access[0];++i) {
        assert(_lseek(fd,0,SEEK_SET)==0&&_write(fd,zero,sizeof zero)==sizeof zero);
        args[0]=0x6000;args[1]=access[i];args[2]=0;args[3]=0;args[4]=0;
        unsigned perfs=perf_calls;
        assert(MapViewOfFile_impl()==0x10000&&seen_writable);
        assert(perf_calls==perfs+1&&perf_kind==VOID_PERF_FILE_MAP&&perf_bytes==sizeof zero&&perf_ns==7000);
        assert(seen_shared==(i<3));memcpy((uint8_t *)view+317,pattern,sizeof pattern);
        args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
        assert(_lseek(fd,317,SEEK_SET)==317&&_read(fd,observed,sizeof observed)==sizeof observed);
        assert(!memcmp(observed,i<3?pattern:zero,sizeof observed));
    }
    /* A read view of a writable mapping stays a shared file mapping. */
    args[0]=0x6000;args[1]=FILE_MAP_READ;args[2]=0;args[3]=0;args[4]=0;
    assert(MapViewOfFile_impl()==0x10000&&!seen_writable&&seen_shared&&!alloc_calls);
    assert(!memcmp(view,zero,sizeof zero));args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
    unsigned before=backend_calls,perfs=perf_calls;
    args[0]=0;assert(MapViewOfFile_impl()==0&&last_error==6&&backend_calls==before);
    args[0]=0x6000;args[3]=65537;assert(MapViewOfFile_impl()==0&&last_error==87&&backend_calls==before);
    args[3]=0;mapping.size=0;assert(MapViewOfFile_impl()==0&&last_error==87&&backend_calls==before);
    assert(perf_calls==perfs&&!alloc_calls&&!blocking_sections);
    /* Read-only (archive) mappings: read windows are copied, not mapped. */
    for(unsigned i=0;i<sizeof file_bytes;++i)file_bytes[i]=(uint8_t)(i*131u+i/65536u+7u);
    assert(_lseek(fd,0,SEEK_SET)==0&&_write(fd,file_bytes,sizeof file_bytes)==sizeof file_bytes);
    assert(_chsize_s(fd,sizeof file_bytes)==0);
    mapping=(mapping_t){fd,sizeof file_bytes+4096+123,PAGE_READONLY};
    pread_eintr=2;pread_chunk=4093;     /* FUSE: interrupted and short reads; the view outlasts the file */
    read_view(FILE_MAP_READ,0x10000,0,(uint32_t)mapping.size-0x10000,1);
    assert(!pread_eintr&&pread_calls>=2+131072/4093+1);
    pread_chunk=0;mapping.protect=PAGE_READONLY|SEC_COMMIT;   /* section flags do not matter */
    read_view(FILE_MAP_READ,0x10000,0x10000,0x10000,0);
    mapping.protect=PAGE_READONLY;
    /* Writable requests on a read-only mapping keep the private file mapping. */
    mapping.size=sizeof file_bytes;before=backend_calls;unsigned allocs=alloc_calls;
    args[0]=0x6000;args[1]=FILE_MAP_COPY;args[2]=0;args[3]=0;args[4]=0;
    assert(MapViewOfFile_impl()==0x10000&&backend_calls==before+1&&seen_writable&&!seen_shared&&alloc_calls==allocs);
    assert(!memcmp(view,file_bytes,sizeof file_bytes));args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
    /* No guest memory for the copy: the read-only file mapping is the fallback. */
    fail_alloc=1;unsigned sections=blocking_sections,reads=pread_calls,protects=protect_calls;
    args[0]=0x6000;args[1]=FILE_MAP_READ;
    assert(MapViewOfFile_impl()==0x10000&&backend_calls==before+2&&alloc_calls==allocs+1&&!seen_writable&&seen_shared);
    assert(blocking_sections==sections&&pread_calls==reads&&protect_calls==protects&&perf_ns==7000&&perf_bytes==sizeof file_bytes);
    assert(!memcmp(view,file_bytes,sizeof file_bytes));args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
    fail_alloc=0;
    /* A read error is not data: the copy is released and the file mapping answers. */
    fail_read=1;unsigned frees=free_calls,dups=dup_calls,closes=close_calls;
    args[0]=0x6000;args[1]=FILE_MAP_READ;args[2]=0;args[3]=0;args[4]=0;
    assert(MapViewOfFile_impl()==0x10000&&backend_calls==before+3&&free_calls==frees+1&&!alloc_va);
    assert(dup_calls==dups+1&&close_calls==closes+1&&dup_fd<0&&!memcmp(view,file_bytes,sizeof file_bytes));
    args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
    fail_read=0;
    /* 16 MiB is the largest copied window; anything larger is mapped. */
    assert(_chsize_s(fd,(16<<20)+65536)==0);
    mapping.size=(16u<<20)+65536;
    read_view(FILE_MAP_READ,0,16u<<20,16u<<20,0);
    allocs=alloc_calls;
    args[0]=0x6000;args[1]=FILE_MAP_READ;args[2]=0;args[3]=0;args[4]=(16u<<20)+1;
    assert(MapViewOfFile_impl()==0x10000&&backend_calls==before+4&&alloc_calls==allocs&&!seen_writable&&seen_shared);
    assert(perf_bytes==(16u<<20)+1&&!memcmp(view,file_bytes,sizeof file_bytes));
    args[0]=0x10000;assert(UnmapViewOfFile_impl()==1);
    assert(dup_calls==close_calls&&dup_fd<0);
    /* Cache allocation failure retains the original copied view. */
    mapping=(mapping_t){fd,sizeof file_bytes,PAGE_READONLY,1,122};fail_cache_alloc=1;
    args[0]=0x6000;args[1]=FILE_MAP_READ;args[2]=0;args[3]=0;args[4]=1024;
    assert(MapViewOfFile_impl()==0x200000&&!mapping.cached&&!memcmp(GPTR(alloc_va),file_bytes,1024));
    args[0]=alloc_va;assert(UnmapViewOfFile_impl());fail_cache_alloc=0;
    /* Two overlapping archive windows need one64KiB read, with no handoff on hit. */
    mapping=(mapping_t){fd,sizeof file_bytes,PAGE_READONLY,1,123};
    args[0]=0x6000;args[1]=FILE_MAP_READ;args[2]=0;args[3]=0x10000;args[4]=2048;
    sections=blocking_sections;reads=pread_calls;dups=dup_calls;
    assert(MapViewOfFile_impl()==0x200000&&mapping.cached_size==ARCHIVE_READ_AHEAD);
    assert(mapping.cached_offset==0x10000&&blocking_sections==sections+1&&pread_calls==reads+1);
    assert(!memcmp(GPTR(alloc_va),file_bytes+0x10000,2048));args[0]=alloc_va;assert(UnmapViewOfFile_impl());
    args[0]=0x6000;args[3]=0x10000+123;args[4]=48000;
    assert(MapViewOfFile_impl()==0x200000&&blocking_sections==sections+1&&pread_calls==reads+1&&dup_calls==dups+1);
    assert(!memcmp(GPTR(alloc_va),file_bytes+0x10000+123,48000));args[0]=alloc_va;assert(UnmapViewOfFile_impl());
    /* Cache cannot serve past its end; replacement is separate from guest views. */
    args[0]=0x6000;args[3]=0x20000;args[4]=4096;
    assert(MapViewOfFile_impl()==0x200000&&mapping.cached_offset==0x20000&&blocking_sections==sections+2);
    assert(!memcmp(GPTR(alloc_va),file_bytes+0x20000,4096));args[0]=alloc_va;assert(UnmapViewOfFile_impl());
    /* A mapping closed/reused during a read receives no cached bytes; the view survives. */
    args[0]=0x6000;args[3]=0;args[4]=1024;replace_mapping=1;
    assert(MapViewOfFile_impl()==0x200000&&!mapping.cached&&mapping.fd==-1);
    assert(!memcmp(GPTR(alloc_va),file_bytes,1024));args[0]=alloc_va;assert(UnmapViewOfFile_impl());mapping.fd=fd;
    /* Close during a failed read still falls back using the owned descriptor. */
    args[0]=0x6000;args[3]=0;args[4]=1024;replace_mapping=1;fail_read=1;
    assert(MapViewOfFile_impl()==0x10000&&!mapping.cached&&mapping.fd==-1);
    assert(!memcmp(view,file_bytes,1024));args[0]=0x10000;assert(UnmapViewOfFile_impl());mapping.fd=fd;fail_read=0;
    /* A writer opts out permanently: a cached block cannot hide changed data. */
    args[0]=0x6000;args[3]=0;args[4]=1024;assert(MapViewOfFile_impl()==0x200000&&mapping.cached);
    args[0]=alloc_va;assert(UnmapViewOfFile_impl());archive_cache_disabled=1;
    file_bytes[317]^=255;assert(_lseek(fd,317,SEEK_SET)==317&&_write(fd,file_bytes+317,1)==1);
    args[0]=0x6000;reads=pread_calls;assert(MapViewOfFile_impl()==0x200000&&pread_calls==reads+1);
    assert(!memcmp(GPTR(alloc_va),file_bytes,1024));args[0]=alloc_va;assert(UnmapViewOfFile_impl());
    free(mapping.cached);mapping.cached=NULL;
    /* Cached prefetch past physical EOF remains zero-filled on later hits. */
    archive_cache_disabled=0;mapping.size=sizeof file_bytes+8192;
    assert(_chsize_s(fd,sizeof file_bytes)==0);
    args[0]=0x6000;args[3]=sizeof file_bytes-1024;args[4]=2048;
    assert(MapViewOfFile_impl()==0x200000&&mapping.cached_size==9216);
    assert(!memcmp(GPTR(alloc_va),file_bytes+sizeof file_bytes-1024,1024));
    for(unsigned i=1024;i<2048;++i)assert(!((uint8_t *)GPTR(alloc_va))[i]);
    args[0]=alloc_va;assert(UnmapViewOfFile_impl());reads=pread_calls;
    args[0]=0x6000;args[3]=sizeof file_bytes;args[4]=8192;assert(MapViewOfFile_impl()==0x200000&&pread_calls==reads);
    for(unsigned i=0;i<8192;++i)assert(!((uint8_t *)GPTR(alloc_va))[i]);
    args[0]=alloc_va;assert(UnmapViewOfFile_impl());
    uint8_t *last_cache=mapping.cached;mapping.fd=-1;mapping_destroy(&object);assert(freed_cache==last_cache);
    mapping.cached=NULL;
    assert(_close(fd)==0&&!blocking);
    puts("PASS actual MapViewOfFile: saved bytes/shared/COW unchanged; readonly copying and64KiB archive read-ahead; overlap hit skipsI/O/handoff, replacement/OOM/EOF/error/handle reuse/writer bypass safe;16MiB limit, protection, byte-exact results");
    return 0;
}
'''


class FileMappingTest(unittest.TestCase):
    def test_actual_shared_and_private_views(self):
        text=(ROOT/"android/host/files.c").read_text(encoding="utf-8")
        host=(ROOT/"android/host/host.h").read_text(encoding="utf-8")
        perf_kinds=re.search(r"enum \{\s*VOID_PERF_FILE_OPEN\b.*?\};",host,re.S).group()
        mapping_type=re.search(r"typedef struct \{[^{}]*\} mapping_t;",text).group()
        code=body(text,"WINAPI_EXPORT(K32, MapViewOfFile,")+body(text,"WINAPI_EXPORT(K32, UnmapViewOfFile,")
        code+=body(text,"static void mapping_destroy(").replace("free(m->cached)","counted_free(m->cached)")
        path=json.dumps(str(ROOT/"build/tests/file_mapping/mapped-save.bin"))
        fixture=(HARNESS.replace("/* ACTUAL_PERF_KINDS */",perf_kinds).replace("/* ACTUAL_MAPPING_TYPE */",mapping_type)
                 .replace("/* ACTUAL_BODIES */",code).replace("FIXTURE_PATH",path))
        compile_probe("file_mapping",fixture,{})
        for name,old,new in (
            ("writer", "!__atomic_load_n(&archive_cache_disabled, __ATOMIC_ACQUIRE)", "1"),
            ("identity", "live->identity == identity", "identity == identity"),
        ):
            with self.subTest(negative=name), self.assertRaises(AssertionError):
                negative_path=json.dumps(str(ROOT/f"build/tests/file_mapping_negative_{name}/mapped-save.bin"))
                compile_probe("file_mapping_negative_"+name,fixture.replace(old,new,1).replace(path,negative_path),{})


if __name__=="__main__":
    unittest.main()
