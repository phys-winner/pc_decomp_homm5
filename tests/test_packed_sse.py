"""Pass-aware packed-float raw-bit checks and the complete original skinning leaf."""
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

import capstone
import pefile

from test_d3d_lifecycle import function
from test_mmx_packed import CLANG, ROOT, command, environment, pc_header

sys.path.insert(0,str(ROOT/'tools'))
import build_android as builder


def instruction(op,dst=0,src=1,address='F1000000'):
    symbol={'addps':'+','subps':'-','mulps':'*','divps':'/'}[op]
    reads=' '.join(f'float _s{i} = _xmm[{src}].f32[{i}];' for i in range(4))
    lanes=' '.join(f'_d.f32[{i}] = (float)(_d.f32[{i}] {symbol} _s{i});' for i in range(4))
    return f'    {{ {reads} xmm_t _d = _xmm[{dst}]; {lanes} _xmm[{dst}] = _d; }} /* 0x{address}: {op} xmm{dst}, xmm{src} */'


def sources():
    leaf=function((ROOT/'generated/game-x86/game_0657.c').read_text(),'void sub_00C687C0(void) {')+'\n'
    names={'sub_00C687C0':'C687C0'}
    for i,(op,self_operand) in enumerate((op,same) for same in (False,True) for op in ('addps','subps','mulps')):
        address=f'{0xF1000000+i*16:08X}';symbol='sub_'+address
        names[symbol]=op[:-2]+('_self' if self_operand else '')
        leaf+=('void '+symbol+'(void) {\n'
               '    uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;\n'
               '    RECOMP_REGS_LOCALS\n    RECOMP_ENTER(0x'+address+'u);\n'+
               instruction(op,0,0 if self_operand else 1,address)+'\n    RECOMP_REGS_OUT();\n}\n')
    packed=builder.packed_sse(leaf.encode())
    assert packed.count(b'typedef float h5_ps4')==33
    outputs=[]
    for prefix,body in (('before_',leaf.encode()),('after_',packed)):
        body=builder.localize_sse(body).decode()
        for old,new in names.items():body=re.sub(r'\b'+old+r'\b',prefix+new,body)
        outputs.append('#include "recomp_types.h"\n'+body)
    return outputs


def prepare(out):
    out.mkdir(parents=True,exist_ok=True)
    before,after=sources()
    (out/'before.c').write_text(before)
    (out/'after.c').write_text(after)
    (out/'probe.c').write_text((ROOT/'tests/fixtures/packed_sse_probe.c').read_text())
    raw=(ROOT/'generated/input/H5_Game.exe').read_bytes()
    manifest=json.loads((ROOT/'config/modules.json').read_text())
    assert hashlib.sha256(raw).hexdigest()==manifest[0]['sha256']
    pe=pefile.PE(data=raw,fast_load=True)
    try:native=pe.get_data(0xC687C0-pe.OPTIONAL_HEADER.ImageBase,386)
    finally:pe.close()
    assert native[-3:]==b'\xC2\x0C\x00' and len(native)==386
    (out/'native_code.h').write_text('static const unsigned char original_code[] = {'+','.join(map(str,native))+'};\n')
    return before,after,hashlib.sha256(native).hexdigest()


