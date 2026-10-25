# Third-party notices

Project-authored port code and documentation are GPL-3.0-or-later. The following
components and upstream-derived portions retain their original terms. This file
does not grant rights to original game code or data.

## Source dependencies

| Component | Version or revision | License | Source and license file |
| --- | --- | --- | --- |
| pcrecomp | `904ac3129d0c9d05efbeec19a1dce6abbe7f5d26` | MIT | [Upstream](https://github.com/sp00nznet/pcrecomp), [LICENSE](reference/pcrecomp/LICENSE) |
| MojoShader | `cf2661bcb55d9a8732e86f79922592d7efdf5383` with marked local extensions | Zlib | [Upstream](https://github.com/icculus/mojoshader), [LICENSE.txt](reference/mojoshader/LICENSE.txt) |
| dlmalloc | 2.8.6, relicensed 2023 | MIT-0 | [Upstream](https://gee.cs.oswego.edu/pub/misc/malloc.c), notice in [malloc.c](reference/dlmalloc/malloc.c) |
| astcenc | 5.7.0 library subset | Apache-2.0 | [Upstream](https://github.com/ARM-software/astc-encoder), [LICENSE.txt](reference/astcenc/LICENSE.txt) |
| etcpak | `3d716e1550023dc5ff8b602636af8b76584e0b66` subset | BSD-3-Clause | [Upstream](https://github.com/wolfpld/etcpak), [LICENSE.txt](reference/etcpak/LICENSE.txt) |
| bcdec | 0.96, bundled with etcpak | MIT OR Unlicense; MIT used here | [Upstream](https://github.com/iOrange/bcdec), both licenses in [bcdec.h](reference/etcpak/bcdec.h) |
| zlib | 1.3.1 inflate/CRC subset for desktop tests | Zlib | [Upstream](https://github.com/madler/zlib), [LICENSE](reference/zlib/LICENSE) |

The pcrecomp MIT notice also applies to portions of the project's lifter,
register model and runtime derived from it. Project adaptations are in `tools/`
and `android/runtime/`. The Win32 compatibility host was adapted from the
project's existing The Void port; no checkout of that project is required.

The vendored MojoShader files include port extensions for legacy PS1.1/1.4
instructions, implicit PS1.4 samplers, vertex fog and legacy input semantics.
These altered sources must not be represented as an unmodified upstream release.

Copyright notices include: pcrecomp, copyright 2026 sp00nz; MojoShader, copyright
2008-2024 Ryan C. Gordon; astcenc, copyright Arm Limited, with the years retained
in each source; etcpak, copyright 2013-2026 Bartosz Taudul; zlib, copyright
1995-2024 Jean-loup Gailly and Mark Adler. Full source notices are retained.

## Adapted x87 sliding window

The algorithm in `android/runtime/recomp_types.h` adapts the MIT-licensed
[NFSU2 recompilation patch](https://github.com/codepdbh/nfsu2-recompiled/blob/62a1d3a17fc7619b9d32df182b4b47d1a4f2e959/patches/pcrecomp/0014-recomp_types-RECOMP_X87_WINDOW-sliding-window-FPU-st.patch),
by sistemas3cecasem. The unmodified patch, author attribution and adaptation notes
are retained in [`patches/pcrecomp/`](patches/pcrecomp/README.md).

## dlmalloc — MIT-0

```text
Copyright 2023 Doug Lea

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## bcdec — MIT

```text
Copyright (c) 2022 Sergii Kudlai

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to
do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Separately installed development tools

Python packages are installed from `requirements.txt`, rather than vendored:

| Package | Version | Upstream license |
| --- | --- | --- |
| capstone | 5.0.7 | BSD-3-Clause |
| pefile | 2024.8.26 | MIT |
| unicorn | 2.1.4 | GPL-2.0-only core; BSD Python bindings; upstream component notices apply |
| pycryptodome | 3.23.0 | BSD-2-Clause and public-domain portions; upstream notices apply |

Unicorn is used for original-code regression checks on the build computer and
is not linked into the Android application. The SDK, NDK, JDK and UPX are
separately installed tools with their own licenses. The optional Windows PGO
runtime is LLVM 18.1.8, Apache-2.0 WITH LLVM-exception; its origin and hashes are
recorded in `dependencies.json`. It is not needed for an Android APK build.

## Original game and middleware

Heroes of Might and Magic V, Tribes of the East, their PC binaries, Granny,
FMOD, other bundled middleware and original game resources remain under their
respective rights holders' terms. They are not licensed by this project's GPL
grant. Original binaries, resource archives, extracted town music XML files,
generated disassembly catalogs, translated C and compiled game libraries are
excluded from the source repository.
