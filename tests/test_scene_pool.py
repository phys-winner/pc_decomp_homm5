"""Execute the whole production 16-byte pool helper and its ownership/type guards."""
import re
import sys
import tempfile
import unittest

from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / 'tools'))
from port_patches import adapt_host_source, load_contract, source_digest
from editions import generated_root

# Independently checked original PE RTTI, allocator globals and TLS field layout.
CANONICAL = ('00E7B68C', '00E7B64C', '00E7B62C', '010E5674', '00FEAB20',
             '00FEAB28', '00FE9740', '00FE9F40', '00FEA740', '00FEA944')
PROVEN = {
    'toe': (CANONICAL, 4, '00FEAB34'),
    'vanilla': (('00E3CAB4', '00E3CA74', '00E3CA54', '0110E6C0', '011095BC',
                 '011095B0', '01108350', '01108B50', '01109350', '01109554'), 8, '011095C0'),
    'hof': (('00DCF814', '00DCF7D4', '00DCF7B0', '010BCDB4', '01038F18',
             '01038F20', '01037B38', '01038338', '01038B38', '01038D3C'), 8, '01038F2C'),
}
SEAMS = {
    'toe': ('00B1F9E0', '00AA5160', '00B1FA39', 'game_0558.c'),
    'vanilla': ('0095BD60', '0093BFB0', '0095BDB9', 'game_0435.c'),
    'hof': ('004F8220', '009373C0', '004F8279', 'game_0086.c'),
}


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum { MIB=0x100000, MEMORY_BYTES=34*MIB, MAX_FREE=31*4096, NODES=12925 };
static uint8_t memory[MEMORY_BYTES], snapshot[MEMORY_BYTES];
static uint32_t slot_starts[512],slot_cursors[512],ordered[MAX_FREE],shuffled[MAX_FREE];
static uint32_t old_nodes[NODES],new_nodes[NODES];
static uint8_t slot_classes[512];
static uint32_t test_base,fixture_pool,class_head,free_count,denied_low,denied_high;
static uint32_t write_denied_low,write_denied_high;
static int fail_allocation,change_head_on_allocate,change_head_on_sort;
static uint32_t g_fs_base;
static unsigned log_calls;
static void void_log(const char *format,...) {(void)format;++log_calls;}
#define GPTR(p) (memory+(uint32_t)((p)-test_base))
#define MEM32(p) (*(uint32_t *)GPTR(p))
static int void_vm_readable(uint32_t address,uint32_t size) {
    return address>=test_base && (uint64_t)address+size<=(uint64_t)test_base+sizeof memory &&
        !(denied_high && address<denied_high && (uint64_t)address+size>denied_low);
}
static int void_vm_writable(uint32_t address,uint32_t size) {
    return void_vm_readable(address,size) &&
        !(write_denied_high && address<write_denied_high && (uint64_t)address+size>write_denied_low);
}
static void *candidate_malloc(size_t size) {
    if(change_head_on_allocate) MEM32(class_head)=0;
    return fail_allocation?NULL:malloc(size);
}
static void candidate_qsort(void *data,size_t count,size_t size,int (*compare)(const void *,const void *)) {
    qsort(data,count,size,compare);
    if(change_head_on_sort) MEM32(class_head)=0;
}
#define malloc candidate_malloc
#define qsort candidate_qsort
#include "actual.h"
#undef malloc
#undef qsort

