"""Run the actual Activity gesture classifier with a deterministic Java event queue."""
from pathlib import Path
import os
import subprocess
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import JAVA_HOME

ROOT = Path(__file__).resolve().parents[1]
JAVA = Path(os.environ.get("JAVA_HOME", str(JAVA_HOME))) / "bin"

FIXTURE = r'''
import java.util.*;
public class TouchControlsCheck {
    static long now = 1000;
    static int width = 1280, height = 800, clicks;
    boolean textEditing;
    int textGeneration,fieldCaret;
    TextConnection textConnection;
    interface InputConnection {}
    static class TextConnection implements InputConnection { TextConnection(int generation) {} }
    static class InputType { static final int TYPE_CLASS_TEXT=1,TYPE_TEXT_FLAG_NO_SUGGESTIONS=2; }
    static class EditorInfo {
        static final int IME_ACTION_DONE=1,IME_FLAG_NO_EXTRACT_UI=2,IME_FLAG_NO_FULLSCREEN=4;
        int inputType,imeOptions,initialSelStart,initialSelEnd;
    }
    static List<Touch> events = new ArrayList<>();
    static Map<Runnable, Long> queue = new HashMap<>();
    int dp(float n) { return Math.round(n); }
    static class Touch {
        final int kind; final float x,y,dx,dy,scale,rotation;
        Touch(int k,float x,float y,float dx,float dy,float s,float angle) {
            kind=k; this.x=x; this.y=y; this.dx=dx; this.dy=dy; scale=s; rotation=angle;
        }
    }
    static void nativeTouch(int k,float x,float y,float dx,float dy,float s,float angle) {
        assert Float.isFinite(x) && Float.isFinite(y) && Float.isFinite(dx)
            && Float.isFinite(dy) && Float.isFinite(s) && Float.isFinite(angle) && Math.abs(angle)<=Math.PI+.000001;
        events.add(new Touch(k,x,y,dx,dy,s,angle));
    }
    static class Context {}
    static int haptics;
    static class HapticFeedbackConstants { static final int LONG_PRESS=0; }
    static class View {
        public boolean performHapticFeedback(int kind) { assert kind==HapticFeedbackConstants.LONG_PRESS; haptics++; return true; }
        View(Context c) {}
        void setContentDescription(String s) {}
        void setFocusable(boolean value) {}
        void setFocusableInTouchMode(boolean value) {}
        int getWidth() { return width; }
        int getHeight() { return height; }
        void postDelayed(Runnable r, long ms) { queue.put(r, now + ms); }
        void removeCallbacks(Runnable r) { queue.remove(r); }
        public boolean onTouchEvent(MotionEvent e) { return false; }
        public boolean performClick() { clicks++; return true; }
        protected void onSizeChanged(int w,int h,int oldw,int oldh) {}
        public boolean onCheckIsTextEditor() {return false;}
        public InputConnection onCreateInputConnection(EditorInfo info) {return null;}
    }
    static class MotionEvent {
        static final int ACTION_DOWN=0, ACTION_UP=1, ACTION_MOVE=2, ACTION_CANCEL=3,
            ACTION_POINTER_DOWN=5, ACTION_POINTER_UP=6;
        final int action,index; final int[] ids; final float[] xs,ys;
        MotionEvent(int a,int i,int[] ids,float[] xs,float[] ys) {
            action=a; index=i; this.ids=ids; this.xs=xs; this.ys=ys;
        }
        int getActionMasked() { return action; }
        int getActionIndex() { return index; }
        int getPointerCount() { return ids.length; }
        int getPointerId(int i) { return ids[i]; }
        int findPointerIndex(int p) {
            for (int i=0;i<ids.length;i++) if(ids[i]==p) return i;
            return -1;
        }
        float getX(int i) { return xs[i]; }
        float getY(int i) { return ys[i]; }
        long getEventTime() { return now; }
    }
    static MotionEvent one(int a,int id,float x,float y) {
        return new MotionEvent(a,0,new int[]{id},new float[]{x},new float[]{y});
    }
    static MotionEvent two(int a,int index,int id1,float x1,float y1,int id2,float x2,float y2) {
        return new MotionEvent(a,index,new int[]{id1,id2},new float[]{x1,x2},new float[]{y1,y2});
    }
    static void advance(long ms) {
        long target = now + ms;
        while (!queue.isEmpty()) {
            Map.Entry<Runnable,Long> next = Collections.min(queue.entrySet(), Map.Entry.comparingByValue());
            if (next.getValue() > target) break;
            Runnable callback=next.getKey(); now=next.getValue(); queue.remove(callback); callback.run();
        }
        now=target;
    }
    static void kinds(int... expected) {
        assert events.size()==expected.length : "count " + events.size() + " != " + expected.length;
        for(int i=0;i<expected.length;i++) assert events.get(i).kind==expected[i]
            : "event " + i + ": " + events.get(i).kind + " != " + expected[i];
    }
    static void near(float actual,float expected) {
        assert Math.abs(actual-expected)<0.00001f : actual + " != " + expected;
    }
    static void clear() { events.clear(); clicks=0; assert queue.isEmpty(); }
    static MotionEvent three(int a,int index,int id1,float x1,float y1,int id2,float x2,float y2,int id3,float x3,float y3) {
        return new MotionEvent(a,index,new int[]{id1,id2,id3},new float[]{x1,x2,x3},new float[]{y1,y2,y3});
    }
    void check() {
        TouchLayer t=new TouchLayer(new Context());

        // A finger going down never presses the mouse or issues an order.
        t.onTouchEvent(one(0,17,640,400));
        kinds(0); near(events.get(0).x,.5f); near(events.get(0).y,.5f);
        advance(50); kinds(0);
        t.onTouchEvent(one(1,17,640,400)); kinds(0,1,7);
        assert queue.isEmpty() && clicks==1;

        // Taps nearby within 300 ms count up: tap, double tap, triple tap, then a tap again.
        events.clear(); advance(100);
        t.onTouchEvent(one(0,23,645,405));
        t.onTouchEvent(one(1,23,645,405)); kinds(0,2,7);
        events.clear(); advance(100);
        t.onTouchEvent(one(0,25,645,405));
        t.onTouchEvent(one(1,25,645,405)); kinds(0,14,7);
        events.clear(); advance(100);
        t.onTouchEvent(one(0,26,645,405));
        t.onTouchEvent(one(1,26,645,405)); kinds(0,1,7);
        // A late or distant tap starts over.
        events.clear(); advance(301);
        t.onTouchEvent(one(0,27,645,405));
        t.onTouchEvent(one(1,27,645,405)); kinds(0,1,7);
        events.clear(); advance(100);
        t.onTouchEvent(one(0,28,745,405));
        t.onTouchEvent(one(1,28,745,405)); kinds(0,1,7);
        t.cancelGesture(); clear();

        // UP may leave a native UI click awaiting a frame; lifecycle cancellation still aborts it.
        t.onTouchEvent(one(0,26,645,405));
        t.onTouchEvent(one(1,26,645,405)); kinds(0,1,7);
        t.cancelGesture(); kinds(0,1,7,10); clear();

        // Motion below the slop remains pending; classified drag reports direct camera deltas.
        t.onTouchEvent(one(0,41,100,100));
        t.onTouchEvent(one(2,41,104,103)); kinds(0);
        t.onTouchEvent(one(2,41,164,180)); kinds(0,3);
        near(events.get(1).dx,.05f); near(events.get(1).dy,.1f);
        advance(700); kinds(0,3);
        t.onTouchEvent(one(1,41,228,260)); kinds(0,3,3,7);
        near(events.get(2).dx,.05f); near(events.get(2).dy,.1f);
        assert clicks==0; clear();

        // A release carrying the only movement must not accidentally become a tap.
        t.onTouchEvent(one(0,7,100,100));
        t.onTouchEvent(one(1,7,200,200)); kinds(0,3,7); clear();

        // A held point is distinct from a pressed button; releasing it emits no tap.
        t.onTouchEvent(one(0,9,320,200));
        int previousHaptics=haptics;
        advance(449); kinds(0); assert haptics==previousHaptics;
        advance(1); kinds(0,5); assert haptics==previousHaptics+1;
        t.onTouchEvent(one(1,9,320,200)); kinds(0,5,7);
        assert clicks==0; clear();

        // Holding then moving is a different intent from immediately dragging the camera.
        t.onTouchEvent(one(0,10,320,200)); advance(450);
        t.onTouchEvent(one(2,10,448,280)); kinds(0,5,6);
        near(events.get(2).dx,.1f); near(events.get(2).dy,.1f);
        t.onTouchEvent(one(1,10,448,280)); kinds(0,5,6,7); clear();

        // Pointer IDs and indices may reorder; transform contains centroid pan and zoom.
        t.onTouchEvent(one(0,71,100,100));
        t.onTouchEvent(two(5,0,93,300,100,71,100,100)); kinds(0,8);
        t.onTouchEvent(two(2,0,71,100,200,93,500,200)); kinds(0,8,4);
        near(events.get(2).x,300f/1280); near(events.get(2).y,.25f);
        near(events.get(2).dx,100f/1280); near(events.get(2).dy,.125f);
        near(events.get(2).scale,2);
        // A lifted finger re-bases the set: the one left pans on from where it is, without a jump.
        t.onTouchEvent(two(6,0,71,100,200,93,500,200)); kinds(0,8,4);
        t.onTouchEvent(one(2,93,520,230)); kinds(0,8,4,4);
        near(events.get(3).dx,20f/1280); near(events.get(3).dy,30f/800);
        near(events.get(3).scale,1); near(events.get(3).rotation,0);
        t.onTouchEvent(one(1,93,520,230)); kinds(0,8,4,4,7);
        assert clicks==0; clear();

        // A finger put back continues the same transform from the new set.
        t.onTouchEvent(one(0,71,100,100));
        t.onTouchEvent(two(5,1,71,100,100,93,300,100));
        t.onTouchEvent(two(2,0,71,100,100,93,400,100)); kinds(0,8,4);
        near(events.get(2).scale,1.5f);
        t.onTouchEvent(two(6,0,71,100,100,93,400,100));
        t.onTouchEvent(two(5,1,93,400,100,71,600,100)); kinds(0,8,4);
        t.onTouchEvent(two(2,0,93,400,100,71,800,100)); kinds(0,8,4,4);
        near(events.get(3).scale,2); near(events.get(3).dx,100f/1280);
        t.onTouchEvent(two(6,1,93,400,100,71,800,100));
        t.onTouchEvent(one(1,93,400,100)); kinds(0,8,4,4,7); clear();

        // A third finger joining re-bases instead of jumping by its own position.
        t.onTouchEvent(one(0,1,200,200));
        t.onTouchEvent(two(5,1,1,200,200,2,400,200));
        t.onTouchEvent(two(2,0,1,250,200,2,450,200)); kinds(0,8,4);
        t.onTouchEvent(three(5,2,1,250,200,2,450,200,3,900,700)); kinds(0,8,4);
        t.onTouchEvent(three(2,0,1,260,200,2,460,200,3,910,700)); kinds(0,8,4,4);
        near(events.get(3).dx,10f/1280); near(events.get(3).dy,0); near(events.get(3).scale,1);
        t.cancelGesture(); clear();

        // A two-finger tap cancels once and never turns the remaining finger into a tap.
        t.onTouchEvent(one(0,81,100,100));
        t.onTouchEvent(two(5,1,81,100,100,82,300,100));
        advance(900); kinds(0,8);
        t.onTouchEvent(two(6,1,81,100,100,82,300,100));
        t.onTouchEvent(one(1,81,100,100)); kinds(0,8,9,7); clear();

        // Two fingers side by side moving down together tilt; the move is reported as dy.
        t.onTouchEvent(one(0,1,300,400));
        t.onTouchEvent(two(5,1,1,300,400,2,700,400)); kinds(0,8);
        t.onTouchEvent(two(2,0,1,300,430,2,700,432)); kinds(0,8,15);
        near(events.get(2).dy,31f/800); near(events.get(2).dx,0);
        t.onTouchEvent(two(2,0,1,302,470,2,701,470)); kinds(0,8,15,15);
        near(events.get(3).dy,39f/800);
        t.onTouchEvent(two(6,1,1,302,470,2,701,470));
        t.onTouchEvent(one(1,1,302,470)); kinds(0,8,15,15,7); clear();
        // Fingers out of step still tilt, and the whole move so far applies.
        t.onTouchEvent(one(0,1,300,400));
        t.onTouchEvent(two(5,1,1,300,400,2,700,400)); kinds(0,8);
        t.onTouchEvent(two(2,0,1,300,409,2,700,401)); kinds(0,8);
        t.onTouchEvent(two(2,0,1,300,425,2,700,408)); kinds(0,8,15);
        near(events.get(2).dy,16.5f/800);
        t.cancelGesture(); clear();
        // One finger moving while the other rests is a transform.
        t.onTouchEvent(one(0,1,300,400));
        t.onTouchEvent(two(5,1,1,300,400,2,700,400));
        t.onTouchEvent(two(2,0,1,300,440,2,700,400)); kinds(0,8,4);
        near(events.get(2).dy,20f/800);
        t.cancelGesture(); clear();
        // Fingers one above the other moving down together pan instead.
        t.onTouchEvent(one(0,1,300,300));
        t.onTouchEvent(two(5,1,1,300,300,2,320,600));
        t.onTouchEvent(two(2,0,1,300,340,2,320,640)); kinds(0,8,4);
        near(events.get(2).dy,40f/800); t.cancelGesture(); clear();

        // Pure pinch and pure two-finger pan are transforms; a zero initial span is finite.
        t.onTouchEvent(one(0,1,200,200));
        t.onTouchEvent(two(5,1,1,200,200,2,400,200));
        t.onTouchEvent(two(2,0,1,100,200,2,500,200)); kinds(0,8,4);
        near(events.get(2).dx,0); near(events.get(2).scale,2);
        t.cancelGesture(); kinds(0,8,4,10); clear();
        t.onTouchEvent(one(0,1,200,200));
        t.onTouchEvent(two(5,1,1,200,200,2,400,200));
        t.onTouchEvent(two(2,0,1,250,210,2,450,210)); kinds(0,8,4);
        near(events.get(2).scale,1); near(events.get(2).dx,50f/1280);
        t.cancelGesture(); clear();
        t.onTouchEvent(one(0,1,200,200));
        t.onTouchEvent(two(5,1,1,200,200,2,200,200));
        t.onTouchEvent(two(2,0,1,100,200,2,300,200)); kinds(0,8,4);
        near(events.get(2).scale,1); t.cancelGesture(); clear();

        // A pure clockwise twist is a transform even without centroid/span changes.
        t.onTouchEvent(one(0,1,400,300));
        t.onTouchEvent(two(5,1,1,400,300,2,600,300));
        t.onTouchEvent(two(2,0,2,500,400,1,500,200)); kinds(0,8,4);
        near(events.get(2).rotation,(float)(Math.PI/2));near(events.get(2).dx,0);near(events.get(2).dy,0);
        near(events.get(2).scale,1);t.cancelGesture();clear();
        near(t.angleDelta((float)-Math.PI+.01f,(float)Math.PI-.01f),.02f);
        near(t.angleDelta((float)Math.PI-.01f,(float)-Math.PI+.01f),-.02f);
        t.onTouchEvent(one(0,1,600,299));
        t.onTouchEvent(two(5,1,1,600,299,2,400,301));
        t.onTouchEvent(two(2,0,1,650,301,2,450,299)); kinds(0,8,4);
        near(events.get(2).rotation,(float)(2*Math.atan(.01)));t.cancelGesture();clear();
        t.onTouchEvent(one(0,1,200,200));
        t.onTouchEvent(two(5,1,1,200,200,2,Float.NaN,300));kinds(0,10);clear();

        // A secondary tap during a primary hold never releases that hold.
        t.onTouchEvent(one(0,1,200,200));advance(600);
        t.onTouchEvent(two(5,1,1,200,200,2,500,300));kinds(0,5,11);
        near(events.get(2).x,500f/1280);near(events.get(2).y,300f/800);
        advance(50);t.onTouchEvent(two(6,1,1,200,200,2,500,300));kinds(0,5,11,12);
        t.onTouchEvent(two(5,1,1,200,200,3,550,300));
        t.onTouchEvent(two(6,1,1,200,200,3,550,300));kinds(0,5,11,12,11,12);
        t.onTouchEvent(one(2,1,300,200));t.onTouchEvent(one(1,1,300,200));kinds(0,5,11,12,11,12,6,7);
        advance(700);assert queue.isEmpty();clear();

        // Physical contacts occupy different cells; 1-2px primary jitter keeps a long hold alive.
        t.onTouchEvent(one(0,17,200,200));advance(1500);
        t.onTouchEvent(one(2,17,202,199));kinds(0,5);
        t.onTouchEvent(two(5,1,17,202,199,31,500,300));kinds(0,5,11);
        near(events.get(2).x,500f/1280);near(events.get(2).y,300f/800);
        advance(70);t.onTouchEvent(two(2,0,17,201,201,31,502,299));kinds(0,5,11);
        advance(40);t.onTouchEvent(two(6,1,17,201,201,31,501,302));kinds(0,5,11,12);
        near(events.get(3).x,501f/1280);near(events.get(3).y,302f/800);
        assert t.holding && !t.panning;
        t.onTouchEvent(one(1,17,201,201));kinds(0,5,11,12,7);
        advance(700);assert queue.isEmpty();clear();

        // The real hold->drag stream preserves HOLD_BEGIN before HOLD_DRAG and a separate secondary point.
        t.onTouchEvent(one(0,17,200,200));advance(1500);
        t.onTouchEvent(one(2,17,240,200));kinds(0,5,6);
        assert t.holding && t.panning;
        near(events.get(2).x,240f/1280);near(events.get(2).dx,40f/1280);
        t.onTouchEvent(two(5,1,17,240,200,31,500,300));kinds(0,5,6,11);
        near(events.get(3).x,500f/1280);near(events.get(3).y,300f/800);
        advance(90);t.onTouchEvent(two(6,1,17,240,200,31,502,301));kinds(0,5,6,11,12);
        near(events.get(4).x,502f/1280);near(events.get(4).y,301f/800);
        assert t.holding && t.panning;
        t.onTouchEvent(one(1,17,240,200));kinds(0,5,6,11,12,7);
        near(events.get(5).x,240f/1280);advance(700);assert queue.isEmpty();clear();

        // A stationary secondary hold is distinct from fast split and retains the primary.
        t.onTouchEvent(one(0,1,200,200));advance(600);
        t.onTouchEvent(two(5,1,1,200,200,2,500,300));advance(599);kinds(0,5,11);
        advance(1);kinds(0,5,11,13);
        t.onTouchEvent(two(6,1,1,200,200,2,500,300));t.onTouchEvent(one(1,1,200,200));kinds(0,5,11,13,7);clear();

        // An immediate primary drag can own a native troop; secondary motion promotes to a camera set.
        t.onTouchEvent(one(0,1,200,200));t.onTouchEvent(one(2,1,240,200));
        t.onTouchEvent(two(5,1,1,240,200,2,500,300));kinds(0,3,11);
        t.onTouchEvent(two(2,0,1,250,200,2,500,300));kinds(0,3,11,3);
        t.onTouchEvent(two(2,0,1,250,200,2,600,300));kinds(0,3,11,3,8);
        t.onTouchEvent(two(2,0,1,250,200,2,700,300));kinds(0,3,11,3,8,4);
        advance(700);kinds(0,3,11,3,8,4);t.cancelGesture();clear();
        t.onTouchEvent(one(0,1,200,200));advance(600);
        t.onTouchEvent(two(5,1,1,200,200,2,500,300));
        t.onTouchEvent(two(6,0,1,200,200,2,500,300));kinds(0,5,11,10);
        t.onTouchEvent(one(1,2,500,300));advance(700);kinds(0,5,11,10);clear();
        t.onTouchEvent(one(0,1,200,200));advance(600);
        t.onTouchEvent(two(5,1,1,200,200,2,500,300));t.cancelGesture();advance(700);
        kinds(0,5,11,10);assert queue.isEmpty();clear();

        // OS cancellation, focus loss and pause abort, with no delayed action.
        t.onTouchEvent(one(0,55,200,200));
        t.onTouchEvent(one(3,55,200,200)); kinds(0,10);
        advance(700); kinds(0,10); assert queue.isEmpty();
        t.onTouchEvent(one(1,55,200,200)); kinds(0,10);
        t.cancelGesture(); kinds(0,10,10); clear();
        t.onTouchEvent(one(0,56,200,200));
        advance(600); t.cancelGesture(); kinds(0,5,10);
        advance(700); assert queue.isEmpty(); clear();

        // Surface recreation cannot manufacture a point or leave a held action behind.
        width=height=0; t.onTouchEvent(one(0,1,100,100)); kinds();
        width=1280; height=800;
        t.onTouchEvent(one(0,1,-10,900)); kinds(0);
        near(events.get(0).x,-10f/1280); near(events.get(0).y,900f/800);
        width=height=0; t.cancelGesture(); kinds(0,10);
        width=1280; height=800; assert queue.isEmpty();
        clear(); t.onTouchEvent(one(0,1,300,300));
        t.onSizeChanged(1600,900,1280,800); kinds(0,10);
        advance(700); assert queue.isEmpty();
        System.out.println("PASS actual touch classifier: tap/double/triple/hold/drag, re-based multi-finger "
            + "transform and tilt, pointer IDs, abort, full Surface");
    }
    public static void main(String[] args) { new TouchControlsCheck().check(); }
    /* ACTUAL_TOUCH_LAYER */
}
'''


def run_check():
    source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf-8-sig")
    assert "nativeMouse" not in source[source.index("    private final class TouchLayer extends View {"):]
    assert "toolbar" not in source and "ToggleButton" not in source
    assert "setContentView(game);" in source
    assert "else if (touch != null) releaseAll();" in source
    destroyed = source[source.index("public void surfaceDestroyed(SurfaceHolder holder)"):].split("}", 1)[0]
    assert destroyed.index("releaseAll();") < destroyed.index("nativeSurface(null);")
    assert "touch.cancelGesture();" in source
    start = source.index("    private final class TouchLayer extends View {")
    body = source[start:source.rfind("}")].replace("private final class TouchLayer", "final class TouchLayer", 1)
    out = ROOT / "build/java-controls-check"
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / "TouchControlsCheck.java"
    fixture.write_text(FIXTURE.replace("    /* ACTUAL_TOUCH_LAYER */", body), encoding="utf-8")
    subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(fixture)], check=True)
    subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "TouchControlsCheck"], check=True)


class TouchControlsTests(unittest.TestCase):
    def test_actual_activity_gestures(self):
        run_check()


if __name__ == "__main__":
    run_check()
