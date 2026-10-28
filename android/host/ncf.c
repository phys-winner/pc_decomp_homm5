/* MMH5.5's New Creature Framework for Tribes of the East 3.1 (Frameworks/NewCreatureFramework/
 * NewCreatureFramework.yml, group Original), as values the lifted bodies read instead of the hex patch
 * (tools/build_android.py:new_creature_framework): the creature limit 180 -> 1000 (IDs up to 999) and
 * the random map generator's guard for NCF creatures without map visuals. The launcher's choice, off by
 * default, arrives before the engine starts; a mod has to bring the creature records up to the limit, as
 * the framework itself requires, or the game stops while it loads them. */
#include "host.h"
#ifdef VOID_ANDROID_APP
#include <jni.h>
#endif

#ifndef HOMM5_LEGACY_UI
static int ncf_enabled, ncf_reported;

void void_ncf_enable(int on)
{
    ncf_enabled = on != 0;
}

/* sub_00ACB380 (the creature count) and the table pushed at 0x00AE261F. The first query reports the
 * choice: it arrives before homm5.log opens. */
uint32_t void_ncf_creatures(void)
{
    if (!ncf_reported) {
        ncf_reported = 1;
        void_log("[port] New Creature Framework %s", ncf_enabled ? "on: creature limit 1000" : "off");
    }
    return ncf_enabled ? 1000u : 180u;
}

/* The copy-assign sub_0040EC70 handed a missing map visual (NULL + 0xC): the framework jumps past the
 * copy at 0x0040EC76; the target as its own source takes the body's self-assignment path, which leaves
 * it unchanged too. */
uint32_t void_ncf_source(uint32_t source, uint32_t self)
{
    return ncf_enabled && source == 0x0Cu ? self : source;
}

#ifdef VOID_ANDROID_APP
JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeNewCreatureFramework(JNIEnv *env, jobject self, jboolean enabled)
{
    (void)env; (void)self;
    void_ncf_enable(enabled == JNI_TRUE);
}
#endif
#endif