static uint32_t random_state;
static uint32_t random_next(void) {
    random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;
    return random_state;
}
static void put(uint8_t *data,uint32_t address,uint32_t value) {
    memcpy(data+(uint32_t)(address-test_base),&value,4);
}
static uint32_t get(const uint8_t *data,uint32_t address) {
    uint32_t value;memcpy(&value,data+(uint32_t)(address-test_base),4);return value;
}
static void setup(uint32_t base) {
    test_base=base;fixture_pool=base+MIB;class_head=base+0x100;
    denied_low=denied_high=0;fail_allocation=change_head_on_allocate=change_head_on_sort=0;free_count=0;
    write_denied_low=write_denied_high=0;
    memset(memory,0xA5,sizeof memory);memset(slot_classes,255,sizeof slot_classes);
    for(uint32_t i=0;i<512;i++) {slot_starts[i]=fixture_pool+i*MIB;slot_cursors[i]=slot_starts[i];}
    for(uint32_t i=0;i<31;i++) {
        slot_classes[i]=1;slot_cursors[i]+=0x10000;
        for(uint32_t j=0;j<4096;j++) {
            uint32_t address=slot_starts[i]+16*j;
            /* One quarter of committed blocks remain live and unavailable. */
            if((j&3u)!=0) ordered[free_count++]=address;
        }
    }
    memcpy(shuffled,ordered,free_count*sizeof ordered[0]);random_state=0x51A7A123;
    for(uint32_t i=free_count;i>1;i--) {
        uint32_t at=random_next()%i,t=shuffled[i-1];shuffled[i-1]=shuffled[at];shuffled[at]=t;
    }
    MEM32(class_head)=shuffled[0];
    for(uint32_t i=0;i<free_count;i++) MEM32(shuffled[i])=i+1<free_count?shuffled[i+1]:0;
    /* A foreign-free queue and live sentinel are intentionally outside the chain. */
    MEM32(base+0x200)=base+0x800;MEM32(base+0x800)=base+0x810;MEM32(base+0x810)=0;
    MEM32(base+0x400)=base+0x400;MEM32(base+0x404)=base+0x400;
}
static unsigned prefix_nodes(uint32_t out[NODES]) {
    uint32_t at=MEM32(class_head);unsigned same=0;
    for(unsigned i=0;i<NODES;i++) {
        assert(at);out[i]=at;
        if(i && out[i-1]/4096==at/4096) ++same;
        at=MEM32(at);
    }
    return same;
}
static void make_list(uint8_t *data,const uint32_t *nodes) {
    uint32_t sentinel=test_base+0x400;
    put(data,sentinel,nodes[0]);put(data,sentinel+4,nodes[NODES-1]);
    for(uint32_t i=0;i<NODES;i++) {
        put(data,nodes[i],i+1<NODES?nodes[i+1]:sentinel);
        put(data,nodes[i]+4,i?nodes[i-1]:sentinel);
        put(data,nodes[i]+8,0x50000000u+4*i);
    }
}
static void check_list_order(const uint8_t *data) {
    uint32_t sentinel=test_base+0x400,previous=sentinel,at=get(data,sentinel);
    for(uint32_t i=0;i<NODES;i++) {
        assert(at!=sentinel && get(data,at+4)==previous && get(data,at+8)==0x50000000u+4*i);
        previous=at;at=get(data,at);
    }
    assert(at==sentinel && get(data,sentinel+4)==previous);
}
static void expect_noop(void) {
    memcpy(snapshot,memory,sizeof memory);
    assert(scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes)==0);
    assert(!memcmp(memory,snapshot,sizeof memory));
}
static uint32_t setup_wrapper(void) {
    setup(0x10000u);
    uint32_t old_head=MEM32(class_head);
    class_head=0x00FEA944u;MEM32(class_head)=old_head;
    memcpy(GPTR(0x00FE9740u),slot_starts,sizeof slot_starts);
    memcpy(GPTR(0x00FE9F40u),slot_cursors,sizeof slot_cursors);
    memcpy(GPTR(0x00FEA740u),slot_classes,sizeof slot_classes);
    MEM32(0x00FEAB28u)=fixture_pool;MEM32(0x00FEAB20u)=0;
    MEM32(FOREIGN_HEAD)=test_base+0x800;
    MEM32(CACHED_HEAD)=class_head;MEM32(LAST_SIZE)=12;
    g_fs_base=0x40000u;MEM32(g_fs_base+0x2Cu)=0x50000u;
    MEM32(0x010E5674u)=3;MEM32(0x50000u+12)=0x60000u;
    MEM32(0x60004u)=0;MEM32(0x60008u)=0;MEM32(0x60000u+OWNER_OFFSET)=1;
    uint32_t root=0x20000u,sentinel=0x90000u;
    MEM32(root)=0x00E7B68Cu;MEM32(root+12)=0x00E7B64Cu;MEM32(root+268)=0x00E7B62Cu;
    MEM32(root+104)=sentinel;MEM32(sentinel)=sentinel;MEM32(sentinel+4)=sentinel;
    log_calls=0;return root+104;
}
static void wrapper_noop(uint32_t list) {
    log_calls=0;memcpy(snapshot,memory,sizeof memory);
    void_scene_pool_reorder(list);
    assert(!log_calls && !memcmp(memory,snapshot,sizeof memory));
}
static void wrapper_guards(void) {
    uint32_t list=setup_wrapper();memcpy(snapshot,memory,sizeof memory);
    put(snapshot,class_head,ordered[0]);
    for(uint32_t i=0;i<free_count;i++) put(snapshot,ordered[i],i+1<free_count?ordered[i+1]:0);
    void_scene_pool_reorder(list);
    assert(log_calls==1 && !memcmp(memory,snapshot,sizeof memory));
    for(unsigned guard=0;guard<24;guard++) {
        list=setup_wrapper();uint32_t root=list-104,sentinel=MEM32(list);
        switch(guard) {
        case 0:list=103;break;
        case 1:list=UINT32_MAX-4;break;
        case 2:MEM32(root)=0;break;
        case 3:MEM32(root+12)=0;break;
        case 4:MEM32(root+268)=0;break;
        case 5:MEM32(list)=UINT32_MAX-4;break;
        case 6:MEM32(sentinel)=sentinel+16;break;
        case 7:MEM32(sentinel+4)=sentinel+16;break;
        case 8:g_fs_base=0;break;
        case 9:MEM32(0x010E5674u)=64;break;
        case 10:MEM32(g_fs_base+0x2C)=0;break;
        case 11:MEM32(0x50000u+12)=0;break;
        case 12:MEM32(0x60000u+OWNER_OFFSET)=0;MEM32(0x60000u+(12u-OWNER_OFFSET))=1;break;
        case 13:MEM32(0x00FEAB20u)=1;break;
        case 14:denied_low=0x00FE9740u;denied_high=denied_low+4;break;
        case 15:denied_low=0x00FE9F40u;denied_high=denied_low+4;break;
        case 16:denied_low=0x00FEA740u;denied_high=denied_low+4;break;
        case 17:denied_low=class_head;denied_high=denied_low+4;break;
        case 18:denied_low=0x010E5674u;denied_high=denied_low+4;break;
        case 19:denied_low=0x00FEAB20u;denied_high=denied_low+4;break;
        case 20:write_denied_low=class_head;write_denied_high=write_denied_low+4;break;
        case 21:write_denied_low=slot_starts[0];write_denied_high=write_denied_low+4;break;
        case 22:denied_low=0x00FEAB28u;denied_high=denied_low+4;break;
        case 23:denied_low=0x60000u+OWNER_OFFSET;denied_high=denied_low+4;break;
        }
        wrapper_noop(list);
    }
    list=setup_wrapper();fail_allocation=1;wrapper_noop(list);
    list=setup_wrapper();MEM32(class_head)=0;wrapper_noop(list);
    puts("PASS whole production wrapper: exact success bytes; 24 type/empty-list/TLS-correct-offset/owner/lock/base/mapping/permission guards, OOM/empty no-ops, foreign queue/cached-head/last-request preserved");
}
int main(void) {
    setup(0x10000);unsigned old_same=prefix_nodes(old_nodes);
    assert(old_same<NODES/100); /* Old randomized LIFO is the negative control. */
    memcpy(snapshot,memory,sizeof memory);
    uint32_t result=scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes);
    assert(result==free_count);
    /* Independent address-order oracle: generated before randomizing links. */
    put(snapshot,class_head,ordered[0]);
    for(uint32_t i=0;i<free_count;i++)
        put(snapshot,ordered[i],i+1<free_count?ordered[i+1]:0);
    assert(!memcmp(memory,snapshot,sizeof memory));
    unsigned new_same=prefix_nodes(new_nodes);
    assert(new_same>98u*(NODES-1)/100u);
    uint32_t at=MEM32(class_head);
    for(uint32_t i=0;i<free_count;i++) {assert(at==ordered[i]);at=MEM32(at);}
    assert(!at); /* Every original free block remains reachable exactly once. */
    make_list(snapshot,old_nodes);make_list(memory,new_nodes);
    check_list_order(snapshot);check_list_order(memory);
    printf("PASS old randomized LIFO negative/new address locality: %u -> %u of %u same-page edges; exact free set, live bytes, payloads, foreign queue, and object/list order preserved\n",old_same,new_same,NODES-1);

    setup(0x10000);fail_allocation=1;expect_noop();
    setup(0x10000);MEM32(shuffled[0])=shuffled[0];expect_noop();
    setup(0x10000);MEM32(shuffled[1])=shuffled[0];expect_noop();
    setup(0x10000);MEM32(shuffled[2])=0x1234;expect_noop();
    setup(0x10000);MEM32(class_head)=fixture_pool+4;expect_noop();
    setup(0x10000);MEM32(class_head)=slot_starts[31];expect_noop();
    setup(0x10000);MEM32(class_head)=slot_starts[0]+0x10000;expect_noop();
    setup(0x10000);MEM32(class_head)=slot_starts[30]+MIB;expect_noop();
    setup(0x10000);MEM32(class_head)=fixture_pool+512u*MIB;expect_noop();
    setup(0x10000);slot_cursors[0]=slot_starts[0];expect_noop();
    setup(0x10000);slot_starts[0]+=16;expect_noop();
    setup(0x10000);slot_cursors[0]++;expect_noop();
    setup(0x10000);slot_cursors[0]=slot_starts[0]+MIB+0x10000;expect_noop();
    setup(0x10000);denied_low=class_head;denied_high=class_head+4;expect_noop();
    setup(0x10000);denied_low=slot_starts[0];denied_high=slot_starts[0]+4;expect_noop();
    setup(0x10000);write_denied_low=class_head;write_denied_high=write_denied_low+4;expect_noop();
    setup(0x10000);write_denied_low=slot_starts[0];write_denied_high=write_denied_low+4;expect_noop();
    setup(0x10000);memset(slot_classes,255,sizeof slot_classes);expect_noop();
    setup(0x10000);MEM32(class_head)=0;expect_noop();
    setup(0x10000);memcpy(snapshot,memory,sizeof memory);
    assert(!scene_pool_order_free16(0xF0000000,class_head,slot_starts,slot_cursors,slot_classes));
    assert(!memcmp(memory,snapshot,sizeof memory));
    setup(0x10000);memcpy(snapshot,memory,sizeof memory);change_head_on_allocate=1;
    put(snapshot,class_head,0); /* Only the injected external writer may change this word. */
    assert(!scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes));
    assert(!memcmp(memory,snapshot,sizeof memory));
    setup(0x10000);memcpy(snapshot,memory,sizeof memory);change_head_on_sort=1;put(snapshot,class_head,0);
    assert(!scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes));
    assert(!memcmp(memory,snapshot,sizeof memory));
    /* In the original metadata NULL cursor means a fully committed 1-MiB slot. */
    setup(0x10000);slot_cursors[0]=0;MEM32(class_head)=slot_starts[0]+MIB-16;MEM32(MEM32(class_head))=0;
    memcpy(snapshot,memory,sizeof memory);
    assert(scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes)==1);
    assert(!memcmp(memory,snapshot,sizeof memory));
    /* Unsigned ordering must remain correct across the 2-GiB boundary. */
    setup(0x7EF00000u);assert(fixture_pool==0x7F000000u);
    assert(scene_pool_order_free16(fixture_pool,class_head,slot_starts,slot_cursors,slot_classes)==free_count);
    at=MEM32(class_head);for(uint32_t i=0;i<free_count;i++) {assert(at==ordered[i]);at=MEM32(at);}assert(!at);
    puts("PASS full-byte failure no-ops: OOM, cycles, bad pointer/alignment/class/committed-end/slot-end/pool-end/cursor/permission, uncommitted cursor, changed head during malloc/qsort; NULL-full cursor and unsigned 2-GiB ordering");
    wrapper_guards();
    return 0;
}
'''


class ScenePoolTests(unittest.TestCase):
    def check_edition(self, edition):
        expected, owner_offset, foreign = PROVEN[edition]
        mappings = dict(zip(CANONICAL, expected))
        contract = load_contract(edition)
        self.assertEqual(contract['sources']['android/host/fastpool.c'],
                         source_digest(ROOT / 'android/host/fastpool.c'))
        reader, clear, call, unit = SEAMS[edition]
        original = f'    RECOMP_CALL(sub_{clear}); /* 0x{call}: call 0x{int(clear, 16):x} */'
        hooks = [patch for patch in contract['generated_patches'] if 'void_scene_pool_reorder' in patch['new']]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]['module'], 'game')
        self.assertEqual(hooks[0]['function'], 'sub_' + reader)
        self.assertEqual(hooks[0]['old'], original)
        self.assertEqual(hooks[0]['new'], original +
                         '\n    { extern void void_scene_pool_reorder(uint32_t); void_scene_pool_reorder(edi); }')
        generated = (generated_root(edition) / 'game-x86' / unit).read_text()
        begin = generated.index('void sub_' + reader + '(void) {')
        end = generated.index('\n}', begin) + 2
        self.assertEqual(generated[begin:end].count(original), 1)
        if edition != 'toe':
            self.assertTrue(set(CANONICAL) <= set(contract['reference_addresses']['android/host/fastpool.c']))
            self.assertEqual({address: contract['addresses'][address] for address in CANONICAL}, mappings)
        with tempfile.TemporaryDirectory() as temporary:
            adapted, _ = adapt_host_source(ROOT / 'android/host/fastpool.c', temporary, edition)
            source = adapted.read_text().replace('#include "host.h"', '')
        harness = re.sub(r'0x([0-9A-Fa-f]{8})(?![0-9A-Fa-f])',
                         lambda match: '0x' + mappings.get(match[1].upper(), match[1]), HARNESS)
        cache, last = {
            'toe': ('00FEAB30', '00F443E8'),
            'vanilla': ('011095B8', '00F5BF30'),
            'hof': ('01038F28', '00EFAB80'),
        }[edition]
        harness = (f'#define OWNER_OFFSET {owner_offset}u\n#define FOREIGN_HEAD 0x{foreign}u\n'
                   f'#define CACHED_HEAD 0x{cache}u\n#define LAST_SIZE 0x{last}u\n' + harness)
        compile_probe('scene_pool_' + edition, harness, {'actual.h': source}, extra_flags=('/O2',))

    def test_toe_actual_helper_and_wrapper(self):
        self.check_edition('toe')

    def test_vanilla_actual_adapted_helper_and_wrapper(self):
        self.check_edition('vanilla')

    def test_hof_actual_adapted_helper_and_wrapper(self):
        self.check_edition('hof')


if __name__ == "__main__":
    unittest.main()
