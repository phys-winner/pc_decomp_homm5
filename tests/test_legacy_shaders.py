"""Translate real H5 PS 1.x bytecode, then compile/render it with local ANGLE.

The test reads the original/generated EXE; no proprietary shader blobs are
committed. ANGLE is an optional local dependency for GPU compiler/pixel checks.
"""
import ctypes as C
import os
import json
from pathlib import Path
import re
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/tests/legacy_shaders"
MOJO = ROOT / "reference/mojoshader"
SOURCES = ["mojoshader.c", "mojoshader_common.c", "mojoshader_assembler.c",
           "mojoshader_preprocessor.c", "mojoshader_lexer.c",
           "profiles/mojoshader_profile_common.c", "profiles/mojoshader_profile_glsl.c",
           "profiles/mojoshader_profile_d3d.c", "profiles/mojoshader_profile_bytecode.c"]


class Error(C.Structure):
    _fields_ = [("error", C.c_char_p), ("filename", C.c_char_p), ("position", C.c_int)]


class Sampler(C.Structure):
    _fields_ = [("type", C.c_int), ("index", C.c_int), ("name", C.c_char_p), ("texbem", C.c_int)]


class ParseData(C.Structure):
    _fields_ = [("error_count", C.c_int), ("errors", C.POINTER(Error)),
                ("profile", C.c_char_p), ("output", C.c_void_p), ("output_len", C.c_int),
                ("instruction_count", C.c_int), ("shader_type", C.c_int),
                ("major_ver", C.c_int), ("minor_ver", C.c_int), ("mainfn", C.c_char_p),
                ("uniform_count", C.c_int), ("uniforms", C.c_void_p),
                ("constant_count", C.c_int), ("constants", C.c_void_p),
                ("sampler_count", C.c_int), ("samplers", C.POINTER(Sampler))]


class SamplerMap(C.Structure):
    _fields_ = [("index", C.c_int), ("type", C.c_int)]


def build_mojo():
    OUT.mkdir(parents=True, exist_ok=True)
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*",
                                                "-property", "installationPath"], text=True).strip())
    msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    compiler = msvc / "bin/Hostx64/x64/cl.exe"
    env = os.environ.copy()
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt",
                                        sdk / f"Include/{version}/shared", sdk / f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk / f"Lib/{version}/ucrt/x64",
                                    sdk / f"Lib/{version}/um/x64"]))
    dll = OUT / "mojo_probe.dll"
    host_shader = ROOT / "android/host/d3d9_shader.c"
    inputs = list(MOJO.rglob("*.h")) + [MOJO / s for s in SOURCES] + [host_shader, Path(__file__)]
    if not dll.exists() or dll.stat().st_mtime < max(p.stat().st_mtime for p in inputs):
        host_source = host_shader.read_text(encoding="utf-8")
        # Exercise the exact production source adapters and CTAB fallback.
        adapters = host_source[host_source.index("static char *insert_before("):
                               host_source.index("d3d_shader *d3d_shader_create(")]
        probe = OUT / "host_adapters.c"
        probe.write_text("#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n"
                         "#include <stdio.h>\n#include <ctype.h>\n"
                         "#define FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))\n" +
                         adapters + "\n__declspec(dllexport) char *probe_patch(const char *s, int p) { return patch_source(s,p); }\n"
                         "__declspec(dllexport) uint8_t *probe_ctab(const uint8_t *s, uint32_t n, int p, uint32_t *out) { return with_synthetic_ctab(s,n,p,out); }\n"
                         "__declspec(dllexport) void probe_free(void *p) { free(p); }\n", encoding="utf-8")
        flags = ["/nologo", "/W0", "/std:c11", "/LD", "/O2", "/D_CRT_SECURE_NO_WARNINGS",
                 "/DMOJOSHADER_NO_VERSION_INCLUDE", "/DMOJOSHADER_FLIP_RENDERTARGET",
                 "/DMOJOSHADER_DEPTH_CLIPPING", "/DSUPPORT_PROFILE_HLSL=0", "/DSUPPORT_PROFILE_ARB1=0",
                 "/DSUPPORT_PROFILE_ARB1_NV=0", "/DSUPPORT_PROFILE_METAL=0", "/DSUPPORT_PROFILE_SPIRV=0",
                 "/DSUPPORT_PROFILE_GLSPIRV=0", "/DSUPPORT_PROFILE_GLSL120=0", "/I" + str(MOJO)]
        proc = subprocess.run([str(compiler)] + flags + [str(MOJO / s) for s in SOURCES] + [str(probe)] +
                              ["/Fe:" + str(dll)], cwd=OUT, env=env, text=True, capture_output=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    lib = C.CDLL(str(dll))
    lib.MOJOSHADER_parse.restype = C.POINTER(ParseData)
    lib.MOJOSHADER_parse.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_uint,
                                    C.c_void_p, C.c_uint, C.c_void_p, C.c_uint,
                                    C.c_void_p, C.c_void_p, C.c_void_p]
    lib.MOJOSHADER_assemble.restype = C.POINTER(ParseData)
    lib.MOJOSHADER_assemble.argtypes = [C.c_char_p, C.c_char_p, C.c_uint] + [C.c_void_p, C.c_uint] * 3 + [C.c_void_p] * 5
    lib.MOJOSHADER_freeParseData.argtypes = [C.POINTER(ParseData)]
    lib.probe_patch.restype = C.c_void_p
    lib.probe_patch.argtypes = [C.c_char_p, C.c_int]
    lib.probe_ctab.restype = C.c_void_p
    lib.probe_ctab.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.POINTER(C.c_uint)]
    lib.probe_free.argtypes = [C.c_void_p]
    return lib


