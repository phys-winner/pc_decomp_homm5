"""Run the Activity's actual display selector and lifecycle refresh requests."""
import subprocess
import unittest
from test_touch_controls import ROOT, JAVA
from test_d3d_lifecycle import function


FIXTURE = r'''
public class RefreshRateCheck extends RefreshRateCheckBase {
    private SurfaceView surface;
    private Surface refreshSurface;
    private float frameRate=60, refreshVote;
    /* Already-ready view here; startup policy/Android dispatch have separate controls. */
    static class Touch { int requests; boolean requestFocus() { requests++;return true; } }
    private Touch touch = new Touch();
    private boolean startupFocusPending;
    boolean isFinishing() { return false; }
    boolean isDestroyed() { return false; }
    private final Window window = new Window();
    /* GameActivity's Wi-Fi multicast lock for the LAN game (held while resumed). */
    static class MulticastLock { boolean held; boolean isHeld() { return held; } void acquire() { held = true; } }
    private MulticastLock lanLock;
    private int hides, releases, nativeSurfaces, pauses;
    private Surface lastNativeSurface;
    /* GameActivity's engine state: loaded, and the DXVK modes' surface hand-back (OpenGL ES here). */
    private boolean nativeReady = true, resumed, surfaceHidden;
    Window getWindow() { return window; }
    void hideSystemUi() { hides++; }
    void releaseAll() { releases++; }
    void nativePause(boolean paused) { assert !paused; pauses++; }
    void nativeSurface(Object value) { nativeSurfaces++; lastNativeSurface=(Surface)value; }
    /* onResume's other duties: the combat overlay (none here) and the next touch hint. */
    static class Overlay { void setRunning(boolean running) {} }
    private Overlay combatOverlay;
    void showNextTouchHint() {}
    boolean dxvkSurface() { return false; }
    /* Tribes of the East's PerfMonitor: the requested mode/vote and lifecycle reach it; the
       no-preferred-mode flag file leaves the mode to the system and keeps the vote. */
    static class PerfMonitor {
        boolean noPreferred; int requests, lastMode = -1, surfaces, focuses, resumes; float lastVote;
        boolean noPreferredMode() { return noPreferred; }
        void requested(Display display, int mode, float vote) { requests++; lastMode = mode; lastVote = vote; }
        void surface(String state) { surfaces++; }
        void focus(boolean on) { focuses++; }
        void resume() { resumes++; }
    }
    private PerfMonitor perf = new PerfMonitor();
    static class Build { static class VERSION { static int SDK_INT=30; } }
    static class WindowManager {
        static class LayoutParams { int preferredDisplayModeId; }
    }
    static class Window {
        final WindowManager.LayoutParams attrs = new WindowManager.LayoutParams();
        int writes;
        WindowManager.LayoutParams getAttributes() { return attrs; }
        void setAttributes(WindowManager.LayoutParams value) { assert value==attrs; writes++; }
    }
    static class Display {
        static class Mode {
            final int id,width,height; final float rate;
            Mode(int i,int w,int h,float r) { id=i;width=w;height=h;rate=r; }
            int getModeId() { return id; }
            int getPhysicalWidth() { return width; }
            int getPhysicalHeight() { return height; }
            float getRefreshRate() { return rate; }
        }
        Mode current; Mode[] modes;
        Display(Mode c,Mode... m) { current=c;modes=m; }
        Mode getMode() { return current; }
        Mode[] getSupportedModes() { return modes; }
    }
    static class Surface {
        static final int FRAME_RATE_COMPATIBILITY_FIXED_SOURCE=1, CHANGE_FRAME_RATE_ONLY_IF_SEAMLESS=0;
        boolean valid=true, failNext;
        int calls;
        float voted;
        boolean isValid() { return valid; }
        void setFrameRate(float rate,int compatibility) {
            assert Build.VERSION.SDK_INT>=30 : "unguarded API30 call";
            assert rate>=10 && rate<=240 && compatibility==FRAME_RATE_COMPATIBILITY_FIXED_SOURCE;
            voted=rate;calls++;
            if (failNext) { failNext=false;throw new IllegalArgumentException("transient fixture rejection"); }
        }
        void setFrameRate(float rate,int compatibility,int strategy) {
            assert Build.VERSION.SDK_INT>=31 && strategy==CHANGE_FRAME_RATE_ONLY_IF_SEAMLESS;
            setFrameRate(rate,compatibility);
        }
    }
    static class SurfaceHolder {
        Surface value;
        SurfaceHolder(Surface s) { value=s; }
        Surface getSurface() { return value; }
    }
    static class SurfaceView {
        Display display; final SurfaceHolder holder;
        SurfaceView(Display d,Surface s) { display=d;holder=new SurfaceHolder(s); }
        Display getDisplay() { return display; }
        SurfaceHolder getHolder() { return holder; }
    }
    /* ACTUAL_METHODS */
    static Display.Mode m(int id,float rate) { return new Display.Mode(id,2944,1840,rate); }
    static Display.Mode sized(int id,int width,int height,float rate) { return new Display.Mode(id,width,height,rate); }
    static void selected(int expected,float fps,Display.Mode current,Display.Mode... modes) {
        int actual=chooseRefreshMode(current,modes,fps);
        assert actual==expected : fps+" FPS: selected "+actual+", expected "+expected;
    }
    static void selector() {
        Display.Mode sixty=m(1,60), ninety=m(2,90), fast=m(3,120), faster=m(4,144);
        for(float fps:new float[]{20,30,60}) {
            selected(1,fps,fast,sixty,ninety,fast,faster);
            selected(1,fps,ninety,faster,fast,ninety,sixty);
        }
        selected(2,45,sixty,sixty,ninety,fast,faster);
        selected(2,90,sixty,sixty,ninety,fast,faster);
        selected(3,40,sixty,sixty,ninety,fast,faster);
        selected(3,120,sixty,sixty,ninety,fast,faster);
        selected(4,48,sixty,sixty,ninety,fast,faster);
        selected(4,72,sixty,sixty,ninety,fast,faster);
        selected(4,144,sixty,sixty,ninety,fast,faster);
        selected(2,30,sixty,ninety,fast); // lowest even cadence wins
        selected(2,60,sixty,ninety,faster); // no even mode: lowest sufficient fallback
        selected(6,120,sixty,m(5,165),faster,m(6,240)); // 240/2 over uneven 144
        selected(3,60,sixty,m(3,119.88f),faster);
        selected(1,20,sixty,m(1,59.94f),ninety,fast);
        selected(7,60,m(7,120),m(8,120),m(7,120));
        selected(3,120,sixty,sized(9,1920,1200,120),fast,sized(10,1840,2944,120));
        selected(0,60,sixty,sized(9,1920,1200,120),sized(10,1840,2944,120));
        selected(0,60,null,fast);
        selected(0,60,sixty,(Display.Mode[])null);
        selected(0,60,sixty,new Display.Mode[0]);
        selected(0,60,sized(1,0,1840,60),fast);
        selected(0,60,sized(1,2944,-1,60),fast);
        selected(0,60,sixty,null,m(0,120),m(-1,120),m(3,Float.NaN),m(4,Float.POSITIVE_INFINITY),
            m(5,Float.NEGATIVE_INFINITY),m(6,0),m(7,-120),sized(8,0,1840,120));
        selected(3,60,sixty,null,m(0,120),m(5,Float.NaN),fast);
        selected(0,60,sixty,m(7,30));
        for(float fps:new float[]{0,9,241,Float.NaN,Float.POSITIVE_INFINITY}) selected(0,fps,sixty,sixty,fast);
    }
    void lifecycle() {
        onResume(); onWindowFocusChanged(true);
        assert window.writes==0 && pauses==1 && touch.requests==0;
        startupFocusPending=true;onWindowFocusChanged(true);
        assert touch.requests==1 && !startupFocusPending;
        onWindowFocusChanged(true);
        assert touch.requests==1 : "ordinary refresh callback repeated startup focus";
        Surface first=new Surface();
        Display.Mode sixty=m(1,60), fast=m(3,120);
        surface=new SurfaceView(new Display(sixty,sixty,fast),first);
        surfaceCreated(surface.holder);
        assert nativeSurfaces==1 && lastNativeSurface==first;
        assert window.attrs.preferredDisplayModeId==1 && window.writes==1 && first.calls==1 && first.voted==60;
        surfaceChanged(surface.holder,1,1280,800);
        onResume(); onWindowFocusChanged(true); requestHighRefresh();
        assert window.writes==1 && first.calls==1 : "repeated lifecycle request";
        onWindowFocusChanged(false);
        assert first.calls==1;
        window.attrs.preferredDisplayModeId=0;
        onResume();
        assert window.writes==2 && first.calls==1 : "resume must restore mode without revoting surface";
        surfaceDestroyed(surface.holder);
        assert lastNativeSurface==null;
        first.valid=false;
        requestHighRefresh();
        assert window.writes==2 && first.calls==1;
        Surface second=new Surface();
        surface.holder.value=second;
        surfaceCreated(surface.holder);
        assert first.calls==1 && second.calls==1 && lastNativeSurface==second;
        surfaceChanged(surface.holder,1,2560,1600);
        onResume(); onWindowFocusChanged(true);
        assert second.calls==1 && window.writes==2;
        frameRate=30;requestHighRefresh();requestHighRefresh();
        assert second.calls==2 && second.voted==30 && window.writes==2;
        Build.VERSION.SDK_INT=31;
        frameRate=120;requestHighRefresh();requestHighRefresh();
        assert second.calls==3 && second.voted==120 && window.attrs.preferredDisplayModeId==3 && window.writes==3;
        frameRate=20;requestHighRefresh();
        assert second.calls==4 && second.voted==20 && window.attrs.preferredDisplayModeId==1 && window.writes==4;
        Build.VERSION.SDK_INT=30;
    }
    static void readiness() {
        RefreshRateCheck noDisplay=new RefreshRateCheck();
        Surface nativeSurface=new Surface();
        noDisplay.surface=new SurfaceView(null,nativeSurface);
        noDisplay.requestHighRefresh();
        assert nativeSurface.calls==0 && noDisplay.window.writes==0;
        noDisplay.surface.display=new Display(m(1,60),m(1,60),m(3,120));
        nativeSurface.valid=false;
        noDisplay.requestHighRefresh();
        assert nativeSurface.calls==0 && noDisplay.window.writes==0;
        noDisplay.surface.holder.value=null;
        noDisplay.requestHighRefresh();
        assert noDisplay.window.writes==0;
        nativeSurface.valid=true; noDisplay.surface.holder.value=nativeSurface;
        noDisplay.requestHighRefresh();
        assert nativeSurface.calls==1 && noDisplay.window.writes==1;

        RefreshRateCheck noMode=new RefreshRateCheck();
        Surface hint=new Surface();
        noMode.surface=new SurfaceView(new Display(m(1,60),m(1,60),m(2,90)),hint);
        noMode.requestHighRefresh(); noMode.requestHighRefresh();
        assert noMode.window.writes==1 && noMode.window.attrs.preferredDisplayModeId==1 && hint.calls==1;
        noMode.frameRate=120;noMode.requestHighRefresh();
        assert noMode.window.writes==2 && noMode.window.attrs.preferredDisplayModeId==0 && hint.calls==2;

        RefreshRateCheck legacy=new RefreshRateCheck();
        Surface legacySurface=new Surface();
        legacy.surface=new SurfaceView(new Display(m(1,60),m(3,120)),legacySurface);
        Build.VERSION.SDK_INT=29;
        legacy.requestHighRefresh();
        assert legacy.window.writes==1 && legacySurface.calls==0;
        Build.VERSION.SDK_INT=30;
        legacy.requestHighRefresh(); legacy.requestHighRefresh();
        assert legacySurface.calls==1 && legacy.window.writes==1;

        RefreshRateCheck retry=new RefreshRateCheck();
        Surface rejected=new Surface(); rejected.failNext=true;
        retry.surface=new SurfaceView(new Display(m(1,60),m(3,120)),rejected);
        retry.requestHighRefresh();
        assert rejected.calls==1;
        retry.requestHighRefresh(); retry.requestHighRefresh();
        assert rejected.calls==2 : "rejected vote must retry once, successful vote must be cached";
    }
    static void perfMonitor() {
        RefreshRateCheck plain = new RefreshRateCheck();
        Surface vote = new Surface();
        plain.surface = new SurfaceView(new Display(m(1,60),m(1,60),m(3,120)), vote);
        plain.frameRate = 120;
        plain.requestHighRefresh();
        assert plain.perf.requests == 1 && plain.perf.lastMode == 3 && plain.perf.lastVote == 120;
        assert plain.window.attrs.preferredDisplayModeId == 3;
        RefreshRateCheck noMode = new RefreshRateCheck();
        noMode.perf.noPreferred = true;
        Surface keep = new Surface();
        noMode.surface = new SurfaceView(new Display(m(1,60),m(1,60),m(3,120)), keep);
        noMode.frameRate = 120;
        noMode.requestHighRefresh();
        assert noMode.perf.lastMode == 0 && noMode.window.attrs.preferredDisplayModeId == 0 && noMode.window.writes == 0;
        assert keep.calls == 1 : "the setFrameRate vote stays without a preferred mode";
        RefreshRateCheck none = new RefreshRateCheck();
        none.perf = null;
        none.surface = new SurfaceView(new Display(m(1,60),m(1,60),m(3,120)), new Surface());
        none.requestHighRefresh();
        assert none.window.attrs.preferredDisplayModeId == 1 : "legacy editions have no PerfMonitor";
    }
    public static void main(String[] args) {
        selector(); new RefreshRateCheck().lifecycle(); readiness(); perfMonitor();
        System.out.println("PASS actual refresh selector and lifecycle: FPS /2 /3 power-efficient cadence, same resolution, nominal tolerance, invalid modes/caps, API30/31 guards, cap change revote, new surface, retry, idempotence");
    }
}
class RefreshRateCheckBase {
    public void surfaceCreated(RefreshRateCheck.SurfaceHolder holder) {}
    public void surfaceChanged(RefreshRateCheck.SurfaceHolder holder,int format,int width,int height) {}
    public void surfaceDestroyed(RefreshRateCheck.SurfaceHolder holder) {}
    protected void onResume() {}
    private boolean focused=true;
    boolean hasWindowFocus() { return focused; }
    public void onWindowFocusChanged(boolean focus) { focused=focus; }
}
'''


class RefreshRateTest(unittest.TestCase):
    def test_actual_selector_and_lifecycle(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        methods = "\n".join(function(source, start) for start in (
            "    private static int chooseRefreshMode(",
            "    private void requestHighRefresh(",
            "    @Override public void surfaceCreated(",
            "    @Override public void surfaceChanged(",
            "    @Override public void surfaceDestroyed(",
            "    @Override protected void onResume(",
            "    private void showDxvkSurface(",
            "    @Override public void onWindowFocusChanged(",
            "    private void restoreStartupFocus(",
        ))
        methods = methods.replace("android.view.Surface", "Surface")
        out = ROOT / "build/java-refresh-check"
        out.mkdir(parents=True, exist_ok=True)
        java = out / "RefreshRateCheck.java"
        java.write_text(FIXTURE.replace("    /* ACTUAL_METHODS */", methods), encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(java)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "RefreshRateCheck"], check=True)

    def test_target_sdk_is_the_launcher_bases(self):
        source = (ROOT / "android/app/AndroidManifest.xml").read_text(encoding="utf8")
        self.assertIn('android:targetSdkVersion="37"', source)
        self.assertIn('android:minSdkVersion="26"', source)


if __name__ == "__main__":
    unittest.main()
