"""Execute the production pure affinity selector against big/LITTLE topologies."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define CPU_SETSIZE 64
typedef uint64_t cpu_set_t;
#define CPU_ZERO(p) (*(p)=0)
#define CPU_SET(i,p) (*(p)|=UINT64_C(1)<<(i))
/* ACTUAL */
static unsigned cases;
static void check(const long *c,int n,uint64_t automatic,uint64_t big,uint64_t next) {
    const uint64_t expected[]={automatic,big,next,0};
    for(int policy=RT_CORES_AUTO;policy<=RT_CORES_ANY;++policy) {
        cpu_set_t mask=UINT64_MAX;
        long selected=render_core_mask(c,n,policy,&mask);
        assert(mask==expected[policy] && (!!selected)==(mask!=0));
        for(int i=0;i<n;++i)if(mask&(UINT64_C(1)<<i))assert(c[i]==selected);
        ++cases;
    }
}
int main(void) {
    const long one_four_three[]={400,400,400,800,800,800,800,1024};
    const long four_four[]={400,400,400,400,1024,1024,1024,1024};
    const long two_six[]={400,400,400,400,400,400,1024,1024};
    const long one_three_four[]={400,400,400,400,800,800,800,1024};
    const long one_seven[]={400,400,400,400,400,400,400,1024};
    const long uniform[]={1024,1024,1024,1024};
    const long unknown[]={400,0,1024},missing[]={400,-1,1024};
    const long four_tiers[]={200,400,700,1024};
    const long unordered[]={1024,400,400,1024,400,400,1024,400};
    check(one_four_three,8,0x78,0x80,0x78);
    check(four_four,8,0xF0,0xF0,0x0F);
    check(two_six,8,0xC0,0xC0,0x3F);
    check(one_three_four,8,0x70,0x80,0x70);
    check(one_seven,8,0x7F,0x80,0x7F);
    check(uniform,4,0,0,0);
    check(NULL,0,0,0,0);
    check(unknown,3,0,0,0);
    check(missing,3,0,0,0);
    check(four_tiers,4,0x04,0x08,0x04);
    check(unordered,8,0x49,0x49,0xB6);
    cpu_set_t mask=UINT64_MAX;
    assert(!render_core_mask(uniform,CPU_SETSIZE+1,RT_CORES_AUTO,&mask)&&!mask);
    printf("PASS render-core selection: %u topology/policy cases; unknown, empty and oversized tables leave scheduling alone\n",cases);
    return 0;
}
'''


class RenderThreadCoresTest(unittest.TestCase):
    def test_topologies_and_policy_overrides(self):
        source = (ROOT / "android/host/d3d9_thread.c").read_text()
        start = source.index("enum { RT_CORES_AUTO")
        enum = source[start:source.index(";", start) + 1]
        actual = enum + "\n" + function(source, "static long render_core_mask(")
        compile_probe("render_thread_cores", HARNESS.replace("/* ACTUAL */", actual), {})


if __name__ == "__main__":
    unittest.main()
