"""Run production Java bank discovery/status/job logic with native-call spies."""
from pathlib import Path
import re
import subprocess
import unittest

from test_touch_controls import JAVA, ROOT
from android_tools import ANDROID_JAR

HARNESS = r'''
package org.homm5.port;
import java.io.*;
import java.nio.file.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;

class TextureService {}
public class BankCheck {
 static final Map<String,long[]> status=new HashMap<>();
 static final List<String> calls=Collections.synchronizedList(new ArrayList<>());
 static long[] progress={0,0,0,0,0};
 static String fail="",cancel="";static int cancelled;
 static CountDownLatch entered,release;
 static String key(String bank){return bank.toLowerCase(Locale.ROOT);}
 static long[] scan(String game,String bank){calls.add("scan:"+key(bank));return status.get(key(bank)).clone();}
 static String message(){return "synthetic bank failure";}
 static void cancel(){++cancelled;progress[0]=Textures.CANCELLED;}
 static long[] progress(){return progress.clone();}
 static int convert(String game,String bank,int format,int threads) {
  String k=key(bank);calls.add("convert:"+k);assert threads>0;
  if(entered!=null) {entered.countDown();try{assert release.await(5,TimeUnit.SECONDS);}catch(InterruptedException e){throw new AssertionError(e);}}
  if(k.equals(cancel)){Textures.current.cancel();return -1;}
  if(Textures.current.cancelled)return -1;
  if(k.equals(fail)){progress=new long[]{Textures.FAILED,0,1,0,16};return -1;}
  long[] s=status.get(k);s[4]=format;s[5]=s[0];s[6]=s[1];s[8]=s[1];
  progress=new long[]{Textures.DONE,1,1,16,16};
  assert Textures.current.progress()[0]!=Textures.DONE : "A single bank is not the completed compound job";
  return 0;
 }
 static int removeOriginals(String game,String bank) {
  String k=key(bank);calls.add("remove-originals:"+k);
  status.get(k)[7]=1;
  if(k.equals(fail)){progress[0]=Textures.FAILED;return -1;}
  status.get(k)[7]=1;status.get(k)[8]=0;progress=new long[]{Textures.DONE,1,1,16,16};return 0;
 }
 static int removeConverted(String game,String bank) {
  String k=key(bank);calls.add("remove-converted:"+k);status.get(k)[4]=0;progress[0]=Textures.DONE;return 0;
 }
 static void reset(){
  status.clear();for(String bank:new String[]{"data","datals","dataa1"})status.put(bank,new long[]{1,16,16,16,0,0,0,0,0});
  calls.clear();fail=cancel="";cancelled=0;entered=release=null;progress=new long[5];Textures.current=null;
 }
 static Textures.Job job(File game,int kind,int format){Textures.Job j=new Textures.Job(game,kind,format);Textures.current=j;j.run();return j;}
 static long operations(){return calls.stream().filter(s->!s.startsWith("scan:")).count();}
 static void ready(){for(long[] s:status.values()){s[4]=Textures.ETC2;s[5]=1;s[6]=16;s[8]=16;}}
 public static void main(String[]args)throws Exception {
  Field loaded=Textures.class.getDeclaredField("loaded");loaded.setAccessible(true);loaded.set(null,Boolean.TRUE);
  Path temp=Files.createTempDirectory("h5-texture-banks-");File game=temp.toFile();
  try {
   for(String name:new String[]{"data","DataLS","dataa1","unrelated"})Files.createDirectory(temp.resolve(name));
   assert Arrays.stream(Textures.banks(game)).map(File::getName).collect(java.util.stream.Collectors.toList()).equals(Arrays.asList("data","DataLS","dataa1"));
   reset();assert Textures.scan(game).textures==3;
   fail="datals";Textures.Job first=job(game,Textures.CONVERT,Textures.ASTC);
   assert first.finished&&first.failure!=null&&!first.cancelled&&first.progress()[0]==Textures.FAILED;
   assert calls.contains("convert:data")&&calls.contains("convert:datals")&&!calls.contains("convert:dataa1");
   Textures.Status partial=Textures.scan(game);assert partial.partial&&partial.converted==0&&!partial.mixedFormats;
   fail="";Textures.Job resumed=job(game,Textures.CONVERT,Textures.ASTC);assert resumed.failure==null&&resumed.progress()[0]==Textures.DONE;
   Textures.Status complete=Textures.scan(game);assert complete.converted==Textures.ASTC&&!complete.partial&&complete.convertedTextures==3;
   status.get("data")[4]=Textures.ETC2;Textures.Status mixed=Textures.scan(game);assert mixed.mixedFormats&&mixed.partial&&mixed.converted==0;
   reset();ready();status.get("datals")[4]=Textures.ASTC;status.get("datals")[7]=1;
   Textures.Job change=job(game,Textures.CONVERT,Textures.ETC2);assert change.failure!=null&&operations()==0 : "Preflight before changing any bank";
   calls.clear();assert job(game,Textures.REMOVE_CONVERTED,0).failure!=null&&operations()==0;
   reset();ready();fail="datals";Textures.Job removal=job(game,Textures.REMOVE_ORIGINALS,0);
   assert removal.failure!=null&&status.get("data")[7]==1&&status.get("datals")[7]==1;
   Textures.Status remaining=Textures.scan(game);assert remaining.originalsRemoved&&remaining.originalsPartiallyRemoved&&remaining.removalPending;
   calls.clear();assert job(game,Textures.REMOVE_CONVERTED,0).failure!=null&&operations()==0;
   fail="";calls.clear();assert job(game,Textures.REMOVE_ORIGINALS,0).failure==null;
   assert !calls.contains("remove-originals:data")&&calls.contains("remove-originals:datals")&&calls.contains("remove-originals:dataa1");
   Textures.Status removed=Textures.scan(game);assert removed.originalsRemoved&&!removed.originalsPartiallyRemoved&&!removed.removalPending;
   reset();cancel="data";Textures.Job stopped=job(game,Textures.CONVERT,Textures.ETC2);
   assert stopped.cancelled&&stopped.failure==null&&stopped.progress()[0]==Textures.CANCELLED&&cancelled==1;
   assert !calls.contains("convert:datals")&&!calls.contains("convert:dataa1");
   reset();entered=new CountDownLatch(1);release=new CountDownLatch(1);
   Textures.Job running=new Textures.Job(game,Textures.CONVERT,Textures.ETC2);Textures.current=running;
   Thread worker=new Thread(running);worker.start();assert entered.await(5,TimeUnit.SECONDS);
   int scans=calls.size();Thread inspector=new Thread(()->Textures.scan(game));inspector.start();
   Thread.sleep(75);assert calls.size()==scans : "A status scan must not reset an active native cancellation";
   running.cancel();assert cancelled==1;release.countDown();worker.join(5000);inspector.join(5000);
   assert !worker.isAlive()&&!inspector.isAlive()&&running.cancelled&&running.failure==null;
   System.out.println("PASS production Java texture banks: discovery, partial/mixed status, compound progress, fail-before-write preflight, only-copy guards, removal resume, cancellation and scan serialization");
  } finally {
   try(java.util.stream.Stream<Path> paths=Files.walk(temp)){for(Path p:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(p);}
  }
 }
}
'''