def result(lib, parsed):
    try:
        p = parsed.contents
        if p.error_count:
            raise ValueError("; ".join(p.errors[i].error.decode() for i in range(p.error_count)))
        return (C.string_at(p.output, p.output_len),
                [(p.samplers[i].index, p.samplers[i].type) for i in range(p.sampler_count)])
    finally:
        lib.MOJOSHADER_freeParseData(parsed)


def translate(lib, code, sampler_type=None, profile=b"glsles3"):
    smap = SamplerMap(0, sampler_type) if sampler_type is not None else None
    return result(lib, lib.MOJOSHADER_parse(profile, b"main", code, len(code), None, 0,
                                          C.byref(smap) if smap else None, int(smap is not None), None, None, None))


def assemble(lib, text):
    source = text.encode()
    return result(lib, lib.MOJOSHADER_assemble(b"test.ps", source, len(source),
                                             None, 0, None, 0, None, 0, None, None, None, None, None))[0]


def translate_host(lib, code, pixel):
    synthetic = False
    try:
        source, samplers = translate(lib, code)
    except ValueError as exc:
        if "without a CTAB" not in str(exc):
            raise
        size = C.c_uint()
        pointer = lib.probe_ctab(code, len(code), int(pixel), C.byref(size))
        try:
            source, samplers = translate(lib, C.string_at(pointer, size.value))
        finally:
            lib.probe_free(pointer)
        synthetic = True
    pointer = lib.probe_patch(source, int(pixel))
    try:
        return C.string_at(pointer), samplers, synthetic
    finally:
        lib.probe_free(pointer)


def embedded_shaders(vertex=False):
    import pefile
    path = ROOT / "generated/input/H5_Game.exe"
    if not path.exists():
        game = json.loads((ROOT / "port.json").read_text(encoding="utf-8"))["game_directory"]
        path = ROOT / game / "bin/H5_Game.exe"
    pe = pefile.PE(str(path), fast_load=True)
    data = path.read_bytes()
    # All aligned version tokens in non-executable data. Locate END at an
    # instruction boundary: SM1 operands have bit31, comments encode length.
    for section in pe.sections:
        if section.Characteristics & 0x20000000:
            continue
        start, end = section.PointerToRawData, section.PointerToRawData + section.SizeOfRawData
        covered_end = start
        for offset in range(start, end - 4, 4):
            if offset < covered_end:
                continue  # CTAB records also contain a shader version DWORD.
            version = struct.unpack_from("<I", data, offset)[0]
            versions = (0xFFFE0101, 0xFFFE0200, 0xFFFE0201, 0xFFFE0300) if vertex else (0xFFFF0101, 0xFFFF0102, 0xFFFF0103, 0xFFFF0104)
            if version not in versions:
                continue
            p = offset + 4
            limit = min(end, offset + 16384)
            while p + 4 <= limit:
                token = struct.unpack_from("<I", data, p)[0]
                if token == 0xFFFF:
                    va = pe.OPTIONAL_HEADER.ImageBase + section.VirtualAddress + offset - start
                    covered_end = p + 4
                    yield va, data[offset:p + 4]
                    break
                if token & 0xFFFF == 0xFFFE:
                    p += 4 * (1 + ((token >> 16) & 0x7FFF))
                elif (version >> 8) & 255 >= 2:
                    p += 4 * (1 + ((token >> 24) & 15))
                elif token & 0x80000000 or token == 0xFFFD:  # argument or PHASE
                    p += 4
                elif token & 0xFFFF == 0x51:  # DEF's immediate values need not have bit31.
                    p += 24
                elif token <= 0x60 or token & 0x40000000:  # opcode, optionally coissue
                    p += 4
                else:
                    break


