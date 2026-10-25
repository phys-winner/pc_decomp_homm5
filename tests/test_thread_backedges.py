"""Run mixed main/FMOD edge budgets across real atomic native thread handoffs."""
import unittest
from test_static_tls import compile_probe
from test_user32_startup import body
from test_fmod_yield import HARNESS, builder, production_fixture


MAIN = r'''
/* One process uses modules with different thresholds. These functions expand
   the identical production macro with the respective module's compile flag. */
#undef RECOMP_YIELD_EVERY
#define RECOMP_YIELD_EVERY 65536u
static void run_main_work(void) {
    RECOMP_REGS_LOCALS
    for(unsigned i=0;i<1024;++i) {l_eax+=i;RECOMP_BACKEDGE();}
    RECOMP_REGS_OUT();
}
#undef RECOMP_YIELD_EVERY
#define RECOMP_YIELD_EVERY 256u
static DWORD WINAPI decoder(void *unused) {
    (void)unused;t_self=&render[0];machine_acquire();void_regs_load(&render[0].regs);
    run_lifted(3*RECOMP_YIELD_EVERY,0);
    void_regs_save(&render[0].regs);machine_release();return 0;
}
int main(void) {
    (void)renderer;(void)sleep_ms;
    void_regs initial;initialize(&initial,0x12340000u);
    initialize(&render[0].regs,0x43210000u);assert(!render[0].regs.backedges);
    t_self=&audio;audio.depth=render[0].depth=1;
    machine_acquire();void_regs_load(&initial);recomp_yield_hook=yield_hook;
    HANDLE worker=CreateThread(NULL,0,decoder,NULL,0,NULL);assert(worker);queue_waiter(2);
    for(unsigned frame=0;frame<3;++frame) {
        run_main_work();assert(g_backedges==1024*(frame+1));
        void_regs before,after;memset(&before,0,sizeof before);memset(&after,0,sizeof after);
        void_regs_save(&before);yield_hook();
        int decoder_completed_turn_budget=owner_steps==RECOMP_YIELD_EVERY*(frame+1);
        assert(decoder_completed_turn_budget);
        void_regs_save(&after);assert(!memcmp(&before,&after,sizeof before));
        assert(!render[0].regs.backedges && audio.depth==1 && machine_contended());
    }
    /* Let the decoder return from its final yield and finish its function. */
    yield_hook();assert(!machine_contended() && g_backedges==3072 && !yields);
    machine_release();assert(WaitForSingleObject(worker,2000)==WAIT_OBJECT_0);CloseHandle(worker);
    puts("PASS actual mixed-module budget: main accumulates1024/2048/3072 edges; decoder completes256 edges each of3 turns; full main context/budget restored and new budget starts0");
    return 0;
}
'''


def fixture(old_global_budget=False):
    harness=HARNESS.replace(body(HARNESS,"int main(void)"),MAIN)
    result=production_fixture(harness)
    if old_global_budget:
        result=result.replace("    r->backedges = g_backedges;\n","")
        result=result.replace("    g_backedges = r->backedges;\n","")
    return result


def run_probe(name,source):
    compile_probe(name,source,{},extra_flags=("/O2","/DRECOMP_GENERATED_CODE","/DRECOMP_LOCAL_REGS",
                                           "/DRECOMP_YIELD_EVERY=256u"),
                  compiler_override=builder.TOOLCHAIN/"bin/clang-cl.exe")


class ThreadBackedgeTest(unittest.TestCase):
    def test_each_thread_keeps_its_module_budget_and_makes_progress(self):
        run_probe("thread_backedges",fixture())

    def test_prior_global_only_counter_starves_decoder_turn(self):
        with self.assertRaisesRegex(AssertionError,"decoder_completed_turn_budget"):
            run_probe("thread_backedges_old_global",fixture(old_global_budget=True))


if __name__=="__main__":unittest.main()
