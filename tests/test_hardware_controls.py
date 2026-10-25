"""Execute the actual Android hardware adapter with device/event and JNI spies."""
from pathlib import Path
import re
import subprocess
import unittest

from test_touch_controls import ROOT, JAVA
from test_d3d_lifecycle import function
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import SDK


FIXTURE = r'''
import java.util.*;
public class HardwareInputCheck {
    static class InputManager {
        interface InputDeviceListener {
            void onInputDeviceAdded(int id); void onInputDeviceChanged(int id); void onInputDeviceRemoved(int id);
        }
    }
    static class InputDevice {
        /* DEVICE_CONSTANTS */
        static class MotionRange {float getFlat(){return .1f;}}
        MotionRange getMotionRange(int axis,int source){return new MotionRange();}
    }
    static class KeyEvent {
        /* KEY_CONSTANTS */
        int action,code,source,device,repeat;
        KeyEvent(int code,boolean down,int source,int device){this.code=code;action=down?0:1;this.source=source;this.device=device;}
        int getAction(){return action;} int getKeyCode(){return code;} int getDeviceId(){return device;}
        int getRepeatCount(){return repeat;} int getUnicodeChar(){return 0;}
        boolean isCtrlPressed(){return false;} boolean isAltPressed(){return false;}
        boolean isFromSource(int s){return (source&s)==s;}
    }
    static class MotionEvent {
        /* MOTION_CONSTANTS */
        float[] axes=new float[64];int source,device,action=2,buttons;
        float x,y;
        MotionEvent(int source,int device){this.source=source;this.device=device;}
        boolean isFromSource(int s){return (source&s)==s;}
        int getActionMasked(){return action;} int getDeviceId(){return device;} int getSource(){return source;}
        InputDevice getDevice(){return new InputDevice();} float getAxisValue(int axis){return axes[axis];}
        float getX(){return x;}float getY(){return y;}int getButtonState(){return buttons;}
    }
    static class SystemClock {static long now;static long uptimeMillis(){return now;}}
    static class View {
        Runnable pending;
        void postOnAnimation(Runnable r){assert pending==null;pending=r;}
        void removeCallbacks(Runnable r){if(pending==r)pending=null;}
        int getWidth(){return 2000;}int getHeight(){return 1000;}
    }
    final View touch=new View();
    boolean textEditing,focus=true;
    static class TextConnection {boolean sendKeyEvent(KeyEvent e){return true;}}
    TextConnection textConnection;
    int helps;
    HardwareInput hardware=new HardwareInput();
    boolean hasWindowFocus(){return focus;}
    void showGamepadHelp(){helps++;hardware.release();}
    static final Map<Integer,Boolean> keys=new HashMap<>(),buttons=new HashMap<>();
    static final List<String> events=new ArrayList<>();
    static float moveX,moveY,rotation,tilt;static int wheels,moves,cameras;
    static void nativeHardwareKey(int vk,boolean down){keys.put(vk,down);events.add("k"+vk+":"+down);}
    static void nativeMouseButton(int b,boolean down){buttons.put(b,down);events.add("m"+b+":"+down);}
    static void nativePointer(float x,float y,boolean relative){moveX=x;moveY=y;moves++;}
    static void nativeWheel(int d){wheels+=d;}
    static void nativePadCamera(float r,float t){rotation=r;tilt=t;cameras++;}
    void key(int code,boolean down,int source,int device){assert hardware.key(new KeyEvent(code,down,source,device));}
    void padKey(int code,boolean down){key(code,down,InputDevice.SOURCE_GAMEPAD,7);}
    void frame(int ms){SystemClock.now+=ms;Runnable r=touch.pending;touch.pending=null;if(r!=null)r.run();}
    void neutral(MotionEvent e){Arrays.fill(e.axes,0);assert hardware.motion(e);frame(16);}
    void run() {
        for(int c=KeyEvent.KEYCODE_A;c<=KeyEvent.KEYCODE_Z;c++)assert keyboardKey(c)=='A'+c-KeyEvent.KEYCODE_A;
        for(int c=KeyEvent.KEYCODE_F1;c<=KeyEvent.KEYCODE_F12;c++)assert keyboardKey(c)==0x70+c-KeyEvent.KEYCODE_F1;
        assert keyboardKey(KeyEvent.KEYCODE_NUMPAD_ENTER)==12&&keyboardKey(KeyEvent.KEYCODE_ENTER)==13;
        assert keyboardKey(KeyEvent.KEYCODE_VOLUME_UP)==0;
        assert hardware.key(new KeyEvent(KeyEvent.KEYCODE_BACK,true,InputDevice.SOURCE_MOUSE,8));
        key(KeyEvent.KEYCODE_A,true,InputDevice.SOURCE_KEYBOARD,3);
        textEditing=true;textConnection=new TextConnection();
        key(KeyEvent.KEYCODE_A,false,InputDevice.SOURCE_KEYBOARD,3);assert !keys.get(65);textEditing=false;
        key(KeyEvent.KEYCODE_CTRL_LEFT,true,InputDevice.SOURCE_KEYBOARD,3);
        key(KeyEvent.KEYCODE_CTRL_RIGHT,true,InputDevice.SOURCE_KEYBOARD,3);
        assert keys.get(0xA2)&&keys.get(0xA3);
        hardware.onInputDeviceRemoved(3);assert !keys.get(0xA2)&&!keys.get(0xA3);
        // Releasing a mapped button uses its press-time action, even if Shift changed first.
        padKey(KeyEvent.KEYCODE_BUTTON_R1,true);padKey(KeyEvent.KEYCODE_BUTTON_X,true);
        padKey(KeyEvent.KEYCODE_BUTTON_R1,false);padKey(KeyEvent.KEYCODE_BUTTON_X,false);
        assert !keys.get(13)&&!keys.containsKey(67)&&!keys.get(0xA0);
        padKey(KeyEvent.KEYCODE_BUTTON_Y,true);assert keys.get(87);
        KeyEvent repeat=new KeyEvent(KeyEvent.KEYCODE_BUTTON_Y,true,InputDevice.SOURCE_GAMEPAD,7);repeat.repeat=1;
        int count=events.size();assert hardware.key(repeat)&&events.size()==count;
        padKey(KeyEvent.KEYCODE_BUTTON_Y,false);
        // Mouse and controller can hold the same button without releasing each other's press.
        MotionEvent mouse=new MotionEvent(InputDevice.SOURCE_MOUSE,8);mouse.buttons=1;mouse.action=MotionEvent.ACTION_BUTTON_PRESS;
        assert hardware.mouse(mouse)&&buttons.get(0);padKey(KeyEvent.KEYCODE_BUTTON_A,true);
        mouse.buttons=0;mouse.action=MotionEvent.ACTION_BUTTON_RELEASE;hardware.mouse(mouse);assert buttons.get(0);
        padKey(KeyEvent.KEYCODE_BUTTON_A,false);assert !buttons.get(0);
        mouse.action=MotionEvent.ACTION_SCROLL;mouse.axes[MotionEvent.AXIS_VSCROLL]=-2;
        hardware.mouse(mouse);assert wheels==-240;wheels=0;
        assert !hardware.mouse(new MotionEvent(InputDevice.SOURCE_TOUCHSCREEN,8));
        // A held, unchanged stick keeps moving every frame, in pixels independent of axis aspect.
        MotionEvent e=new MotionEvent(InputDevice.SOURCE_JOYSTICK,7);
        e.axes[MotionEvent.AXIS_X]=1;hardware.motion(e);frame(20);float fast=moveX;assert fast>0&&moveY==0;
        int before=moves;frame(20);assert moves==before+1;
        padKey(KeyEvent.KEYCODE_BUTTON_L1,true);frame(20);assert Math.abs(moveX/fast-.22f)<.001f;
        padKey(KeyEvent.KEYCODE_BUTTON_L1,false);neutral(e);before=moves;
        e.axes[MotionEvent.AXIS_X]=.1f;e.axes[MotionEvent.AXIS_Y]=Float.NaN;
        hardware.motion(e);frame(20);assert moves==before&&touch.pending==null;
        e.axes[MotionEvent.AXIS_RX]=1; // Z/RZ are preferred when present.
        e.axes[MotionEvent.AXIS_Z]=-.7f;e.axes[MotionEvent.AXIS_RZ]=.6f;
        hardware.motion(e);frame(20);assert cameras>0&&rotation>0&&tilt<0;
        neutral(e);e.axes[MotionEvent.AXIS_HAT_X]=-1;hardware.motion(e);assert keys.get(0x25);
        key(KeyEvent.KEYCODE_DPAD_LEFT,true,InputDevice.SOURCE_GAMEPAD,7);
        neutral(e);assert keys.get(0x25);key(KeyEvent.KEYCODE_DPAD_LEFT,false,InputDevice.SOURCE_GAMEPAD,7);assert !keys.get(0x25);
        // Analog and digital reports for one trigger produce one wheel stream.
        e.axes[MotionEvent.AXIS_RTRIGGER]=1;hardware.motion(e);padKey(KeyEvent.KEYCODE_BUTTON_R2,true);
        for(int i=0;i<50;i++)frame(20);assert wheels>=720&&wheels<=840;
        neutral(e);padKey(KeyEvent.KEYCODE_BUTTON_R2,false);frame(20);
        padKey(KeyEvent.KEYCODE_BUTTON_B,true);padKey(KeyEvent.KEYCODE_BUTTON_R1,true);
        hardware.onInputDeviceRemoved(7);assert !buttons.get(1)&&!keys.get(0xA0);frame(16);assert touch.pending==null;
        padKey(KeyEvent.KEYCODE_BUTTON_A,true);e.axes[MotionEvent.AXIS_X]=1;hardware.motion(e);
        focus=false;frame(16);assert !buttons.get(0)&&hardware.held.isEmpty()&&hardware.pads.isEmpty();focus=true;
        padKey(KeyEvent.KEYCODE_BUTTON_SELECT,true);assert helps==1;
        hardware.release();assert touch.pending==null;
        System.out.println("PASS hardware adapter: keyboard mapping, held references, press-time chords, repeated keys, mouse buttons/wheel, radial speed, precision, drift/NaN, camera, hat/key dedup, trigger dedup, unplug and focus release");
    }
    /* ACTUAL_CODE */
    public static void main(String[] args){new HardwareInputCheck().run();}
}
'''


class HardwareControlsTest(unittest.TestCase):
    def test_actual_hardware_adapter(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        code = function(source, "    private final class HardwareInput ") + function(source, "    private static int keyboardKey(")
        fixture = FIXTURE.replace("    /* ACTUAL_CODE */", code)
        android = (SDK / 'platforms/android-36/android.jar')
        for kind, cls in (("KEY", "KeyEvent"), ("MOTION", "MotionEvent"), ("DEVICE", "InputDevice")):
            listing = subprocess.check_output([str(JAVA / "javap.exe"), "-constants", "-classpath", str(android), "android.view." + cls], text=True)
            constants = re.findall(r"public static final int (\w+) = (-?\d+);", listing)
            self.assertGreater(len(constants), 10)
            fixture = fixture.replace(f"/* {kind}_CONSTANTS */", "\n".join(f"static final int {k}={v};" for k, v in constants))
        out = ROOT / "build/java-hardware-check"
        out.mkdir(exist_ok=True)
        path = out / "HardwareInputCheck.java"
        path.write_text(fixture, encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-d", str(out), str(path)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "HardwareInputCheck"], check=True)


if __name__ == "__main__":
    unittest.main()
