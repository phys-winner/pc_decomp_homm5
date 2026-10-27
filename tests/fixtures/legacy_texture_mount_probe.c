#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x2000000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
static void concat(void),append(void),pattern(void),compare(void),insert(void),record(void),attributes(void),entry_size(void),entry_time(void),zip_constructor(void);
static void fixture_call(uint32_t target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#define RECOMP_CALL(fn) fixture_call((uint32_t)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((uint32_t)(va))
/* ACTUAL */
static const unsigned char constants[]={/* CONSTANTS */};
static jmp_buf complete;
static uint32_t heap,vector,converted_record,open_path;
static int empty,present,opened,record_count;
static int inserting,have_entry,map_lookups,destroyed;
static void make_zip(void) {
 uint32_t base=0xB0000,central=base+175,end=base+238;
 memset(GPTR(base),0,260);MEM32(base)=0x04034B50;MEM16(base+4)=20;MEM32(base+10)=MEM32(0x930C);
 MEM32(base+14)=0xC2A8FA9D;MEM32(base+18)=128;MEM32(base+22)=128;MEM16(base+26)=17;
 memcpy(GPTR(base+30),"Textures/Test.dds",17);
 memcpy(GPTR(central),GPTR(0x9300),46);MEM32(central)=0x02014B50;MEM16(central+4)=20;MEM16(central+6)=20;
 MEM32(central+16)=0xC2A8FA9D;MEM32(central+20)=128;MEM32(central+24)=128;MEM16(central+28)=17;
 memcpy(GPTR(central+46),"Textures/Test.dds",17);
 MEM32(end)=0x06054B50;MEM16(end+8)=1;MEM16(end+10)=1;MEM32(end+12)=63;MEM32(end+16)=175;
}
#if NATIVE_COUNT == 8
static const char *const names[]={"p5-texts.pak","p5-data.pak","p6-texts.pak","p6-data.pak","p7-texts.pak","p7-data.pak","p8-texts.pak","p8-data.pak"};
static const int priorities[]={-1,1,-1,2,-1,3,-1,4};
#else
static const char *const names[]={"texts.pak","p0-data.pak","p1-data.pak","p2-data.pak","p3-data.pak","p0-texts.pak","p1-texts.pak","p2-texts.pak","p3-texts.pak","a1-texts.pak","a1-sound.pak","a1-data.pak","a1p1-data.pak","a1p1-texts.pak","a1p1-sound.pak"};
static const int priorities[]={-1,1,1,1,1,-1,-1,-1,-1,2,2,2,3,-1,3};
#endif
static uint32_t allocate(uint32_t n) {
 uint32_t p=heap;heap+=(n+31u)&~15u;assert(heap<0xF0000);memset(GPTR(p),0,n);return p;
}
static void string_copy(uint32_t out,uint32_t begin,uint32_t end) {
 assert(end>=begin&&end-begin<1024);uint32_t n=end-begin,p=allocate(n+1);
 memcpy(GPTR(p),GPTR(begin),n);MEM32(out)=p;MEM32(out+4)=p+n;MEM32(out+8)=p+n+1;
}
static const char *string(uint32_t p) {return (const char *)GPTR(MEM32(p));}
static void fixture_call(uint32_t target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 if(target==CONCAT){concat();return;}
 if(target==APPEND){append();return;}
 if(target==COMPARE){compare();return;}
 if(target==RECORD){record();return;}
 if(target==ATTRIBUTES){attributes();return;}
 if(target==ENTRY_SIZE){entry_size();return;}
 if(target==ENTRY_TIME){entry_time();return;}
 if(target==GET_ATTACHED){g_eax=0x7000;g_esp+=4;return;}
 if(target==CAST){g_eax=0x7000;g_esp+=4;return;}
 if(target==GET_DEFAULT){g_eax=0x7100;g_esp+=4;return;}
 if(target==ALLOC||target==NEW){g_eax=allocate(MEM32(g_esp+4));g_esp+=4;return;}
 if(target==FREE){uint32_t p=MEM32(g_esp+4);if(p)memset(GPTR(p),0xDD,8);g_esp+=4;return;}
 if(target==COPY_FS){assert(g_ecx==g_edx);g_eax=MEM32(g_esp+4);g_esp+=8;return;}
 if(target==STRING){string_copy(g_ecx,MEM32(g_esp+4),MEM32(g_esp+8));g_eax=g_ecx;g_esp+=12;return;}
 if(target==APPEND_BYTES){
  uint32_t b=MEM32(g_esp+4),e=MEM32(g_esp+8),at=MEM32(g_ecx+4);assert(e>=b&&at+e-b<MEM32(g_ecx+8));
  memcpy(GPTR(at),GPTR(b),e-b);MEM8(at+e-b)=0;MEM32(g_ecx+4)=at+e-b;g_eax=g_ecx;g_esp+=12;return;
 }
 if(target==COPY_RECORDS){
  uint32_t out=MEM32(g_esp+4);for(uint32_t p=g_ecx;p<g_edx;p+=16,out+=16){
   string_copy(out,MEM32(p),MEM32(p+4));MEM32(out+12)=MEM32(p+12);
  }g_eax=out;g_esp+=8;return;
 }
 if(target==CONSTRUCT_RECORD){
  uint32_t p=MEM32(g_esp+4);assert(g_edx==1);string_copy(g_ecx,MEM32(p),MEM32(p+4));
  MEM32(g_ecx+12)=MEM32(p+12);g_eax=g_ecx+16;g_esp+=8;return;
 }
 if(target==DESTROY_VECTOR){g_esp+=4;return;}
 if(target==FACTORY){
  assert(g_ecx==0x1000);vector=g_edx;assert(vector==0x100000-FRAME-16+VECTOR_OFFSET);
  record_count=(int)((MEM32(vector+4)-MEM32(vector))/16);assert(record_count==(empty?0:NATIVE_COUNT+1));
  if(!empty){
   for(unsigned i=0;i<NATIVE_COUNT;++i){char expected[100];snprintf(expected,sizeof expected,"game/secondary/%s",names[i]);uint32_t p=MEM32(vector)+i*16;assert(!strcmp(string(p),expected)&&MEM32(p+12)==(uint32_t)priorities[i]);}
   converted_record=MEM32(vector+4)-16;assert(!strcmp(string(converted_record),"game/secondary/zz_port_textures_v2.pak"));assert(MEM32(converted_record+12)==0x80000000u);
  }
  longjmp(complete,1);
 }
 if(target==FIND){
  assert(!strcmp(string(MEM32(g_esp+4)),string(open_path)));
  MEM32(g_ecx)=present?1:UINT32_MAX;MEM32(g_ecx+4)=0;
  MEM32(g_ecx+0x144)=MEM32(g_ecx+0x150)=0;g_eax=g_ecx;g_esp+=8;return;
 }
 if(target==FIND_PATH){uint32_t out=MEM32(g_esp+4);string_copy(out,MEM32(open_path),MEM32(open_path+4));g_eax=out;g_esp+=8;return;}
 if(target==FIND_NEXT){MEM32(g_ecx)=UINT32_MAX;g_eax=g_ecx;g_esp+=4;return;}
 if(target==FIND_FREE){g_esp+=4;return;}
 if(target==ADD_PAK){assert(!strcmp(string(MEM32(g_esp+4)),string(open_path))&&MEM32(g_esp+8)==0x80000000u);++opened;g_esp+=12;return;}
 if(target==WRAPPER){
  assert(inserting);uint32_t wrapper=g_ecx,zip=allocate(0x28);make_zip();MEM32(wrapper+4)=0;
  g_ecx=zip;zip_constructor();assert(MEM32(zip+0x10)-MEM32(zip+0xC)==4);
  MEM32(wrapper+0xC)=zip;g_eax=wrapper;return;
 }
 if(target==FILE_OPEN){MEM32(g_ecx)=1;g_eax=g_ecx;g_esp+=12;return;}
 if(target==FILE_SIZE){g_eax=260;g_esp+=4;return;}
 if(target==0xDEAD2000){g_eax=0;g_esp+=4;return;}
 if(target==FILE_MAP_ENABLE){g_esp+=12;return;}
 if(target==ZIP_MAP){uint32_t offset=MEM32(g_esp+8),size=MEM32(g_esp+12);assert(offset+size<=260);MEM32(g_ecx+4)=0xB0000+offset;MEM32(g_ecx+0x14)=0;g_eax=g_ecx;g_esp+=16;return;}
 if(target==ZIP_MAP_FREE){g_esp+=4;return;}
 if(target==ZIP_VECTOR){
#if NATIVE_COUNT == 8
  uint32_t source=MEM32(g_esp+4),cleanup=8;
#else
  assert(MEM32(g_esp+12)==1&&MEM32(g_esp+16)==1);uint32_t source=MEM32(g_esp+8),cleanup=20;
#endif
  uint32_t n=MEM32(g_ecx+4)-MEM32(g_ecx),p=allocate(n+4);
  if(n)memcpy(GPTR(p),GPTR(MEM32(g_ecx)),n);MEM32(p+n)=MEM32(source);MEM32(g_ecx)=p;MEM32(g_ecx+4)=MEM32(g_ecx+8)=p+n+4;
  g_eax=p+n;g_esp+=cleanup;return;
 }
 if(target==ARCHIVE_SLOT){assert(inserting);g_eax=0x8200;g_esp+=8;return;}
 if(target==ENTRY_NAME){
  assert(inserting&&MEM32(g_esp+4)==0&&MEM32(g_esp+8)==g_edx);string_copy(g_edx,0x3200,0x3211);g_eax=g_edx;g_esp+=12;return;
 }
 if(target==MAP_FIND){assert(inserting);++map_lookups;g_eax=have_entry?0xA000:0;g_esp+=8;return;}
 if(target==MAP_CREATE){assert(inserting);g_eax=0xA010;g_esp+=8;return;}
 if(target==0xDEAD1000){assert(g_ecx==0xA100&&MEM32(g_esp+4)==1);++destroyed;g_esp+=8;return;}
 fprintf(stderr,"unexpected archive callback %08X\n",target);abort();
}
static void reset(void) {
 memset(memory,0,sizeof memory);memcpy(GPTR(CONSTANTS),constants,sizeof constants);heap=0x20000;vector=converted_record=0;opened=0;
 MEM32(VERSION_IAT)=0xDEAD2000;
 memcpy(GPTR(0x3000),"game/data",10);string_copy(0x1000,0x3000,0x3009);
 memcpy(GPTR(0x3100),"game/secondary",15);string_copy(0x1100,0x3100,0x3100+(empty?0:14));
 g_eax=0;g_ecx=0x1000;g_edx=0x1100;g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
 g_esp=0x100000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1200;MEM32(g_esp+8)=0;
 fp_set_cw(0x007f);g_fp_sp=128;g_fp_top=0;
}
int main(void) {
 for(empty=0;empty<=1;++empty){reset();if(!setjmp(complete))builder();assert(g_fp_sp==128&&g_fp_top==0);if(empty)continue;
  open_path=converted_record;
  for(present=0;present<=1;++present){
   g_ecx=0x8000;g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
   g_esp=0x110000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=open_path;MEM32(g_esp+8)=0x80000000u;pattern();
   assert(g_esp==0x11000C&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
   assert(opened==present&&g_fp_sp==128&&g_fp_top==0);
  }
 }
 const int priorities[]={-1,0,1,2,3,4};
 for(unsigned a=0;a<6;++a)for(unsigned b=0;b<6;++b)for(uint32_t t=98;t<=102;++t){
  MEM32(0x1800+4)=100;MEM32(0x1800+12)=(uint32_t)priorities[a];g_esp=0x120000;
  MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1800;MEM32(g_esp+8)=t;MEM32(g_esp+12)=(uint32_t)priorities[b];compare();
  int expected=priorities[a]!=priorities[b]&&priorities[a]!=-1&&priorities[b]!=-1?priorities[a]<priorities[b]:100<t;
  assert((g_eax&255)==(unsigned)expected&&g_esp==0x120010);
 }
 /* A converted source keeps its original timestamp and decoded priority.
  * Later archives must therefore make the same decision as against the source. */
 empty=0;inserting=1;
 for(unsigned p=0;p<6;++p)for(int old=0;old<=1;++old){
  reset();have_entry=old;map_lookups=destroyed=0;
  memcpy(GPTR(0x3200),"Textures/Test.dds",18);
  MEM32(0x900C)=0x9200;MEM32(0x9010)=0x9204;MEM32(0x9200)=0x9300;
  MEM32(0x9300+0x18)=128;MEM32(0x9300+0xC)=0x50221883;
  MEM32(0x9300+0x26)=0x48540000u|((uint32_t)(priorities[p]+1)<<8);
  MEM32(0xA010)=0xA100;MEM32(0xA100)=0xA200;MEM32(0xA200)=0xDEAD1000;
  MEM32(0xA104)=0x50221883;MEM32(0xA10C)=(uint32_t)priorities[p];
  g_ecx=0x8000;g_esp=0x130000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1100;MEM32(g_esp+8)=0x80000000u;
  g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;insert();
  if(g_esp!=0x13000C||g_ebx!=0x11223344||g_esi!=0x22334455||g_edi!=0x33445566||g_ebp!=0x44556677)
   fprintf(stderr,"insert return p=%u old=%d esp=%08X regs=%08X,%08X,%08X,%08X\n",p,old,g_esp,g_ebx,g_esi,g_edi,g_ebp);
  assert(g_esp==0x13000C&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
  uint32_t r=MEM32(0xA010);assert(r!=0xA100&&MEM32(r+4)==0x50221883&&MEM32(r+12)==(uint32_t)priorities[p]&&destroyed==old);
  for(unsigned q=0;q<6;++q)for(int delta=-1;delta<=1;++delta){
   g_esp=0x120000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=r;MEM32(g_esp+8)=0x50221883u+(uint32_t)delta;MEM32(g_esp+12)=(uint32_t)priorities[q];compare();
   int expected=priorities[p]!=priorities[q]&&priorities[p]!=-1&&priorities[q]!=-1?priorities[p]<priorities[q]:delta>0;
   assert((g_eax&255)==(unsigned)expected);
  }
 }
 const uint32_t invalid[]={0,0x48540001,0x48540600,0x4854FF00,0x11110000};
 for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];++i){
  reset();have_entry=1;map_lookups=destroyed=0;MEM32(0x900C)=0x9200;MEM32(0x9010)=0x9204;MEM32(0x9200)=0x9300;
  MEM32(0x9300+0x18)=128;MEM32(0x9300+0x26)=invalid[i];MEM32(0xA010)=0xA100;
  g_ecx=0x8000;g_esp=0x130000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1100;MEM32(g_esp+8)=0x80000000u;insert();
  assert(g_esp==0x13000C&&!map_lookups&&!destroyed&&MEM32(0xA010)==0xA100);
 }
 /* Marker-like external attributes in an ordinary archive have no special
  * meaning: its archive priority and strict timestamp comparison remain native. */
 for(unsigned p=0;p<6;++p)for(unsigned marker=0;marker<2;++marker)for(int old=0;old<=1;++old){
  reset();have_entry=old;map_lookups=destroyed=0;
  memcpy(GPTR(0x3200),"Textures/Test.dds",18);
  MEM32(0x9300+0x18)=128;MEM32(0x9300+0xC)=0x50221883;
  MEM32(0x9300+0x26)=marker?0x48540500u:0;
  MEM32(0xA010)=0xA100;MEM32(0xA100)=0xA200;MEM32(0xA200)=0xDEAD1000;
  MEM32(0xA104)=0x50221883;MEM32(0xA10C)=(uint32_t)priorities[p];
  g_ecx=0x8000;g_esp=0x130000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1100;MEM32(g_esp+8)=(uint32_t)priorities[p];insert();
  assert(g_esp==0x13000C&&map_lookups==1&&!destroyed);
  uint32_t r=MEM32(0xA010);
  assert((old?r==0xA100:r!=0xA100)&&MEM32(r+4)==0x50221883&&MEM32(r+12)==(uint32_t)priorities[p]);
 }
 /* Only the six exact tagged values are decoded. */
 const uint32_t invalid_tags[]={0x40000006u,0x400000FFu,0x40000100u,0x50000003u};
 for(unsigned i=0;i<sizeof invalid_tags/sizeof invalid_tags[0];++i){
  MEM32(0x1804)=100;MEM32(0x180C)=4;g_esp=0x120000;
  MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x1800;MEM32(g_esp+8)=99;MEM32(g_esp+12)=invalid_tags[i];compare();
  assert((g_eax&255)==1&&g_esp==0x120010);
 }
 puts("PASS actual legacy bank builder/String/vector ABI; optional absent/present open; native ZIP parser/attrs+insert+constructor/compare; source priority/time retained after removal; later Map +/-2seconds/all priorities; invalid metadata and ordinary archive guards");
}
