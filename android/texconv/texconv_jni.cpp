/* JNI for org.homm5.port.Textures (the launcher's texture section). */
#include <jni.h>

#include "texconv.h"

namespace {

struct Utf {
    JNIEnv *env;
    jstring text;
    const char *chars;
    Utf(JNIEnv *e, jstring t) : env(e), text(t), chars(t ? e->GetStringUTFChars(t, nullptr) : nullptr) {}
    ~Utf() { if (chars) env->ReleaseStringUTFChars(text, chars); }
};

}  // namespace

extern "C" {

/* {textures, bytes, estimateEtc2, estimateAstc, convertedFormat, convertedTextures,
 *  convertedBytes, originalsRemoved, removableBytes}, or null with the reason in
 *  nativeMessage(). */
JNIEXPORT jlongArray JNICALL Java_org_homm5_port_Textures_nativeScan(JNIEnv *env, jclass, jstring game)
{
    Utf dir(env, game);
    if (!dir.chars) return nullptr;
    texconv_status s;
    if (texconv_scan(dir.chars, &s)) return nullptr;
    jlong values[] = {s.textures, s.bytes, s.estimate_etc2, s.estimate_astc, s.converted_format, s.converted_textures,
                      s.converted_bytes, s.originals_removed, s.removable_bytes};
    jlongArray out = env->NewLongArray(9);
    if (out) env->SetLongArrayRegion(out, 0, 9, values);
    return out;
}

JNIEXPORT jint JNICALL Java_org_homm5_port_Textures_nativeConvert(JNIEnv *env, jclass, jstring game, jint format, jint threads)
{
    Utf dir(env, game);
    return dir.chars ? texconv_convert(dir.chars, format, threads) : -1;
}

JNIEXPORT jint JNICALL Java_org_homm5_port_Textures_nativeRemoveOriginals(JNIEnv *env, jclass, jstring game)
{
    Utf dir(env, game);
    return dir.chars ? texconv_remove_originals(dir.chars) : -1;
}

JNIEXPORT jint JNICALL Java_org_homm5_port_Textures_nativeRemoveConverted(JNIEnv *env, jclass, jstring game)
{
    Utf dir(env, game);
    return dir.chars ? texconv_remove_converted(dir.chars) : -1;
}

JNIEXPORT void JNICALL Java_org_homm5_port_Textures_nativeCancel(JNIEnv *, jclass) { texconv_cancel(); }

/* {state, done, total, bytesDone, bytesTotal} */
JNIEXPORT jlongArray JNICALL Java_org_homm5_port_Textures_nativeProgress(JNIEnv *env, jclass)
{
    texconv_progress p;
    texconv_get_progress(&p);
    jlong values[] = {p.state, p.done, p.total, p.bytes_done, p.bytes_total};
    jlongArray out = env->NewLongArray(5);
    if (out) env->SetLongArrayRegion(out, 0, 5, values);
    return out;
}

JNIEXPORT jstring JNICALL Java_org_homm5_port_Textures_nativeMessage(JNIEnv *env, jclass)
{
    texconv_progress p;
    texconv_get_progress(&p);
    return env->NewStringUTF(p.message);
}

}  // extern "C"
