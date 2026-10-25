# pc_decomp_homm5

Heroes of Might and Magic V: Tribes of the East on Android ARM64 through static
x86 recompilation, with native touch controls and a Direct3D 9 to OpenGL ES bridge.

**Development version: 0.1-dev.** The release build uses ThinLTO and PGO.
This is an experimental port for sideloading.
The original game's menus, adventure maps, towns, battles, sound and saves run
through a local Win32 compatibility host. The game and eight DLLs are translated
from x86 to C ahead of time, then compiled into `libhomm5.so` with the Android NDK.

## Supported original game

The port has been tested with the **Russian version of Heroes of Might and
Magic V - Tribes of the East 3.1** from
[Heroes of Might and Magic 5: Bundle on GOG](https://www.gog.com/en/game/heroes_of_might_and_magic_5_bundle).
Use your own installed copy of this edition. The base game, Hammers of Fate,
other languages, executable revisions and mods are not verified build inputs.

The SHA-256 values of the required executable and DLLs are pinned in
[`config/modules.json`](config/modules.json). The lifter verifies every input
before copying, unpacking or relocating it. The original installation is read
only; unpacked images and generated C go into ignored local directories.

Original EXE/DLL files, resource archives, music, videos, maps and saves are not
distributed in this repository. The eight town music XML resources are read
from the original `data/data.pak` during packaging, checked against the hashes in
`config/music/manifest.json`, and patched in a separate Android overlay.

## Current capabilities and limits

- Original menus, profile creation, scenario loading, adventure maps, towns,
  battles, saving and loading have been exercised during development.
- Touch input supports selection, movement, camera gestures, tooltips,
  spell targeting, troop and artifact transfers, and the Android keyboard.
- Additional game settings control render scale, interface scale, frame limit
  and camera sensitivity. The default frame limit is 60 FPS.
- LAN play has been tested between Android devices and between Android and the
  original PC game. Network discovery depends on the local Wi-Fi network.
- The launcher accepts an installed game folder or a ZIP containing its files.
  It can convert DXT textures to ASTC/ETC2 and skip the intro videos.
- ARM64 Android 8.0 or later and OpenGL ES 3.2 are required. The manifest targets
  API 28; this development package uses legacy external storage access.
- Native libraries and APK packaging support 16 KiB alignment. This does not
  establish testing on a device with 16 KiB memory pages.
- Campaign completion, every map, every GPU and every Android version have not
  been verified. Development test results are not a complete compatibility claim.

## Build requirements

The current scripts build on **Windows x64**, without Gradle. Install:

| Tool | Version |
| --- | --- |
| Python | 3.13 used during development |
| Android SDK platform | `platforms;android-36` |
| Android SDK Build Tools | `build-tools;36.1.0` |
| Android NDK | `27.2.12479018` |
| JDK | 17 or later; 24.0.1 used during development |
| UPX | 5.2.1, for unpacking the private copy of `fmod.dll` |

Python requirements are pinned in [`requirements.txt`](requirements.txt).
The needed source snapshots of pcrecomp, MojoShader, dlmalloc, astcenc and etcpak
are vendored in `reference/`; zlib sources support desktop regression tests.
Versions, origins and local adaptations are recorded in
[`dependencies.json`](dependencies.json) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
Keep the supplied MojoShader snapshot: a plain upstream checkout omits the
legacy shader fixes used by this port.

## Build the APK

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$env:ANDROID_NDK = Join-Path $env:ANDROID_HOME "ndk\27.2.12479018"
$env:JAVA_HOME = Read-Host "JDK installation directory"
$homm5Upx = Read-Host "Path to upx.exe"

Copy-Item port.example.json port.json
notepad port.json
```

Set `game_directory` to the directory containing the original game's `bin/`,
`data/`, `music/`, `profiles/` and other resource folders. Absolute paths and
paths relative to the repository root are supported. Use forward slashes or
escaped backslashes in JSON. The example uses `originals/tribes-of-the-east`.
`device` is optional and is needed only for developer deployment tools.
The personal `port.json` and the entire `originals/` directory stay outside Git.

The scripts resolve the SDK using `ANDROID_SDK`, `ANDROID_HOME`, then
`ANDROID_SDK_ROOT`, or the current account's usual Windows SDK location.
`ANDROID_NDK` overrides the pinned NDK under that SDK. Set `JAVA_HOME` explicitly.

Generate all nine modules, then compile and package:

```powershell
python -X utf8 tools/lift_homm5.py --upx $homm5Upx
python -X utf8 tools/call_protocol.py
python -X utf8 tools/x87_locals.py
python -X utf8 tools/build_game_apk.py --thinlto --no-pgo
```

Output: **`build/android-game/heroes-v.apk`**.

Generation creates checked PE images under `generated/input/`, function catalogs
under `config/*.catalog.*` and C sources under `generated/`. These are all local
build outputs. Compilation fingerprints sources, headers, compiler and flags
before reusing objects. The APK builder compiles the texture converter and Java
launcher, includes the prepared PE images and port overlays, aligns the APK and
signs it with a locally generated development key.
Native builds remap embedded source paths to repository-relative names.

The two analysis steps produce `build/call-protocol/summary.json` and `x87.json`
from the generated sources. Run them again after regenerating or repairing
lifted functions; these reports are required by the native source transforms.

For lower memory use and fewer compilation workers:

```powershell
python -X utf8 tools/build_android.py --shared --thinlto --no-pgo --jobs 4 --thinlto-jobs 2
python -X utf8 tools/build_game_apk.py --skip-native --thinlto --no-pgo
```

`--no-pgo` makes the documented build independent of a local training profile.
The `0.1-dev` release uses the existing `build/pgo/homm5.profdata` profile to
retain the previous build's PGO optimizations. Its SHA-256 is
`0f0354d4be698c77ce8e00b6c1f4adcccc95ada2c4666983e7359cd536b05fa1`.
The profile stays outside Git. To build with that profile available locally:

```powershell
python -X utf8 tools/build_game_apk.py --thinlto --pgo-use build/pgo/homm5.profdata
```

`--pgo-use PATH` also accepts another compatible LLVM profile. Without either
flag, an existing `build/pgo/homm5.profdata` is used automatically. Performance
can differ between profile-use builds and the profile-independent build above.

The signing key is created in `build/android/debug.keystore`. Keep your local key
if you want subsequent APKs to update the same installation. Another key requires
uninstalling the old package or signing with the original key. Keys and keystores
are excluded from Git.

## Install and provide game resources

1. Install your APK on an ARM64 Android device and open **Heroes V**.
2. Grant the requested file access. Select the original game folder or a ZIP
   containing the installed game. An offline GOG installer EXE is not a game ZIP.
3. Let the launcher copy or unpack the resources. Texture conversion is optional
   and can take time and additional storage space.
4. Start the game from the launcher. Intro skipping and cleanup are available
   there; keep a separate copy of your original game files.

The application ID is `org.homm5.port`.

| Data | Device directory |
| --- | --- |
| Original resource copy | `/sdcard/HeroesV/game/` |
| Prepared PE images | `/sdcard/HeroesV/lifted/` |
| Settings, profiles and saves | `/sdcard/HeroesV/userdata/` |

Optional installation through ADB:

```powershell
python tools/build_game_apk.py --skip-native --thinlto --install
```

If several devices are connected, pass `--serial SERIAL` or set `ANDROID_SERIAL`
or `HOMM5_SERIAL` locally. No device identifier is included in the repository.

## Touch controls

| Gesture | Action |
| --- | --- |
| Tap | Original selection or contextual action |
| Double tap your hero or town | Open its screen |
| Drag the map | Move the camera |
| Two fingers | Move, zoom and rotate the camera |
| Hold an interface element | Show its tooltip |
| Swipe a list | Scroll |
| Drag troops or artifacts | Transfer between slots |
| Aim a selected ability, then release | Confirm the target |
| Second finger while aiming | Cancel targeting |

## Versions and local release files

Development versions advance as `0.1-dev`, `0.2-dev`, `0.3-dev`, and so on.
The version is stored in `android/app/AndroidManifest.xml`; increase
`android:versionCode` for every subsequent published build. Version `0.1-dev`
uses code `2`.

Local release copies use `heroes-v-0.1-dev-<sha256-prefix>.apk`, where the suffix
is the first eight characters of the APK's SHA-256, with a companion `.sha256`
file. The `pub/` directory is ignored. Building and naming an APK does not
automatically publish it or create a Git tag.

## Checks

The packaging, toolchain resolution and resource transformation checks can run
without the original game or a device:

```powershell
python -m unittest discover -s tests -p test_android_tools.py
python -m unittest discover -s tests -p test_town_music.py
python -m unittest discover -s tests -p test_deploy.py
python -m unittest discover -s tests -p test_apk_pgo.py
python -m unittest discover -s tests -p test_apk_thinlto.py
python -m unittest discover -s tests -p test_builder_thinlto.py
```

Additional tests use the original installation, generated C, a local Microsoft
C++ toolchain, optional ANGLE binaries or an explicitly selected Android device.
They are not all prerequisites for packaging an APK. The Windows host and tools
are retained for differential checks of the same runtime and generated code.

## License

Project-authored port code and documentation are licensed under the
**GNU General Public License, version 3 or (at your option) any later version**
(`GPL-3.0-or-later`). See [`LICENSE`](LICENSE). This is a strong copyleft license;
redistribution of covered modifications carries the corresponding source and
license obligations.

Vendored dependencies and derived upstream portions retain their licenses and
copyright notices; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
The GPL grant does not relicense Heroes V, its middleware, resources or code
translated from the original binaries. A locally built APK contains translated
game code and prepared PE images, even though the large game resource archives
are supplied separately. Rights to those components remain with their respective
holders. This is an unofficial project, unaffiliated with Ubisoft, Nival or GOG.

## GitHub description

Android ARM64 port of Heroes V: Tribes of the East via static x86 recompilation,
with touch controls. Requires original game files.
