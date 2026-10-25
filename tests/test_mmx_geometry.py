"""Packing and signed comparisons against actual x86 MMX instructions."""
import unittest
import pefile
from test_mmx_packed import ROOT, generated_leaf, compile_variant


class MmxGeometryTest(unittest.TestCase):
    def test_native_packing_comparison_and_negative_controls(self):
        out = ROOT / 'build/tests/mmx_geometry'
        out.mkdir(parents=True, exist_ok=True)
        with pefile.PE(str(ROOT / 'generated/input/H5_Game.exe')) as pe:
            native = pe.get_data(0xC68210-pe.OPTIONAL_HEADER.ImageBase, 191)
        (out/'native_code.h').write_text('static const unsigned char original_code[] = {'+','.join(map(str,native))+'};\n')
        (out/'leaf.c').write_text('#include "recomp_types.h"\n'+generated_leaf())
        fixture = (ROOT/'tests/fixtures/mmx_packed_probe.c').read_text()
        fixture = fixture.replace('{"packuswb",0x67,0},{"pcmpeqw",0x75,0}',
                                  '{"packuswb",0x67,0},{"pcmpeqw",0x75,0},{"packssdw",0x6B,0},{"pcmpgtw",0x65,0}')
        fixture = fixture.replace('default:abort();', 'case 18:return mmx_packssdw(a,b);case 19:return mmx_pcmpgtw(a,b);default:abort();')
        fixture = fixture.replace('op<18;', 'op<20;').replace('360000', '400000')
        fixture = fixture.replace(r'helpers\":18', r'helpers\":20')
        (out/'probe.c').write_text(fixture)
        header = (ROOT/'android/runtime/recomp_types.h').read_text()
        for arch in ('x86','x64'):
            result = compile_variant(out, header, arch, arch)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('400000', result.stdout)
            print(result.stdout.strip())
        for name,old,new in (
            ('comparison','MMX_VIEW(signed_words, a) > MMX_VIEW(signed_words, b)','MMX_VIEW(signed_words, a) >= MMX_VIEW(signed_words, b)'),
            ('saturation','{32767,32767,32767,32767}','{32766,32766,32766,32766}')):
            mutant = header.replace(old,new,1)
            self.assertNotEqual(mutant, header)
            result = compile_variant(out, mutant, 'x86', 'bad_'+name)
            self.assertEqual(result.returncode, 25, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
