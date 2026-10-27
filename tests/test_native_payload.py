"""Exercise native payload framing and the real Java install/retry/cache logic."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_game_apk as builder

JAVA = Path(os.environ.get("JAVA_HOME", "C:/Portable/jdk-24.0.1")) / "bin"


class NativePayloadTest(unittest.TestCase):
    def test_real_arm64_xz_chunks_cache_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(builder, "ROOT", Path(directory)), patch.object(builder, "CHUNK", 4096):
            library = Path(directory) / "libtest.so"
            data = (b"\x00\x00\x00\x94\x1f\x20\x03\xd5" * 1100) + b"tail"
            library.write_bytes(data)
            packed, row = builder.compress_library(library)
            name, size, digest, chunk, sizes = row.split()
            streams = [int(size) for size in sizes.split(",")]
            self.assertEqual((name, int(size), digest, int(chunk)), (library.name, len(data), hashlib.sha256(data).hexdigest(), 4096))
            self.assertEqual(len(streams), 3)
            decoded = subprocess.run([builder.xz_tool(), "-dc", str(packed)], capture_output=True, check=True).stdout
            self.assertEqual(decoded, data)
            mtime = packed.stat().st_mtime_ns
            with patch.object(builder, "xz_tool", side_effect=AssertionError("cache must be reused")):
                self.assertEqual(builder.compress_library(library), (packed, row))
            self.assertEqual(packed.stat().st_mtime_ns, mtime)
            packed.with_suffix(".sizes").write_text("1", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Invalid native XZ cache"):
                builder.compress_library(library)

    @unittest.skipUnless((JAVA / "javac.exe").is_file(), "JDK required")
    def test_actual_java_installer_retry_hash_update_and_availability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                "android/content/Context.java": '''package android.content;
public class Context {
 public java.io.File files; public android.content.res.AssetManager assets;
 public static class Info {public String nativeLibraryDir;}
 public Info info=new Info();
 public java.io.File getFilesDir(){return files;}
 public android.content.res.AssetManager getAssets(){return assets;}
 public Info getApplicationInfo(){return info;}
}''',
                "android/content/res/AssetManager.java": '''package android.content.res;
public class AssetManager {
 public String index;
 public java.io.InputStream open(String path) throws java.io.IOException {
  if(index==null)throw new java.io.FileNotFoundException(path);
  return new java.io.ByteArrayInputStream(index.getBytes(java.nio.charset.StandardCharsets.US_ASCII));
 }
}''',
                "android/os/SystemClock.java": "package android.os; public class SystemClock {public static long elapsedRealtime(){return 0;}}",
                "android/util/Log.java": "package android.util; public class Log {public static int i(String tag,String text){return 0;}}",
            }
            source = (ROOT / "android/app/src/org/homm5/port/NativeLibrary.java").read_text(encoding="utf-8")
            source = source.replace("System.loadLibrary(", "PayloadCheck.loadLibrary(").replace("System.load(", "PayloadCheck.load(")
            source = source.replace("private static native long nativeUnpack(AssetManager assets, String name, String path,\n                                            long total, int chunk, int[] sizes);", '''private static long nativeUnpack(AssetManager assets,String name,String path,long total,int chunk,int[] sizes) {
                ++PayloadCheck.unpacks;
                try { java.nio.file.Files.write(new File(path).toPath(),PayloadCheck.payload); }
                catch(IOException e){throw new RuntimeException(e);}
                return PayloadCheck.fail ? -1 : total;
            }''')
            self.assertNotIn("native long nativeUnpack", source)
            sources["org/homm5/port/NativeLibrary.java"] = source
            sources["org/homm5/port/PayloadCheck.java"] = r'''package org.homm5.port;
import java.io.*;import java.nio.file.*;import java.security.*;import android.content.Context;import android.content.res.AssetManager;
public class PayloadCheck {
 static byte[] payload="first engine".getBytes();static int unpacks,loads;static boolean fail;
 static void load(String file){assert new File(file).isFile();++loads;}
 static void loadLibrary(String name){assert name.equals("homm5xz");}
 static String hash(byte[] data)throws Exception {
  StringBuilder s=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(data))s.append(String.format("%02x",b&255));return s.toString();
 }
 static void index(Context c,String name)throws Exception {c.assets.index=name+" "+payload.length+" "+hash(payload)+" 4096 24\n";}
 static void invalid(Context c)throws Exception {
  int before=loads;try{NativeLibrary.load(c,"homm5");throw new AssertionError("invalid payload accepted");}
  catch(IOException expected){}assert before==loads;
 }
 public static void main(String[] args)throws Exception {
  Context c=new Context();c.files=new File(args[0]);c.files.mkdirs();c.info.nativeLibraryDir=new File(c.files,"lib").getPath();c.assets=new AssetManager();
  String name=System.mapLibraryName("homm5");File target=new File(c.files,"native/"+name),stamp=new File(target+".sha256"),part=new File(target+".part");
  assert !NativeLibrary.available(c,"homm5");index(c,name);assert NativeLibrary.available(c,"homm5");
  fail=true;invalid(c);assert !target.exists()&&!stamp.exists()&&!part.exists();
  fail=false;NativeLibrary.load(c,"homm5");assert unpacks==2&&loads==1&&stamp.isFile();
  NativeLibrary.load(c,"homm5");assert unpacks==2&&loads==2;
  Files.write(target.toPath(),new byte[1]);NativeLibrary.load(c,"homm5");assert unpacks==3&&loads==3;
  byte[] old=Files.readAllBytes(target.toPath());payload="next engine!".getBytes();index(c,name);
  String expected=c.assets.index;payload[0]^=1;invalid(c);assert java.util.Arrays.equals(old,Files.readAllBytes(target.toPath()))&&!stamp.exists()&&!part.exists();
  payload[0]^=1;Files.write(part.toPath(),new byte[]{1});NativeLibrary.load(c,"homm5");assert loads==4&&!part.exists();
  assert java.util.Arrays.equals(payload,Files.readAllBytes(target.toPath()));
  for(String bad:new String[]{name+" 1 broken 4096 24",name+" -1 "+hash(payload)+" 4096 24",name+" 1 "+hash(payload)+" 0 24",name+" 1 "+hash(payload)+" 4096 -24",name+" 1 "+hash(payload)+" 4096 24,24",name+" 1 "+hash(payload)+" 4096 24,"}){
   c.assets.index=bad;assert !NativeLibrary.available(c,"homm5");invalid(c);
  }
  c.assets.index=expected.replace(name,"other.so");assert !NativeLibrary.available(c,"homm5");invalid(c);
  c.assets.index=null;File plain=new File(c.info.nativeLibraryDir,name);plain.getParentFile().mkdirs();assert plain.createNewFile();assert NativeLibrary.available(c,"homm5");
  System.out.println("PASS real Java payload install: retry, SHA rejection, atomic old-copy preservation, update, cache, malformed index and availability");
 }
}'''
            paths = []
            for name, text in sources.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                paths.append(str(path))
            subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(root), *paths], check=True, capture_output=True)
            subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(root), "org.homm5.port.PayloadCheck", str(root / "files")], check=True)


if __name__ == "__main__":
    unittest.main()
