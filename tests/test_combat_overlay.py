"""Exercise the actual overlay state and JNI confirmation token without a device."""
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT
from test_static_tls import compile_probe


JAVA_PROBE = r'''
public class CombatOverlayCheck {
 static final int VISIBLE=0,GONE=8;
 static class Gravity {static final int BOTTOM=80,RIGHT=5;}
 static class LayoutParams {int gravity,rightMargin,bottomMargin;}
 static class Control {
  int visibility=GONE;boolean enabled=true;String text="",description="";
  LayoutParams position=new LayoutParams();int maxWidth;
  Object getLayoutParams(){return position;}void setLayoutParams(LayoutParams value){position=value;}
  void setMaxWidth(int value){maxWidth=value;}
  void setVisibility(int value){visibility=value;}int getVisibility(){return visibility;}
  void setEnabled(boolean value){enabled=value;}void setText(String value){text=value;}
  String getText(){return text;}void setContentDescription(String value){description=value;}
 }
 final Control confirm=new Control(),hint=new Control();
 boolean russian,running=true;int generation,hintEpoch,hintKind,dismissedEpoch,visibility;
 float uiScale=1,density=2.75f;int width=2340,height=1080;
 int getWidth(){return width;}int getHeight(){return height;}int dp(float value){return Math.round(value*density);}
 void setVisibility(int value){visibility=value;}
 /* ACTUAL */
 public static void main(String[] args) {
  CombatOverlayCheck ui=new CombatOverlayCheck();
  ui.update(0,0,0);assert ui.visibility==GONE&&ui.confirm.visibility==GONE&&ui.hint.visibility==GONE;
  ui.update(7,2,1);assert ui.confirm.visibility==VISIBLE&&ui.confirm.enabled;
  assert ui.hint.text.contains("melee")&&ui.hint.description.contains("Tap to hide");
  ui.confirm.enabled=false;ui.update(7,2,1);assert !ui.confirm.enabled;
  ui.update(8,2,1);assert ui.confirm.enabled;
  ui.dismissHint();assert ui.hint.visibility==GONE&&ui.visibility==VISIBLE;
  ui.update(8,2,1);assert ui.hint.visibility==GONE;
  ui.update(0,3,2);assert ui.hint.visibility==VISIBLE&&ui.hint.text.contains("without returning");
  assert ui.confirm.visibility==GONE;
  ui.setRunning(false);assert ui.visibility==GONE;
  ui.update(9,3,2);assert ui.visibility==GONE;
  ui.setRunning(true);assert ui.visibility==VISIBLE;
  ui.russian=true;ui.update(9,4,3);assert ui.hint.text.contains("без возвращения");
  ui.update(0,4,0);assert ui.visibility==GONE;
  ui.setRunning(false);ui.setRunning(true);assert ui.visibility==GONE;
  ui.update(0,5,1);ui.dismissHint();assert ui.visibility==GONE;
  ui.update(0,5,1);assert ui.hint.visibility==GONE;
   ui.update(0,5,0);assert ui.visibility==GONE;
   ui.update(0,5,1);assert ui.visibility==GONE&&ui.hint.visibility==GONE;
   ui.update(0,5,2);assert ui.visibility==GONE&&ui.hint.visibility==GONE;
   ui.update(10,5,3);assert ui.visibility==VISIBLE&&ui.hint.visibility==GONE;
   ui.update(0,5,3);assert ui.visibility==GONE;
  ui.update(0,6,1);assert ui.hint.visibility==VISIBLE;
  ui.positionControls(ui.width,ui.height);
  assert ui.confirm.position.gravity==(Gravity.BOTTOM|Gravity.RIGHT);
  assert ui.confirm.position.rightMargin==33&&ui.confirm.position.bottomMargin==292;
  ui.setUiScale(2);assert ui.confirm.position.bottomMargin==583;
  ui.setUiScale(.5f);assert ui.confirm.position.bottomMargin==146;
  ui.setUiScale(Float.NaN);assert ui.uiScale==1&&ui.confirm.position.bottomMargin==292;
  ui.width=1280;ui.height=720;ui.density=2;ui.positionControls(ui.width,ui.height);
  assert ui.confirm.position.rightMargin==24&&ui.confirm.position.bottomMargin==194;
  ui.setUiScale(100);assert ui.uiScale==2&&ui.confirm.position.bottomMargin==389;
  ui.height=180;ui.positionControls(ui.width,ui.height);assert ui.confirm.position.bottomMargin==60;
  System.out.println("PASS actual combat controls: token/repeat guard, hint epochs/dismissal/locales, lifecycle");
 }
}
'''


