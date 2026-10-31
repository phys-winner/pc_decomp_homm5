"""The launcher base's texture card over the port's converter: production TexconvBackend.java and
Textures.java with the native calls of libtexconv.so replaced by spies."""
from pathlib import Path
import re
import shutil
import unittest

from test_launcher_base import APP, LAUNCHER, PLATFORM_JAR, ROOT, java, javac, prepare

HARNESS = r'''
package org.homm5.port;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.*;
import org.homm5.port.launcher.TextureBackend;

public class BackendCheck {
 static final Map<String,long[]> status=new HashMap<>();
 static final List<String> calls=Collections.synchronizedList(new ArrayList<>());
 static long[] progress={0,0,0,0,0};
 static String fail="";static boolean cancelInside;static TexconvBackend backend;static long[] seen;
 static String key(String bank){return bank.toLowerCase(Locale.ROOT);}
 static long[] scan(String game,String bank){calls.add("scan:"+key(bank));long[] s=status.get(key(bank));return s==null?null:s.clone();}
 static String message(){return "synthetic bank failure";}
 static void cancel(){calls.add("cancel");progress[0]=Textures.CANCELLED;}
 static long[] progress(){return progress.clone();}
 static int convert(String game,String bank,int format,int threads){
  String k=key(bank);calls.add("convert:"+k+":"+format);
  progress=new long[]{Textures.CONVERTING,1,2,8,16};seen=backend.progress();
  if(cancelInside){backend.cancel();return -1;}
  if(k.equals(fail))return -1;
  long[] s=status.get(k);s[4]=format;s[5]=s[0];s[6]=s[1];s[8]=s[1];progress=new long[]{Textures.DONE,1,1,16,16};return 0;
 }
 static int removeOriginals(String game,String bank){String k=key(bank);calls.add("remove-originals:"+k);status.get(k)[7]=1;status.get(k)[8]=0;return 0;}
 static int removeConverted(String game,String bank){String k=key(bank);calls.add("remove-converted:"+k);status.get(k)[4]=0;status.get(k)[8]=0;return 0;}
 static void reset(){
  status.clear();for(String bank:new String[]{"data","datals","dataa1"})status.put(bank,new long[]{1,16,16,16,0,0,0,0,0});
  calls.clear();fail="";cancelInside=false;progress=new long[5];seen=null;Textures.current=null;
 }
 static void loaded(Boolean value)throws Exception{Field f=Textures.class.getDeclaredField("loaded");f.setAccessible(true);f.set(null,value);}
 public static void main(String[] args)throws Exception{
  Path temp=Files.createTempDirectory("h5-texconv-backend-");File game=temp.toFile();
  try{
   for(String name:new String[]{"data","DataLS","dataa1"})Files.createDirectory(temp.resolve(name));
   loaded(Boolean.TRUE);reset();backend=new TexconvBackend();
   TextureBackend.Scan s=backend.scan(game);
   assert s.failure==null&&s.textures==3&&s.bytes==48&&s.converted==0&&s.removable==0&&!s.originalsRemoved;
   assert backend.progress()==null : "no operation yet";
   assert backend.convert(game,TextureBackend.ASTC,8)==0 : backend.message();
   assert calls.contains("convert:data:"+Textures.ASTC)&&calls.contains("convert:dataa1:"+Textures.ASTC);
   assert Textures.current!=null&&Textures.current.finished : "the job is the converter's current one";
   assert seen!=null&&seen.length==4&&seen[1]==3&&seen[3]==3000 : "{done, total, bytesDone, bytesTotal} over the banks: "+Arrays.toString(seen);
   s=backend.scan(game);
   assert s.converted==TextureBackend.ASTC&&s.convertedTextures==3&&s.convertedBytes==48 : "converted";
   assert s.removable==48&&!s.originalsRemoved : "the originals can go after a conversion: "+s.removable;
   assert backend.removeOriginals(game)==0 : backend.message();
   s=backend.scan(game);
   assert s.originalsRemoved&&s.removable==0&&s.converted==TextureBackend.ASTC : "the originals are gone";
   calls.clear();
   assert backend.undo(game)==1&&backend.message().contains("only copy") : "no undo without the originals: "+backend.message();
   assert calls.stream().noneMatch(c->c.startsWith("remove-converted")) : "checked before anything changes";
   reset();fail="datals";
   assert backend.convert(game,TextureBackend.ETC2,8)==1&&backend.message().startsWith("DataLS: synthetic bank failure") : backend.message();
   s=backend.scan(game);
   assert s.converted==0 : "a partial conversion is no conversion: converting again finishes it";
   fail="";assert backend.convert(game,TextureBackend.ETC2,8)==0;
   assert backend.scan(game).converted==TextureBackend.ETC2;
   assert backend.undo(game)==0&&backend.scan(game).converted==0 : "undo";
   reset();cancelInside=true;
   assert backend.convert(game,TextureBackend.ETC2,8)==2 : "stopped";
   assert calls.contains("cancel")&&!calls.contains("convert:datals:"+Textures.ETC2) : calls.toString();
   reset();loaded(Boolean.FALSE);
   assert backend.convert(game,TextureBackend.ETC2,8)==1&&backend.message().equals("libtexconv.so");
   assert "libtexconv.so".equals(backend.scan(game).failure);
   loaded(Boolean.TRUE);
   Files.delete(temp.resolve("data"));
   assert backend.scan(game).failure!=null : "a game folder without data cannot be scanned";
   System.out.println("PASS TexconvBackend: scan mapping, compound progress, convert, remove originals, guarded undo, failure, resume, stop, missing converter");
  }finally{
   try(java.util.stream.Stream<Path> paths=Files.walk(temp)){for(Path p:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(p);}
  }
 }
}
'''