class TextureBankWorkflowTest(unittest.TestCase):
    def test_production_java_workflow(self):
        out = ROOT / 'build/tests/texture-bank-workflow'
        out.mkdir(parents=True, exist_ok=True)
        text = (ROOT / 'android/app/src/org/homm5/port/Textures.java').read_text()
        bodies = {
            'nativeScanBank': 'return BankCheck.scan(game,bank);',
            'nativeConvertBank': 'return BankCheck.convert(game,bank,format,threads);',
            'nativeRemoveOriginalsBank': 'return BankCheck.removeOriginals(game,bank);',
            'nativeRemoveConvertedBank': 'return BankCheck.removeConverted(game,bank);',
            'nativeCancel': 'BankCheck.cancel();', 'nativeProgress': 'return BankCheck.progress();',
            'nativeMessage': 'return BankCheck.message();',
        }
        for name, body in bodies.items():
            text, count = re.subn(r'(private static) native ([\w\[\]]+ ' + name + r'\([^;]*\));',
                                  lambda match: match[1] + ' ' + match[2] + ' {' + body + '}', text)
            self.assertEqual(count, 1, name)
        (out / 'Textures.java').write_text(text, encoding='utf-8')
        (out / 'BankCheck.java').write_text(HARNESS, encoding='utf-8')
        compiled = subprocess.run([str(JAVA / 'javac.exe'), '--release', '8', '-encoding', 'UTF-8',
                                   '-cp', str(ANDROID_JAR), '-d', str(out), str(out / 'Textures.java'), str(out / 'BankCheck.java')], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        tested = subprocess.run([str(JAVA / 'java.exe'), '-ea', '-cp', str(out) + ';' + str(ANDROID_JAR), 'org.homm5.port.BankCheck'], capture_output=True, text=True, timeout=20)
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
        print(tested.stdout.strip())


if __name__ == '__main__':
    unittest.main()
