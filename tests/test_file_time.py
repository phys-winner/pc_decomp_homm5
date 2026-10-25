"""Execute real Set/GetFileTime and timestamp suppression around real I/O bodies."""
import re
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
#include <time.h>
typedef intptr_t ssize_t;
typedef int64_t off_t;
static uint8_t memory[0x10000];
#define GPTR(at) (memory+(at))
#define MEM32(at) (*(uint32_t *)GPTR(at))
#define MEM64(at) (*(uint64_t *)GPTR(at))
static uint32_t args[5],last_error;
#define ARG(i) args[i]
#define WINAPI_EXPORT(dll,name,nargs) uint32_t name##_impl(void)
#define GENERIC_WRITE_ 0x40000000u
#define ERROR_INVALID_HANDLE_ 6u
#define ERROR_ACCESS_DENIED_ 5u
#define ERROR_NOT_SUPPORTED_ 50u
#define ERROR_INVALID_PARAMETER_ 87u
#define UTIME_OMIT 1073741822L
#define SEEK_CUR 1
static void void_set_last_error(uint32_t v) { last_error=v; }
static int void_vm_readable(uint32_t va,uint32_t n) { return va>=0x100 && (uint64_t)va+n<=sizeof memory; }
static int void_vm_writable(uint32_t va,uint32_t n) { return void_vm_readable(va,n); }
static uint32_t void_errno_to_win32(int e) { return e==EBADF ? 6u : e==EINVAL ? 87u : 5u; }
/* ACTUAL_FILE_TYPE */
static file_t fixture;
static file_t *file_get(uint32_t handle) { return handle==0x6000 ? &fixture : NULL; }
struct stat { struct timespec st_ctim,st_atim,st_mtim; };
static struct stat attributes;
static unsigned futimens_calls;
static int fstat_error,time_error,time_intr,read_left;
static int fstat(int fd,struct stat *out) {
    assert(fd==9);if(fstat_error) { errno=EBADF;return -1; } *out=attributes;return 0;
}
static int futimens(int fd,const struct timespec times[2]) {
    assert(fd==9);++futimens_calls;
    if(time_intr) { time_intr=0;errno=EINTR;return -1; }
    if(time_error) { errno=EACCES;return -1; }
    for(int i=0;i<2;++i) {
        if(times[i].tv_nsec==UTIME_OMIT)continue;
        assert(times[i].tv_nsec>=0&&times[i].tv_nsec<1000000000L);
        if(i)attributes.st_mtim=times[i];else attributes.st_atim=times[i];
    }
    return 0;
}
/* ACTUAL_PERF_KINDS */
/* Host clock: only reads advance it, so a recorded duration covers the I/O. */
static uint64_t perf_clock=5000;
static unsigned perf_calls;
static int perf_kind=-1;
static uint64_t perf_ns,perf_bytes;
static uint64_t void_perf_now_ns(void) { return perf_clock; }
static void void_perf_add(int kind,uint64_t ns,uint64_t bytes) { ++perf_calls;perf_kind=kind;perf_ns=ns;perf_bytes=bytes; }
/* The guest machine lock: ReadFile releases it only for large reads. */
static int released,expect_blocking,read_error;
static unsigned blocking_sections;
static void void_blocking_begin(void) { assert(!released);released=1;++blocking_sections; }
static void void_blocking_end(void) { assert(released);released=0; }
static void console_write(file_t *f,const uint8_t *p,uint32_t n) { (void)f;(void)p;(void)n;assert(0); }
static ssize_t read(int fd,void *out,size_t size) {
    assert(fd==9&&released==expect_blocking);perf_clock+=250;
    if(read_error) { errno=EIO;return -1; }
    if(!read_left)return 0;size_t n=(size_t)read_left;if(n>size)n=size;
    memset(out,'A',n);read_left-=(int)n;attributes.st_atim=(struct timespec){999,123};return (ssize_t)n;
}
static ssize_t pread(int fd,void *out,size_t size,off_t offset) { assert(offset>=0);return read(fd,out,size); }
/* Reads with the machine released use their own descriptor (same number here). */
static unsigned dup_calls,close_calls;
static int dup(int fd) { assert(fd==9&&!released);++dup_calls;return 9; }
static int close(int fd) { assert(fd==9&&!released);++close_calls;return 0; }
static ssize_t write(int fd,const void *in,size_t size) {
    assert(fd==9&&in);attributes.st_mtim=(struct timespec){888,456};return (ssize_t)size;
}
static ssize_t pwrite(int fd,const void *in,size_t size,off_t offset) { assert(offset>=0);return write(fd,in,size); }
static off_t lseek(int fd,off_t offset,int whence) { assert(fd==9&&offset==0&&whence==SEEK_CUR);return 3; }
static int ftruncate(int fd,off_t size) { assert(fd==9&&size==3);attributes.st_mtim=(struct timespec){777,789};return 0; }
/* ACTUAL_BODIES */
static uint32_t set(uint64_t creation,uint64_t access,uint64_t modified) {
    MEM64(0x100)=creation;MEM64(0x110)=access;MEM64(0x120)=modified;
    args[0]=0x6000;args[1]=0x100;args[2]=0x110;args[3]=0x120;return SetFileTime_impl();
}
int main(void) {
    fixture.fd=9;fixture.granted_access=0xC0000000u;
    attributes=(struct stat){{1234,123456700},{2345,234567800},{3456,345678900}};
    const uint64_t epoch=116444736000000000ull;
    struct timespec t;
    assert(filetime_to_unix(epoch+1,&t)&&t.tv_sec==0&&t.tv_nsec==100);
    assert(filetime_to_unix(epoch-1,&t)&&t.tv_sec==-1&&t.tv_nsec==999999900);
    assert(filetime_to_unix(1,&t)&&t.tv_sec==-11644473600ll&&t.tv_nsec==100);
    assert(!filetime_to_unix(UINT64_C(0x8000000000000000),&t));
    uint64_t samples[]={1,10000000,epoch-1,epoch,epoch+1,epoch+2147483648ull*10000000+9876543,INT64_MAX};
    for(unsigned i=0;i<sizeof samples/sizeof samples[0];++i) {
        assert(filetime_to_unix(samples[i],&t));assert(unix_to_filetime(t.tv_sec,t.tv_nsec)==samples[i]);
    }
    args[0]=0x6000;args[1]=0x200;args[2]=0x210;args[3]=0x220;
    assert(GetFileTime_impl()==1);uint64_t creation=MEM64(0x200);
    assert(MEM64(0x210)==epoch+2345ull*10000000+2345678);
    time_intr=1;
    assert(set(creation,epoch+10000001,epoch-1)==1&&futimens_calls==2);
    assert(attributes.st_atim.tv_sec==1&&attributes.st_atim.tv_nsec==100);
    assert(attributes.st_mtim.tv_sec==-1&&attributes.st_mtim.tv_nsec==999999900);
    unsigned count=futimens_calls;assert(set(0,0,0)==1&&futimens_calls==count);
    args[1]=args[2]=args[3]=0;assert(SetFileTime_impl()==1&&futimens_calls==count);
    assert(set(creation+1,epoch,epoch)==0&&last_error==50&&futimens_calls==count);
    assert(set(0,epoch,UINT64_C(0x8000000000000000))==0&&last_error==87&&futimens_calls==count);
    assert(attributes.st_atim.tv_sec==1); /* rejected multi-field call is atomic */
    assert(set(0,UINT64_MAX,UINT64_MAX)==1&&futimens_calls==count&&fixture.keep_times==3);
    struct timespec old_access=attributes.st_atim,old_modified=attributes.st_mtim;
    args[0]=0x6000;args[1]=0x1000;args[2]=3;args[3]=0x300;args[4]=0;read_left=3;
    assert(ReadFile_impl()==1&&MEM32(0x300)==3&&!memcmp(GPTR(0x1000),"AAA",3));
    assert(attributes.st_atim.tv_sec==old_access.tv_sec&&attributes.st_atim.tv_nsec==old_access.tv_nsec);
    assert(WriteFile_impl()==1&&MEM32(0x300)==3);
    assert(attributes.st_mtim.tv_sec==old_modified.tv_sec&&attributes.st_mtim.tv_nsec==old_modified.tv_nsec);
    assert(SetEndOfFile_impl()==1&&attributes.st_mtim.tv_sec==old_modified.tv_sec);
    assert(set(0,epoch+70000000,0)==1&&fixture.keep_times==2);
    args[0]=0x6000;args[1]=0x1000;args[2]=3;args[3]=0x300;args[4]=0;read_left=3;
    assert(ReadFile_impl()==1&&attributes.st_atim.tv_sec==999&&attributes.st_mtim.tv_sec==old_modified.tv_sec);
    count=futimens_calls;fixture.granted_access=0x80000000u;
    assert(set(0,epoch,epoch)==0&&last_error==5&&futimens_calls==count);
    fixture.granted_access=0x100;assert(set(0,epoch,epoch)==1&&fixture.keep_times==0);
    count=futimens_calls;args[0]=0;assert(SetFileTime_impl()==0&&last_error==6);
    args[0]=0x6000;args[1]=UINT32_MAX;assert(SetFileTime_impl()==0&&last_error==998&&futimens_calls==count);
    args[1]=0;args[2]=sizeof memory-7;assert(SetFileTime_impl()==0&&last_error==998&&futimens_calls==count);
    args[2]=0;fstat_error=1;assert(SetFileTime_impl()==0&&last_error==6);fstat_error=0;
    time_error=1;assert(set(0,epoch+1,epoch+1)==0&&last_error==5&&fixture.keep_times==0);time_error=0;
    assert(attributes.st_atim.tv_sec==0&&attributes.st_atim.tv_nsec==0);
    fixture.std_stream=1;assert(set(0,0,0)==0&&last_error==6);
    /* Reads are timed; 16 KiB and larger ones run with the machine released. */
    fixture.std_stream=0;fixture.keep_times=0;
    assert(!blocking_sections&&perf_calls==2&&perf_kind==VOID_PERF_FILE_READ&&perf_bytes==3&&perf_ns==250);
    uint64_t clock=perf_clock;
    args[0]=0x6000;args[1]=0x1000;args[2]=16383;args[3]=0x300;args[4]=0;read_left=20000;
    assert(ReadFile_impl()==1&&MEM32(0x300)==16383&&!blocking_sections&&perf_calls==3);
    assert(perf_kind==VOID_PERF_FILE_READ&&perf_bytes==16383&&perf_ns==perf_clock-clock&&perf_ns==250);
    expect_blocking=1;args[2]=16384;read_left=20000;
    assert(ReadFile_impl()==1&&MEM32(0x300)==16384&&!released&&blocking_sections==1&&perf_bytes==16384);
    /* A short tail ends at EOF: two reads, both timed inside one released section. */
    args[2]=16384;read_left=1000;memset(GPTR(0x1000),0,16384);
    assert(ReadFile_impl()==1&&MEM32(0x300)==1000&&blocking_sections==2&&perf_bytes==1000&&perf_ns==500);
    assert(GPTR(0x1000)[999]=='A'&&!GPTR(0x1000)[1000]);
    /* Overlapped large reads take the same released, timed path. */
    MEM32(0x400)=MEM32(0x404)=0xCCCCCCCCu;MEM32(0x408)=16;MEM32(0x40C)=0;
    args[4]=0x400;read_left=20000;
    assert(ReadFile_impl()==1&&MEM32(0x300)==16384&&MEM32(0x400)==0&&MEM32(0x404)==16384&&blocking_sections==3);
    /* A failed read re-acquires the machine and records no bytes. */
    args[4]=0;read_error=1;unsigned calls=perf_calls;
    assert(ReadFile_impl()==0&&last_error==5&&MEM32(0x300)==0&&!released&&blocking_sections==4);
    assert(perf_calls==calls+1&&perf_bytes==0);read_error=0;
    /* Rejected handles and buffers are neither timed nor released. */
    expect_blocking=0;args[0]=0;assert(ReadFile_impl()==0&&last_error==6&&perf_calls==calls+1);
    args[0]=0x6000;args[1]=sizeof memory-16000;
    assert(ReadFile_impl()==0&&last_error==998&&perf_calls==calls+1&&blocking_sections==4);
    puts("PASS actual Set/GetFileTime: 100ns precision, pre-Unix/2038+/maximum positive times, unchanged creation, NULL/zero/-1, per-handle freeze over Read/Write/truncate, writable-attributes access, memory bounds, atomic rejects, EINTR and futimens errors; ReadFile timed as read, >=16KiB reads (sync/overlapped/failed) with the machine released");
    return 0;
}
'''


class FileTimeTest(unittest.TestCase):
    def test_actual_bodies(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        file_type = text[text.index("typedef struct {\n    int fd;"):text.index("static int file_restore_kept_times(")]
        signatures = ["static int file_restore_kept_times(", "static uint64_t unix_to_filetime(", "static int filetime_to_unix("]
        names = ["GetFileTime", "SetFileTime", "ReadFile", "WriteFile", "SetEndOfFile"]
        code = "\n".join(body(text, s) for s in signatures)
        code += "\n".join(body(text, "WINAPI_EXPORT(K32, " + name + ",") for name in names)
        host = (ROOT / "android/host/host.h").read_text(encoding="utf-8")
        perf_kinds = re.search(r"enum \{\s*VOID_PERF_FILE_OPEN\b.*?\};", host, re.S).group()
        fixture = (HARNESS.replace("/* ACTUAL_FILE_TYPE */", file_type).replace("/* ACTUAL_BODIES */", code)
                   .replace("/* ACTUAL_PERF_KINDS */", perf_kinds))
        compile_probe("file_time", fixture, {})


if __name__ == "__main__":
    unittest.main()
