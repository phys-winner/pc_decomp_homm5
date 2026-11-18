"""Bounded decoder/loader tests on synthetic art; no licensed assets or Android bitmap emulation claims."""
from pathlib import Path
import subprocess
import unittest

from test_touch_controls import ROOT, JAVA

STUBS = {
    "android/graphics/Bitmap.java": r'''
package android.graphics;
public class Bitmap {
 public enum Config { ARGB_8888 }
 public final int width,height;public final int[] pixels;
 public Bitmap(int w,int h,int[] p){width=w;height=h;pixels=p;}
 public static Bitmap createBitmap(int[] p,int o,int stride,int w,int h,Config config){
  assert o>=0&&stride>=w&&p.length>=o+(h-1)*stride+w;
  return new Bitmap(w,h,java.util.Arrays.copyOfRange(p,o,o+h*stride));
 }
}
''',
    "android/graphics/BitmapFactory.java": r'''
package android.graphics;
public class BitmapFactory {
 public static class Options { public boolean inJustDecodeBounds;public int outWidth,outHeight; }
 public static int decodes;
 public static Bitmap decodeFile(String p,Options options){
  try{byte[] b=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(p));
   if(b.length==4){options.outWidth=800;options.outHeight=600;}
   else {options.outWidth=5000;options.outHeight=5000;}
  }catch(java.io.IOException e){}return null;
 }
 public static Bitmap decodeFile(String p){
  ++decodes;
  try{byte[] b=java.nio.file.Files.readAllBytes(java.nio.file.Paths.get(p));
   return b[0]==1?new Bitmap(800,600,null):null;
  }catch(java.io.IOException e){return null;}
 }
}
''',
    "android/util/Log.java": '''package android.util;public class Log {
 public static int w(String tag,String text,Throwable error){return 0;}
}''',
    "org/homm5/port/Games.java": r'''
package org.homm5.port;
import java.io.File;
final class Games {
 static File child(File parent,String path) {
  File current=parent;
  for(String part:path.split("/")) {
   File[] files=current.listFiles();if(files==null)return null;
   current=null;for(File file:files)if(file.getName().equalsIgnoreCase(part)){current=file;break;}
   if(current==null)return null;
  }return current;
 }
}
''',
}

