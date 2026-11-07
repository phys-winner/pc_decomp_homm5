"""The actual Android overlay must share the native touch viewport, including bars."""
import subprocess
import unittest
from test_d3d_lifecycle import function
from test_touch_controls import ROOT, JAVA


class SplitZoneOverlayTest(unittest.TestCase):
    def test_drawn_zones_match_native_hit_areas(self):
        actual = function((ROOT / 'android/app/src/org/homm5/port/GameActivity.java').read_text(encoding='utf-8'),
                          'private final class TroopZones extends View')
        fixture = r'''
import java.util.*;
public class SplitZoneOverlayCheck {
    static String language="ru";
    static String edition="toe";
    String gameEdition(){return edition;}
    int dp(int value){return value;}
    static class Context {}
    static class View {
        static final int GONE=8,VISIBLE=0,IMPORTANT_FOR_ACCESSIBILITY_NO=2;
        int width,height,visibility;
        View(Context c){}
        int getWidth(){return width;} int getHeight(){return height;}
        void setImportantForAccessibility(int value){} void setVisibility(int value){visibility=value;} void invalidate(){}
        protected void onDraw(Canvas canvas){}
    }
    static class RectF {
        float left,top,right,bottom;
        void set(float l,float t,float r,float b){left=l;top=t;right=r;bottom=b;}
        float width(){return right-left;} float height(){return bottom-top;}
        float centerX(){return (left+right)*.5f;} float centerY(){return (top+bottom)*.5f;}
    }
    static class Paint {
        static final int ANTI_ALIAS_FLAG=1;
        enum Style{FILL,STROKE} enum Align{CENTER}
        float textSize;
        Paint(int flags){} void setColor(int c){} void setStyle(Style s){} void setStrokeWidth(float w){}
        void setTextAlign(Align a){} void setTextSize(float s){textSize=s;} float getTextSize(){return textSize;}
        float measureText(String t){return t.length()*textSize*.55f;}
    }
    static class Canvas {
        List<float[]> boxes=new ArrayList<>();
        List<String> texts=new ArrayList<>();
        List<float[]> ink=new ArrayList<>();
        void drawRoundRect(RectF r,int x,int y,Paint p){boxes.add(new float[]{r.left,r.top,r.right,r.bottom});}
        void drawText(String t,float x,float y,Paint p){texts.add(t);ink.add(new float[]{x-p.measureText(t)/2,x+p.measureText(t)/2});}
        void drawRect(float l,float t,float r,float b,Paint p){}
    }
    /* ACTUAL */
    public static void main(String[] args){
        SplitZoneOverlayCheck owner=new SplitZoneOverlayCheck();
        int[][] cases={{2400,1080,1280,800},{1280,800,640,360},{1280,720,1280,720},
                       {1080,2400,1280,800},{2400,1080,1680,756}};
        for(int[] c:cases){
            TroopZones zones=owner.new TroopZones(new Context());zones.width=c[0];zones.height=c[1];
            zones.update(2,50,c[2],c[3]);Canvas canvas=new Canvas();zones.onDraw(canvas);
            assert canvas.boxes.size()==4;
            double fit=Math.min((double)c[0]/c[2],(double)c[1]/c[3]);
            double ox=(c[0]-c[2]*fit)*.5,oy=(c[1]-c[3]*fit)*.5;
            for(int i=0;i<2;i++){
                float[] b=canvas.boxes.get(i*2);
                double[] expected={i==0?.25:.51,.04,i==0?.49:.75,.18};
                for(int k=0;k<4;k++){
                    double mapped=(b[k]-(k%2==0?ox:oy))/fit/(k%2==0?c[2]:c[3]);
                    assert Math.abs(mapped-expected[k])<.00001 : Arrays.toString(c)+" "+k+" "+mapped;
                }
            }
        }
        TroopZones zones=owner.new TroopZones(new Context());zones.width=2400;zones.height=1080;
        zones.update(-1,0,2400,1080);zones.hint(true,2400,1080);
        Canvas hints=new Canvas();zones.onDraw(hints);
        assert zones.visibility==View.VISIBLE&&hints.boxes.size()==1&&hints.texts.size()==2;
        assert hints.texts.get(0).contains("другим пальцем");
        assert hints.boxes.get(0)[2]-hints.boxes.get(0)[0]<2400*.5f;
        for(String locale:new String[]{"ru","en"})for(int[] c:cases){
            language=locale;
            TroopZones fitHint=owner.new TroopZones(new Context());fitHint.width=c[0];fitHint.height=c[1];
            fitHint.hint(true,c[2],c[3]);Canvas fitted=new Canvas();fitHint.onDraw(fitted);
            float[] box=fitted.boxes.get(0);
            assert Math.abs((box[0]+box[2])/2-c[0]/2f)<.001f;
            assert box[0]>=0&&box[2]<=c[0];
            float widest=0;
            for(float[] line:fitted.ink){
                assert line[0]>=box[0]+11.99f&&line[1]<=box[2]-11.99f;
                widest=Math.max(widest,line[1]-line[0]);
            }
            assert Math.abs(box[2]-box[0]-widest-24)<.001f;
        }
        language="ru";
        zones.update(2,50,2400,1080);Canvas both=new Canvas();zones.onDraw(both);
        assert both.boxes.size()==5&&both.texts.stream().anyMatch(t->t.contains("0,5"));
        zones.hint(false,2400,1080);Canvas onlyZones=new Canvas();zones.onDraw(onlyZones);
        assert onlyZones.boxes.size()==4&&onlyZones.texts.size()==2;
        zones.update(-1,0,2400,1080);assert zones.visibility==View.GONE;
        for(String selected:new String[]{"vanilla","hof"}){
            edition=selected;zones.hint(true,2400,1080);zones.update(2,50,2400,1080);
            Canvas legacy=new Canvas();zones.onDraw(legacy);
            assert legacy.boxes.size()==5&&legacy.texts.stream().anyMatch(t->t.contains("1 с, затем 0,5 с"));
        }
        System.out.println("PASS actual split overlay: native hit bounds at wide, tall, letterboxed and scaled resolutions");
    }
}
'''.replace('/* ACTUAL */', actual)
        out = ROOT / 'build/tests/split-zone-overlay'
        out.mkdir(parents=True, exist_ok=True)
        source = out / 'SplitZoneOverlayCheck.java'
        source.write_text(fixture, encoding='utf-8')
        subprocess.run([str(JAVA / 'javac.exe'), '--release', '8', '-encoding', 'UTF-8', '-d', str(out), str(source)], check=True)
        subprocess.run([str(JAVA / 'java.exe'), '-ea', '-cp', str(out), 'SplitZoneOverlayCheck'], check=True)


if __name__ == '__main__':
    unittest.main()