class Angle:
    """Headless GLES 3 context using a locally installed ANGLE distribution."""
    def __init__(self):
        candidates = [Path(os.environ.get("ANGLE_DIR", "__missing__")),
                      Path(r"C:\Program Files\obs-studio\obs-plugins\64bit"),
                      Path(r"C:\Program Files\Mozilla Firefox")]
        directory = next((p for p in candidates if (p / "libEGL.dll").exists()), None)
        if directory is None:
            raise unittest.SkipTest("ANGLE_DIR with libEGL.dll and libGLESv2.dll required for GLES checks")
        self.dll_directory = os.add_dll_directory(str(directory))
        self.egl = C.WinDLL(str(directory / "libEGL.dll"))
        self.gl = C.WinDLL(str(directory / "libGLESv2.dll"))
        self.api(self.egl, "eglGetDisplay", C.c_void_p, C.c_void_p)
        self.api(self.egl, "eglInitialize", C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p)
        self.api(self.egl, "eglChooseConfig", C.c_uint, C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_void_p), C.c_int, C.POINTER(C.c_int))
        self.api(self.egl, "eglCreatePbufferSurface", C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int))
        self.api(self.egl, "eglCreateContext", C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int))
        self.api(self.egl, "eglMakeCurrent", C.c_uint, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p)
        self.display = self.egl.eglGetDisplay(None)
        assert self.egl.eglInitialize(self.display, None, None), "eglInitialize failed"
        attrs = (C.c_int * 15)(0x3033, 1, 0x3040, 0x40, 0x3024, 8, 0x3023, 8, 0x3022, 8, 0x3021, 8, 0x3038, 0, 0)
        config, count = C.c_void_p(), C.c_int()
        assert self.egl.eglChooseConfig(self.display, attrs, C.byref(config), 1, C.byref(count)) and count.value
        self.surface = self.egl.eglCreatePbufferSurface(self.display, config, (C.c_int * 5)(0x3057, 8, 0x3056, 8, 0x3038))
        self.context = self.egl.eglCreateContext(self.display, config, None, (C.c_int * 3)(0x3098, 3, 0x3038))
        assert self.surface and self.context and self.egl.eglMakeCurrent(self.display, self.surface, self.surface, self.context)
        for name, result_type, args in [
            ("glCreateShader", C.c_uint, [C.c_uint]),
            ("glShaderSource", None, [C.c_uint, C.c_int, C.POINTER(C.c_char_p), C.c_void_p]),
            ("glCompileShader", None, [C.c_uint]),
            ("glGetShaderiv", None, [C.c_uint, C.c_uint, C.POINTER(C.c_int)]),
            ("glGetShaderInfoLog", None, [C.c_uint, C.c_int, C.c_void_p, C.c_void_p]),
            ("glDeleteShader", None, [C.c_uint]),
            ("glCreateProgram", C.c_uint, []),
            ("glAttachShader", None, [C.c_uint, C.c_uint]),
            ("glLinkProgram", None, [C.c_uint]),
            ("glGetProgramiv", None, [C.c_uint, C.c_uint, C.POINTER(C.c_int)]),
            ("glGetProgramInfoLog", None, [C.c_uint, C.c_int, C.c_void_p, C.c_void_p]),
            ("glUseProgram", None, [C.c_uint]),
            ("glDeleteProgram", None, [C.c_uint]),
            ("glViewport", None, [C.c_int] * 4),
            ("glGenVertexArrays", None, [C.c_int, C.POINTER(C.c_uint)]),
            ("glBindVertexArray", None, [C.c_uint]),
            ("glDrawArrays", None, [C.c_uint, C.c_int, C.c_int]),
            ("glReadPixels", None, [C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_void_p]),
            ("glGenTextures", None, [C.c_int, C.POINTER(C.c_uint)]),
            ("glActiveTexture", None, [C.c_uint]),
            ("glBindTexture", None, [C.c_uint, C.c_uint]),
            ("glTexParameteri", None, [C.c_uint, C.c_uint, C.c_int]),
            ("glTexImage2D", None, [C.c_uint, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_void_p]),
            ("glGetUniformLocation", C.c_int, [C.c_uint, C.c_char_p]),
            ("glUniform1i", None, [C.c_int, C.c_int]),
            ("glGetError", C.c_uint, [])]:
            self.api(self.gl, name, result_type, *args)
        vao = C.c_uint()
        self.gl.glGenVertexArrays(1, C.byref(vao))
        self.gl.glBindVertexArray(vao)
        self.gl.glViewport(0, 0, 8, 8)

    @staticmethod
    def api(lib, name, result_type, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result_type, list(args)

    def compile(self, source, shader_type=0x8B30):
        shader = self.gl.glCreateShader(shader_type)
        text = C.c_char_p(source)
        self.gl.glShaderSource(shader, 1, C.byref(text), None)
        self.gl.glCompileShader(shader)
        status = C.c_int()
        self.gl.glGetShaderiv(shader, 0x8B81, C.byref(status))
        if not status.value:
            log = C.create_string_buffer(32768)
            self.gl.glGetShaderInfoLog(shader, len(log), None, log)
            raise AssertionError(log.value.decode() + "\n" + source.decode())
        return shader

    def render(self, source, coordinates, samplers):
        varying_names = re.findall(rb"in highp vec4 (io_\d+_\d+);", source)
        vertex = b"#version 300 es\nprecision highp float;\n" + b"".join(b"out highp vec4 " + n + b";\n" for n in varying_names)
        vertex += b"void main() { vec2 p[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3)); gl_Position = vec4(p[gl_VertexID],0,1);\n"
        for name in varying_names:
            values = coordinates.get(name.decode(), (0, 0, 0, 1))
            vertex += name + b" = vec4(" + ",".join(str(float(v)) for v in values).encode() + b");\n"
        vertex += b"}\n"
        vs, ps = self.compile(vertex, 0x8B31), self.compile(source)
        program = self.gl.glCreateProgram()
        self.gl.glAttachShader(program, vs)
        self.gl.glAttachShader(program, ps)
        self.gl.glLinkProgram(program)
        status = C.c_int()
        self.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        if not status.value:
            log = C.create_string_buffer(32768)
            self.gl.glGetProgramInfoLog(program, len(log), None, log)
            raise AssertionError(log.value.decode())
        self.gl.glUseProgram(program)
        for stage, _ in samplers:
            texture = C.c_uint()
            self.gl.glGenTextures(1, C.byref(texture))
            self.gl.glActiveTexture(0x84C0 + stage)
            self.gl.glBindTexture(0x0DE1, texture)
            for key, value in [(0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)]:
                self.gl.glTexParameteri(0x0DE1, key, value)
            pixels = bytes([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255, 255, 255, 0, 255])
            self.gl.glTexImage2D(0x0DE1, 0, 0x8058, 2, 2, 0, 0x1908, 0x1401, pixels)
            self.gl.glUniform1i(self.gl.glGetUniformLocation(program, f"ps_s{stage}".encode()), stage)
        self.gl.glDrawArrays(4, 0, 3)
        pixel = (C.c_ubyte * 4)()
        self.gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
        assert self.gl.glGetError() == 0
        self.gl.glDeleteProgram(program)
        self.gl.glDeleteShader(vs)
        self.gl.glDeleteShader(ps)
        return tuple(pixel)


class LegacyShadersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build_mojo()

    def test_embedded_h5_ps1(self):
        shaders = list(embedded_shaders())
        self.assertGreaterEqual(len(shaders), 17)
        for address, code in shaders:
            with self.subTest(address=f"{address:08X}"):
                source, _ = translate(self.lib, code)
                (OUT / f"{address:08X}.frag").write_bytes(source)
        print(f"PASS translate {len(shaders)} embedded H5 PS1.x shaders")

    def test_gles_compiles_embedded_h5_ps1(self):
        angle = Angle()
        shaders = list(embedded_shaders())
        for address, code in shaders:
            with self.subTest(address=f"{address:08X}"):
                source, _ = translate(self.lib, code)
                shader = angle.compile(source)
                angle.gl.glDeleteShader(shader)
        print(f"PASS GLES3 compile {len(shaders)} embedded H5 PS1.x shaders")

    def test_gles_compiles_embedded_h5_vertex(self):
        angle = Angle()
        shaders = list(embedded_shaders(vertex=True))
        self.assertGreaterEqual(len(shaders), 1)
        ctab_count = 0
        for address, code in shaders:
            with self.subTest(address=f"{address:08X}"):
                source, _, synthetic = translate_host(self.lib, code, pixel=False)
                ctab_count += synthetic
                (OUT / f"{address:08X}.vert").write_bytes(source)
                shader = angle.compile(source, 0x8B31)
                angle.gl.glDeleteShader(shader)
        print(f"PASS GLES3 compile {len(shaders)} embedded H5 vertex shaders ({ctab_count} using production synthetic CTAB)")

    def test_pixels_and_implicit_samplers(self):
        angle = Angle()
        cases = [
            # Mojo's assembler names opcode64 TEXCRD for both SM1 variants.
            ("ps_1_1\ntexcrd t0\nmov r0,t0\n", {"io_5_0": (-0.25, 1.75, 0.4, 0.2)}, (0, 255, 102, 255), []),
            ("ps_1_1\ntex t0\nmov r0,t0\n", {"io_5_0": (0.75, 0.25, 0, 1)}, (0, 255, 0, 255), [(0, 0)]),
            ("ps_1_4\ndef c0,0.5,0.5,0.5,0.5\ntexcrd r1.rgb,t2\nmad r0.rgb,r1,c0,c0\nmov r0.a,c0.a\n", {"io_5_2": (-0.5, 0.25, 0.5, 0.8)}, (64, 159, 191, 128), []),
            ("ps_1_4\ntexcrd r0.rgb,t2.xyw\nmov r0.a,r0.r\n", {"io_5_2": (0.25, 0.5, 0.1, 0.75)}, (64, 128, 191, 64), []),
            ("ps_1_4\ntexcrd r0.rg,t2_dw.xyw\nmov r0.b,r0.r\nmov r0.a,r0.g\n", {"io_5_2": (0.25, 0.375, 0.1, 0.5)}, (128, 191, 128, 191), []),
            ("ps_1_4\ntexld r0,t3\n", {"io_5_3": (0.75, 0.25, 0, 1)}, (0, 255, 0, 255), [(0, 0)]),
            ("ps_1_4\ntexld r0,t3_dw.xyw\n", {"io_5_3": (0.375, 0.125, 0, 0.5)}, (0, 255, 0, 255), [(0, 0)]),
            ("ps_1_4\ntexcrd r1.rgb,t2\nphase\ntexld r0,r1_dz\n", {"io_5_2": (0.375, 0.125, 0.5, 1)}, (0, 255, 0, 255), [(0, 0)]),
            ("ps_1_4\ntexld r4,t1\nmov r0,r4\n", {"io_5_1": (0.25, 0.75, 0, 1)}, (0, 0, 255, 255), [(4, 0)]),
        ]
        for assembly, coords, expected, samplers in cases:
            with self.subTest(assembly=assembly):
                source, actual_samplers = translate(self.lib, assemble(self.lib, assembly))
                self.assertEqual(actual_samplers, samplers)
                actual = angle.render(source, coords, samplers)
                self.assertTrue(all(abs(a - e) <= 1 for a, e in zip(actual, expected)), (actual, expected, source))
        print(f"PASS GLES pixels for {len(cases)} legacy coordinate/sample semantics")

    def test_sampler_dimensions_and_invalid_modifiers(self):
        code = assemble(self.lib, "ps_1_4\ntexld r0,t2.xyw\n")
        for sampler_type, declaration, coordinates in [(0, b"sampler2D", b"ps_t2.xy"),
                                                      (1, b"samplerCube", b"ps_t2.xyw"),
                                                      (2, b"sampler3D", b"ps_t2.xyw")]:
            source, samplers = translate(self.lib, code, sampler_type)
            self.assertIn(declaration, source)
            self.assertIn(coordinates, source)
            self.assertEqual(samplers, [(0, sampler_type)])
        # Change a known-valid TEXLD source token to a forbidden ALU negate.
        code = bytearray(assemble(self.lib, "ps_1_4\ntexld r0,t2\n"))
        offset = next(i for i in range(4, len(code) - 8, 4) if struct.unpack_from("<I", code, i)[0] == 0x42)
        word = struct.unpack_from("<I", code, offset + 8)[0]
        struct.pack_into("<I", code, offset + 8, word | (1 << 24))
        with self.assertRaisesRegex(ValueError, "source modifier"):
            translate(self.lib, bytes(code))


if __name__ == "__main__":
    unittest.main()
