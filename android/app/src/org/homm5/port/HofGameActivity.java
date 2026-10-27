package org.homm5.port;

/** Hammers of Fate owns its library and profile in a separate Android process. */
public final class HofGameActivity extends GameActivity {
    @Override protected String gameEdition() { return "hof"; }
}
