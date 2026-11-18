"""Run createLoading with a small FrameLayout gravity/measurement model, not an Android decoder.

The center-gravity margin formula mirrors FrameLayout.layoutChildren: asymmetric top/bottom margins
on a MATCH_PARENT child move its top above the viewport. Device captures remain a separate gate.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

HARNESS = r'''
package org.homm5.port;
import java.util.*;
public class GameActivity {
 static class Color {static final int BLACK=0xff000000;static int rgb(int r,int g,int b){return 0xff000000|r<<16|g<<8|b;}}
 static class Gravity {static final int LEFT=3,TOP=48,BOTTOM=80,CENTER=17;}
 static class Bitmap {int width,height;Bitmap(int w,int h){width=w;height=h;}}
 static class View {
  static final int VISIBLE=0,GONE=8;
  int left,top,width,height,visibility=VISIBLE,color;boolean clickable;FrameLayout.LayoutParams params;
  void setBackgroundColor(int c){color=c;}void setClickable(boolean c){clickable=c;}
  void setVisibility(int v){visibility=v;}
  int wrapHeight(){return 0;}
 }
 static class FrameLayout extends View {
  static class LayoutParams {
   int width,height,gravity=-1,leftMargin,topMargin,rightMargin,bottomMargin;
   LayoutParams(int w,int h){width=w;height=h;}LayoutParams(int w,int h,int g){this(w,h);gravity=g;}
   void setMargins(int l,int t,int r,int b){leftMargin=l;topMargin=t;rightMargin=r;bottomMargin=b;}
  }
  List<View> children=new ArrayList<>();FrameLayout(GameActivity a){}
  void addView(View child,LayoutParams p){child.params=p;children.add(child);}
  void layout(int x,int y,int w,int h){
   left=x;top=y;width=w;height=h;
   for(View child:children){
    LayoutParams p=child.params;
    int cw=p.width<0?w-p.leftMargin-p.rightMargin:p.width;
    int ch=p.height==-1?h-p.topMargin-p.bottomMargin:child.wrapHeight();
    int g=p.gravity==-1?Gravity.TOP|Gravity.LEFT:p.gravity;
    int cx,cy;
    switch(g&7){case 1:cx=(w-cw)/2+p.leftMargin-p.rightMargin;break;
     case 5:cx=w-cw-p.rightMargin;break;default:cx=p.leftMargin;}
    switch(g&112){case 16:cy=(h-ch)/2+p.topMargin-p.bottomMargin;break;
     case 80:cy=h-ch-p.bottomMargin;break;default:cy=p.topMargin;}
    if(child instanceof FrameLayout)((FrameLayout)child).layout(x+cx,y+cy,cw,ch);
    else {child.left=x+cx;child.top=y+cy;child.width=cw;child.height=ch;}
   }
  }
 }
 static class ImageView extends View {
  enum ScaleType {FIT_CENTER}ScaleType scale;Bitmap bitmap;ImageView(GameActivity a){}
  void setScaleType(ScaleType s){scale=s;}void setImageBitmap(Bitmap b){bitmap=b;}
 }
 static class TextView extends View {
  final GameActivity a;String text;int gravity,size,paddingTop,paddingBottom;
  TextView(GameActivity a){this.a=a;}void setText(String s){text=s;}void setTextColor(int c){color=c;}
  void setTextSize(int n){size=n;}void setGravity(int g){gravity=g;}
  void setPadding(int l,int t,int r,int b){paddingTop=t;paddingBottom=b;}
  int wrapHeight(){return a.dp(size)+paddingTop+paddingBottom;}
 }
 static class Games {static String title(String edition){return "Heroes V: "+edition;}}
 float density;String edition;Bitmap startupArtwork;ImageView loadingImage;TextView loadingTitle,loadingText;
 View loading;FrameLayout game=new FrameLayout(this);
 static final int T_PREPARING=5;
 int dp(int n){return Math.round(n*density);}String gameEdition(){return edition;}
 static String text(int id){assert id==T_PREPARING;return "Preparing game...";}
 /* ACTUAL */
 void check(int w,int h,Bitmap bitmap){
  startupArtwork=bitmap;game=new FrameLayout(this);createLoading();game.layout(0,0,w,h);
  assert loading instanceof FrameLayout&&loading.color==Color.BLACK&&loading.clickable;
  assert loadingImage.scale==ImageView.ScaleType.FIT_CENTER&&loadingImage.bitmap==bitmap;
  assert loadingTitle.visibility==(bitmap==null?View.VISIBLE:View.GONE);
  assert loadingText.params.gravity==Gravity.BOTTOM&&loadingText.top>=0;
  assert loadingText.top+loadingText.height<=h;
  if(bitmap==null)return;
  ImageView image=loadingImage;FrameLayout.LayoutParams p=image.params;
  assert image.left>=0&&image.top>=0 : "image view is clipped above the viewport: "+image.top;
  assert image.width>0&&image.height>0;
  double scale=Math.min(image.width/(double)bitmap.width,image.height/(double)bitmap.height);
  double dw=scale*bitmap.width,dh=scale*bitmap.height;
  double x=image.left+(image.width-dw)*.5,y=image.top+(image.height-dh)*.5;
  assert x>=p.leftMargin-.01&&y>=p.topMargin-.01 : "artwork outside reserved rectangle";
  assert x+dw<=w-p.rightMargin+.01&&y+dh<=h-p.bottomMargin+.01;
  assert Math.abs((x+dw*.5)-(p.leftMargin+(w-p.rightMargin))*.5)<=1;
  assert Math.abs((y+dh*.5)-(p.topMargin+(h-p.bottomMargin))*.5)<=1;
  assert y+dh<=loadingText.top : "artwork overlaps bottom status";
  assert Math.abs(dw/dh-bitmap.width/(double)bitmap.height)<.00001;
 }
 public static void main(String[] args){
  int[][] screens={{2400,1080},{1920,1080},{1280,800},{1080,2400}};
  Bitmap[] art={new Bitmap(800,600),new Bitmap(640,480),new Bitmap(434,600),new Bitmap(1024,768),null};
  for(String edition:new String[]{"toe","vanilla","hof"})for(float density:new float[]{1,1.5f,2.75f,4})
   for(int[] screen:screens)for(Bitmap bitmap:art){GameActivity a=new GameActivity();a.density=density;a.edition=edition;
    a.check(screen[0],screen[1],bitmap);}
  System.out.println("PASS actual loading layout: full reserved artwork rectangle, FIT_CENTER/aspect, title fallback and bottom status; 240 modeled screen/density/edition/art combinations");
 }
}
'''


class StartupLayoutTest(unittest.TestCase):
    def run_layout(self, method):
        with tempfile.TemporaryDirectory(prefix="startup-layout-", dir=ROOT / "build/tests") as directory:
            out = Path(directory)
            source = out / "GameActivity.java"
            source.write_text(HARNESS.replace("/* ACTUAL */", method), encoding="utf8")
            compiled = subprocess.run([str(JAVA / "javac.exe"), "-encoding", "UTF-8", "-d", str(out), str(source)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            return subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "org.homm5.port.GameActivity"],
                                  capture_output=True, text=True, timeout=15)

    def actual(self):
        return function((ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8"),
                        "private void createLoading(")

    def test_actual_loading_geometry(self):
        result = self.run_layout(self.actual())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_old_centered_match_parent_is_rejected(self):
        actual = self.actual()
        correct = "new FrameLayout.LayoutParams(-1, -1, Gravity.TOP | Gravity.LEFT)"
        self.assertEqual(actual.count(correct), 1)
        result = self.run_layout(actual.replace(correct, "new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER)"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("image view is clipped above the viewport", result.stderr)


if __name__ == "__main__":
    unittest.main()
