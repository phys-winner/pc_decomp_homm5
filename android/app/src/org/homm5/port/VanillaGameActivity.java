package org.homm5.port;

/** Vanilla owns its library and profile in a separate Android process. */
public final class VanillaGameActivity extends GameActivity {
    @Override protected String gameEdition() { return "vanilla"; }
}