CHECK = r'''
package org.homm5.port;
import android.graphics.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;
public class StartupArtCheck {
 static void put(byte[] b,int p,int v){for(int i=0;i<4;++i)b[p+i]=(byte)(v>>>(8*i));}
 static byte[] header(int w,int h,int size,int format){
  byte[] b=new byte[128+size];put(b,0,0x20534444);put(b,4,124);put(b,76,32);
  put(b,12,h);put(b,16,w);put(b,84,format);return b;
 }
 static byte[] rgba(int w,int h,int padding,boolean alpha){
  int pitch=w*4+padding;byte[] b=header(w,h,h*pitch,0);
  put(b,8,8);put(b,20,pitch);put(b,88,32);put(b,92,0xff0000);put(b,96,0xff00);put(b,100,255);
  put(b,104,alpha?0xff000000:0);
  for(int y=0;y<h;++y)for(int x=0;x<w;++x)put(b,128+y*pitch+x*4,0x42102000+y*w+x);
  return b;
 }
 static void dxtBlock(byte[] b,int p,int c0,int c1){
  for(int i=0;i<8;++i)b[p+i]=(byte)(i*2+(i*2+1)*16);
  b[p+8]=(byte)c0;b[p+9]=(byte)(c0>>8);b[p+10]=(byte)c1;b[p+11]=(byte)(c1>>8);
  put(b,p+12,0xe4e4e4e4);
 }
 static void decoders(){
  for(boolean alpha:new boolean[]{false,true}) {
   byte[] data=rgba(7,3,4,alpha);int[] p=StartupArt.decodeDds(data);assert p.length==21;
   for(int i=0;i<p.length;++i)assert p[i]==((alpha?0x42102000:0xff102000)+i);
   assert StartupArt.decodeDds(Arrays.copyOf(data,data.length-1))==null;
  }
  byte[] dxt=header(4,4,16,0x33545844);dxtBlock(dxt,128,0xf800,0x07e0);
  int[] p=StartupArt.decodeDds(dxt);int[] colors={0xff0000,0x00ff00,0xaa5500,0x55aa00};
  for(int i=0;i<16;++i)assert p[i]==((i*17<<24)|colors[i%4]);
  dxt=header(5,3,32,0x33545844);dxtBlock(dxt,128,0xf800,0x07e0);dxtBlock(dxt,144,0x001f,0xffff);
  p=StartupArt.decodeDds(dxt);assert p.length==15&&p[4]==0x000000ff&&p[9]==0x440000ff&&p[14]==0x880000ff;
  assert StartupArt.decodeDds(Arrays.copyOf(dxt,dxt.length-1))==null;
  assert StartupArt.decodeDds(null)==null;
  for(int n=0;n<128;++n)assert StartupArt.decodeDds(new byte[n])==null;
  for(int where:new int[]{0,4,76,84,88,92,96,100}){
   byte[] bad=rgba(2,2,0,true);put(bad,where,17);assert StartupArt.decodeDds(bad)==null;
  }
  for(int size:new int[]{0,-1,Integer.MAX_VALUE,2049})for(int axis:new int[]{12,16}){
   byte[] bad=rgba(2,2,0,true);put(bad,axis,size);assert StartupArt.decodeDds(bad)==null;
  }
  for(int stride:new int[]{-1,1,Integer.MAX_VALUE}){
   byte[] bad=rgba(2,2,0,true);put(bad,20,stride);assert StartupArt.decodeDds(bad)==null;
  }
 }
 static void bank(Path game,String filename,String entry,byte[] bytes)throws IOException{
  Path p=game.resolve(filename);Files.createDirectories(p.getParent());
  try(ZipOutputStream zip=new ZipOutputStream(Files.newOutputStream(p))){zip.putNextEntry(new ZipEntry(entry));zip.write(bytes);zip.closeEntry();}
 }
 static void loader(Path work)throws Exception{
  assert StartupArt.load(null,"toe")==null;
  String[] editions={"toe","hof","vanilla"},splashes={"splasha2.bmp","splasha1.bmp","splash.bmp"};
  String[] suffixes={"A2","A1",""},banks={"data/a2p1-data.pak","dataa1/a1p1-data.pak","DataLS/p6-data.pak"};
  for(int i=0;i<editions.length;++i){
   String e=editions[i];Path game=work.resolve(e);Files.createDirectories(game);
   assert StartupArt.splashName(e).equals(splashes[i]);assert StartupArt.load(game.toFile(),e)==null;
   String entry=("UI/pwlscreen/Front"+suffixes[i]+".(Texture).dds").toUpperCase(Locale.ROOT);
   bank(game,banks[i],entry,rgba(7,3,4,true));Bitmap b=StartupArt.load(game.toFile(),e);
   assert b!=null&&b.width==7&&b.height==3&&b.pixels[20]==0x42102014;
   Path splash=game.resolve(splashes[i].toUpperCase(Locale.ROOT));
   Files.write(splash,new byte[]{1,0,0,0});b=StartupArt.load(game.toFile(),e);assert b.width==800&&b.height==600;
   Files.write(splash,new byte[]{0,0,0,0});b=StartupArt.load(game.toFile(),e);assert b.width==7; // Bounds but decode failure falls back.
   int decodes=BitmapFactory.decodes;
   Files.write(splash,new byte[5]);assert StartupArt.load(game.toFile(),e).width==7;assert BitmapFactory.decodes==decodes;
   try(RandomAccessFile large=new RandomAccessFile(splash.toFile(),"rw")){large.setLength(17*1024*1024+1);}
   assert StartupArt.load(game.toFile(),e).width==7;assert BitmapFactory.decodes==decodes;
   Files.delete(splash);
   bank(game,banks[i],entry,rgba(1024,1024,0,false));b=StartupArt.load(game.toFile(),e);
   assert b.width==1024&&b.height==768&&b.pixels.length==1024*768;
   bank(game,"data/data.pak",entry,rgba(3,2,0,false));
   Files.write(game.resolve(banks[i]),new byte[]{1,2,3}); // Bad higher-priority bank, valid base bank.
   b=StartupArt.load(game.toFile(),e);assert b.width==3&&b.height==2;
  }
  java.lang.reflect.Method read=StartupArt.class.getDeclaredMethod("read",InputStream.class);read.setAccessible(true);
  InputStream huge=new InputStream(){int remaining=17*1024*1024+1;
   public int read(){return remaining--<=0?-1:0;}
   public int read(byte[] b,int p,int n){if(remaining==0)return -1;int count=Math.min(n,remaining);remaining-=count;return count;}
  };
  try{read.invoke(null,huge);throw new AssertionError("unbounded artwork input");}
  catch(java.lang.reflect.InvocationTargetException expected){assert expected.getCause() instanceof IOException;}
 }
 public static void main(String[] args)throws Exception{
  decoders();loader(Paths.get(args[0]));
  System.out.println("PASS actual StartupArt: BGRA pitch/alpha, DXT3 colors/alpha/edge blocks, malformed bounds and lengths, all-edition bank/name/case fallback, bitmap decode failure, crop and bounded input (synthetic bitmap adapter)");
 }
}
'''


class StartupArtTest(unittest.TestCase):
    def test_actual_decoder_and_loader(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="startup-art-", dir=ROOT / "build/tests") as directory:
            out = Path(directory)
            files = dict(STUBS)
            files["org/homm5/port/StartupArt.java"] = (ROOT / "android/app/src/org/homm5/port/StartupArt.java").read_text()
            files["org/homm5/port/StartupArtCheck.java"] = CHECK
            for name, text in files.items():
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf8")
            compiled = subprocess.run([str(JAVA / "javac.exe"), "-encoding", "UTF-8", "-d", str(out),
                                       *[str(out / p) for p in files]], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            tested = subprocess.run([str(JAVA / "java.exe"), "-ea", "-Xmx256m", "-cp", str(out),
                                     "org.homm5.port.StartupArtCheck", str(out / "inputs")],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            print(tested.stdout.strip())


if __name__ == "__main__":
    unittest.main()
