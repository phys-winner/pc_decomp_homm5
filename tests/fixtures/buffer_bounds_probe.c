#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#endif
#ifdef GPTR
#undef GPTR
#endif
#include "prefix.h"

#define ARGS d3d_buffer *,const void *,int,uint32_t,uint32_t,int,uint32_t,uint32_t,uint32_t *,uint32_t *
int bounds_baseline(ARGS);
int bounds_candidate(ARGS);
static uint32_t rng=0xD3D90032u;
static uint32_t random32(void){uint32_t x=rng;x^=x<<13;x^=x>>17;x^=x<<5;return rng=x;}
enum { BYTES=2*1024*1024 };
static unsigned char *memory;
static void compare(d3d_buffer *ib,const void *up,int wide,uint32_t start,uint32_t count,
    int indexed,uint32_t base,uint32_t index,unsigned testcase) {
    uint32_t lo1=0x12345678,hi1=0x9ABCDEF0,lo2=lo1,hi2=hi1;
    int a=bounds_baseline(ib,up,wide,start,count,indexed,base,index,&lo1,&hi1);
    int b=bounds_candidate(ib,up,wide,start,count,indexed,base,index,&lo2,&hi2);
    if(a!=b||lo1!=lo2||hi1!=hi2){
        fprintf(stderr,"oracle mismatch case%u mode%d count%u base%u result%d/%d [%u,%u]/[%u,%u]\n",testcase,wide,count,base,a,b,lo1,hi1,lo2,hi2);exit(3);
    }
}
static void oracle(void) {
    d3d_buffer ib={0};ib.shadow=0x10000;ib.size=65536;
    uint32_t cases=0;
    for(unsigned wide=0;wide<2;wide++) for(unsigned count=0;count<=2049;count++) {
        ib.format=wide?102:101;
        for(unsigned misalign=0;misalign<4;misalign++) {
            unsigned char *p=memory+0x10000+misalign;
            for(unsigned i=0;i<count;i++)if(wide){uint32_t value=random32()&0x00FFFFFF;memcpy(p+4*i,&value,4);}
                else{uint16_t value=(uint16_t)random32();memcpy(p+2*i,&value,2);}
            compare(&ib,p,wide,0,count,1,0,0,cases++);
            compare(&ib,p,wide,0,count,1,(uint32_t)-13,0,cases++);
            ib.shadow=0x10000+misalign;
            compare(&ib,NULL,0,0,count,1,17,0,cases++);
        }
    }
    for(unsigned n=0;n<20000;n++) {
        ib.format=(n&1)?102:101;ib.shadow=0x10000+(n&15);ib.size=(n&31)?65536:7;
        uint32_t count=random32()%8193,base=random32(),index=random32()%32;
        if((n&15)==0)count=UINT32_MAX;
        if((n&15)==1)index=UINT32_MAX;
        compare((n&127)?&ib:NULL,NULL,0,random32(),count,(n&63)!=0,base,index,cases++);
    }
    uint32_t edges[]={0,1,65535,65536,0x7FFFFFFFu,0x80000000u,UINT32_MAX};
    uint32_t bases[]={0,1,UINT32_MAX,0x80000000u,0x7FFFFFFFu};
    for(unsigned n=0;n<sizeof edges/sizeof *edges;n++)for(unsigned b=0;b<sizeof bases/sizeof *bases;b++)
        compare(NULL,edges+n,1,0,1,1,bases[b],0,cases++);
    compare(NULL,NULL,0,UINT32_MAX,2,0,0,0,cases++);
    printf("{\"oracle\":\"PASS\",\"cases\":%u,\"full_ret_and_outputs\":true,\"signed_base_and_raw_max\":true}\n",cases);
}
static void guarded_tails(void) {
    unsigned page;
    unsigned char *p;
#ifdef _WIN32
    SYSTEM_INFO info;GetSystemInfo(&info);page=info.dwPageSize;
    p=VirtualAlloc(NULL,2*page,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    DWORD old;if(!p||!VirtualProtect(p+page,page,PAGE_NOACCESS,&old))exit(4);
#else
    page=(unsigned)sysconf(_SC_PAGESIZE);p=mmap(NULL,2*page,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(p==MAP_FAILED||mprotect(p+page,page,PROT_NONE))exit(4);
#endif
    unsigned tested=0;
    for(unsigned wide=0;wide<2;wide++)for(unsigned count=1;count<97;count++){
        unsigned unit=wide?4:2;unsigned char *end=p+page-count*unit;
        for(unsigned i=0;i<count*unit;i++)end[i]=(unsigned char)random32();
        compare(NULL,end,wide,0,count,1,0,0,100000+tested++);
    }
#ifdef _WIN32
    VirtualFree(p,0,MEM_RELEASE);
#else
    munmap(p,2*page);
#endif
    printf("{\"guard_page_tails\":\"PASS\",\"cases\":%u}\n",tested);
}
int main(void) {
#ifdef _WIN32
    SetThreadAffinityMask(GetCurrentThread(),(DWORD_PTR)128);
    memory=VirtualAlloc(GPTR(0),BYTES,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
#else
    memory=mmap(GPTR(0),BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
#endif
    if(memory!=GPTR(0)){fprintf(stderr,"fixed guest fixture mapping unavailable\n");return 2;}
    for(unsigned i=0;i<BYTES;i+=4){uint32_t x=random32();memcpy(memory+i,&x,4);}
    oracle();guarded_tails();
    return 0;
}
