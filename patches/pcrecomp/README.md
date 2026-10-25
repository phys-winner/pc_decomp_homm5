# NFSU2 x87 window adaptation

The unmodified `0014-recomp_types-RECOMP_X87_WINDOW-sliding-window-FPU-st.patch`
is from [codepdbh/nfsu2-recompiled, revision
62a1d3a17fc7619b9d32df182b4b47d1a4f2e959](https://github.com/codepdbh/nfsu2-recompiled/tree/62a1d3a17fc7619b9d32df182b4b47d1a4f2e959/patches/pcrecomp).
Patch author: sistemas3cecasem <paukarvv@gmail.com>; original patch commit
`486a9a1898f4720b62436b6edc475be513f34419`; SHA-256
`740560cd6d8eadd132ddc180c963388b92a4316040e2023b4c0ee4ee4c2db518`.
The NFSU2 project's authored runtime/tooling code is MIT; see the linked repository's
licensing statement. The underlying pcrecomp license is retained in
`reference/pcrecomp/LICENSE`.

H5 adapts the algorithm in `android/runtime/recomp_types.h` and shares that
header with its prepared PC runtime. Production builds define
`RECOMP_X87_WINDOW` consistently for generated code and host code. The vendor
snapshot and canonical generated functions are unchanged.

Differences from the original patch:

- Array-lvalue aliases retain the old 64-byte `sizeof` for VM snapshots.
- Pop zeroes both the new logical ST(7) and its exact int64 shadow, preserving
  all eight slots even for the existing model's inactive/unbalanced state.
- Existing shift helpers remain available unchanged for direct host callers
  and baseline tests; generated push/pop use the fast window helpers.
- Storage is defined once per runtime; existing thread/callback snapshots copy
  the logical eight slots into the current valid window without storing all
  256 implementation slots or an implementation index per thread.
- Build guards reject escaped window pointers and pop expressions whose
  unsequenced operand could use the previous window.

Focused checks: `tests/test_x87_window.py`, `tests/test_build_guards.py`, and
fallback/window variants of `tests/test_windows_runtime.py`. Full game and
device performance require separate measurements; this patch carries no FPS
claim by itself.
