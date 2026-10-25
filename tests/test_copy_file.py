"""Run actual CopyFileA/W bodies with bounded guest RAM and short POSIX I/O."""
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define strdup _strdup
typedef intptr_t ssize_t;
static uint8_t memory[0x10000];
#define GPTR(x) (memory + (x))
#define MEM8(x) (*(uint8_t *)GPTR(x))
#define MEM16(x) (*(uint16_t *)GPTR(x))
static uint32_t args[3], last_error;
#define ARG(n) args[n]
#define WINAPI_EXPORT(dll, name, count) uint32_t name##_impl(void)
#define WIN_MAX_PATH 260
#define ERROR_PATH_NOT_FOUND_ 3u
#define ERROR_ACCESS_DENIED_ 5u
#define ERROR_NOT_ENOUGH_MEMORY_ 8u
#define VLOG(...) ((void)0)
static void void_set_last_error(uint32_t error) { last_error = error; }
static int void_vm_readable(uint32_t at, uint32_t size) { return at >= 0x100 && (uint64_t)at + size <= sizeof memory; }
#include "strings.h"

/* Deterministic POSIX boundary: all contents are real byte arrays, and every
 * read/write is short. Injected EINTR and terminal errors exercise the actual
 * host copy loop independently of Windows CRT differences. */
#define O_RDONLY 1
#define O_WRONLY 2
#define O_NONBLOCK 4
#define O_CLOEXEC 8
#define O_CREAT 16
#define O_EXCL 32
#define S_ISREG(mode) (((mode) & 0170000) == 0100000)
struct stat { uint32_t st_mode; uint64_t st_dev, st_ino; struct timespec st_atim, st_mtim; };
typedef struct { char path[512]; uint8_t bytes[65536]; size_t size; struct stat st; int exists; } node;
typedef struct { node *file; size_t offset; int flags; } descriptor;
static node nodes[16];
static descriptor fds[32];
static int read_intr, write_intr, read_failure, write_failure, zero_write, close_failure;
static unsigned opens, reads, writes;
static node *lookup(const char *path) {
    for (unsigned i=0; i<16; ++i) if (nodes[i].exists && !_stricmp(nodes[i].path,path)) return &nodes[i];
    return NULL;
}
static node *make(const char *path) {
    for (unsigned i=0;i<16;++i) if (!nodes[i].exists) {
        node *n=&nodes[i]; memset(n,0,sizeof *n); n->exists=1; strcpy(n->path,path);
        n->st=(struct stat){0100644,9,i+100,{123,456},{789,321}}; return n;
    }
    abort();
}
static char *to_host(const char *path, int *parent, char *normalized) {
    (void)normalized; if (parent) *parent=path && !strstr(path,"missing_parent/");
    if (!path || !*path) return NULL;
    char *out=malloc(strlen(path)+9); assert(out); sprintf(out,"/mapped/%s",path); return out;
}
static uint32_t void_errno_to_win32(int error) {
    switch(error) { case ENOENT:return 2; case EEXIST:return 80; case ENOSPC:return 112; default:return 5; }
}
static int open(const char *path, int flags, ...) {
    assert(!strncmp(path,"/mapped/",8)); ++opens;
    node *n=lookup(path);
    if (n && (flags&O_EXCL)) { errno=EEXIST;return -1; }
    if (!n && (!(flags&O_CREAT) || strstr(path,"missing_parent/"))) { errno=ENOENT;return -1; }
    if (!n) n=make(path);
    for(int i=3;i<32;++i) if(!fds[i].file) { fds[i]=(descriptor){n,0,flags};return i; }
    abort();
}
static int fstat(int fd, struct stat *out) { assert(fds[fd].file); *out=fds[fd].file->st;return 0; }
static int ftruncate(int fd, int64_t length) {
    assert(fds[fd].file && length==0); fds[fd].file->size=0; return 0;
}
static ssize_t read(int fd, void *out, size_t size) {
    ++reads; if(read_intr) { read_intr=0;errno=EINTR;return -1; }
    if(read_failure) { errno=EIO;return -1; }
    descriptor *d=&fds[fd]; assert(d->file);
    size_t count=d->file->size-d->offset; if(count>size)count=size; if(count>103)count=103;
    memcpy(out,d->file->bytes+d->offset,count);d->offset+=count;return (ssize_t)count;
}
static ssize_t write(int fd, const void *data, size_t size) {
    ++writes; if(write_intr) { write_intr=0;errno=EINTR;return -1; }
    if(write_failure) { errno=ENOSPC;return -1; }
    if(zero_write)return 0;
    descriptor *d=&fds[fd]; assert(d->file);if(size>17)size=17;
    assert(d->offset+size<=sizeof d->file->bytes);memcpy(d->file->bytes+d->offset,data,size);
    d->offset+=size; if(d->file->size<d->offset)d->file->size=d->offset;return (ssize_t)size;
}
static int fchmod(int fd, uint32_t mode) { fds[fd].file->st.st_mode=0100000|mode; return 0; }
static int futimens(int fd, const struct timespec times[2]) {
    fds[fd].file->st.st_atim=times[0];fds[fd].file->st.st_mtim=times[1];return 0;
}
static int close(int fd) {
    int fail=close_failure && (fds[fd].flags&O_WRONLY); fds[fd].file=NULL;
    if(fail) { errno=EIO;return -1; } return 0;
}
/* Directory listing cache: the destination's parent listing is dropped once
 * the copy has run (descriptors closed), whatever its result. */
