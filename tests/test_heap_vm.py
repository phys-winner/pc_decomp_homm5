"""Exercise real dlmalloc against the production guest VM, including unmaps."""
import unittest

from test_mmx_packed import CLANG
from test_static_tls import ROOT, compile_probe
from test_vm_pressure import HARNESS as VM_HARNESS


def harness(body):
    prefix = '#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#undef GPTR\n'
    prefix += VM_HARNESS[:VM_HARNESS.index('#include "vm_actual.h"')]
    # Heap creation holds heap_lock while the allocator enters vm_lock.
    prefix = prefix.replace('assert(!vm_locked);last_error=error;', 'last_error=error;')
    prefix = prefix.replace('assert(!*p && !vm_locked);*p=vm_locked=1;', 'assert(!*p);*p=1;')
    prefix = prefix.replace('assert(*p && vm_locked);*p=vm_locked=0;', 'assert(*p);*p=0;')
    prefix += '\n#define GVA(p) ((uint32_t)((unsigned char *)(p)-memory))\nstatic uint32_t g_cur_func;\n'
    return prefix + '\n#include "memory_actual.h"\nint main(void) {\n' + body + '\nreturn 0; }\n'


class HeapVmTest(unittest.TestCase):
    def probe(self, name, body):
        source = (ROOT/'android/host/memory.c').read_text(encoding='utf-8')
        source = source[source.index('#define PAGES'):]
        source = source.replace('#include "../../reference/dlmalloc/malloc.c"',
                                '#include "'+(ROOT/'reference/dlmalloc/malloc.c').as_posix()+'"')
        compile_probe(name, harness(body), {'memory_actual.h': source},
                      extra_flags=('/W0',), compiler_override=CLANG)

    def test_destroy_merged_segments_and_outstanding_large_blocks(self):
        self.probe('heap-vm-destroy', r'''
        for (unsigned mode=0;mode<2;++mode) {
            page_size=mode?16384:4096;assert(void_guest_reserve());
            uint32_t baseline=void_vm_available();
            for (unsigned cycle=0;cycle<64;++cycle) {
                uint32_t heap=void_heap_create(0,0), blocks[8];assert(heap);
                for (unsigned i=0;i<8;++i) {
                    blocks[i]=void_heap_alloc(heap,200000,0);assert(blocks[i]);MEM32(blocks[i])=i;
                }
                for (unsigned i=0;i<8;++i) assert(MEM32(blocks[i])==i);
                assert(void_heap_destroy(heap) && void_vm_available()==baseline);
                heap=void_heap_create(0,0);assert(heap);
                uint32_t large=void_heap_alloc(heap,5u*1024*1024,0);assert(large);
                MEM32(large)=0x12345678;
                assert(void_heap_destroy(heap) && void_vm_available()==baseline);
            }
        }
        puts("PASS actual dlmalloc: 4/16-KiB VM, 128 merged-segment destroys and 128 outstanding 5-MiB block destroys, all guest granules reclaimed");
        ''')

    def test_trim_and_failed_unmap_preserve_neighbors_and_win32_rules(self):
        self.probe('heap-vm-trim', r'''
        for (unsigned mode=0;mode<2;++mode) {
            page_size=mode?16384:4096;assert(void_guest_reserve());
            uint32_t baseline=void_vm_available(), heap=void_heap_create(0,0), blocks[8];assert(heap);
            uint32_t barrier=void_vm_alloc(0,0x10000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_);assert(barrier);
            MEM32(barrier)=0xAABBCCDD;
            for(unsigned i=0;i<8;++i){blocks[i]=void_heap_alloc(heap,200000,0);assert(blocks[i]);}
            for(unsigned i=0;i<8;++i)assert(void_heap_free(heap,blocks[i]));
            mspace space=heap_space(heap);
            assert(mspace_trim(space,0) && mspace_footprint(space)==512u*1024);
            assert(baseline-void_vm_available()==mspace_footprint(space)+0x10000 && MEM32(barrier)==0xAABBCCDD);
            assert(void_heap_destroy(heap) && void_vm_free(barrier,0,MEM_RELEASE_) && void_vm_available()==baseline);

            uint32_t a=void_vm_alloc(0x400000,0x80000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_);
            uint32_t b=void_vm_alloc(0x480000,0x40000,MEM_RESERVE_|MEM_COMMIT_,PAGE_READWRITE_);
            assert(a==0x400000 && b==0x480000);MEM32(a)=0xABCDEF12;MEM32(b)=0x98765432;
            uint32_t used=void_vm_available();fail_remap=1;
            assert(guest_sys_free(GPTR(a+0x40000),0x40000)==-1);
            assert(void_vm_available()==used && page_alloc[(a+0x40000)/4096]==a/4096);
            assert(void_vm_writable(a+0x40000,4) && MEM32(a)==0xABCDEF12 && MEM32(b)==0x98765432);
            assert(guest_sys_free(GPTR(a+0x40000),0x40000)==0);
            assert(void_vm_available()==used+0x40000 && !void_vm_readable(a+0x40000,4));
            assert(page_alloc[a/4096]==a/4096 && MEM32(a)==0xABCDEF12 && MEM32(b)==0x98765432);
            assert(!void_vm_free(a+0x10000,0,MEM_RELEASE_));
            assert(guest_sys_free(GPTR(a),0x10000)==-1);
            assert(guest_sys_free(GPTR(a),0x80000)==-1);
            assert(guest_sys_free(GPTR(a),0)==-1 && guest_sys_free(GPTR(a),SIZE_MAX)==-1);
            assert(guest_sys_free(GPTR(a+1),0x10000)==-1);
            assert(guest_sys_free(GPTR(GUEST_THUNK_BASE),0x10000)==-1);
            assert(void_vm_free(a,0,MEM_RELEASE_) && void_vm_free(b,0,MEM_RELEASE_));
            assert(void_vm_available()==baseline);
        }
        puts("PASS actual dlmalloc trim, heap-only suffix release, remap-failure rollback, adjacent data and public MEM_RELEASE rules on 4/16-KiB VM");
        ''')


if __name__ == '__main__':
    unittest.main()
