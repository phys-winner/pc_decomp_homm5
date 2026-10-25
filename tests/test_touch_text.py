"""Run the actual bounded IME queue with engine focus and Android callback spies."""
from pathlib import Path
import unittest
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
#define VOID_ANDROID_APP 1
static unsigned char memory[0x40000];
static uint32_t unreadable_start,unreadable_end;
static int void_vm_readable(uint32_t address,uint32_t size) {
    return address>=0x100&&(uint64_t)address+size<=sizeof memory&&
        (!unreadable_end||address>=unreadable_end||(uint64_t)address+size<=unreadable_start);
}
static uint32_t *memory32(uint32_t address) {
    assert(!(address&3)&&void_vm_readable(address,4));return (uint32_t*)(memory+address);
}
#define GPTR(address) (memory+(uint32_t)(address))
#define MEM32(address) (*memory32((uint32_t)(address)))
static int lock_depth;
static void pthread_mutex_lock(pthread_mutex_t *m) {(void)m;assert(!lock_depth);++lock_depth;}
static void pthread_mutex_unlock(pthread_mutex_t *m) {(void)m;assert(lock_depth==1);--lock_depth;}

typedef struct {uint32_t field,value;int kind,key;} edit;
static edit edits[2048];
static unsigned edit_count,focus_calls,callback_count;
static uint32_t mock_field,mock_epoch=1,callback_generation;
static int mock_kind=1,callback_enabled;
static unsigned change_after;
static int change_mode,cancel_after;
static uint32_t keys[8];
static int key_down[8];
static unsigned key_count;
static unsigned state_calls,getter_calls;
static uint32_t state_generation,state_count,state_caret;
static uint16_t state_text[4096];
static int getter_change,model_edits,cancel_on_state;
static uint32_t getter_vector=0x18010;
uint32_t void_touch_text_cancel(void);

static int void_dispatch_find(uint32_t method) {return method==0x00C88007u;}
static uint32_t void_call_guest_this(uint32_t method,uint32_t this_ptr,int count,const uint32_t *args) {
    assert(!lock_depth&&method==0x00C88007u&&this_ptr==mock_field+0xF8&&!count&&!args);
    ++getter_calls;
    if(getter_change==1)mock_field+=0x100;
    else if(getter_change==2)++mock_epoch;
    else if(getter_change==3)void_touch_text_cancel();
    else if(getter_change==4)++mock_kind;
    return getter_vector;
}
static void model_edit(uint32_t field,int kind,int key,uint32_t value) {
    uint32_t vector=kind==1?field+0x134:getter_vector;
    uint32_t begin=MEM32(vector),count=(MEM32(vector+4)-begin)/2;
    uint16_t *text=(uint16_t*)GPTR(begin);
    uint32_t caret=MEM32(field+(kind==1?0x11C:0x120));
    assert(caret<=count&&count<4096);
    if(key&&(value==8||value==46)) {
        if(value==8&&caret) {--caret;memmove(text+caret,text+caret+1,(count-caret-1)*2);--count;}
        else if(value==46&&caret<count) {memmove(text+caret,text+caret+1,(count-caret-1)*2);--count;}
    } else if(!key&&value!='#') {
        memmove(text+caret+1,text+caret,(count-caret)*2);text[caret++]=(uint16_t)value;++count;
    }
    MEM32(vector+4)=begin+count*2;MEM32(field+(kind==1?0x11C:0x120))=caret;
}

