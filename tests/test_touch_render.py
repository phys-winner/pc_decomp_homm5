"""Execute the production native render-scale request/reset/rollback path."""
from pathlib import Path
import unittest
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]

RESYNC_MAIN = r'''
int main(void){
 /* INITIALIZE */
 MEMF(0xF74BE8)=1024;MEMF(0xF74BEC)=768;
 unsigned char config[256];memset(config,0x5A,sizeof config);memcpy(GPTR(0xF490C0),config,sizeof config);
 void_touch_set_scale(1.25f);
 const int displays[][3]={{2688,1216,1698},{2399,1081,1705},{2340,1080,1664}};
 const int percentages[]={25,50,100},stale[][3]={{1920,1080,1366},{1024,768,1024}};
 for(unsigned display=0;display<3;++display)for(unsigned scale=0;scale<3;++scale)for(unsigned old=0;old<2;++old){
  fixture_physical_w=displays[display][0];fixture_physical_h=displays[display][1];
  int percent=percentages[scale];void_touch_set_render_scale(percent*.01f);
  unsigned width=(unsigned)(fixture_physical_w*percent+50)/100,height=(unsigned)(fixture_physical_h*percent+50)/100;
  set_size(width,height);
  MEMF(0xF74BF0)=(float)stale[old][0]*percent/100;MEMF(0xF74BF4)=(float)stale[old][1]*percent/100;
  MEMF(0xF74BE0)=(float)stale[old][2]/1.25f;MEMF(0xF74BE4)=768/1.25f;
  gesture_active=1;int old_ui=ui_resizes,old_aborts=aborts,old_layouts=scale_layouts;
  /* The actual scale pump cannot fix the stale physical geometry by itself. */
  float stale_w=MEMF(0xF74BE0),stale_h=MEMF(0xF74BE4);void_touch_scale_pump();
  assert(MEMF(0xF74BE0)==stale_w&&MEMF(0xF74BE4)==stale_h&&scale_layouts==old_layouts&&aborts==old_aborts);
  /* Loading, pending navigation and an unsafe owner must never initialize the UI early. */
  MEM32(0x22000)=0xE34674;pump();MEM32(0x22000)=0xE230E4;
  MEM32(0x40000)=0;pump();MEM32(0x40000)=0x40000;
  top=0;pump();top=0x22000;surface=0;pump();surface=1;
  thread=8;pump();thread=7;ui_mapped=0;pump();ui_mapped=1;ui_dispatch=0;pump();ui_dispatch=1;
  storage.in_scene=1;pump();storage.in_scene=0;storage.recording=&storage;pump();storage.recording=NULL;
  assert(ui_resizes==old_ui&&aborts==old_aborts&&gesture_active&&!resets&&!scene_ends);
  /* A remembered failure cannot suppress needed UI-only geometry recovery. */
  render_attempt.request=render_request;render_attempt.device=storage.com.guest;
  render_attempt.width=width;render_attempt.height=height;
  render_attempt.physical_w=fixture_physical_w;render_attempt.physical_h=fixture_physical_h;render_attempt.failed=1;
  pump();
  assert(ui_resizes==old_ui+1); /* Current matching-backbuffer early return fails here. */
  assert(aborts==old_aborts+1&&!gesture_active&&!resets&&!scene_ends&&!render_attempt.failed);
  assert(MEMF(0xF74BF0)==width&&MEMF(0xF74BF4)==height);
  assert(fixture_input_w==(int)width&&fixture_input_h==(int)height&&!memcmp(expected,GPTR(0x1002930),sizeof expected));
  void_touch_scale_pump();
  assert(scale_percent==125&&scale_layouts==old_layouts+1);
  assert(fabsf(MEMF(0xF74BE0)-(float)displays[display][2]/1.25f)<.0002f&&fabsf(MEMF(0xF74BE4)-614.4f)<.0002f);
  /* Pixel-to-UI uses the repaired physical dimensions, including off-centre cursor positions. */
  assert(fabsf((width*.73f)*MEMF(0xF74BE0)/MEMF(0xF74BF0)-MEMF(0xF74BE0)*.73f)<.0002f);
  assert(fabsf((height*.31f)*MEMF(0xF74BE4)/MEMF(0xF74BF4)-MEMF(0xF74BE4)*.31f)<.0002f);
  old_aborts=aborts;gesture_active=1;
  for(unsigned idle=0;idle<20;++idle){pump();void_touch_scale_pump();}
  assert(aborts==old_aborts&&gesture_active&&ui_resizes==old_ui+1&&scale_layouts==old_layouts+1&&!resets);
 }
 /* Even UI-only recovery rechecks callbacks before touching a changed owner/geometry. */
 for(int changed=1;changed<=5;++changed){
  fixture_physical_w=2688;fixture_physical_h=1216;void_touch_set_render_scale(.5f);set_size(1344,608);
  MEMF(0xF74BF0)=960;MEMF(0xF74BF4)=540;
  int old_ui=ui_resizes,old_aborts=aborts;gesture_active=1;abort_change=changed;
  pump();assert(ui_resizes==old_ui&&aborts==old_aborts+1&&!resets);
  abort_change=0;top=0x22000;surface=1;
  if(changed==3)MEM32(0x1002938)^=1;
 }
 assert(!memcmp(config,GPTR(0xF490C0),sizeof config));
 puts("PASS actual matching-BB render/UI resync: display2688x1216 and surface changes at25/50/100, stale16:9/4:3, actual125% scale restore/cursor basis, no D3DReset, abort-before-resize, safe-screen/callback guards and idempotence");
 return 0;
}
'''

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

    def matching_ui_fixture(self):
        from test_d3d_lifecycle import function
        source = (ROOT / "android/host/touch_render.c").read_text(encoding="utf-8")
        for name in ("d3d9_internal.h", "input.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', '')
        source = '\n'.join(line for line in source.splitlines()
                           if not line.startswith("extern int void_android_"))
        fixture = HARNESS[:HARNESS.index('int main(void){')]
        fixture = fixture.replace('static int aborts,resets,', 'static int gesture_active,scale_layouts;\nstatic int aborts,resets,', 1)
        fixture = fixture.replace('++aborts;', '++aborts;gesture_active=0;', 1)
        fixture = fixture.replace(')&&resets);', '));assert(!gesture_active);', 1)
        dispatch = function(fixture, 'static void_fn void_dispatch_find(')
        fixture = fixture.replace(dispatch, dispatch.replace('void_dispatch_find(', 'render_dispatch_find(', 1) + r'''
static void_fn void_dispatch_find(uint32_t a){
 if(a==0x8885D0||a==0xA50560)return NULL;
 if(a==0x66A4D0)return dispatch?dummy:NULL;
 return render_dispatch_find(a);
}
''')
        calls = function(fixture, 'static uint32_t void_call_guest(')
        fixture = fixture.replace(calls, calls.replace('void_call_guest(', 'render_guest_fixture(', 1) + r'''
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int pops){
 if(va==0x66A4D0){
  assert(!locked&&n==1&&args&&!args[0]&&pops&&!gesture_active);
  assert(MEMF(0xF74BF0)==fixture_input_w&&MEMF(0xF74BF4)==fixture_input_h);
  ++scale_layouts;return 0;
 }
 return render_guest_fixture(va,n,args,pops);
}
''')
        scale = (ROOT / 'android/host/touch_scale.c').read_text(encoding='utf-8')
        scale = (function(scale, 'void void_touch_set_scale(') +
                 function(scale, 'static int scale_pump(') + function(scale, 'void void_touch_scale_pump('))
        fixture += r'''
#define VLOG(...) ((void)0)
static pthread_mutex_t scale_lock;
static int scale_percent=100;
static uint32_t viewport_scratch;
static struct {uint32_t root;} viewport;
static struct {uint32_t screen;int requested,percent;} fit;
static struct {uint32_t screen,root;float width,height;} loading_layout;
static void_fn original_list_layout;
static void sub_00A50560(void){}
static void scale_list_layout(void){}
static void scale_layout_override(void){}
static void void_dispatch_add(uint32_t a,void_fn f){(void)a;(void)f;assert(0);}
static uint32_t scale_read32(uint32_t a){return void_vm_readable(a,4)?MEM32(a):0;}
static uint32_t scale_current_screen(void){return top;}
static void scale_refresh_text(void){}
static void void_touch_combat_frame(uint32_t s,float w,float h,float hud,float a,float b){
 (void)s;(void)w;(void)h;(void)hud;(void)a;(void)b;
}
static uint32_t void_galloc(uint32_t n){assert(n==16);return 0x80000;}
static int scale_viewport_ready(float w,float h){(void)w;(void)h;viewport.root=0x24000;return 1;}
static uint32_t scale_screen_root(uint32_t s){(void)s;return 0x24000;}
static int scale_is_root(uint32_t r){(void)r;return 1;}
static int scale_fits(uint32_t r,int a,float w,float h,float bw,float bh,int requested){
 (void)r;(void)a;(void)w;(void)h;(void)bw;(void)bh;return requested;
}
#include "touch_scale_impl.h"
'''
        initialization = HARNESS[HARNESS.index(' for(int i=0;i<14;i++)'):HARNESS.index(' unsigned char ui_and_config')]
        fixture += RESYNC_MAIN.replace(' /* INITIALIZE */', initialization)
        return fixture, {'touch_render_impl.h': source, 'touch_scale_impl.h': scale}

    def test_matching_backbuffer_resynchronizes_stale_ui_geometry(self):
        fixture, headers = self.matching_ui_fixture()
        compile_probe('touch_render_matching_ui', fixture, headers)

    def test_actual_legacy_matching_backbuffer_ui_resync(self):
        import re
        import sys
        from test_d3d_lifecycle import function
        sys.path.insert(0, str(ROOT / 'tools'))
        import port_patches
        # Original legacy data globals and parent-rectangle relayout ABI, independently pinned.
        originals = {
            'vanilla': ('00FC50C8', '00F07D54', '00F07D4C', '00AF8620', '00A77250', '00AF8E10', '00401040'),
            'hof': ('00F3D2F0', '00F24180', '00F24178', '00A35EE0', '00BE1C30', '00A366D0', '00884EF0'),
        }
        for edition, expected in originals.items():
            with self.subTest(edition=edition):
                fixture, _ = self.matching_ui_fixture()
                addresses = dict(port_patches.load_contract(edition)['addresses'])
                for key, value in zip(('01002930', '00F74BF0', '00F74BE0', '00487990', '00A504B0', '00488220', '008384D0'), expected):
                    self.assertEqual(addresses[key], value)
                addresses.update({'01002938': f"{int(addresses['01002930'],16)+8:08X}",
                                  '0002214C': '00022144', '0002314C': '00023144'})
                fixture = fixture.replace('ui_dispatch=0;pump();ui_dispatch=1;', '')
                fixture = fixture.replace('#include "touch_render_impl.h"',
                    'void void_touch_legacy_resize(uint32_t width,uint32_t height);\n#include "touch_render_impl.h"', 1)
                # The real legacy relayout visits one root through layout/children/next.
                callbacks = r'''
static int legacy_resize_active,legacy_layout_phase;
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args){
 unsigned phase=(unsigned)legacy_layout_phase++%3;
 assert(!gesture_active);
 if(phase==0){
  assert(va==0x487990&&self==0x24000&&n==1&&args&&args[0]==viewport_scratch);
  float *rect=(float *)GPTR(args[0]);
  assert(rect[0]==0&&rect[1]==0&&rect[2]==MEMF(0xF74BE0)&&rect[3]==MEMF(0xF74BE4));
  if(legacy_resize_active)++ui_resizes;else ++scale_layouts;
 }else if(phase==1)assert(va==0x488220&&self==0x24000-0xF8&&!n&&!args);
 else {assert(va==0x8384D0&&self==0x20000&&!n&&!args);return 0;}
 return 0;
}
'''
                fixture = fixture.replace('#include "touch_scale_impl.h"', callbacks + '#include "touch_scale_impl.h"' + r'''
void void_touch_legacy_resize(uint32_t width,uint32_t height){
 assert(!gesture_active&&(MEMF(0xF74BF0)!=width||MEMF(0xF74BF4)!=height));
 legacy_resize_active=1;legacy_resize_actual(width,height);legacy_resize_active=0;
}
''')
                fixture = fixture.replace(' MEMF(0xF74BE8)=1024;',
                    ' MEM32(0x22098)=0x24000;MEM32(0x24000)=0x70000;MEM32(0x70048)=0x487990;\n MEMF(0xF74BE8)=1024;', 1)
                fixture = re.sub(r'(0x|sub_)([0-9A-Fa-f]+)',
                    lambda m: m[1] + addresses.get(f'{int(m[2],16):08X}', m[2]), fixture)
                render, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_render.c',
                    ROOT / 'build/tests' / ('matching-render-' + edition), edition)
                source = render.read_text(encoding='utf-8')
                for name in ('d3d9_internal.h', 'input.h', 'touch.h'):
                    source = source.replace(f'#include "{name}"\n', '')
                source = '\n'.join(line for line in source.splitlines() if not line.startswith('extern int void_android_'))
                path, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_scale.c',
                    ROOT / 'build/tests' / ('matching-render-' + edition), edition)
                scale = path.read_text(encoding='utf-8')
                # Replace the two fixture root helpers with the actual mapped implementations.
                for signature in ('static uint32_t scale_screen_root(',):
                    fixture = fixture.replace(function(fixture, signature),
                        function(scale, 'static uint32_t scale_root(') + function(scale, signature))
                body = (function(scale, 'static uint32_t scale_virtual_base(') +
                        function(scale, 'void void_touch_legacy_root_rect(') +
                        function(scale, 'void void_touch_legacy_relayout(') +
                        function(scale, 'void void_touch_legacy_resize(').replace('void_touch_legacy_resize(', 'legacy_resize_actual(', 1) +
                        function(scale, 'void void_touch_set_scale(') + function(scale, 'static int scale_pump(') +
                        function(scale, 'void void_touch_scale_pump('))
                compile_probe('touch_render_matching_ui_' + edition, fixture,
                    {'touch_render_impl.h': source, 'touch_scale_impl.h': body})


if __name__ == "__main__":
    unittest.main()