static unsigned forget_calls;
static int forgot_subtree=-1;
static char forgotten[512];
static void listing_forget_parent(const char *path, int subtree) {
    assert(path&&strlen(path)<sizeof forgotten);
    for(int i=3;i<32;++i)assert(!fds[i].file);
    ++forget_calls;forgot_subtree=subtree;strcpy(forgotten,path);
}
#include "copy.h"
static void no_leaks(void) { for(int i=3;i<32;++i)assert(!fds[i].file); }
static uint32_t copy_a(const char *from, const char *to, int fail) {
    strcpy((char *)GPTR(0x100),from);strcpy((char *)GPTR(0x400),to);
    unsigned forgets=forget_calls;forgotten[0]=0;
    args[0]=0x100;args[1]=0x400;args[2]=(uint32_t)fail;uint32_t r=CopyFileA_impl();no_leaks();
    char mapped[512];snprintf(mapped,sizeof mapped,"/mapped/%s",to);
    assert(forget_calls==forgets+1&&forgot_subtree==0&&!strcmp(forgotten,mapped));
    return r;
}
int main(void) {
    node *src=make("/mapped/source"),*dst;
    src->size=40037;for(size_t i=0;i<src->size;++i)src->bytes[i]=(uint8_t)(i*73+11);
    read_intr=write_intr=1;
    assert(copy_a("source","dest",1)==1);dst=lookup("/mapped/dest");assert(dst);
    assert(dst->size==src->size&&!memcmp(dst->bytes,src->bytes,src->size));
    assert(reads>300&&writes>2000&&!read_intr&&!write_intr);
    assert(dst->st.st_mtim.tv_sec==789&&dst->st.st_atim.tv_nsec==456);
    memset(dst->bytes,0xCC,50000);dst->size=50000;
    assert(copy_a("source","dest",1)==0&&last_error==80&&dst->size==50000&&dst->bytes[0]==0xCC);
    assert(copy_a("source","dest",0)==1&&dst->size==40037&&!memcmp(dst->bytes,src->bytes,src->size));
    assert(copy_a("source","source",0)==0&&last_error==32&&src->size==40037&&src->bytes[0]==11);
    assert(copy_a("source","source",1)==0&&last_error==80&&src->size==40037);
    node *hard=make("/mapped/hard");hard->st.st_ino=src->st.st_ino;hard->size=3;memcpy(hard->bytes,"old",3);
    assert(copy_a("source","hard",0)==0&&last_error==32&&hard->size==3&&!memcmp(hard->bytes,"old",3));
    dst->st.st_mode=0100444;assert(copy_a("source","dest",0)==0&&last_error==5&&dst->size==40037);
    dst->st.st_mode=0100644;
    assert(copy_a("absent","dest",0)==0&&last_error==2&&dst->size==40037);
    assert(copy_a("source","missing_parent/dest",0)==0&&last_error==3);
    assert(copy_a("missing_parent/source","dest",0)==0&&last_error==3&&dst->size==40037);
    node *dir=make("/mapped/dir");dir->st.st_mode=0040755;
    assert(copy_a("dir","dest",0)==0&&last_error==5&&dst->size==40037);
    assert(copy_a("source","dir",0)==0&&last_error==5);
    make("/mapped/empty");assert(copy_a("empty","dest",0)==1&&dst->size==0);
    src->st.st_mode=0100444;assert(copy_a("source","readonly-copy",1)==1);
    assert((lookup("/mapped/readonly-copy")->st.st_mode&0777)==0444);
    /* Actual A/W converters are included: Russian CP1251 and Cyrillic UTF-16. */
    make("/mapped/caf\xD0\xB9")->bytes[0]=42;lookup("/mapped/caf\xD0\xB9")->size=1;
    assert(copy_a("caf\xE9","ansi-copy",1)==1&&lookup("/mapped/ansi-copy")->bytes[0]==42);
    void_utf8_to_gw("source",0x100,260);void_utf8_to_gw("\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA",0x400,260);
    args[0]=0x100;args[1]=0x400;args[2]=1;assert(CopyFileW_impl()==1);no_leaks();
    assert(lookup("/mapped/\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA")->size==src->size);
    assert(!strcmp(forgotten,"/mapped/\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA")&&forgot_subtree==0);
    unsigned before=opens,forgets=forget_calls;args[0]=0;assert(CopyFileW_impl()==0&&last_error==3&&opens==before);
    args[0]=UINT32_MAX;assert(CopyFileW_impl()==0&&last_error==998&&opens==before);
    MEM8(0xFFFF)='X';args[0]=0xFFFF;assert(CopyFileA_impl()==0&&last_error==998&&opens==before);
    memset(GPTR(0x100),'X',260);args[0]=0x100;assert(CopyFileA_impl()==0&&last_error==206&&opens==before);
    for(uint32_t i=0;i<260;++i)MEM16(0x100+i*2)='X';assert(CopyFileW_impl()==0&&last_error==206&&opens==before);
    MEM16(0x100)=0;assert(CopyFileW_impl()==0&&last_error==3&&opens==before);
    assert(forget_calls==forgets);   /* rejected guest paths never reach the host */
    /* Terminal I/O failures never report a successful copy or leak an fd. */
    read_failure=1;assert(copy_a("source","io-copy",0)==0&&last_error==5);read_failure=0;
    write_failure=1;assert(copy_a("source","io-copy",0)==0&&last_error==112);write_failure=0;
    zero_write=1;assert(copy_a("source","io-copy",0)==0&&last_error==29);zero_write=0;
    close_failure=1;assert(copy_a("source","io-copy",0)==0&&last_error==5);close_failure=0;
    assert(src->size==40037&&src->bytes[0]==11);no_leaks();
    puts("PASS actual CopyFileA/W: byte-exact short/EINTR I/O, overwrite/truncation, fail-if-exists, same inode/hard link, read-only, missing file/parent, directories, empty file, CP1251/UTF16, guest bounds, timestamps, terminal I/O/close failures and nonaltering rejects; destination listing invalidated after every host copy attempt");
    return 0;
}
'''


class CopyFileTest(unittest.TestCase):
    def test_actual_bodies(self):
        text = (ROOT / "android/host/files.c").read_text(encoding="utf-8")
        copy = text[text.index("static uint32_t copy_file("):text.index("static uint32_t move_file(")]
        strings = (ROOT / "android/host/strings.c").read_text(encoding="utf-8").replace('#include "host.h"', "")
        compile_probe("copy_file", HARNESS, {"copy.h": copy, "strings.h": strings})


if __name__ == "__main__":
    unittest.main()