@unittest.skipUnless(LAUNCHER is not None and PLATFORM_JAR.is_file(), "the launcher base and android-37.0 are required")
class TexconvBackendTest(unittest.TestCase):
    def test_backend_over_production_textures(self):
        out = ROOT / "build/tests/texconv-backend"
        prepared = prepare(out / "prepared")
        text = (APP / "Textures.java").read_text(encoding="utf-8")
        bodies = {
            "nativeScanBank": "return BackendCheck.scan(game,bank);",
            "nativeConvertBank": "return BackendCheck.convert(game,bank,format,threads);",
            "nativeRemoveOriginalsBank": "return BackendCheck.removeOriginals(game,bank);",
            "nativeRemoveConvertedBank": "return BackendCheck.removeConverted(game,bank);",
            "nativeCancel": "BackendCheck.cancel();", "nativeProgress": "return BackendCheck.progress();",
            "nativeMessage": "return BackendCheck.message();",
        }
        for name, body in bodies.items():
            text, count = re.subn(r"(private static) native ([\w\[\]]+ " + name + r"\([^;]*\));",
                                  lambda match: match[1] + " " + match[2] + " {" + body + "}", text)
            self.assertEqual(count, 1, name)
        source = out / "src/org/homm5/port"
        source.mkdir(parents=True, exist_ok=True)
        (source / "Textures.java").write_text(text, encoding="utf-8")
        (source / "BackendCheck.java").write_text(HARNESS, encoding="utf-8")
        classes = out / "classes"
        if classes.exists():
            shutil.rmtree(classes)
        javac(classes, [*map(Path, prepared["sources"]), APP / "TexconvBackend.java", source / "Textures.java", source / "BackendCheck.java"])
        self.assertIn("PASS TexconvBackend", java(classes, "org.homm5.port.BackendCheck"))

    def test_port_json_names_the_backend_and_the_textures_feature_stays(self):
        backend = (APP / "TexconvBackend.java").read_text(encoding="utf-8")
        self.assertIn("public final class TexconvBackend implements TextureBackend", backend)   # loaded by name in :launcher
        textures = (APP / "Textures.java").read_text(encoding="utf-8")
        for native in ("nativeScanBank", "nativeConvertBank", "nativeRemoveOriginalsBank", "nativeRemoveConvertedBank"):
            self.assertIn(native, textures)   # android/texconv/texconv_jni.cpp binds org.homm5.port.Textures
        self.assertNotIn("TextureService", textures)


if __name__ == "__main__":
    unittest.main()
