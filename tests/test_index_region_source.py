"""Pinned index-region selection, byte scope, and the actual Android pipeline."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_android as builder
import index_region as region


class IndexRegionSourceTest(unittest.TestCase):
    def test_exact_function_guard_line_endings_idempotence_and_scope(self):
        changed=[]
        for path in builder.generated_sources():
            source=path.read_bytes();result=region.index_region(source)
            if result!=source:
                changed.append(path.relative_to(ROOT).as_posix())
                self.assertEqual(result.count(b'H5_INDEX_REGION_FAST_BEGIN'),1)
                self.assertEqual(region.index_region(result),result)
        self.assertEqual(changed,['generated/game-x86/game_0641.c'])
        raw=(ROOT/changed[0]).read_bytes()
        for newline in (b'\n',b'\r\n'):
            source=raw.replace(b'\r\n',b'\n').replace(b'\n',newline)
            result=region.index_region(source)
            self.assertNotEqual(result,source)
            start=source.index(b'void sub_00C362E0(void) {')
            stop=source.index(b'void sub_00C36540(void) {')
            self.assertEqual(result[:start],source[:start])
            self.assertEqual(result[result.index(b'void sub_00C36540(void) {'):],source[stop:])
            if newline==b'\r\n':self.assertEqual(result.count(b'\n'),result.count(b'\r\n'))
            mutant=source.replace(b'eax = ecx; /* 0x00C364C8',b'eax = edx; /* 0x00C364C8',1)
            self.assertNotEqual(mutant,source)
            self.assertEqual(region.index_region(mutant),mutant)
        (ROOT/'build/pc-full/index-region-proof/source-scope.json').write_text(json.dumps(dict(
            changed=changed,function_sha256=region.FUNCTION_SHA256,
            implementation_sha256=hashlib.sha256((ROOT/'tools/index_region.py').read_bytes()).hexdigest()),indent=2)+'\n')

    def test_actual_android_pipeline_and_existing_global_register_option(self):
        source=ROOT/'generated/game-x86/game_0641.c';raw=source.read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory,patch.object(builder,'OUT',Path(directory)):
            prepared,_=builder.override_source(source,True)
            body=prepared.read_bytes()
            self.assertIn(b'H5_INDEX_REGION_FAST_BEGIN',body)
            self.assertIn(b'uint32_t l_backedges = g_backedges;',body)
            self.assertEqual(body.count(b'uint32_t l_backedges = g_backedges;'),1)
            self.assertEqual(builder.override_source(source,True)[0].read_bytes(),body)
            global_source,_=builder.override_source(source,False)
            self.assertNotIn(b'H5_INDEX_REGION_FAST_BEGIN',global_source.read_bytes())
            for chunk,count in (('game_0355.c',0),('game_0356.c',1)):
                selected,_=builder.override_source(source.with_name(chunk),True)
                self.assertEqual(selected.read_bytes().count(b'uint32_t l_backedges = g_backedges;'),count)
        self.assertEqual(source.read_bytes(),raw)

if __name__=='__main__':unittest.main()
