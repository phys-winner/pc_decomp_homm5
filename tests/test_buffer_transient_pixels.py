"""GLES pixel oracle for actual consumed-stream range/rebase helper results."""
import ctypes as C
import json
from pathlib import Path
import struct
import unittest

from test_legacy_shaders import Angle
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

CASES = [
    dict(name="positive16", first=8, base=5, raw=[3, 4, 5], wide=False, instances=1),
    dict(name="negative16", first=8, base=-5, raw=[13, 14, 15], wide=False, instances=1),
    dict(name="negative32", first=8, base=-65531, raw=[65539, 65540, 65541], wide=True, instances=1),
    dict(name="arrays", first=7, base=0, raw=None, wide=False, instances=1),
    dict(name="instanced", first=8, base=-5, raw=[13, 14, 15], wide=False, instances=2),
]


def actual_ranges():
    """Compile the production math bodies; consume their results in real draws."""
    text=(ROOT/"android/host/d3d9_gl.c").read_text(encoding="utf-8")
    code=body(text,"static int draw_stream_range(")+body(text,"static int draw_rebase(")
    path=ROOT/"build/tests/buffer_transient_pixels/ranges.json"
    rows=""
    for i,case in enumerate(CASES):
        rows+=f'''assert(draw_stream_range(680,24,20,12,{case['first']},{case['first']+2},&lo,&bytes));
assert(draw_stream_range(80,32,16,12,0,{case['instances']-1},&ilo,&ibytes));
assert(draw_rebase({case['base'] & 0xffffffff}u,{case['first']},{int(case['raw'] is not None)},&base));
fprintf(out,"%s[ %u, %u, %u, %u, %d ]",{json.dumps(',' if i else '')},lo,bytes,ilo,ibytes,base);
'''
    harness='''#include <assert.h>
#include <stdint.h>
#include <stdio.h>
'''+code+f'''
int main(void) {{
FILE *out=fopen({json.dumps(str(path))},"w"); assert(out);
uint32_t lo,bytes,ilo,ibytes; int32_t base;
fputs("[",out);
{rows}
fputs("]",out);assert(!fclose(out));
puts("PASS actual transient range/rebase bodies for GLES pixel cases");return 0;
}}
'''
    compile_probe("buffer_transient_pixels",harness,{})
    return json.loads(path.read_text())


class TransientPixelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ranges=actual_ranges()
        cls.angle=Angle()
        a=cls.angle
        for name,ret,args in [
            ("glGenBuffers",None,[C.c_int,C.POINTER(C.c_uint)]),
            ("glDeleteBuffers",None,[C.c_int,C.POINTER(C.c_uint)]),
            ("glBindBuffer",None,[C.c_uint,C.c_uint]),
            ("glBufferData",None,[C.c_uint,C.c_ssize_t,C.c_void_p,C.c_uint]),
            ("glVertexAttribPointer",None,[C.c_uint,C.c_int,C.c_uint,C.c_ubyte,C.c_int,C.c_void_p]),
            ("glEnableVertexAttribArray",None,[C.c_uint]),
            ("glDisableVertexAttribArray",None,[C.c_uint]),
            ("glVertexAttribDivisor",None,[C.c_uint,C.c_uint]),
            ("glVertexAttrib2f",None,[C.c_uint,C.c_float,C.c_float]),
            ("glClearColor",None,[C.c_float]*4),
            ("glClear",None,[C.c_uint]),
        ]:
            a.api(a.gl,name,ret,*args)
        a.api(a.egl,"eglGetProcAddress",C.c_void_p,C.c_char_p)
        def extension(names,arguments):
            pointer=next((a.egl.eglGetProcAddress(n.encode()) for n in names if a.egl.eglGetProcAddress(n.encode())),None)
            if not pointer: raise unittest.SkipTest("ANGLE base-vertex extension required")
            return C.WINFUNCTYPE(None,*arguments)(pointer)
        cls.draw_base=extension(["glDrawElementsBaseVertexOES","glDrawElementsBaseVertexEXT"],
                                [C.c_uint,C.c_int,C.c_uint,C.c_void_p,C.c_int])
        cls.draw_instances=extension(["glDrawElementsInstancedBaseVertexOES","glDrawElementsInstancedBaseVertexEXT"],
                                     [C.c_uint,C.c_int,C.c_uint,C.c_void_p,C.c_int,C.c_int])
        vs=a.compile(b"#version 300 es\nprecision highp float;\nlayout(location=0) in vec2 p;\n"
                     b"layout(location=1) in vec4 c;\nlayout(location=2) in vec2 instance_offset;\n"
                     b"out vec4 color;\nvoid main(){gl_Position=vec4(p+instance_offset,0,1);color=c;}\n",0x8B31)
        ps=a.compile(b"#version 300 es\nprecision highp float;\nin vec4 color;\nout vec4 output_color;\n"
                     b"void main(){output_color=color;}\n")
        cls.program=a.gl.glCreateProgram()
        for shader in (vs,ps):a.gl.glAttachShader(cls.program,shader)
        a.gl.glLinkProgram(cls.program)
        status=C.c_int();a.gl.glGetProgramiv(cls.program,0x8B82,C.byref(status));assert status.value
        a.gl.glUseProgram(cls.program)
        for shader in (vs,ps):a.gl.glDeleteShader(shader)

    def render(self,case_id,compact,queued=False):
        gl=self.angle.gl;case=CASES[case_id]
        lo,length,ilo,ilength,new_base=self.ranges[case_id]
        owned=[];scratch={}
        def upload(data,reuse=None):
            if reuse is not None and reuse in scratch:buffer=scratch[reuse]
            else:
                value=C.c_uint();gl.glGenBuffers(1,C.byref(value));buffer=value.value;owned.append(buffer)
                if reuse is not None:scratch[reuse]=buffer
            gl.glBindBuffer(0x8F37,buffer)
            gl.glBufferData(0x8F37,len(data),bytes(data),0x88E0)
            return buffer
        def attribute(slot,buffer,size,kind,norm,stride,offset,divisor=0):
            gl.glBindBuffer(0x8892,buffer);gl.glVertexAttribPointer(slot,size,kind,norm,stride,C.c_void_p(offset))
            gl.glEnableVertexAttribArray(slot);gl.glVertexAttribDivisor(slot,divisor)
        gl.glViewport(0,0,8,8);gl.glClearColor(0,0,0,1);gl.glClear(0x4000)
        for draw in range(2 if queued else 1):
            first=case["first"];positions=bytearray(680);colors=bytearray(416)
            triangle=((-0.5,-1),(0.5,-1),(-0.5,1)) if case["instances"]>1 else ((-1,-1),(3,-1),(-1,3))
            palette=((255,0,0,255),(0,255,0,255),(0,0,255,255)) if not draw else ((0,255,255,255),(255,0,255,255),(255,255,0,255))
            for i,(position,color) in enumerate(zip(triangle,palette)):
                struct.pack_into("<2f",positions,24+(first+i)*20+4,*position)
                colors[16+(first+i)*12+3:16+(first+i)*12+7]=bytes(color)
            pos_buffer=upload(positions[lo:lo+length] if compact else positions,"position" if compact else None)
            # This stream stays in its original storage in the compact path.
            color_buffer=upload(colors)
            attribute(0,pos_buffer,2,0x1406,0,20,4 if compact else 28)
            attribute(1,color_buffer,4,0x1401,1,12,19+(first*12 if compact else 0))
            if case["instances"]>1:
                instance=bytearray(80)
                for i,x in enumerate((-0.5,0.5)):struct.pack_into("<2f",instance,32+i*16+4,x,0)
                inst_buffer=upload(instance[ilo:ilo+ilength] if compact else instance,"instance" if compact else None)
                attribute(2,inst_buffer,2,0x1406,0,16,4 if compact else 36,1)
            else:
                gl.glDisableVertexAttribArray(2);gl.glVertexAttribDivisor(2,0);gl.glVertexAttrib2f(2,0,0)
            gl.glViewport(draw*4,0,4,8) if queued else gl.glViewport(0,0,8,8)
            if case["raw"] is None:gl.glDrawArrays(4,0 if compact else first,3)
            else:
                kind=0x1405 if case["wide"] else 0x1403;unit=4 if case["wide"] else 2
                indices=struct.pack("<3"+("I" if case["wide"] else "H"),*case["raw"])
                index_buffer=upload(indices if compact else bytes(4*unit)+indices,"index" if compact else None)
                gl.glBindBuffer(0x8893,index_buffer)
                pointer=C.c_void_p(0 if compact else 4*unit);base=new_base if compact else case["base"]
                if case["instances"]>1:self.draw_instances(4,3,kind,pointer,case["instances"],base)
                else:self.draw_base(4,3,kind,pointer,base)
        # No readback/synchronization occurs between the queued orphaning draws.
        pixels=(C.c_ubyte*256)();gl.glReadPixels(0,0,8,8,0x1908,0x1401,pixels)
        self.assertEqual(gl.glGetError(),0)
        values=(C.c_uint*len(owned))(*owned);gl.glDeleteBuffers(len(owned),values)
        return bytes(pixels)

    def test_mixed_streams_and_draw_modes(self):
        for i,case in enumerate(CASES):
            with self.subTest(case=case["name"]):
                reference=self.render(i,False);compact=self.render(i,True)
                self.assertGreater(sum(bool(reference[p] or reference[p+1] or reference[p+2]) for p in range(0,256,4)),16)
                self.assertEqual(compact,reference)

    def test_queued_orphaned_stores_preserve_earlier_draw(self):
        reference=self.render(1,False,True);compact=self.render(1,True,True)
        self.assertEqual(compact,reference)
        self.assertNotEqual(compact[:16],compact[16:32])


if __name__=="__main__":
    unittest.main()
