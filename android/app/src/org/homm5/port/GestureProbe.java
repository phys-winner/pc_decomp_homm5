package org.homm5.port;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;

/** Development aid: replays scripted multi-finger gestures into the touch
 *  layer, which adb's single-pointer input cannot. Present only while the
 *  flag file <base>/gestures exists. Driven by
 *
 *    adb shell am broadcast -a org.homm5.port.GESTURE -p org.homm5.port --es script "STEPS"
 *
 *  STEPS, separated by ';' (coordinates in screen pixels, times in ms):
 *    down ID X Y | move ID X Y | up ID | wait MS
 *    glide MS ID X Y [ID X Y ...]   the listed fingers move in a straight line, 60 Hz. */
final class GestureProbe extends BroadcastReceiver {
    static final String ACTION = "org.homm5.port.GESTURE";
    private static final long FRAME_MS = 16;

    private final View target;
    private final Handler handler = new Handler(Looper.getMainLooper());
    /* Finger ID -> position, in pointer index order. */
    private final LinkedHashMap<Integer, float[]> fingers = new LinkedHashMap<>();
    private long downTime;

    private GestureProbe(View target) { this.target = target; }

    static GestureProbe register(Context context, View target, File base) {
        if (!new File(base, "gestures").exists()) return null;
        GestureProbe probe = new GestureProbe(target);
        IntentFilter filter = new IntentFilter(ACTION);
        if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(probe, filter, Context.RECEIVER_EXPORTED);
        else context.registerReceiver(probe, filter);
        Log.i("HeroesV", "gesture probe ready");
        return probe;
    }

    @Override public void onReceive(Context context, Intent intent) {
        String script = intent.getStringExtra("script");
        if (script == null) return;
        long start = SystemClock.uptimeMillis() + FRAME_MS, at = 0;
        /* Planned positions, so a glide starts where the previous steps left each finger. */
        Map<Integer, float[]> planned = new LinkedHashMap<>();
        for (Map.Entry<Integer, float[]> finger : fingers.entrySet()) planned.put(finger.getKey(), finger.getValue().clone());
        try {
            for (String step : script.split(";")) {
                String[] w = step.trim().split("\\s+");
                if (w.length == 0 || w[0].isEmpty()) continue;
                switch (w[0]) {
                case "wait":
                    at += Long.parseLong(w[1]);
                    break;
                case "down": case "move": {
                    int id = Integer.parseInt(w[1]);
                    float x = Float.parseFloat(w[2]), y = Float.parseFloat(w[3]);
                    planned.put(id, new float[] {x, y});
                    String kind = w[0];
                    handler.postAtTime(() -> apply(kind, id, x, y), start + at);
                    break;
                }
                case "up": {
                    int id = Integer.parseInt(w[1]);
                    planned.remove(id);
                    handler.postAtTime(() -> apply("up", id, 0, 0), start + at);
                    break;
                }
                case "glide": {
                    long duration = Long.parseLong(w[1]);
                    ArrayList<float[]> paths = new ArrayList<>();   /* id, x0, y0, x1, y1 */
                    for (int i = 2; i + 2 < w.length; i += 3) {
                        int id = Integer.parseInt(w[i]);
                        float[] from = planned.get(id);
                        if (from == null) throw new IllegalArgumentException("glide of a finger that is up: " + id);
                        float x = Float.parseFloat(w[i + 1]), y = Float.parseFloat(w[i + 2]);
                        paths.add(new float[] {id, from[0], from[1], x, y});
                        planned.put(id, new float[] {x, y});
                    }
                    long frames = Math.max(1, duration / FRAME_MS);
                    for (long f = 1; f <= frames; ++f) {
                        float t = (float)f / frames;
                        /* One event per frame carries every finger, as the touch screen reports them. */
                        handler.postAtTime(() -> {
                            boolean moved = false;
                            for (float[] path : paths) {
                                float[] finger = fingers.get((int)path[0]);
                                if (finger == null) continue;
                                finger[0] = path[1] + (path[3] - path[1]) * t;
                                finger[1] = path[2] + (path[4] - path[2]) * t;
                                moved = true;
                            }
                            if (moved) dispatch(MotionEvent.ACTION_MOVE);
                        }, start + at + f * FRAME_MS);
                    }
                    at += frames * FRAME_MS;
                    break;
                }
                default:
                    throw new IllegalArgumentException("unknown step " + w[0]);
                }
            }
        } catch (RuntimeException error) {
            Log.w("HeroesV", "gesture script rejected: " + error);
        }
    }

    private void apply(String kind, int id, float x, float y) {
        int action;
        if (kind.equals("down")) {
            if (fingers.containsKey(id)) return;
            fingers.put(id, new float[] {x, y});
            int index = indexOf(id);
            if (fingers.size() == 1) downTime = SystemClock.uptimeMillis();
            action = fingers.size() == 1 ? MotionEvent.ACTION_DOWN
                   : MotionEvent.ACTION_POINTER_DOWN | (index << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        } else if (kind.equals("move")) {
            float[] at = fingers.get(id);
            if (at == null) return;
            at[0] = x; at[1] = y;
            action = MotionEvent.ACTION_MOVE;
        } else {
            if (!fingers.containsKey(id)) return;
            int index = indexOf(id);
            action = fingers.size() == 1 ? MotionEvent.ACTION_UP
                   : MotionEvent.ACTION_POINTER_UP | (index << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
        }
        dispatch(action);
        if (kind.equals("up")) fingers.remove(id);
    }

    private int indexOf(int id) {
        int index = 0;
        for (int key : fingers.keySet()) { if (key == id) return index; ++index; }
        return -1;
    }

    private void dispatch(int action) {
        int count = fingers.size(), i = 0;
        MotionEvent.PointerProperties[] properties = new MotionEvent.PointerProperties[count];
        MotionEvent.PointerCoords[] coords = new MotionEvent.PointerCoords[count];
        for (Map.Entry<Integer, float[]> finger : fingers.entrySet()) {
            properties[i] = new MotionEvent.PointerProperties();
            properties[i].id = finger.getKey();
            properties[i].toolType = MotionEvent.TOOL_TYPE_FINGER;
            coords[i] = new MotionEvent.PointerCoords();
            coords[i].x = finger.getValue()[0];
            coords[i].y = finger.getValue()[1];
            coords[i].pressure = 1;
            coords[i].size = 0.05f;
            ++i;
        }
        MotionEvent event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action, count, properties, coords,
                0, 0, 1, 1, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0);
        target.dispatchTouchEvent(event);
        event.recycle();
    }
}