static int void_touch_text_focus(uint32_t *field,int *kind,uint32_t *epoch) {
    assert(!lock_depth);++focus_calls;
    *field=mock_field;*kind=mock_kind;*epoch=mock_epoch;return mock_field!=0;
}
static void void_touch_text_dispatch(uint32_t field,int kind,int key,uint32_t value) {
    assert(!lock_depth&&edit_count<2048);
    edits[edit_count++]=(edit){field,value,kind,key};
    if(model_edits)model_edit(field,kind,key,value);
    if(edit_count==change_after) {
        if(change_mode==1)mock_field+=0x100;
        else if(change_mode==2)++mock_kind;
        else if(change_mode==3)++mock_epoch;
        else mock_field=0;
    }
    if(cancel_after&&(int)edit_count==cancel_after)void_touch_text_cancel();
}
static void void_input_key(uint32_t key,int down) {
    assert(!lock_depth&&key_count<8);keys[key_count]=key;key_down[key_count++]=down;
}
void void_android_text_focus(int enabled,uint32_t generation) {
    assert(!lock_depth);++callback_count;callback_enabled=enabled;callback_generation=generation;
}
void void_android_text_state(uint32_t generation,const uint16_t *text,uint32_t count,uint32_t caret) {
    assert(!lock_depth&&count<=4096&&caret<=count);
    assert((uintptr_t)text<(uintptr_t)memory||(uintptr_t)text>=(uintptr_t)(memory+sizeof memory));
    ++state_calls;state_generation=generation;state_count=count;state_caret=caret;
    memcpy(state_text,text,count*sizeof text[0]);
    if(cancel_on_state)void_touch_text_cancel();
}
#include "cp1251_impl.h"
#include "touch_text_impl.h"

