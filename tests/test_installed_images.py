"""Exercise installed-image validation, APK-cache migration and native image routing."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_d3d_lifecycle import function
from test_static_tls import compile_probe
from test_touch_controls import JAVA, ROOT

APP = ROOT / "android/app/src/org/homm5/port"

JAVA_CHECK = r'''
package org.homm5.port;
import android.content.Context;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
public class InstalledImagesCheck {
    static void write(File root,String path,byte[] bytes) throws Exception {
        File file=new File(root,path); file.getParentFile().mkdirs(); Files.write(file.toPath(),bytes);
    }
    static void write(File root,String path,String text) throws Exception {write(root,path,text.getBytes(StandardCharsets.UTF_8));}
    static IOException reject(Context c,File game,String id,String reason) throws Exception {
        return reject(c,game,id,false,reason);
    }
    static IOException reject(Context c,File game,String id,boolean allow,String reason) throws Exception {
        try {Assets.verifyOriginals(c,game,id,allow);throw new AssertionError("accepted "+reason);}
        catch(IOException expected) {assert expected.getMessage().contains(reason):expected;return expected;}
    }
    public static void main(String[] args) throws Exception {
        File root=new File(args[0]);
        for(String id:Games.IDS) {
            File game=new File(root,id+"/game"),assets=new File(root,id+"/assets"),own=new File(root,id+"/private");
            Context c=new Context(assets,own);
            String bin=id.equals("hof")?"bina1/":"bin/",images=Games.images(id),overlay=Games.overlay(id);
            byte[] exe="original EXE".getBytes(StandardCharsets.UTF_8),granny="original DLL".getBytes(StandardCharsets.UTF_8);
            // Windows installation names may have different case on Android.
            write(game,bin.toUpperCase()+"h5_GAME.EXE",exe); write(game,bin.toUpperCase()+"GRANNY2.DLL",granny);
            File exeFile=Games.child(game,bin+"H5_Game.exe"),dllFile=Games.child(game,bin+"granny2.dll");
            String first=bin+"H5_Game.exe "+exe.length+" "+NativeLibrary.sha256(exeFile)+"\n";
            String second=bin+"granny2.dll "+granny.length+" "+NativeLibrary.sha256(dllFile)+"\n";
            write(assets,images+"/originals.txt",first+second);
            Assets.verifyOriginals(c,game,id);
            write(game,bin.toUpperCase()+"h5_GAME.EXE","altered EXE!");
            try {Assets.verifyOriginals(c,game,id);throw new AssertionError("strict default accepted another build");}
            catch(Assets.UnsupportedOriginalException expected) {assert expected.path.equals(bin+"H5_Game.exe");}
            Files.write(exeFile.toPath(),new byte[1]);
            IOException mismatch=reject(c,game,id,"Unsupported original file");
            assert mismatch instanceof Assets.UnsupportedOriginalException;
            assert ((Assets.UnsupportedOriginalException)mismatch).path.equals(bin+"H5_Game.exe");
            String diagnosis=mismatch.getMessage();
            assert diagnosis.contains(Games.title(id)+" "+Games.version(id)):diagnosis;
            assert diagnosis.contains("Expected: "+exe.length+" bytes, SHA-256 "+first.trim().split(" ")[2]):diagnosis;
            assert diagnosis.contains("Found: 1 bytes, SHA-256 "+NativeLibrary.sha256(exeFile)):diagnosis;
            assert diagnosis.contains(exeFile.getAbsolutePath()):diagnosis;
            Assets.verifyOriginals(c,game,id,true);
            Files.write(dllFile.toPath(),"another DLL".getBytes(StandardCharsets.UTF_8));
            Assets.verifyOriginals(c,game,id,true); // The choice covers the installed build, not just its first file.
            assert dllFile.delete();
            assert !(reject(c,game,id,false,"missing") instanceof Assets.UnsupportedOriginalException);
            assert !(reject(c,game,id,true,"missing") instanceof Assets.UnsupportedOriginalException);
            Files.write(dllFile.toPath(),granny);
            Files.write(exeFile.toPath(),new byte[0]);
            for(boolean allow:new boolean[]{false,true}) {
                assert !(reject(c,game,id,allow,"empty") instanceof Assets.UnsupportedOriginalException);
            }
            Files.write(exeFile.toPath(),exe); assert dllFile.delete(); reject(c,game,id,"missing");
            Files.write(dllFile.toPath(),granny);
            for(boolean allow:new boolean[]{false,true}) {
                for(String invalid:new String[]{first,first+first,first.replace(bin,"../")+second,
                        first.replace(" "+exe.length+" "," invalid ")+second,
                        first.replace(" "+exe.length+" "," 0 ")+second,
                        first.replace(first.trim().split(" ")[2],"bad-hash")+second}) {
                    write(assets,images+"/originals.txt",invalid);
                    IOException problem=reject(c,game,id,allow,invalid.equals(first)?"Incomplete":"Invalid");
                    assert !(problem instanceof Assets.UnsupportedOriginalException);
                }
            }
            write(assets,images+"/originals.txt",first+second);
            write(assets,images+"/index.txt","fmod.dll 8 unused\noriginals.txt 1 unused\n");
            write(assets,images+"/fmod.dll","prepared");
            write(own,images+"/.apk-index","old build");
            write(own,images+"/H5_Game.exe","old duplicate"); write(own,images+"/granny2.dll","old duplicate");
            File installed=Assets.images(c,root,id);
            assert new File(installed,"fmod.dll").isFile();
            assert !new File(installed,"H5_Game.exe").exists() && !new File(installed,"granny2.dll").exists();
            assert !new File(assets,images+"/H5_Game.exe").exists();
            write(assets,overlay+"/index.txt","data/ui.pak 2 unused\n"); write(assets,overlay+"/data/ui.pak","UI");
            write(own,overlay+"/.apk-index","old music overlay");
            write(own,overlay+"/data/z_homm5_android_town_music.pak","retired patch");
            write(own,overlay+"/data/Sounds/_(Music)/Towns/Haven.(Music).xdb","retired loose patch");
            File current=Assets.overlay(c,false,id);
            assert current!=null && new File(current,"data/ui.pak").isFile();
            assert !new File(current,"data/z_homm5_android_town_music.pak").exists();
            assert !new File(current,"data/Sounds").exists();
            assert java.util.Arrays.equals(Files.readAllBytes(exeFile.toPath()),exe);
            assert java.util.Arrays.equals(Files.readAllBytes(dllFile.toPath()),granny);
            assert new File(assets,images+"/originals.txt").delete(); reject(c,game,id,"originals.txt");
        }
        System.out.println("PASS three editions: original hashes, case-insensitive bin/bina1, rejected bad inputs and old-cache migration");
    }
}
'''

C_CHECK = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define strcasecmp _stricmp
#define F_OK 0
#define VIRTUAL_BIN "C:\\Games\\HeroesV\\" HOMM5_BIN
enum {MOD_LIFTED_EXE,MOD_LIFTED_DLL,MOD_PSEUDO,ST_READY};
typedef struct {char name[64],win_path[260];int kind,state;uint32_t base,size,entry,refs;uint8_t *pristine;} void_module;
typedef struct {const char *name,*file;uint32_t base;int exe,optional;} lifted_spec;
static const lifted_spec lifted[]={{"H5_Game.exe","H5_Game.exe",16,1,0},{"granny2.dll","granny2.dll",32,0,0},{"fmod.dll","fmod.dll",48,0,0}};
static const char *pseudo_names[]={"kernel32.dll"};
static void_module modules[8];static int module_count,missing_count,mapped,absent,unresolvable;static uint32_t exe_base;
static uint8_t memory[128];
#define GPTR(va) (memory+(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
static void add_pseudo(const char *name){(void)name;modules[module_count++].kind=MOD_PSEUDO;}
static void void_log(const char *format,...){(void)format;}
static const char *void_thunk_name(uint32_t va){(void)va;return "stub";}
static char *void_path_to_host(const char *path){
    assert(strstr(path,VIRTUAL_BIN)==path);
    if(unresolvable)return NULL;
    const char *file=strrchr(path,'\\');assert(file);
    char *out=malloc(256);assert(out);snprintf(out,256,"/installed/%s/%s",HOMM5_BIN,file+1);return out;
}
static int access(const char *path,int mode){(void)path;(void)mode;return 0;}
static int map_image(void_module *m,const char *path,uint32_t base){
    char expected[256];
    if(!strcmp(m->name,"fmod.dll"))snprintf(expected,sizeof expected,"/prepared/fmod.dll");
    else snprintf(expected,sizeof expected,"/installed/%s/%s",HOMM5_BIN,m->name);
    assert(!strcmp(path,expected));
    if(absent&&!strcmp(m->name,"H5_Game.exe"))return 0;
    m->base=base;m->size=8;++mapped;return 1;
}
static int bind_imports(void_module *m){assert(m->base);return 1;}
/* ACTUAL */
static void reset(void){
    for(int i=0;i<module_count;++i)free(modules[i].pristine);
    memset(modules,0,sizeof modules);module_count=0;mapped=0;
}
int main(void){
    assert(void_modules_init("/prepared"));assert(mapped==3&&exe_base==16);reset();
    absent=1;assert(!void_modules_init("/prepared"));assert(!mapped);reset();absent=0;
    unresolvable=1;assert(!void_modules_init("/prepared"));assert(!mapped);reset();
    printf("PASS native routing %s: installed EXE/Granny, prepared FMOD, no fallback on missing original\n",HOMM5_BIN);return 0;
}
'''


class InstalledImagesTest(unittest.TestCase):
    def test_original_hashes_and_upgrade_remove_retired_assets(self):
        with tempfile.TemporaryDirectory(prefix="homm5-installed-") as temp:
            out = Path(temp)
            files = {
                "android/content/Context.java": '''package android.content;
                    import java.io.*;
                    public class Context {
                        private final File assets,files;
                        public Context(File a,File f){assets=a;files=f;}
                        public Context getAssets(){return this;}
                        public File getFilesDir(){return files;}
                        public InputStream open(String name)throws IOException{return new FileInputStream(new File(assets,name));}
                    }''',
                "android/util/Log.java": '''package android.util; public class Log {
                    public static int w(String tag,String text){return 0;}
                    public static int i(String tag,String text){return 0;}
                }''',
                "org/homm5/port/Assets.java": (APP / "Assets.java").read_text(),
                "org/homm5/port/Games.java": (APP / "Games.java").read_text(),
                "org/homm5/port/NativeLibrary.java": '''package org.homm5.port;
                    import java.io.*;import java.security.*;
                    class NativeLibrary {
                        static boolean available(android.content.Context c,String name){return true;}
                        ''' + function((APP / "NativeLibrary.java").read_text(), "static String sha256(") + "}",
                "org/homm5/port/InstalledImagesCheck.java": JAVA_CHECK,
            }
            for name, source in files.items():
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out),
                            *[str(out / name) for name in files]], check=True)
            subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "org.homm5.port.InstalledImagesCheck",
                            str(out / "data")], check=True)
        activity = (APP / "GameActivity.java").read_text(encoding="utf-8")
        worker = activity[activity.index('new Thread(() -> {'):activity.index('}, "native-library").start();')]
        self.assertLess(worker.index("Assets.verifyOriginals("), worker.index("NativeLibrary.load("))

    def test_native_loader_reads_the_selected_installation(self):
        actual = function((ROOT / "android/host/pe.c").read_text(), "int void_modules_init(")
        for bin_name in ("bin", "bina1"):
            with self.subTest(bin=bin_name):
                compile_probe("installed_images_" + bin_name, C_CHECK.replace("/* ACTUAL */", actual), {},
                              extra_flags=(f'/DHOMM5_BIN="{bin_name}"',))


if __name__ == "__main__":
    unittest.main()
