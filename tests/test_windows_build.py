"""Exercise the complete PC builder orchestration with disposable inputs/tools."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('pc_builder',ROOT/'tools/build_windows.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class WindowsBuildTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'build');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'build/windows-x86';self.profile=self.root/'build/profile'
        (self.root/'config').mkdir();(self.root/'generated/input').mkdir(parents=True)
        (self.root/'config/windows.manifest').write_bytes((ROOT/'config/windows.manifest').read_bytes())
        original=json.loads((ROOT/'config/modules.json').read_text())
        self.manifest=original;self.images={};self.chunks=[];dispatch=[]
        for item in original:
            folder=self.root/'generated'/f"{item['name']}-x86";folder.mkdir()
            image=self.root/'generated/input'/item['file'];image.write_bytes(item['name'].encode())
            self.images[str(image)]=item
            (folder/'report.json').write_text(json.dumps(dict(status='GENERATED',rebased_sha256=builder.sha(image))))
            address=int(item['base'],16)+0x1000
            chunk=folder/(item['name']+'_0000.c');chunk.write_text('void sub_%08X(void) {}\n'%address)
            self.chunks.append(chunk)
            dispatch.append('{0x%08Xu, sub_%08X},\n'%(address,address))
            (folder/'recomp_dispatch.c').write_text(''.join(dispatch))
            (folder/(item['name']+'_funcs.h')).write_text('/* functions */\n')
        (self.root/'config/modules.json').write_text(json.dumps(original))
        for name in ('image_loader.c','recomp_trace.c'):
            path=self.root/'reference/pcrecomp/runtime/recomp32'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('/* host */')
        (self.root/'native').mkdir();(self.root/'native/windows_host.c').write_text('/* PC host */')
        self.compiler=self.root/'clang-cl.exe';self.compiler.write_bytes(b'compiler1')
        self.linker=self.root/'link.exe';self.linker.write_bytes(b'linker1')
        self.lld=self.root/'ld.lld.exe';self.lld.write_bytes(b'lld1')
        self.calls=[];self.fail=False;self.max_workers=[];self.closed_pe=set()
        self.patches=contextlib.ExitStack();self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(builder,'ROOT',self.root))
        self.patches.enter_context(patch.object(builder,'prepare',side_effect=self.prepare))
        self.stage=self.patches.enter_context(patch.object(builder,'prepare_game',return_value={'private':True}))
        self.patches.enter_context(patch.object(builder,'compiler_environment',return_value=(self.compiler,self.linker,{})))
        self.patches.enter_context(patch.object(builder.pefile,'PE',side_effect=self.pe))
        self.patches.enter_context(patch.object(builder.subprocess,'run',side_effect=self.run_tool))
        replace=builder.os.replace
        def checked_replace(source,target):
            if Path(source).name=='homm5-static.pending.exe':self.assertIn(str(source),self.closed_pe)
            return replace(source,target)
        self.patches.enter_context(patch.object(builder.os,'replace',side_effect=checked_replace))
        original_pool=builder.ThreadPoolExecutor
        def pool(*args,**kwargs):self.max_workers.append(kwargs.get('max_workers'));return original_pool(*args,**kwargs)
        self.patches.enter_context(patch.object(builder,'ThreadPoolExecutor',side_effect=pool))

    def prepare(self,path):
        path.mkdir(parents=True,exist_ok=True)
        for name in ('recomp_types.h','native32.h','native32.c'):
            file=path/name
            if not file.exists():file.write_text('/* private '+name+' */')
        return {'private_runtime':'current'}

    def pe(self,path,**kwargs):
        del kwargs
        item=self.images.get(str(path));base=int(item['base'],16) if item else builder.HOST_BASE
        return SimpleNamespace(FILE_HEADER=SimpleNamespace(Machine=0x14C),OPTIONAL_HEADER=SimpleNamespace(
            ImageBase=base,SizeOfImage=0x3000,AddressOfEntryPoint=0x1000,
            DATA_DIRECTORY=[SimpleNamespace(Size=0) for _ in range(16)]),close=lambda:self.closed_pe.add(str(path)))

    def run_tool(self,argv,**kwargs):
        self.calls.append((argv,kwargs))
        if self.fail:return SimpleNamespace(returncode=1,stdout='',stderr='planted compiler failure')
        if '/c' in argv:
            obj=Path(next(a[3:] for a in argv if a.startswith('/Fo')))
            source=Path(argv[argv.index('/c')+1]);obj.write_bytes(source.read_bytes()+b' object')
        else:
            expected=[str(self.lld),'-flavor','link'] if argv[0]==str(self.lld) else [str(self.linker)]
            self.assertEqual(argv[:-1],expected);self.assertTrue(argv[-1].startswith('@'))
            self.closed_pe.discard(str(self.output/'homm5-static.pending.exe'))
            (self.output/'homm5-static.pending.exe').write_bytes(b'linked current static host')
        return SimpleNamespace(returncode=0,stdout='',stderr='')

    def main(self,*extra,default_output=False):
        if default_output:self.output=self.root/('build/windows-x86-thinlto' if '--thinlto' in extra else 'build/windows-x86')
        argv=['build_windows.py',*([] if default_output else ['--output',str(self.output)]),'--profile',str(self.profile),*extra]
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()):builder.main()
        return json.loads((self.output/'plan.json').read_text())

    def test_plan_has_nine_modules_and_no_compilation(self):
        p=self.main('--plan','--generated-only')
        self.assertEqual((len(p['modules']),p['sources'],p['static_functions']),(9,10,9))
        self.assertEqual(self.calls,[]);self.assertFalse((self.output/'objects.json').exists())
        text=(self.output/'pc_dispatch.c').read_text()
        addresses=[int(a,16) for a in re.findall(r'\{0x([0-9A-F]+)u,',text)]
        self.assertEqual(addresses,sorted(addresses));self.assertEqual(len(set(addresses)),9)
        self.assertIn('all addresses remain NX',(self.output/'pc_modules.h').read_text())

    def test_actual_cache_tracks_source_header_compiler_and_object(self):
        p=self.main('--generated-only');self.assertEqual(p['compile'],10);self.assertEqual(self.max_workers[-1],4)
        flags=self.calls[0][0]
        for value in ('/O2','/DVOID_GUEST_BASE=0','/DRECOMP_TRACE','/clang:--target=i686-pc-windows-msvc'):
            self.assertIn(value,flags)
        generated_calls=[a for a,k in self.calls if '/DRECOMP_GENERATED_CODE' in a]
        self.assertEqual(len(generated_calls),9)
        self.assertTrue(all('/DRECOMP_LOCAL_REGS' in a and '/DRECOMP_PLAIN_MEMORY' in a for a in generated_calls))
        self.assertEqual(sum('/DRECOMP_YIELD_EVERY=2048u' in a for a in generated_calls),1)
        self.calls.clear();self.assertEqual(self.main('--generated-only')['reused'],10);self.assertEqual(self.calls,[])
        self.chunks[0].write_text(self.chunks[0].read_text()+'/* changed source */')
        self.assertEqual(self.main('--generated-only')['compile'],1)
        (self.output/'objects'/ (self.chunks[1].stem+'.obj')).write_bytes(b'corrupted object')
        self.assertEqual(self.main('--generated-only')['compile'],1)
        (self.output/'runtime/recomp_types.h').write_text('/* changed header */')
        self.assertEqual(self.main('--generated-only')['compile'],10)
        self.compiler.write_bytes(b'compiler2');self.assertEqual(self.main('--generated-only')['compile'],10)
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertEqual((receipt['status'],receipt['execution']),('COMPILED','UNVERIFIED'))

    def test_input_hash_and_dispatch_duplicates_fail_before_tools(self):
        self.main('--plan')
        image=Path(next(iter(self.images)));image.write_bytes(b'wrong image')
        with self.assertRaisesRegex(ValueError,'image/report mismatch'):self.main('--plan')
        item=self.images[str(image)];image.write_bytes(item['name'].encode())
        first=self.chunks[0].parent/'recomp_dispatch.c';second=self.chunks[1].parent/'recomp_dispatch.c'
        own=second.read_text();second.write_text(own+first.read_text())
        self.assertEqual(self.main('--plan')['static_functions'],9)
        second.write_text(own+first.read_text().replace('sub_','sub_BAD'))
        with self.assertRaisesRegex(ValueError,'Conflicting static dispatch'):self.main('--plan')
        self.assertEqual(self.calls,[])

    def test_pgo_modes_keep_diagnostics_and_invalidate_changed_training(self):
        runtime=self.root/builder.PROFILE_RUNTIME;runtime.parent.mkdir(parents=True);runtime.write_bytes(b'profile runtime')
        with patch.object(builder,'PROFILE_RUNTIME_SHA256',builder.sha(runtime)),patch.object(builder,'stage_profile'):
            self.main('--thinlto','--pgo-generate')
        generated=[a for a,k in self.calls if '/DRECOMP_GENERATED_CODE' in a]
        self.assertEqual(len(generated),9)
        self.assertTrue(all('/clang:-fprofile-generate' in a and '/DRECOMP_TRACE' in a for a in generated))
        host=next(a for a,k in self.calls if '/c' in a and str(self.root/'native/windows_host.c') in a)
        self.assertIn('/DPC_PGO_GENERATE',host)
        self.assertIn(str(runtime),(self.output/'link.rsp').read_text())
        self.assertFalse(json.loads((self.output/'receipt.json').read_text())['identity']['pgo']['clean_fps_eligible'])
        data=self.root/'training.profdata';data.write_bytes(b'profile1');self.calls.clear()
        self.assertEqual(self.main('--generated-only','--thinlto','--pgo-use',str(data))['compile'],10)
        self.assertEqual(sum('/clang:-fprofile-use='+str(data) in a for a,k in self.calls),9)
        generated=[a for a,k in self.calls if '/DRECOMP_GENERATED_CODE' in a]
        self.assertTrue(all('/W0' not in a and '/clang:-Werror=backend-plugin' in a for a in generated))
        self.calls.clear();self.assertEqual(self.main('--generated-only','--thinlto','--pgo-use',str(data))['reused'],10)
        data.write_bytes(b'profile2')
        self.assertEqual(self.main('--generated-only','--thinlto','--pgo-use',str(data))['compile'],10)

    def test_pgo_rejects_missing_or_changed_runtime_and_missing_profile_before_build(self):
        for arguments in (('--pgo-generate',),('--pgo-use',str(self.root/'missing.profdata'))):
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):self.main(*arguments,'--plan')
        runtime=self.root/builder.PROFILE_RUNTIME;runtime.parent.mkdir(parents=True);runtime.write_bytes(b'wrong runtime')
        with self.assertRaises(ValueError):self.main('--pgo-generate','--plan')
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            self.main('--pgo-generate','--pgo-use',str(self.root/'missing.profdata'),'--plan')
        self.assertEqual(self.calls,[])

    def test_argument_and_output_guards(self):
        for jobs in ('0','33','-1'):
            with self.subTest(jobs=jobs),self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
                self.main('--jobs',jobs,'--plan')
        with self.assertRaises(SystemExit),contextlib.redirect_stderr(io.StringIO()):
            self.main('--output',str(self.root/'outside'),'--plan')
        self.assertEqual(self.calls,[])

    def test_canonical_last_dispatch_and_stale_cumulative_entries(self):
        table=self.chunks[0].parent/'recomp_dispatch.c'
        original=table.read_text();last=self.chunks[-1].parent/'recomp_dispatch.c'
        stale='{0x10001000u, sub_10001000},\n'
        table.write_text(original+stale)
        self.assertEqual(self.main('--plan')['static_functions'],9)
        text=(self.output/'pc_dispatch.c').read_text()
        self.assertNotIn('sub_10001000',text)
        table.write_text(original+stale+stale.replace('sub_10001000','sub_10002000'))
        with self.assertRaisesRegex(ValueError,'Conflicting static dispatch'):self.main('--plan')
        table.write_text(original)
        last.write_text(last.read_text()+stale)
        with self.assertRaisesRegex(ValueError,'Canonical dispatch entry outside current guest images'):self.main('--plan')
        self.assertEqual(self.calls,[])

    def test_canonical_entry_requires_a_compiled_body(self):
        original=self.chunks[0].read_text()
        self.chunks[0].write_text('/* missing body */\n')
        with self.assertRaisesRegex(ValueError,'compiled function bodies'):self.main('--plan')
        self.chunks[0].write_text(original+'void sub_00401100(void) {}\n')
        with self.assertRaisesRegex(ValueError,'compiled function bodies'):self.main('--plan')
        self.assertEqual(self.calls,[])

    def test_full_link_nx_fixed_base_and_failure_keeps_previous_executable(self):
        with patch.object(builder,'stage_profile') as stage:
            p=self.main('--jobs','2')
            self.assertEqual((p['sources'],p['compile']),(14,14));self.assertEqual(self.max_workers[-1],2)
            stage.assert_called_once_with(self.profile.resolve(),self.root/'build/windows-game')
            self.stage.assert_called_once_with(self.root/'build/windows-game')
        response=(self.output/'link.rsp').read_text()
        for flag in ('/BASE:0x60000000','/DYNAMICBASE:NO','/FIXED','/MACHINE:X86','/NXCOMPAT','/MAP:'):
            self.assertIn(flag,response)
        target=self.output/'homm5-static.exe';before=target.read_bytes()
        self.assertEqual(target.with_suffix('.exe.manifest').read_bytes(),builder.windows_manifest_bytes())
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertTrue(receipt['manifest']['changed']);self.assertFalse(receipt['manifest']['executable_timestamp_updated'])
        self.chunks[0].write_text(self.chunks[0].read_text()+'/* new source */');self.fail=True
        with self.assertRaisesRegex(RuntimeError,'Compile failed'):self.main()
        self.assertEqual(target.read_bytes(),before)

    @patch.object(builder,'stage_profile')
    def test_thinlto_separate_default_flags_linker_cache_and_jobs(self,_stage):
        self.main(default_output=True)
        normal=self.output;normal_objects=(normal/'objects.json').read_bytes()
        self.assertTrue(all('/clang:-flto=thin' not in a for a,k in self.calls if '/c' in a))
        self.calls.clear()
        p=self.main('--thinlto','--jobs','3',default_output=True)
        self.assertTrue(p['thinlto']);self.assertEqual(p['compile'],14)
        self.assertEqual(self.output,self.root/'build/windows-x86-thinlto')
        self.assertEqual(self.max_workers[-1],3)
        for args,kwargs in self.calls:
            if '/c' in args:
                for flag in ('/O2','/clang:-flto=thin','/clang:-ffp-contract=off','/clang:-fno-strict-aliasing','/clang:-fwrapv'):
                    self.assertIn(flag,args)
        response=(self.output/'link.rsp').read_text()
        for flag in ('/OPT:REF','/OPT:ICF','/OPT:lldlto=2','/threads:3','/OPT:lldltojobs=3',
                     '/lldltocache:'+str(self.output/'thinlto-cache'),
                     '/lldltocachepolicy:cache_size=0%:cache_size_bytes=4g:prune_interval=0s'):
            self.assertIn(flag,response)
        receipt=json.loads((self.output/'receipt.json').read_text())
        self.assertEqual(receipt['linker'],dict(command=[str(self.lld),'-flavor','link'],sha256=builder.sha(self.lld)))
        self.calls.clear();self.assertEqual(self.main('--thinlto',default_output=True)['reused'],14)
        self.assertFalse(any('/c' in a for a,k in self.calls))
        self.assertEqual((normal/'objects.json').read_bytes(),normal_objects)

    def test_explicit_output_thinlto_rejects_incompatible_object_cache(self):
        self.main('--generated-only');output=self.output
        self.assertEqual(self.main('--thinlto','--generated-only')['compile'],10)
        self.assertEqual(self.output,output)
        self.assertEqual(self.main('--thinlto','--generated-only')['reused'],10)
        self.assertEqual(self.main('--generated-only')['compile'],10)

    def test_missing_lld_rejected_before_compilation(self):
        self.lld.unlink()
        with self.assertRaisesRegex(ValueError,'ThinLTO requires the NDK ld.lld.exe'):
            self.main('--thinlto','--plan',default_output=True)
        self.assertEqual(self.calls,[])

    def test_profile_seed_preserves_existing_progress_and_inputs(self):
        source=self.root/builder.PROFILE_SEED;(source/'Saves').mkdir(parents=True)
        (source/'input_a2.cfg').write_bytes(b'original key bindings')
        (source/'Saves/save_6.sav').write_bytes(b'original read-only save6')
        cfg=source/'user_a2-max2048.cfg'
        cfg.write_text('setvar gfx_fullscreen = 1\nsetvar gfx_resolution = 2944x1840\nsetvar gfx_window_size = 2944x1840\nsetvar gfx_shadow_resolution = 2048\n')
        before={p:builder.sha(p) for p in (source/'input_a2.cfg',source/'Saves/save_6.sav',cfg)}
        legacy=self.profile/'Documents/My Games/Heroes of Might and Magic V \ufffd Tribes of the East/Profiles/hero/Saves'
        legacy.mkdir(parents=True);(legacy/'save_8.sav').write_bytes(b'legacy progress remains')
        builder.stage_profile(self.profile)
        copied=list(self.profile.glob('Documents/My Games/*\u2014*/Profiles/hero'))
        self.assertEqual(len(copied),1);profile=copied[0]
        self.assertEqual((profile/'Saves/save_6.sav').read_bytes(),b'original read-only save6')
        text=(profile/'user_a2.cfg').read_text()
        for setting in ('gfx_fullscreen = 0','gfx_resolution = 1472x920','gfx_window_size = 1472x920','gfx_shadow_resolution = 2048'):
            self.assertIn(setting,text)
        (profile/'Saves/save_6.sav').write_bytes(b'new user progress');(profile/'user_a2.cfg').write_text('user settings')
        builder.stage_profile(self.profile)
        self.assertEqual((profile/'Saves/save_6.sav').read_bytes(),b'new user progress')
        self.assertEqual((profile/'user_a2.cfg').read_text(),'user settings')
        self.assertEqual({p:builder.sha(p) for p in before},before)
        self.assertEqual((profile/'name.txt').read_text(encoding='utf16'),'hero')
        self.assertIn('profile_name = hero',(profile.parents[1]/'global_a2.cfg').read_text())
        self.assertTrue((self.profile/'AppData').is_dir())
        self.assertEqual((legacy/'save_8.sav').read_bytes(),b'legacy progress remains')

    def test_verified_manifest_staging_preserves_pe_and_only_touches_changed_existing_context(self):
        target=self.root/'build/context-test.exe';target.parent.mkdir(parents=True);target.write_bytes(b'unchanged PE bytes')
        body=builder.windows_manifest_bytes();digest=builder.sha(target)
        with patch.object(builder.os,'utime',wraps=builder.os.utime) as touch:
            first=builder.stage_manifest(target)
            self.assertEqual(target.with_suffix('.exe.manifest').read_bytes(),body)
            self.assertEqual(first['sha256'],builder.WINDOWS_MANIFEST_SHA256)
            self.assertTrue(first['changed']);self.assertTrue(first['executable_timestamp_updated'])
            touch.assert_called_once_with(target.resolve(),None)
            self.assertFalse(builder.stage_manifest(target)['changed']);self.assertEqual(touch.call_count,1)
            target.with_suffix('.exe.manifest').write_bytes(b'old sidecar')
            fresh=builder.stage_manifest(target,fresh_executable=True)
            self.assertTrue(fresh['changed']);self.assertFalse(fresh['executable_timestamp_updated'])
            self.assertEqual(touch.call_count,1);self.assertEqual(builder.sha(target),digest)

    def test_unverified_windows_manifest_fails_before_prepare_or_tools(self):
        (self.root/'config/windows.manifest').write_bytes(b'unverified locale setting')
        with patch.object(builder,'prepare',side_effect=AssertionError('must validate before preparing')):
            with self.assertRaisesRegex(ValueError,'differs from the verified configuration'):self.main('--plan')
        self.assertEqual(self.calls,[])

    def test_main_compiles_transformed_bytes_with_original_module_flags(self):
        self.chunks[0].write_text('void sub_00401000(void) {\n    _xmm[0].u32[0] = 1;\n}\n')
        self.main('--generated-only')
        compiled=[a for a,k in self.calls if '/c' in a and Path(a[a.index('/c')+1]).name==self.chunks[0].name]
        self.assertEqual(len(compiled),1)
        source=Path(compiled[0][compiled[0].index('/c')+1])
        self.assertTrue(source.is_relative_to(self.output/'patched'))
        self.assertIn('xmm_t l_xmm[8]',source.read_text())
        for flag in ('/DRECOMP_GENERATED_CODE','/DRECOMP_LOCAL_REGS','/DRECOMP_PLAIN_MEMORY','/I'+str(self.chunks[0].parent)):
            self.assertIn(flag,compiled[0])
        self.assertEqual(self.main('--generated-only')['reused'],10)


class WindowsTransformsTest(unittest.TestCase):
    def test_actual_sources_match_pure_passes_and_preserve_native_overrides(self):
        transforms=builder.source_transforms
        saved_out=transforms.OUT
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp, \
                patch.object(transforms,'override_source',side_effect=AssertionError('Android native override path forbidden')):
            output=Path(tmp)
            for relative in ('generated/msvcr71-x86/msvcr71_0003.c','generated/fmod-x86/fmod_0014.c','generated/game-x86/game_0106.c',
                             'generated/game-x86/game_0355.c','generated/game-x86/game_0356.c',
                             'generated/game-x86/game_0641.c','generated/game-x86/game_0657.c','generated/granny2-x86/granny2_0001.c'):
                source=ROOT/relative;raw=source.read_bytes();expected=transforms.guard_fpu_memory(raw)
                if b'goto _ljump; }' in expected:
                    expected=transforms.direct_jump_tables(expected,transforms.module_image(source.parent.name[:-4]))
                expected=transforms.packed_sse(expected)
                expected=transforms.fast_rep_movs(expected)
                expected=transforms.index_region(expected)
                expected=transforms.localize_sse(expected)
                expected=transforms.localize_backedges(expected,transforms.BACKEDGE_HOT_FUNCTIONS)
                # Whole-program call protocol and x87 locals (build/call-protocol summaries) run last.
                expected=transforms.apply_protocol(expected,transforms.call_protocol(),source.parent.name[:-4])
                expected=transforms.apply_x87(expected,transforms.x87_plan())
                prepared=builder.prepare_generated(source,output)
                self.assertEqual(prepared.read_bytes(),expected)
                self.assertEqual(source.read_bytes(),raw)
                self.assertEqual(builder.prepare_generated(source,output).read_bytes(),expected)
                if source.name=='msvcr71_0003.c':
                    self.assertIn(b'void_lift_trap(0x130041DBu,',expected)
                if source.name=='fmod_0014.c':
                    self.assertIn(b'static void *const _jt[',expected)
                    self.assertIn(b'void sub_1102BC0B(void) {',expected)
                    self.assertNotIn(b'void sub_1102BC0B_lifted(void)',expected)
                    # Android's native overrides keep the full protocol at their calls and exits.
                    self.assertIn(b'RECOMP_CALL_P(sub_1102BC0B, 0xFFu, 0xFFu, 1, ',expected)
                    override=expected[expected.index(b'void sub_1102BC0B(void) {'):]
                    self.assertNotIn(b'RECOMP_EXIT_P(',override[:override.index(b'\n}\r\n')])
                self.assertIn(b'RECOMP_CALL_P(',expected)
                if source.name in ('game_0355.c','game_0356.c','game_0657.c','granny2_0001.c'):
                    self.assertIn(b'recomp_movs_fast(',expected)
                if source.name=='game_0106.c':self.assertIn(b'xmm_t l_xmm[8]',expected)
                if source.name in ('game_0657.c','granny2_0001.c'):self.assertIn(b'typedef float h5_ps4',expected)
                if source.name=='game_0641.c':self.assertIn(b'H5_INDEX_REGION_FAST_BEGIN',expected)
                self.assertEqual(expected.count(b'uint32_t l_backedges = g_backedges;'),
                                 int(source.name in ('game_0356.c','game_0641.c')))
        self.assertEqual(transforms.OUT,saved_out)


if __name__=='__main__':unittest.main()