static void clear_observations(void) {
    edit_count=focus_calls=callback_count=key_count=0;
    state_calls=getter_calls=0;
    change_after=0;change_mode=cancel_after=0;
    memset(edits,0,sizeof edits);memset(keys,0,sizeof keys);memset(key_down,0,sizeof key_down);
}
static void reset(void) {
    mock_field=0;mock_kind=1;mock_epoch=1;
    unreadable_start=unreadable_end=0;getter_change=model_edits=cancel_on_state=0;
    getter_vector=0x18010;memset(memory,0,sizeof memory);
    void_touch_text_cancel();void_touch_text_pump();clear_observations();
}
static uint32_t arm(uint32_t field,int kind,uint32_t epoch) {
    mock_field=field;mock_kind=kind;mock_epoch=epoch;
    void_touch_text_arm();
    assert(!callback_count&&!edit_count&&!key_count);
    void_touch_text_pump();
    assert(callback_count==1&&callback_enabled&&callback_generation);
    return callback_generation;
}
static void expect_edit(unsigned index,uint32_t field,int kind,int key,uint32_t value) {
    assert(index<edit_count&&edits[index].field==field&&edits[index].kind==kind);
    assert(edits[index].key==key&&edits[index].value==value);
}
static void test_explicit_arm_and_encoding(void) {
    const uint16_t word[]={'A',0x041F,0x0440,0x0438,0x0432,0x0435,0x0442,0x0401,0x0451,0x2116,0x20AC};
    reset();mock_field=0x1000;
    void_touch_text_pump();
    assert(!focus_calls&&!callback_count&&!edit_count);
    assert(!void_touch_text_enqueue(callback_generation,word,1));
    assert(!void_touch_text_key(callback_generation,8,1));
    uint32_t generation=arm(0x1000,1,7);
    uint16_t copy[sizeof word/sizeof word[0]];memcpy(copy,word,sizeof word);
    assert(void_touch_text_enqueue(generation,copy,(uint32_t)(sizeof copy/sizeof copy[0])));
    memset(copy,0,sizeof copy); /* The Android buffer need not survive until the VM pump. */
    assert(!edit_count&&!key_count);
    void_touch_text_pump();
    assert(edit_count==sizeof word/sizeof word[0]&&callback_count==1);
    for(unsigned i=0;i<edit_count;++i)expect_edit(i,0x1000,1,0,word[i]);
    for(unsigned byte=0;byte<256;++byte) {
        uint8_t encoded=0;uint16_t unit=void_ansi_to_u16((uint8_t)byte);
        assert(void_u16_to_ansi(unit,&encoded)&&encoded==byte);
    }
    unsigned queries=focus_calls;void_touch_text_pump();
    assert(focus_calls==queries+1&&callback_count==1&&!key_count);

    /* A pending explicit choice may become ready later; default focus alone cannot arm it. */
    reset();void_touch_text_arm();void_touch_text_pump();
    assert(callback_count==1&&!callback_enabled);
    assert(!void_touch_text_enqueue(callback_generation,word,1));
    mock_field=0x2000;void_touch_text_pump();
    assert(callback_count==2&&callback_enabled);
    assert(void_touch_text_enqueue(callback_generation,word,1));void_touch_text_pump();
    assert(edit_count==1);expect_edit(0,0x2000,1,0,'A');
}
static void test_generation_changes(void) {
    const uint16_t text[]={'A','B','C'};
    for(int mode=1;mode<=3;++mode) {
        reset();uint32_t old=arm(0x3000,1,10);
        assert(void_touch_text_enqueue(old,text,3));
        if(mode==1)mock_field=0x4000;
        else if(mode==2)mock_kind=2;
        else ++mock_epoch; /* A reused engine address still represents a new user choice. */
        void_touch_text_pump();
        assert(!edit_count&&callback_count==2&&callback_enabled&&callback_generation!=old);
        assert(!void_touch_text_enqueue(old,text,1)&&!void_touch_text_key(old,8,1));
        assert(void_touch_text_enqueue(callback_generation,text,1));void_touch_text_pump();
        assert(edit_count==1);expect_edit(0,mock_field,mock_kind,0,'A');
    }
    reset();uint32_t old=arm(0x3000,1,10);
    assert(void_touch_text_enqueue(old,text,3));mock_field=0;void_touch_text_pump();
    assert(!edit_count&&callback_count==2&&!callback_enabled&&callback_generation!=old);
    assert(!void_touch_text_enqueue(old,text,1));
}
static void test_per_character_focus_guard(void) {
    const uint16_t text[]={'A','B','C'};
    for(int mode=0;mode<=3;++mode) {
        reset();uint32_t generation=arm(0x5000,1,20);
        assert(void_touch_text_enqueue(generation,text,3));
        assert(void_touch_text_enqueue(generation,text,3));
        change_after=1;change_mode=mode;void_touch_text_pump();
        assert(edit_count==1&&!key_count);expect_edit(0,0x5000,1,0,'A');
        assert(!void_touch_text_enqueue(generation,text,1));
        unsigned queries=focus_calls;void_touch_text_pump();
        assert(edit_count==1&&focus_calls==queries&&callback_count==2&&!callback_enabled);
        assert(callback_generation!=generation);
    }
    reset();uint32_t generation=arm(0x5000,1,20);
    assert(void_touch_text_enqueue(generation,text,3));cancel_after=1;void_touch_text_pump();
    assert(edit_count==1);void_touch_text_pump();
    assert(callback_count==2&&!callback_enabled&&callback_generation!=generation);
}
static void test_atomic_validation_and_bounds(void) {
    const uint16_t valid[]={'V'},mixed[]={'A',0xD83D,0xDE00,'B'};
    const uint16_t cjk[]={'A',0x4E2D},controls[]={'A',0,'B'},newline[]={'A',10,'B'};
    uint16_t large[257];for(unsigned i=0;i<257;++i)large[i]=(uint16_t)('A'+i%26);
    reset();uint32_t generation=arm(0x6000,2,30);
    assert(void_touch_text_enqueue(generation,valid,1));
    assert(!void_touch_text_enqueue(generation,NULL,1));
    assert(!void_touch_text_enqueue(generation,valid,0));
    assert(!void_touch_text_enqueue(generation,large,257));
    assert(!void_touch_text_enqueue(generation,mixed,4));
    assert(!void_touch_text_enqueue(generation,cjk,2));
    assert(!void_touch_text_enqueue(generation,controls,3));
    assert(!void_touch_text_enqueue(generation,newline,3));
    assert(!void_touch_text_key(generation,65,1));
    assert(!void_touch_text_key(generation,8,0));
    assert(!void_touch_text_key(generation,46,257));
    assert(void_touch_text_enqueue(generation,valid,1));void_touch_text_pump();
    assert(edit_count==2);expect_edit(0,0x6000,2,0,'V');expect_edit(1,0x6000,2,0,'V');
    clear_observations();assert(void_touch_text_enqueue(generation,large,256));void_touch_text_pump();
    assert(edit_count==256);
    for(unsigned i=0;i<256;++i)expect_edit(i,0x6000,2,0,large[i]);
    clear_observations();assert(void_touch_text_key(generation,8,256));void_touch_text_pump();
    assert(edit_count==256);
    for(unsigned i=0;i<256;++i)expect_edit(i,0x6000,2,1,8);
}
static void test_queue_capacity_and_cancel(void) {
    reset();uint32_t generation=arm(0x7000,1,40);
    for(unsigned i=0;i<64;++i) {
        uint16_t value=(uint16_t)('A'+i%26);
        if(i&1)assert(void_touch_text_key(generation,46,1));
        else assert(void_touch_text_enqueue(generation,&value,1));
    }
    const uint16_t overflow[]={'!'};
    assert(!void_touch_text_enqueue(generation,overflow,1));
    assert(!void_touch_text_key(generation,8,1));void_touch_text_pump();
    assert(edit_count==64);
    for(unsigned i=0;i<64;++i)expect_edit(i,0x7000,1,(i&1)!=0,(i&1)?46:'A'+i%26);
    clear_observations();assert(void_touch_text_enqueue(generation,overflow,1));
    uint32_t cancelled=void_touch_text_cancel();
    assert(cancelled!=generation&&!edit_count&&!callback_count);
    assert(!void_touch_text_enqueue(generation,overflow,1));
    assert(!void_touch_text_enqueue(cancelled,overflow,1));
    assert(!void_touch_text_key(cancelled,8,1));void_touch_text_pump();
    assert(!edit_count&&!focus_calls&&callback_count==1&&!callback_enabled);
    assert(callback_generation==cancelled);
    uint32_t later=void_touch_text_cancel();void_touch_text_pump();
    assert(later!=cancelled&&callback_generation==later&&!callback_enabled);
    clear_observations();generation=arm(0x7000,1,41);
    assert(generation!=later&&void_touch_text_enqueue(generation,overflow,1));void_touch_text_pump();
    assert(edit_count==1);expect_edit(0,0x7000,1,0,'!');
}
static void test_edit_keys_and_enter(void) {
    const uint16_t text[]={'Z'};
    reset();uint32_t generation=arm(0x8000,2,50);
    assert(void_touch_text_key(generation,8,2));
    assert(void_touch_text_key(generation,46,3));void_touch_text_pump();
    assert(edit_count==5&&!key_count);
    for(unsigned i=0;i<5;++i)expect_edit(i,0x8000,2,1,i<2?8:46);
    clear_observations();assert(void_touch_text_enqueue(generation,text,1));
    assert(void_touch_text_key(generation,13,1));
    assert(void_touch_text_enqueue(generation,text,1));
    assert(void_touch_text_key(generation,8,1));void_touch_text_pump();
    assert(edit_count==1&&key_count==2);expect_edit(0,0x8000,2,0,'Z');
    assert(keys[0]==13&&key_down[0]==1&&keys[1]==13&&key_down[1]==0);
    assert(!void_touch_text_enqueue(generation,text,1));void_touch_text_pump();
    assert(callback_count==1&&!callback_enabled&&callback_generation!=generation);
    assert(edit_count==1&&key_count==2);
}
static void set_snapshot(uint32_t field,int kind,const uint16_t *text,uint32_t count,int32_t caret,int32_t start) {
    uint32_t vector=kind==1?field+0x134:getter_vector;
    if(kind==2) {MEM32(field+0xF8)=0x18000;MEM32(0x18004)=0x00C88007u;}
    MEM32(vector)=0x19000;MEM32(vector+4)=0x19000+count*2;
    if(count)memcpy(GPTR(0x19000),text,count*2);
    MEM32(field+(kind==1?0x11C:0x120))=(uint32_t)caret;
    if(kind==1)MEM32(field+0x130)=(uint32_t)start;
}
static void test_authoritative_snapshots(void) {
    const uint16_t text[]={'A',0x041F,0x00CF,0x4E2D,0xD83D,0xDE00};
    reset();set_snapshot(0x9000,1,text,6,2,3);
    uint32_t generation=arm(0x9000,1,60);
    assert(state_calls==1&&state_generation==generation&&state_count==6&&state_caret==5);
    assert(!memcmp(state_text,text,sizeof text)&&!getter_calls);
    clear_observations();void_touch_text_pump();assert(!state_calls);
    MEM32(0x9000+0x11C)=0;void_touch_text_pump();assert(state_calls==1&&state_caret==3);
    MEM32(0x9000+0x130)=0x7FFFFFFF;MEM32(0x9000+0x11C)=0x7FFFFFFF;
    void_touch_text_pump();assert(state_calls==2&&state_caret==6);
    MEM32(0x9000+0x130)=0x80000000u;void_touch_text_pump();assert(state_calls==3&&state_caret==0);
    /* Reading authoritative UTF16 must not reinterpret U+00CF as CP1251 Cyrillic. */
    assert(state_text[1]==0x041F&&state_text[2]==0x00CF&&state_text[3]==0x4E2D);
    clear_observations();generation=arm(0x9000,1,60);
    assert(state_calls==1&&state_generation==generation&&state_count==6);
    clear_observations();void_touch_text_cancel();void_touch_text_pump();assert(!state_calls&&!callback_enabled);

    reset();set_snapshot(0xA000,2,text,6,4,0);generation=arm(0xA000,2,61);
    assert(state_calls==1&&state_generation==generation&&state_count==6&&state_caret==4&&getter_calls==1);
    assert(!memcmp(state_text,text,sizeof text));
    clear_observations();void_touch_text_pump();assert(!state_calls&&getter_calls==1);
    MEM32(0xA000+0x120)=99;void_touch_text_pump();assert(state_calls==1&&state_caret==6);
    MEM32(0xA000+0x120)=0xFFFFFFFFu;void_touch_text_pump();assert(state_calls==1&&state_caret==6);
    MEM32(0xA000+0x120)=0;void_touch_text_pump();assert(state_calls==2&&state_caret==0);
    ((uint16_t*)GPTR(0x19000))[0]='B';void_touch_text_pump();assert(state_calls==3&&state_text[0]=='B');
}
static void test_filtered_edits_and_snapshots(void) {
    for(int kind=1;kind<=2;++kind) {
        const uint16_t committed[]={'A','#',0x0411},expected[]={'A',0x0411};
        reset();set_snapshot(0xB000,kind,NULL,0,0,0);
        uint32_t generation=arm(0xB000,kind,70);clear_observations();model_edits=1;
        assert(void_touch_text_enqueue(generation,committed,3));void_touch_text_pump();
        assert(edit_count==3&&state_calls==1&&state_count==2&&state_caret==2);
        assert(!memcmp(state_text,expected,sizeof expected));
        clear_observations();const uint16_t rejected[]={'#'};
        assert(void_touch_text_enqueue(generation,rejected,1));void_touch_text_pump();assert(!state_calls);
        assert(void_touch_text_key(generation,8,1));void_touch_text_pump();
        assert(state_calls==1&&state_count==1&&state_caret==1&&state_text[0]=='A');
        MEM32(0xB000+(kind==1?0x11C:0x120))=0;
        assert(void_touch_text_key(generation,46,1));void_touch_text_pump();
        assert(state_calls==2&&!state_count&&!state_caret);
    }
    reset();set_snapshot(0xB000,1,NULL,0,0,0);uint32_t generation=arm(0xB000,1,71);
    clear_observations();model_edits=1;change_after=1;change_mode=1;
    const uint16_t value[]={'A'};assert(void_touch_text_enqueue(generation,value,1));
    void_touch_text_pump();assert(edit_count==1&&!state_calls&&!void_touch_text_enqueue(generation,value,1));
}
static void test_snapshot_bounds_and_stale_getter(void) {
    static uint16_t large[4097];for(unsigned i=0;i<4097;++i)large[i]=(uint16_t)('A'+i%26);
    reset();set_snapshot(0xC000,1,large,4096,4096,0);arm(0xC000,1,80);
    assert(state_calls==1&&state_count==4096&&state_caret==4096&&!memcmp(state_text,large,8192));
    clear_observations();MEM32(0xC000+0x138)+=2;void_touch_text_pump();assert(!state_calls);
    for(int invalid=0;invalid<8;++invalid) {
        reset();set_snapshot(0xC000,1,large,3,2,0);arm(0xC000,1,81);clear_observations();
        if(invalid==0)MEM32(0xC000+0x134)=0x19001;
        else if(invalid==1)MEM32(0xC000+0x138)=0x18FFE;
        else if(invalid==2)MEM32(0xC000+0x138)=0x19007;
        else if(invalid==3)MEM32(0xC000+0x134)=0;
        else if(invalid==4) {unreadable_start=0x19000;unreadable_end=0x19006;}
        else if(invalid==5) {unreadable_start=0xC000;unreadable_end=0xC13C;}
        else if(invalid==6)mock_field=0xFFFFFFFCu;
        else mock_field=0xC001;
        void_touch_text_pump();assert(!state_calls);
    }
    for(int invalid=0;invalid<5;++invalid) {
        reset();set_snapshot(0xD000,2,large,3,2,0);arm(0xD000,2,82);clear_observations();
        if(invalid==0)MEM32(0xD000+0xF8)=0x18001;
        else if(invalid==1)MEM32(0x18004)=0x12345678;
        else if(invalid==2)getter_vector=0x18011;
        else if(invalid==3)getter_vector=0xFFFFFFFCu;
        else {unreadable_start=0xD120;unreadable_end=0xD124;}
        void_touch_text_pump();assert(!state_calls);
    }
    for(int mode=1;mode<=4;++mode) {
        reset();set_snapshot(0xE000,2,large,3,2,0);uint32_t generation=arm(0xE000,2,83);
        clear_observations();((uint16_t*)GPTR(0x19000))[0]='!';getter_change=mode;
        void_touch_text_pump();assert(getter_calls==1&&!state_calls);
        assert(!void_touch_text_key(generation,8,1));
    }
    reset();set_snapshot(0xE000,1,large,3,2,0);arm(0xE000,1,84);
    clear_observations();cancel_on_state=1;((uint16_t*)GPTR(0x19000))[0]='!';
    void_touch_text_pump();assert(state_calls==1);
    void_touch_text_pump();assert(!callback_enabled&&!lock_depth);
}
int main(void) {
    test_explicit_arm_and_encoding();test_generation_changes();test_per_character_focus_guard();
    test_atomic_validation_and_bounds();test_queue_capacity_and_cancel();test_edit_keys_and_enter();
    test_authoritative_snapshots();test_filtered_edits_and_snapshots();test_snapshot_bounds_and_stale_getter();
    assert(!lock_depth);
    puts("PASS native IME: bounded CP1251 edits, generation/focus guards, actual UTF16 snapshots/getter ABI, filtered text/caret changes, unchanged suppression, malformed ranges and stale callbacks");
    return 0;
}
'''


class TouchTextTest(unittest.TestCase):
    def test_actual_queue(self):
        source = (ROOT / "android/host/touch_text.c").read_text(encoding="utf-8")
        for name in ("host.h", "input.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', '')
        strings = (ROOT / "android/host/strings.c").read_text(encoding="utf-8")
        converters = strings[strings.index("static const uint16_t cp1251_high["):strings.index("uint8_t void_ansi_lower(")]
        compile_probe("touch_text", HARNESS, {"touch_text_impl.h": source, "cp1251_impl.h": converters})


if __name__ == "__main__":
    unittest.main()
