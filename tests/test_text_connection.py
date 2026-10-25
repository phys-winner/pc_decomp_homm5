"""Exercise the actual Android InputConnection and focus-generation methods."""
import subprocess
import unittest
from test_touch_controls import ROOT, JAVA
from test_d3d_lifecycle import function

FIXTURE = r'''
import java.util.*;
import java.lang.ref.WeakReference;
public class TextConnectionCheck {
    boolean textEditing,windowFocus=true,finishing;
    int textGeneration,fieldCaret;
    String fieldText="",lastPreview="";
    void updateTextPreview(){lastPreview=textEditing?visibleText():"";}
    TextConnection textConnection;
    Touch touch=new Touch();
    static final String INPUT_METHOD_SERVICE="input";
    Manager manager=new Manager();
    static WeakReference<TextConnectionCheck> currentActivity=new WeakReference<>(null);
    List<Runnable> callbacks=new ArrayList<>();
    void runOnUiThread(Runnable action){callbacks.add(action);}
    static class Touch {void requestFocus(){} Object getWindowToken(){return this;}}
    static class InputMethodManager {
        static final int SHOW_IMPLICIT=1;
        int shows,hides,restarts;
        void hideSoftInputFromWindow(Object token,int flags){hides++;}
        void restartInput(Touch touch){restarts++;}
        void showSoftInput(Touch touch,int flags){shows++;}
    }
    static class Manager extends InputMethodManager {}
    Object getSystemService(String name){assert name.equals(INPUT_METHOD_SERVICE);return manager;}
    boolean hasWindowFocus(){return windowFocus;}
    boolean isFinishing(){return finishing;}
    boolean isDestroyed(){return false;}
    static class BaseInputConnection {
        BaseInputConnection(Object target,boolean full){}
        public boolean commitText(CharSequence text,int cursor){return false;}
        public boolean setComposingText(CharSequence text,int cursor){return false;}
        public boolean finishComposingText(){return false;}
        public boolean deleteSurroundingText(int before,int after){return false;}
        public boolean deleteSurroundingTextInCodePoints(int before,int after){return false;}
        public CharSequence getTextBeforeCursor(int length,int flags){return null;}
        public CharSequence getTextAfterCursor(int length,int flags){return null;}
        public boolean performEditorAction(int action){return false;}
        public boolean sendKeyEvent(KeyEvent event){return false;}
    }
    static class EditorInfo {static final int IME_ACTION_DONE=6;}
    static class KeyEvent {
        static final int ACTION_DOWN=0,ACTION_UP=1,ACTION_MULTIPLE=2,KEYCODE_DEL=67,KEYCODE_FORWARD_DEL=112,KEYCODE_ENTER=66;
        int action,code,unicode;String characters;
        KeyEvent(int a,int c){action=a;code=c;}
        KeyEvent(int a,int c,int u){this(a,c);unicode=u;}
        KeyEvent(String text){action=ACTION_MULTIPLE;characters=text;}
        int getAction(){return action;}int getKeyCode(){return code;}
        int getUnicodeChar(){return unicode;}String getCharacters(){return characters;}
    }
    static List<String> edits=new ArrayList<>();
    static boolean accept=true;
    static boolean nativeText(int generation,String text){edits.add("T:"+generation+":"+text);return accept;}
    static boolean nativeTextKey(int generation,int key,int count){edits.add("K:"+generation+":"+key+":"+count);return accept;}
    static int nativeTextCancel(){return 100;}
    /* ACTUAL_METHODS */
    /* ACTUAL_CONNECTION */
    TextConnection connect(int generation){textEditing=true;textGeneration=generation;fieldText="";fieldCaret=0;return textConnection=new TextConnection(generation);}
    void check(){
        TextConnection c=connect(11);
        assert c.commitText("Привет",1);assert edits.equals(Arrays.asList("T:11:Привет"));edits.clear();
        assert c.setComposingText("П",1)&&c.setComposingText("Пр",1)&&c.setComposingText("Прив",1);
        assert edits.isEmpty();assert c.finishComposingText();assert c.finishComposingText();
        assert edits.equals(Arrays.asList("T:11:Прив"));edits.clear();
        assert c.setComposingText("старое",1);c=connect(12);
        TextConnection stale=new TextConnection(11);stale.composing="stale";
        assert !stale.finishComposingText()&&!stale.commitText("stale",1)&&!stale.deleteSurroundingText(1,0);
        assert edits.isEmpty();
        assert c.setComposingText("абв",1)&&c.deleteSurroundingText(2,0)&&edits.isEmpty();
        assert c.finishComposingText()&&edits.equals(Arrays.asList("T:12:а"));edits.clear();
        assert c.setComposingText("аб",1)&&c.deleteSurroundingText(4,1);
        assert edits.equals(Arrays.asList("K:12:8:2","K:12:46:1"));edits.clear();
        assert c.sendKeyEvent(new KeyEvent(0,67))&&c.sendKeyEvent(new KeyEvent(1,67));
        assert edits.equals(Arrays.asList("K:12:8:1"));edits.clear();
        assert c.setComposingText("Я\uD83D\uDE00",1)&&c.deleteSurroundingTextInCodePoints(1,0)&&edits.isEmpty();
        assert c.finishComposingText()&&edits.equals(Arrays.asList("T:12:Я"));edits.clear();
        assert c.setComposingText("аб",1)&&c.deleteSurroundingTextInCodePoints(4,1);
        assert edits.equals(Arrays.asList("K:12:8:2","K:12:46:1"));edits.clear();
        assert !c.deleteSurroundingTextInCodePoints(-1,0)&&!c.deleteSurroundingTextInCodePoints(257,0);
        assert c.setComposingText("до",1)&&c.sendKeyEvent(new KeyEvent(0,62,32));
        assert c.sendKeyEvent(new KeyEvent(1,62,32))&&c.sendKeyEvent(new KeyEvent(0,0,0x42F));
        assert c.sendKeyEvent(new KeyEvent("текст"));
        assert edits.equals(Arrays.asList("T:12:до","T:12: ","T:12:Я","T:12:текст"));edits.clear();
        assert !c.sendKeyEvent(new KeyEvent(0,0,0x80000060))&&!c.sendKeyEvent(new KeyEvent(0,0,7))&&edits.isEmpty();
        assert c.setComposingText("Герой",1)&&c.sendKeyEvent(new KeyEvent(0,66));
        assert edits.equals(Arrays.asList("T:12:Герой","K:12:13:1"))&&!textEditing&&c.composing.isEmpty();edits.clear();
        assert !c.finishComposingText()&&!c.commitText("late",1)&&edits.isEmpty();
        c=connect(13);String large=String.join("",Collections.nCopies(257,"A"));
        assert !c.setComposingText(large,1)&&!c.commitText(large,1)&&edits.isEmpty();
        assert !c.deleteSurroundingText(-1,0)&&!c.deleteSurroundingText(257,0);
        assert c.setComposingText("discard",1);accept=false;assert !c.commitText("unsupported",1);accept=true;
        assert c.composing.isEmpty();edits.clear();assert c.finishComposingText()&&edits.isEmpty();
        setTextFocus(true,20);assert textEditing&&manager.shows==1&&manager.restarts==1;
        c=textConnection=new TextConnection(20);c.setComposingText("cancel",1);
        setTextFocus(false,21);assert !textEditing&&c.composing.isEmpty()&&!c.finishComposingText()&&edits.isEmpty();
        int shows=manager.shows;setTextFocus(true,20);assert !textEditing&&manager.shows==shows;
        windowFocus=false;setTextFocus(true,22);assert !textEditing&&textGeneration==100;
        windowFocus=true;setTextFocus(true,99);assert !textEditing;
        setTextFocus(true,101);assert textEditing&&manager.shows==shows+1;
        int hides=manager.hides;setTextFocus(false,102);
        assert !textEditing&&textGeneration==102&&fieldText.isEmpty()&&manager.hides==hides+1;
        currentActivity=new WeakReference<>(this);
        shows=manager.shows;onTextFocus(true,200);assert callbacks.size()==1;
        currentActivity=new WeakReference<>(new TextConnectionCheck());callbacks.remove(0).run();
        assert !textEditing&&manager.shows==shows;
        currentActivity=new WeakReference<>(this);onTextFocus(true,201);callbacks.remove(0).run();
        assert textEditing&&textGeneration==201&&manager.shows==shows+1;
        setTextState(201,"Префикс",3);assert fieldText.equals("Префикс")&&fieldCaret==3;
        c=textConnection=new TextConnection(201);assert visibleText().equals("Пре│фикс");
        assert c.setComposingText("новый",1)&&lastPreview.equals("Преновый│фикс");
        assert c.getTextBeforeCursor(5,0).toString().equals("новый");
        assert c.getTextAfterCursor(2,0).toString().equals("фи");
        assert c.getTextBeforeCursor(-1,0).length()==0&&c.getTextAfterCursor(-1,0).length()==0;
        setTextState(200,"stale",0);assert fieldText.equals("Префикс");
        setTextState(201,"Фильтр",999);assert fieldCaret==6&&fieldText.equals("Фильтр");
        assert c.finishComposingText();edits.clear();
        currentActivity=new WeakReference<>(this);onTextState(201,"Герой",2);assert callbacks.size()==1;
        callbacks.remove(0).run();assert fieldText.equals("Герой")&&visibleText().equals("Ге│рой");
        onTextState(201,"wrong Activity",0);currentActivity=new WeakReference<>(new TextConnectionCheck());
        callbacks.remove(0).run();assert fieldText.equals("Герой");
        hideTextInput();setTextState(201,"late",0);assert fieldText.isEmpty()&&lastPreview.isEmpty();
        System.out.println("PASS actual IME: Russian/compose/edit/Enter, generation/lifecycle; authoritative visible text, caret/composition, IME context, stale snapshot rejection");
    }
    public static void main(String[] args){new TextConnectionCheck().check();}
}
'''


class TextConnectionTest(unittest.TestCase):
    def test_actual_connection(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        methods = "\n".join(function(source, name) for name in ("    private void hideTextInput(", "    private void setTextFocus(", "    private void setTextState(", "    private String visibleText("))
        methods += function(source, "    private static void onTextFocus(").replace("GameActivity activity", "TextConnectionCheck activity")
        methods += function(source, "    private static void onTextState(").replace("GameActivity activity", "TextConnectionCheck activity")
        connection = function(source, "    private final class TextConnection extends BaseInputConnection {")
        out = ROOT / "build/java-ime-check"
        out.mkdir(parents=True, exist_ok=True)
        java = out / "TextConnectionCheck.java"
        java.write_text(FIXTURE.replace("    /* ACTUAL_METHODS */", methods).replace("    /* ACTUAL_CONNECTION */", connection), encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(java)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "TextConnectionCheck"], check=True)


if __name__ == "__main__":
    unittest.main()