class CombatOverlayTest(unittest.TestCase):
    def test_overlay_state(self):
        source = (ROOT / "android/app/src/org/homm5/port/CombatOverlay.java").read_text(encoding="utf-8")
        methods = "\n".join(function(source, signature) for signature in (
            "    void update(", "    void setRunning(", "    void setUiScale(", "    private void positionControls("))
        dismiss = function(source, "        hint.setOnClickListener(view -> {")
        methods += "\nvoid dismissHint() {" + dismiss.split("{", 1)[1]
        out = ROOT / "build/tests/combat-overlay"
        out.mkdir(parents=True, exist_ok=True)
        src = out / "CombatOverlayCheck.java"
        src.write_text(JAVA_PROBE.replace("/* ACTUAL */", methods), encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(src)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "CombatOverlayCheck"], check=True)

    def test_confirmation_jni_keeps_generation_unscaled(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
        body = function(source, "JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeCombatConfirm(")
        harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include "touch.h"
#define JNIEXPORT
#define JNICALL
typedef void JNIEnv;typedef void *jclass;typedef int jint;
static void_touch_event last;static unsigned calls;
void void_touch_enqueue(const void_touch_event *event){last=*event;++calls;}
/* ACTUAL */
int main(void){
 for(int token=-1;token<=1;++token)Java_org_homm5_port_GameActivity_nativeCombatConfirm(NULL,NULL,token);
 assert(calls==1&&last.kind==TOUCH_COMBAT_CONFIRM&&last.dx==1&&last.scale==1&&last.x==0&&last.y==0);
 Java_org_homm5_port_GameActivity_nativeCombatConfirm(NULL,NULL,0xFFFFFF);
 assert(calls==2&&last.dx==(float)0xFFFFFF);
 Java_org_homm5_port_GameActivity_nativeCombatConfirm(NULL,NULL,0x1000000);
 assert(calls==2);puts("PASS combat confirmation JNI: exact 24-bit token and invalid-input guard");return 0;
}
'''
        compile_probe("combat-overlay-jni", harness.replace("/* ACTUAL */", body),
                      {"touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf-8")})

    def test_route_updates_are_native_and_control_jni_deduplicates_only_success(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
        body = function(source, "void void_android_combat_overlay(")
        harness = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
enum {JNI_OK=0,JNI_ERR=-1,JNI_EDETACHED=-2,JNI_VERSION_1_6=0x10006};
typedef int jint;typedef void *jclass;typedef void *jmethodID;
typedef const struct NativeTable *JNIEnv;
typedef const struct InvokeTable *JavaVM;
struct NativeTable {
 jmethodID (*GetStaticMethodID)(JNIEnv *,jclass,const char *,const char *);
 int (*ExceptionCheck)(JNIEnv *);
 void (*CallStaticVoidMethod)(JNIEnv *,jclass,jmethodID,...);
 void (*ExceptionClear)(JNIEnv *);
};
struct InvokeTable {
 int (*GetEnv)(JavaVM *,void **,int);
 int (*AttachCurrentThread)(JavaVM *,JNIEnv **,void *);
 int (*DetachCurrentThread)(JavaVM *);
};
static JavaVM *jvm;
static void *activity;
static JNIEnv environment;
static int env_result=JNI_OK,attach_result=JNI_OK,missing_method,lookup_throws,call_throws,exception;
static unsigned route_calls,getenv_calls,attach_calls,detach_calls,lookups,callbacks,clears,logs;
static unsigned events,route_event;
static const float *last_points;
static unsigned last_count;
static jint last_generation,last_epoch,last_hint;
/* Valid worker packet: mode/count, matrix16, two world points and four footprint corners. */
static const float path[36]={1,2,2,0,0,-1,0,-2,0,1,0,0,1,0,0,0,0,1,
 .1f,.2f,0,.8f,.7f,0,.7f,.6f,0,.9f,.6f,0,.9f,.8f,0,.7f,.8f,0};
static void d3d_gl_combat_route(const float *points,unsigned count) {
 ++route_calls;route_event=++events;last_points=points;last_count=count;
}
static int get_env(JavaVM *vm,void **out,int version) {
 assert(vm==jvm&&version==JNI_VERSION_1_6&&route_event==events);
 ++getenv_calls;++events;*out=env_result==JNI_OK?&environment:NULL;return env_result;
}
static int attach(JavaVM *vm,JNIEnv **out,void *args) {
 assert(vm==jvm&&!args);++attach_calls;*out=attach_result==JNI_OK?&environment:NULL;return attach_result;
}
static int detach(JavaVM *vm) {assert(vm==jvm);++detach_calls;return JNI_OK;}
static jmethodID method(JNIEnv *env,jclass owner,const char *name,const char *signature) {
 assert(env==&environment&&owner==activity&&!strcmp(name,"onCombatOverlay")&&!strcmp(signature,"(III)V"));
 ++lookups;if(lookup_throws)exception=1;return missing_method||lookup_throws?NULL:(void *)0xCA11;
}
static int check(JNIEnv *env) {assert(env==&environment);return exception;}
static void callback(JNIEnv *env,jclass owner,jmethodID id,...) {
 assert(env==&environment&&owner==activity&&id==(void *)0xCA11&&!exception);
 va_list ap;va_start(ap,id);last_generation=va_arg(ap,jint);last_epoch=va_arg(ap,jint);last_hint=va_arg(ap,jint);va_end(ap);
 ++callbacks;if(call_throws)exception=1;
}
static void clear(JNIEnv *env) {assert(env==&environment&&exception);exception=0;++clears;}
static void void_log(const char *message,...) {assert(strstr(message,"combat overlay"));++logs;}
static const struct NativeTable natives={method,check,callback,clear};
static const struct InvokeTable invokes={get_env,attach,detach};
static JavaVM machine=&invokes;
/* ACTUAL */
static void send(uint32_t generation,uint32_t epoch,int hint,const float *points,unsigned count) {
 unsigned before=route_calls;void_android_combat_overlay(generation,epoch,hint,points,count);
 assert(route_calls==before+1&&last_points==points&&last_count==count);
}
int main(void) {
 environment=&natives;
 /* The native renderer receives changes/clears even without Java or a valid activity. */
 send(0,0,0,path,36);assert(!getenv_calls&&!callbacks);
 jvm=&machine;send(0,0,0,NULL,0);assert(!getenv_calls&&!callbacks);
 activity=(void *)0x1234;send(0,0,0,path,36);assert(callbacks==1&&getenv_calls==1);
 /* Geometry animation and hiding do not cross JNI when controls have not changed. */
 for(int frame=0;frame<40;++frame)send(0,0,0,frame&1?path:NULL,frame&1?36:0);
 assert(getenv_calls==1&&callbacks==1);
 send(7,2,1,path,36);assert(callbacks==2&&last_generation==7&&last_epoch==2&&last_hint==1);
 send(8,2,1,path,36);assert(callbacks==3&&last_generation==8);
 send(8,3,1,path,36);assert(callbacks==4&&last_epoch==3);
 send(8,3,2,NULL,0);assert(callbacks==5&&last_hint==2);
 send(8,3,2,path,36);assert(callbacks==5);
 /* Lookup and callback failures must not acknowledge the new controls. */
 missing_method=1;send(9,3,2,path,36);assert(callbacks==5);
 missing_method=0;send(9,3,2,path,36);assert(callbacks==6&&last_generation==9);
 lookup_throws=1;send(10,3,2,path,36);assert(callbacks==6&&clears==1&&logs==1&&!exception);
 lookup_throws=0;send(10,3,2,path,36);assert(callbacks==7&&last_generation==10);
 call_throws=1;send(11,3,2,path,36);assert(callbacks==8&&clears==2&&logs==2&&!exception);
 call_throws=0;send(11,3,2,path,36);assert(callbacks==9&&last_generation==11);
 send(11,3,2,NULL,0);assert(callbacks==9);
 /* Detached threads attach once and always detach after a successful attachment. */
 env_result=JNI_EDETACHED;attach_result=JNI_ERR;send(12,3,2,path,36);
 assert(attach_calls==1&&!detach_calls&&callbacks==9);
 attach_result=JNI_OK;send(12,3,2,path,36);assert(attach_calls==2&&detach_calls==1&&callbacks==10);
 call_throws=1;send(13,3,2,path,36);assert(attach_calls==3&&detach_calls==2&&callbacks==11&&clears==3);
 call_throws=0;send(13,3,2,NULL,0);assert(attach_calls==4&&detach_calls==3&&callbacks==12);
 env_result=JNI_ERR;send(14,3,2,path,36);assert(callbacks==12);
 env_result=JNI_OK;send(14,3,2,path,36);assert(callbacks==13&&last_generation==14);
 /* UI disposal cannot suppress native route cleanup or cache undelivered controls. */
 activity=NULL;send(0,0,0,NULL,0);assert(callbacks==13);
 activity=(void *)0x1234;send(0,0,0,NULL,0);assert(callbacks==14&&!last_generation&&!last_epoch&&!last_hint);
 puts("PASS native route/JNI bridge: route first on every update/clear, III controls only, successful-send dedup, exception/attach retry and thread cleanup");
 return 0;
}
'''
        compile_probe("combat-overlay-route-jni", harness.replace("/* ACTUAL */", body), {})


if __name__ == "__main__":
    unittest.main()