def windows_codegen(out,arch):
    rows=[]
    for line in (out/'probe.map').read_text().splitlines():
        match=re.match(r'\s*0001:[0-9A-Fa-f]{8}\s+(\S+)\s+([0-9A-Fa-f]{8,16})\s+',line)
        if match:rows.append((int(match[2],16),match[1]))
    names={name:address for address,name in rows};report={}
    pe=pefile.PE(str(out/'probe.exe'),fast_load=True)
    cs=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32 if arch=='x86' else capstone.CS_MODE_64)
    try:
        for variant in ('before','after'):
            name=('_' if arch=='x86' else '')+variant+'_C687C0';start=names[name]
            end=min(address for address,_ in rows if address>start)
            code=list(cs.disasm(pe.get_data(start-pe.OPTIONAL_HEADER.ImageBase,end-start),start))
            counts={mnemonic:sum(i.mnemonic==mnemonic for i in code) for mnemonic in ('mulps','addps','mulss','addss')}
            report[variant]=dict(bytes=end-start,instructions=len(code),**counts)
            (out/(variant+'-assembly.txt')).write_text('\n'.join(f'{i.address:08X} {i.mnemonic} {i.op_str}' for i in code)+'\n')
    finally:pe.close()
    (out/'codegen.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def windows_probe(out,arch,mutant=False,thin=False,portable=False):
    before,after,native_sha=prepare(out)
    if portable:
        after=after.replace('#if defined(__i386__) || defined(__x86_64__)','#if 0')
        (out/'after.c').write_text(after)
    if mutant:
        changed=(after.replace('_du | 0x00400000u','_du | 0x00000000u') if mutant=='nan' else
                 after.replace('__asm__("mulps %1, %0"','__asm__("addps %1, %0"',1))
        assert changed!=after
        (out/'after.c').write_text(changed)
    (out/'recomp_types.h').write_text(pc_header((ROOT/'android/runtime/recomp_types.h').read_text()))
    target='i686' if arch=='x86' else 'x86_64'
    flags=[CLANG,'/nologo','/W0','/O2','/std:c11','/D_CRT_SECURE_NO_WARNINGS',
           f'/clang:--target={target}-pc-windows-msvc','/clang:-fno-strict-aliasing','/clang:-fwrapv','/clang:-ffp-contract=off']
    if arch=='x86':flags+=['/DVOID_GUEST_BASE=0']
    if thin:flags+=['/clang:-flto=thin','/Gy']
    env,linker=environment(arch)
    for name in ('before','after','probe'):
        extra=['/DRECOMP_GENERATED_CODE','/DRECOMP_LOCAL_REGS','/DRECOMP_PLAIN_MEMORY','/DRECOMP_TRACE'] if name!='probe' else []
        command([*flags,*extra,'/c',name+'.c','/Fo'+name+'.obj'],out,env)
    tool=[CLANG.with_name('ld.lld.exe'),'-flavor','link'] if thin else [linker]
    lto=['/threads:2','/opt:lldltojobs=2','/opt:lldlto=2','/lldltocache:'+str(out/'thinlto-cache')] if thin else []
    command([*tool,'/nologo','before.obj','after.obj','probe.obj','/OUT:probe.exe','/MAP:probe.map',
             '/BASE:'+('0x70000000' if arch=='x86' else '0x140000000'),'/DYNAMICBASE:NO','/FIXED','/STACK:262144',*lto],out,env)
    result=command([out/'probe.exe'],out,env,check=False)
    proof=windows_codegen(out,arch) if not mutant else None
    if proof:
        assert proof['after']['mulps']>=15 and proof['after']['addps']>=12,proof
    (out/'verification.json').write_text(json.dumps(dict(arch=arch,thinlto=thin,portable=portable,mutant=mutant,returncode=result.returncode,
        stdout=result.stdout,stderr=result.stderr,original_pe_leaf_sha256=native_sha,
        codegen=proof,flags=list(map(str,flags)),executable_sha256=hashlib.sha256((out/'probe.exe').read_bytes()).hexdigest(),
        source_sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in ('before.c','after.c','probe.c')}),indent=2)+'\n')
    return result


