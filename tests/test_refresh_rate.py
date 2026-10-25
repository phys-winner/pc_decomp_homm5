"""Run the Activity's actual display selector and lifecycle refresh requests."""
import subprocess
import unittest
from test_touch_controls import ROOT, JAVA
from test_d3d_lifecycle import function


FIXTURE = r'''
public class RefreshRateCheck extends RefreshRateCheckBase {
    private SurfaceView surface;
    private Surface refreshSurface;
    private Object touch = new Object();
    private final Window window = new Window();
    /* GameActivity's Wi-Fi multicast lock for the LAN game (held while resumed). */
    static class MulticastLock { boolean held; boolean isHeld() { return held; } void acquire() { held = true; } }
    private MulticastLock lanLock;
    private int hides, releases, nativeSurfaces, pauses;
    private Surface lastNativeSurface;
    Window getWindow() { return window; }
    void hideSystemUi() { hides++; }
    void releaseAll() { releases++; }
    void nativePause(boolean paused) { assert !paused; pauses++; }
    void nativeSurface(Object value) { nativeSurfaces++; lastNativeSurface=(Surface)value; }
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
        static final int FRAME_RATE_COMPATIBILITY_DEFAULT=0;
        boolean valid=true, failNext;
        int calls;
        boolean isValid() { return valid; }
        void setFrameRate(float rate,int compatibility) {
            assert Build.VERSION.SDK_INT>=30 : "unguarded API30 call";
            assert rate==120f && compatibility==FRAME_RATE_COMPATIBILITY_DEFAULT;
            calls++;
            if (failNext) { failNext=false;throw new IllegalArgumentException("transient fixture rejection"); }
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
    static void selected(int expected,Display.Mode current,Display.Mode... modes) {
        int actual=chooseRefreshMode(current,modes);
        assert actual==expected : "selected "+actual+", expected "+expected;
    }
    static void selector() {
        Display.Mode sixty=m(1,60), ninety=m(2,90), fast=m(3,120), faster=m(4,144);
        selected(0,sixty,sixty,ninety);
        selected(3,sixty,sixty,ninety,fast,faster);
        selected(3,ninety,faster,fast,ninety);
        selected(3,fast,sixty,fast,faster);
        selected(4,sixty,sixty,ninety,faster);
        selected(4,sixty,m(5,165),faster,m(6,240));
        selected(3,sixty,m(8,119.5f),m(3,120),m(9,120.5f),faster);
        selected(8,sixty,faster,m(8,119.5f));
        selected(9,sixty,faster,m(9,120.5f));
        selected(3,sixty,m(9,120.4f),m(3,119.75f),faster);
        selected(7,m(7,120),m(8,120),m(7,120));
        selected(7,m(7,144),m(8,144),m(7,144));
        selected(7,m(7,119.75f),m(8,120.25f),m(7,119.75f));
        selected(3,sixty,sized(9,1920,1200,120),fast,sized(10,1840,2944,120));
        selected(0,sixty,sized(9,1920,1200,120),sized(10,1840,2944,120));
        selected(0,null,fast);
        selected(0,sixty,(Display.Mode[])null);
        selected(0,sixty,new Display.Mode[0]);
        selected(0,sized(1,0,1840,60),fast);
        selected(0,sized(1,2944,-1,60),fast);
        selected(0,sixty,null,m(0,120),m(-1,120),m(3,Float.NaN),m(4,Float.POSITIVE_INFINITY),
            m(5,Float.NEGATIVE_INFINITY),m(6,0),m(7,-120),sized(8,0,1840,120));
        selected(3,sixty,null,m(0,120),m(5,Float.NaN),fast);
        selected(0,sixty,m(7,119.49f));
    }
    void lifecycle() {
        onResume(); onWindowFocusChanged(true);
        assert window.writes==0 && pauses==1;
        Surface first=new Surface();
        Display.Mode sixty=m(1,60), fast=m(3,120);
        surface=new SurfaceView(new Display(sixty,sixty,fast),first);
        surfaceCreated(surface.holder);
        assert nativeSurfaces==1 && lastNativeSurface==first;
        assert window.attrs.preferredDisplayModeId==3 && window.writes==1 && first.calls==1;
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
        assert noMode.window.writes==0 && noMode.window.attrs.preferredDisplayModeId==0 && hint.calls==1;

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
    public static void main(String[] args) {
        selector(); new RefreshRateCheck().lifecycle(); readiness();
        System.out.println("PASS actual refresh selector and lifecycle: same-resolution 120/144, nominal tolerance, invalid modes, API guard, new surface, retry, idempotence");
    }
}
class RefreshRateCheckBase {
    public void surfaceCreated(RefreshRateCheck.SurfaceHolder holder) {}
    public void surfaceChanged(RefreshRateCheck.SurfaceHolder holder,int format,int width,int height) {}
    public void surfaceDestroyed(RefreshRateCheck.SurfaceHolder holder) {}
    protected void onResume() {}
    public void onWindowFocusChanged(boolean focus) {}
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
            "    @Override public void onWindowFocusChanged(",
        ))
        methods = methods.replace("android.view.Surface", "Surface")
        out = ROOT / "build/java-refresh-check"
        out.mkdir(parents=True, exist_ok=True)
        java = out / "RefreshRateCheck.java"
        java.write_text(FIXTURE.replace("    /* ACTUAL_METHODS */", methods), encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(java)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "RefreshRateCheck"], check=True)

    def test_legacy_target_unchanged(self):
        source = (ROOT / "android/app/AndroidManifest.xml").read_text(encoding="utf8")
        self.assertIn('android:targetSdkVersion="28"', source)


if __name__ == "__main__":
    unittest.main()
