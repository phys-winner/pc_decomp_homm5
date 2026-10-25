"""Execute the production native render-scale request/reset/rollback path."""
from pathlib import Path
import unittest
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int locked;
static void pthread_mutex_lock(pthread_mutex_t *m) {(void)m;assert(!locked);locked=1;}
static void pthread_mutex_unlock(pthread_mutex_t *m) {(void)m;assert(locked);locked=0;}
enum {TOUCH_ABORT=10};
#define D3DERR_INVALIDCALL 0x8876086Cu
typedef struct {int kind;float x,y,dx,dy,scale,rotation;} void_touch_event;
typedef void (*void_fn)(void);
typedef struct {struct {uint32_t guest;} com;uint32_t window,pp[14];int in_scene;void *recording;} d3d_device;
static d3d_device storage,replacement,*g_d3d_device=&storage;
static struct {uint32_t max_texture;} d3d_gl_limits={8192};
static int mapped=1,writable=1,dispatch=1,surface=1,physical_valid=1;
static int fixture_physical_w=2944,fixture_physical_h=1840,fixture_input_w=1280,fixture_input_h=800;
static uint32_t module=0x400000,fixture_hwnd=0x101,thread=7,top=0x22000;
static int aborts,resets,queries,logs,fail_mode,fail_call,rollback_fail,abort_change,request_during_reset;
static int ui_mapped=1,ui_dispatch=1,ui_resizes,reset_updates_ui,notify_on_failure;
static int scene_ends,reset_opens_scene=1;
static uint32_t g_ecx,g_edx;
static uint32_t expected[14];
static char last_log[256];
static int physical_size(int*w,int*h){assert(!locked);*w=fixture_physical_w;*h=fixture_physical_h;return physical_valid;}
static int surface_ready(void){assert(!locked);return surface;}
static int (*void_android_display_size)(int*,int*)=physical_size;
static int (*void_android_render_ready)(void)=surface_ready;
static uint32_t void_module_exe_base(void){return module;}
static int void_vm_readable(uint32_t a,uint32_t n){return mapped&&a>0&&(uint64_t)a+n<=sizeof memory&&(ui_mapped||a!=0xF74BF0);}
static int void_vm_writable(uint32_t a,uint32_t n){return writable&&void_vm_readable(a,n);}
static void dummy(void){}
static void_fn void_dispatch_find(uint32_t a){if(!a)return NULL;assert(a==0xA3FFC0||a==0x8385A0||a==0xD119FC||a==0x90000||a==0x90004||a==0xB295D0);return dispatch&&(a!=0xB295D0||ui_dispatch)?dummy:NULL;}
static uint32_t void_window_main(void){return fixture_hwnd;}
static uint32_t void_window_thread(uint32_t h){assert(h==fixture_hwnd);return thread;}
static uint32_t void_thread_id(void){return 7;}
static void void_input_screen_size(int*w,int*h){*w=fixture_input_w;*h=fixture_input_h;}
static void void_touch_engine_event(const void_touch_event*e){
 assert(!locked&&e->kind==TOUCH_ABORT&&e->scale==1);
 assert(!memcmp(expected,GPTR(0x1002930),sizeof expected));++aborts;
 if(abort_change==1)top=0x23000;
 if(abort_change==2)surface=0;
 if(abort_change==3)MEM32(0x1002938)^=1;
 if(abort_change==4)fixture_physical_w++;
 if(abort_change==5)fixture_input_w++;
}
static void void_log(const char*format,...){va_list a;va_start(a,format);vsnprintf(last_log,sizeof last_log,format,a);va_end(a);++logs;}
void void_touch_set_render_scale(float scale);
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t*args,int pops){
 assert(!locked);
 if(va==0x90004) {
  assert(n==1&&args[0]==storage.com.guest&&pops==1&&storage.in_scene&&!storage.recording);
  storage.in_scene=0;++scene_ends;return 0;
 }
 if(va==0x8385A0){assert(!n&&!args&&pops==1);++queries;return top?0x20000:0;}
 if(va==0xD119FC){assert(n==5&&args&&!pops&&args[0]==0x20024&&!args[1]&&args[2]==0xF272C0&&args[3]==0xF323A8&&!args[4]);return top;}
 if(va==0xB295D0){
  assert(!n&&!args&&pops==1&&g_ecx==storage.pp[0]&&g_edx==storage.pp[1]);
  assert((MEMF(0xF74BF0)!=(float)g_ecx||MEMF(0xF74BF4)!=(float)g_edx)&&resets);
  MEMF(0xF74BF0)=(float)g_ecx;MEMF(0xF74BF4)=(float)g_edx;++ui_resizes;return 0;
 }
 assert(va==0xA3FFC0&&!n&&!args&&pops==1&&aborts);
 assert(surface&&!storage.in_scene&&!storage.recording);++resets;
 for(int i=2;i<14;i++)assert(MEM32(0x1002930+4*i)==expected[i]);
 uint32_t width=MEM32(0x1002930),height=MEM32(0x1002934);
 memcpy(storage.pp,GPTR(0x1002930),sizeof storage.pp);fixture_input_w=(int)width;fixture_input_h=(int)height;
 storage.in_scene=reset_opens_scene; /* Actual A3FFC0 returns after its final BeginScene. */
 if(reset_updates_ui||(notify_on_failure&&resets==fail_call)){MEMF(0xF74BF0)=(float)width;MEMF(0xF74BF4)=(float)height;}
 if(resets==fail_call){
  if(fail_mode==1){MEM32(0x1002954)=0xCAFE;return 0x88760868u;}
  if(fail_mode==2){fixture_input_w--;return 0;}
  if(fail_mode==3){storage.pp[0]--;return 0;}
  if(fail_mode==4){MEM32(0x1002930)--;return 0;}
  if(fail_mode==5)return 1; /* Positive/nonzero native recreation result is also failure. */
  if(fail_mode==7){
   replacement=storage;g_d3d_device=&replacement;
   MEM32(0x1002930)=replacement.pp[0]=777;MEM32(0x1002934)=replacement.pp[1]=555;
   fixture_input_w=777;fixture_input_h=555;return 0;
  }
  if(fail_mode==6){
   MEM32(0x10029A8)=storage.com.guest=0x32000;MEM32(0x32000)=0x31000;
   MEM32(0x1002930)=storage.pp[0]=777;MEM32(0x1002934)=storage.pp[1]=555;
   fixture_input_w=777;fixture_input_h=555;return 0x88760868u;
  }
 }
 if(rollback_fail&&resets==fail_call+1)return 0x8876086Au;
 if(request_during_reset){request_during_reset=0;void_touch_set_render_scale(.75f);}
 return 0;
}
#include "touch_render_impl.h"
static void expect_current(void){memcpy(expected,GPTR(0x1002930),sizeof expected);}
static void set_size(uint32_t w,uint32_t h){MEM32(0x1002930)=w;MEM32(0x1002934)=h;storage.pp[0]=w;storage.pp[1]=h;fixture_input_w=(int)w;fixture_input_h=(int)h;MEMF(0xF74BF0)=(float)w;MEMF(0xF74BF4)=(float)h;expect_current();}
static void pump(void){expect_current();void_touch_render_pump();}
static void idle(void){int old_aborts=aborts,old_resets=resets;pump();assert(aborts==old_aborts&&resets==old_resets);}
int main(void){
 for(int i=0;i<14;i++)MEM32(0x1002930+4*i)=0x100u+(unsigned)i;
 MEM32(0x1002938)=22;MEM32(0x100294C)=fixture_hwnd;
 storage.com.guest=0x30000;storage.window=fixture_hwnd;
 MEM32(0x30000)=0x31000;MEM32(0x31040)=0x90000;MEM32(0x310A8)=0x90004;
 MEM32(0x10029A8)=storage.com.guest;MEM8(0x1002991)=1;MEM32(0x10024FC)=fixture_hwnd;
 MEM32(0xFE719C)=0x10000;MEM32(0x20004)=0x8000;MEM32(0x8004)=0x20;
 MEM32(0x22000)=MEM32(0x23000)=0xE230E4;
 MEM32(0x2214C)=0x40000;MEM32(0x40000)=0x40000;
 MEM32(0x2314C)=0x41000;MEM32(0x41000)=0x41000;
 memcpy(storage.pp,GPTR(0x1002930),sizeof storage.pp);set_size(1280,800);
 unsigned char ui_and_config[256];memset(ui_and_config,0x5A,sizeof ui_and_config);
 memcpy(GPTR(0xF490C0),ui_and_config,sizeof ui_and_config);
 memcpy(GPTR(0xF74BE0),ui_and_config,32);memcpy(GPTR(0x10268C4),ui_and_config,8);
 /* Setter records only. Pause/surface loss, startup and all incomplete states defer. */
 void_touch_set_render_scale(.5f);assert(!aborts&&!resets);
 surface=0;idle();surface=1;
 void_android_render_ready=NULL;idle();void_android_render_ready=surface_ready;
 void_android_display_size=NULL;idle();void_android_display_size=physical_size;
 module=0;idle();module=0x400000;mapped=0;idle();mapped=1;writable=0;idle();writable=1;
 dispatch=0;idle();dispatch=1;MEM8(0x1002991)=0;idle();MEM8(0x1002991)=1;
 ui_mapped=0;idle();ui_mapped=1;ui_dispatch=0;idle();ui_dispatch=1;
 fixture_hwnd=0;idle();fixture_hwnd=0x101;thread=8;idle();thread=7;
 MEM32(0x10024FC)=0;idle();MEM32(0x10024FC)=fixture_hwnd;
 MEM32(0x100294C)=0;idle();MEM32(0x100294C)=fixture_hwnd;
 MEM32(0x10029A8)=0;idle();MEM32(0x10029A8)=storage.com.guest;
 g_d3d_device=NULL;idle();g_d3d_device=&storage;
 storage.in_scene=1;idle();storage.in_scene=0;storage.recording=&storage;idle();storage.recording=NULL;
 storage.com.guest++;idle();storage.com.guest--;
 storage.window++;idle();storage.window--;
 MEM32(0x31040)=0;idle();MEM32(0x31040)=0x90000;
 physical_valid=0;idle();physical_valid=1;fixture_physical_w=0;idle();fixture_physical_w=2944;
 fixture_physical_h=-1;idle();fixture_physical_h=1840;d3d_gl_limits.max_texture=1024;idle();d3d_gl_limits.max_texture=8192;
 fixture_input_w--;idle();fixture_input_w++;storage.pp[0]--;idle();storage.pp[0]++;
 MEM32(0x1002930)=0;idle();MEM32(0x1002930)=1280;
 MEM32(0x22000)=0xE34674;idle();MEM32(0x22000)=0xE230E4;
 MEM32(0x40000)=0;idle();MEM32(0x40000)=0x40000;
 top=0;idle();top=0x22000;MEM32(0xFE719C)=0;idle();MEM32(0xFE719C)=0x10000;
 assert(!aborts&&!resets&&!logs);
 pump();assert(aborts==1&&resets==1&&logs==1);
 assert(scene_ends==1&&!storage.in_scene);
 assert(ui_resizes==1&&MEMF(0xF74BF0)==1472&&MEMF(0xF74BF4)==920);
 assert(fixture_input_w==1472&&fixture_input_h==920&&strstr(last_log,"render-scale=50%"));
 for(int i=2;i<14;i++)assert(MEM32(0x1002930+4*i)==expected[i]);
 for(int i=0;i<20;i++)idle();assert(resets==1);
 assert(!memcmp(GPTR(0xF490C0),ui_and_config,256)&&!memcmp(GPTR(0xF74BE0),ui_and_config,16)&&!memcmp(GPTR(0x10268C4),ui_and_config,8));
 reset_updates_ui=1;int old_ui=ui_resizes;
 void_touch_set_render_scale(-1);pump();assert(fixture_input_w==736&&fixture_input_h==460&&ui_resizes==old_ui);reset_updates_ui=0;
 int before=resets;void_touch_set_render_scale(NAN);void_touch_set_render_scale(INFINITY);idle();assert(resets==before);
 void_touch_set_render_scale(100);pump();assert(fixture_input_w==2944&&fixture_input_h==1840);
 set_size(1280,800);d3d_gl_limits.max_texture=2048;idle(); /* Desired full size exceeds the device. */
 void_touch_set_render_scale(.5f);pump();assert(fixture_input_w==1472&&fixture_input_h==920); /* A larger display can still render below its limit. */
 d3d_gl_limits.max_texture=8192;void_touch_set_render_scale(1);pump();
 /* An original game resize is corrected once; a physical resize gets a fresh target. */
 set_size(1280,800);pump();assert(fixture_input_w==2944&&fixture_input_h==1840);
 fixture_physical_w=2399;fixture_physical_h=1501;void_touch_set_render_scale(.55f);pump();assert(fixture_input_w==1319&&fixture_input_h==826);
 idle();fixture_physical_w=2944;fixture_physical_h=1840;
 /* HRESULT failure or a lying successful Reset restores all14DWORDs and input. */
 for(int mode=1;mode<=5;mode++){
  set_size(1280,800);void_touch_set_render_scale(.5f);fail_mode=mode;fail_call=resets+1;
  notify_on_failure=1;old_ui=ui_resizes;
  int count=resets;pump();assert(resets==count+2&&fixture_input_w==1280&&fixture_input_h==800&&!storage.in_scene);
  assert(ui_resizes==old_ui+1&&MEMF(0xF74BF0)==1280&&MEMF(0xF74BF4)==800);notify_on_failure=0;
  assert(!memcmp(expected,GPTR(0x1002930),sizeof expected));assert(strstr(last_log,"rejected"));
  for(int i=0;i<20;i++)idle();assert(resets==count+2);fail_mode=0;
 }
 /* Explicitly repeating a failed request permits one retry, never a frame-loop storm. */
 void_touch_set_render_scale(.5f);pump();assert(fixture_input_w==1472&&fixture_input_h==920);
 set_size(1280,800);void_touch_set_render_scale(.5f);fail_mode=1;fail_call=resets+1;pump();fail_mode=0;
 fixture_physical_w=3000;fixture_physical_h=1800;pump();assert(fixture_input_w==1500&&fixture_input_h==900);
 fixture_physical_w=2944;fixture_physical_h=1840;pump();assert(fixture_input_w==1472&&fixture_input_h==920);
 set_size(1280,800);void_touch_set_render_scale(.5f);fail_mode=1;fail_call=resets+1;rollback_fail=1;
 int count=resets;pump();assert(resets==count+2&&strstr(last_log,"rollback=8876086A"));
 for(int i=0;i<20;i++)idle();assert(resets==count+2);fail_mode=rollback_fail=0;
 /* Reset replacing its owner must not receive the previous owner's PP snapshot. */
 set_size(1280,800);void_touch_set_render_scale(.5f);fail_mode=6;fail_call=resets+1;count=resets;
 pump();assert(resets==count+1&&MEM32(0x1002930)==777&&MEM32(0x1002934)==555);
 fail_mode=0;MEM32(0x10029A8)=storage.com.guest=0x30000;storage.in_scene=0;
 /* A new native host owner with the SAME guest COM address is also foreign. */
 set_size(1280,800);void_touch_set_render_scale(.5f);fail_mode=7;fail_call=resets+1;count=resets;
 int before_ends=scene_ends;
 pump();assert(resets==count+1&&scene_ends==before_ends&&g_d3d_device==&replacement);
 assert(MEM32(0x1002930)==777&&MEM32(0x1002934)==555&&replacement.in_scene==1);
 fail_mode=0;g_d3d_device=&storage;storage.in_scene=0;
 /* A native abort callback changing owner/focus/PP cannot reset the wrong state. */
 for(int changed=1;changed<=5;changed++){
  set_size(1280,800);void_touch_set_render_scale(.5f);abort_change=changed;
  count=resets;pump();assert(resets==count);abort_change=0;top=0x22000;surface=1;
  if(changed==3)MEM32(0x1002938)^=1;
  if(changed==4)fixture_physical_w--;
 }
 /* A UI-thread request arriving during reset is retained for the next owner pump. */
 set_size(1280,800);
 request_during_reset=1;pump();assert(fixture_input_w==1472&&fixture_input_h==920);
 pump();assert(fixture_input_w==2208&&fixture_input_h==1380);idle();
 assert(!memcmp(GPTR(0xF490C0),ui_and_config,256));
 /* If nativeReset returns with no open scene, do not invent an EndScene call. */
 reset_opens_scene=0;int old_ends=scene_ends;
 void_touch_set_render_scale(.5f);pump();assert(!storage.in_scene&&scene_ends==old_ends);
 puts("PASS actual render-scale: record-only25..100, readiness/capabilities/owner, nativeReset ABI, fullPP rollback, originalUIresize, failure backoff, resize and concurrent request, no direct config/UI writes");
 return 0;
}
'''


class TouchRenderTest(unittest.TestCase):
    def test_native_reset_request_and_rollback(self):
        source = (ROOT / "android/host/touch_render.c").read_text(encoding="utf-8")
        for name in ("d3d9_internal.h", "input.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', '')
        source = '\n'.join(line for line in source.splitlines()
                           if not line.startswith("extern int void_android_"))
        compile_probe("touch_render", HARNESS, {"touch_render_impl.h": source})


if __name__ == "__main__":
    unittest.main()