class PackedSseTest(unittest.TestCase):
    def test_exact_register_only_idempotent_and_crlf(self):
        for op in ('addps','subps','mulps'):
            for dst,src in ((0,1),(7,3),(4,4)):
                source=(instruction(op,dst,src)+'\r\n').encode()
                transformed=builder.packed_sse(source)
                self.assertNotEqual(source,transformed)
                self.assertEqual(transformed.count(b'typedef float h5_ps4'),1)
                self.assertIn(b'__builtin_reduce_or',transformed)
                self.assertTrue(transformed.endswith(b'\r\n'))
                self.assertEqual(builder.packed_sse(transformed),transformed)
                self.assertIn(f'memcpy(&_s, &_xmm[{src}]'.encode(),transformed)
                self.assertIn(f'memcpy(&_d, &_xmm[{dst}]'.encode(),transformed)
        for line in (instruction('divps'),instruction('addps').replace('xmm1 */','xmmword ptr [eax] */'),
                     instruction('mulps').replace('_s2 = _xmm[1]','_s2 = _xmm[2]'),
                     instruction('subps').replace('_d.f32[3] - _s3','_d.f32[3] + _s3')):
            source=(line+'\n').encode();self.assertEqual(builder.packed_sse(source),source)

    def test_all_five_actual_chunks_and_shared_preparation(self):
        expected={'granny2_0000.c':58,'granny2_0001.c':426,'granny2_0003.c':40,'game_0657.c':45,'game_0701.c':3}
        seen=0
        for name,count in expected.items():
            module='granny2' if name.startswith('granny') else 'game'
            source=(ROOT/'generated'/f'{module}-x86'/name).read_bytes()
            result=builder.packed_sse(source)
            self.assertEqual(result.count(b'typedef float h5_ps4'),count)
            self.assertEqual(builder.packed_sse(result),result)
            self.assertEqual((ROOT/'generated'/f'{module}-x86'/name).read_bytes(),source)
            seen+=count
        self.assertEqual(seen,572)
        untouched=(ROOT/'generated/game-x86/game_0355.c').read_bytes()
        self.assertEqual(builder.packed_sse(untouched),untouched)
        self.assertIn('body = source_transforms.packed_sse(body)',(ROOT/'tools/build_windows.py').read_text())
        self.assertIn('text = packed_sse(text)',(ROOT/'tools/build_android.py').read_text())

    def test_actual_ieee_and_complete_original_leaf(self):
        oracle_hashes=[]
        for arch,thin,portable in (('x86',False,False),('x64',False,False),('x86',True,False),('x86',True,True)):
            out=ROOT/'build/tests'/('packed_sse_'+arch+('_thinlto' if thin else '')+('_portable' if portable else ''))
            result=windows_probe(out,arch,thin=thin,portable=portable)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('"primitive_raw_state_checks":107904',result.stdout)
            self.assertIn('"whole_leaf_state_checks":384',result.stdout)
            self.assertIn('"yield_state_checks":48',result.stdout)
            self.assertIn('"original_pe_hardware_cases":'+('384' if arch=='x86' else '0'),result.stdout)
            oracle_hashes.append(hashlib.sha256((out/'native-ieee.bin').read_bytes()).hexdigest())
        self.assertEqual(len(set(oracle_hashes)),1)
        bad=windows_probe(ROOT/'build/tests/packed_sse_bad_operator','x86',mutant=True)
        self.assertEqual(bad.returncode,2,bad.stdout+bad.stderr)
        self.assertIn('whole skinning state mismatch',bad.stderr)
        bad_nan=windows_probe(ROOT/'build/tests/packed_sse_bad_nan','x86',mutant='nan',portable=True,thin=True)
        self.assertEqual(bad_nan.returncode,2,bad_nan.stdout+bad_nan.stderr)
        self.assertIn('packed IEEE state mismatch',bad_nan.stderr)

    def test_android_exact_same_pass_builds(self):
        out=ROOT/'build/tests/packed_sse_arm64';prepare(out)
        oracle=ROOT/'build/tests/packed_sse_x86_thinlto/native-ieee.bin'
        if not oracle.exists():
            checked=windows_probe(oracle.parent,'x86',thin=True)
            self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        vectors=oracle.read_bytes();self.assertEqual(len(vectors),16+107904*16)
        (out/'native-ieee.bin').write_bytes(vectors)
        (out/'recomp_types.h').write_text((ROOT/'android/runtime/recomp_types.h').read_text())
        flags=[builder.CLANG,'--target='+builder.TARGET,'-O2','-std=gnu11','-fno-strict-aliasing','-fwrapv',
               '-ffp-contract=off','-fPIE','-w']
        import os
        env=os.environ.copy()
        for name in ('before','after','probe'):
            extra=['-DRECOMP_GENERATED_CODE','-DRECOMP_LOCAL_REGS','-DRECOMP_PLAIN_MEMORY','-DRECOMP_TRACE'] if name!='probe' else []
            command([*flags,*extra,'-c',name+'.c','-o',name+'.o'],out,env)
        command([builder.CLANG,'--target='+builder.TARGET,'-pie','before.o','after.o','probe.o','-lm','-o','probe'],out,env)
        elf=(out/'probe').read_bytes()
        self.assertEqual(elf[:5],b'\x7FELF\x02');self.assertEqual(int.from_bytes(elf[18:20],'little'),183)
        (out/'build-receipt.json').write_text(json.dumps(dict(status='BUILT_NOT_EXECUTED',
            target=builder.TARGET,elf_sha256=hashlib.sha256((out/'probe').read_bytes()).hexdigest(),
            x86_hardware_reference_sha256=hashlib.sha256(vectors).hexdigest(),reference_bytes=len(vectors),
            flags=list(map(str,flags))),indent=2)+'\n')
        counts={}
        for variant in ('before','after'):
            disassembled=command([builder.TOOLCHAIN/'bin/llvm-objdump.exe','--no-show-raw-insn',
                '--disassemble-symbols='+variant+'_C687C0',out/'probe'],out,env).stdout
            (out/(variant+'-assembly.txt')).write_text(disassembled)
            counts[variant]={op:len(re.findall(r'\b'+op+r'\s+v\d+\.4s',disassembled)) for op in ('fmul','fadd')}
        self.assertGreaterEqual(counts['after']['fmul'],15);self.assertGreaterEqual(counts['after']['fadd'],12)
        (out/'codegen.json').write_text(json.dumps(counts,indent=2)+'\n')


if __name__=='__main__':unittest.main()
