import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import agentic_wine_time_weather_matrix_runner as runner
from scene_utils.matrix_resume import capture_integrity, read_json, simulator_lock, write_json
from scene_utils.time_weather_matrix import load_time_weather_spec, iter_time_weather_combinations


class MatrixResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.code = self.root / 'scene.py'
        self.code.write_text('print("scene")\n')
        self.output = self.root / 'matrix' / 'noon__clear'
        self.manifest = {'code_file_posix': str(self.code), 'code_file_windows': str(self.code),
                         'output_dir_posix': str(self.root / 'matrix'), 'duration_seconds': 1,
                         'image_dimensions': [16,9], 'scene_specifications': 'Camera Contract: front'}
        self.cli = ['--time-preset','noon','--weather-preset','clear']
        self.calls = 0

    def fake_run(self, manifest, timeout, dry_run, cwd, **kwargs):
        self.calls += 1
        if not dry_run:
            out = kwargs['output_dir_override']
            (out/'front').mkdir(parents=True)
            for n in range(1,21):
                Image.new('RGB',(16,9),(n,0,0)).save(out/'front'/f'front_frame_{n:08d}.png')
            write_json(out/'cleanup_status.json', {'complete':True,'errors':[]})
        return {'dry_run':dry_run,'returncode':0,'process_success':True,'success':True}

    def run_capture(self, **kwargs):
        with patch.object(runner,'run_manifest',side_effect=self.fake_run):
            return runner.run_variant(self.manifest,self.output,self.cli,None,2,0,**kwargs)

    def test_revalidates_and_skips_complete_capture(self):
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.run_capture()['status'],'SKIPPED_VERIFIED')
        self.assertEqual(self.calls,1)

    def test_corrupt_frame_is_preserved_before_retry(self):
        self.run_capture()
        broken=self.output/'front/front_frame_00000001.png'
        broken.write_bytes(b'corrupt')
        self.assertTrue(self.run_capture()['success'])
        saved=list((self.output.parent/'failed_attempts').rglob(broken.name))
        self.assertEqual(len(saved),1)
        self.assertEqual(saved[0].read_bytes(),b'corrupt')
        self.assertEqual(self.calls,2)

    def test_changed_valid_image_invalidates_hash(self):
        self.run_capture()
        Image.new('RGB',(16,9),'blue').save(self.output/'front/front_frame_00000001.png')
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.calls,2)

    def test_source_change_invalidates_receipt(self):
        self.run_capture()
        self.code.write_text('print("changed")\n')
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.calls,2)

    def test_settings_change_invalidates_receipt(self):
        self.run_capture()
        self.cli += ['--fog-density','50']
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.calls,2)

    def test_missing_frame_retries(self):
        self.run_capture()
        (self.output/'front/front_frame_00000007.png').unlink()
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.calls,2)

    def test_process_failure_cannot_pass_full_frames(self):
        def failed(*args,**kwargs):
            result=self.fake_run(*args,**kwargs)
            return dict(result,returncode=1,process_success=False)
        with patch.object(runner,'run_manifest',side_effect=failed):
            result=runner.run_variant(self.manifest,self.output,self.cli,None,2,0)
        self.assertFalse(result['success'])
        self.assertEqual(self.calls,2)
        self.assertTrue(list((self.output.parent/'failed_attempts').rglob('variant_result.json')))

    def test_cleanup_failure_stops_retries(self):
        def failed(*args,**kwargs):
            result=self.fake_run(*args,**kwargs)
            write_json(self.output/'cleanup_status.json',{'complete':False,'errors':['destroy failed']})
            return result
        with patch.object(runner,'run_manifest',side_effect=failed):
            result=runner.run_variant(self.manifest,self.output,self.cli,None,2,0)
        self.assertFalse(result['success'])
        self.assertFalse(result['cleanup_verified'])
        self.assertEqual(self.calls,1)

    def test_dry_run_does_not_touch_capture(self):
        self.run_capture()
        receipt=(self.output/'variant_result.json').read_bytes()
        result=self.run_capture(dry_run=True)
        self.assertFalse(result['success'])
        self.assertEqual(result['status'],'DRY_RUN_ONLY')
        self.assertEqual((self.output/'variant_result.json').read_bytes(),receipt)

    def test_duplicate_lock_rejected_and_released(self):
        path=self.root/'simulator.lock'
        with simulator_lock(path):
            with self.assertRaises(RuntimeError):
                with simulator_lock(path):
                    self.fail('second owner acquired lock')
        with simulator_lock(path):
            pass

    def test_exact_paper_matrix(self):
        spec=load_time_weather_spec()
        combinations=list(iter_time_weather_combinations(spec))
        self.assertEqual(len(combinations),8)
        self.assertEqual({x['variant_name'] for x in combinations},
                         {f'{t}__{w}' for t in ('noon','night') for w in ('clear','storm','worst','foggy')})
        self.assertEqual({x['key']:x['label'] for x in spec['weather_presets']},
                         {'clear':'Clear','storm':'Heavy Rainy','worst':'Stormy','foggy':'Foggy'})

    def test_missing_required_camera_fails(self):
        self.run_capture()
        self.manifest['scene_specifications']='Camera Contract: front and rear'
        errors,_,_=capture_integrity(self.output,self.manifest)
        self.assertTrue(any('rear' in x for x in errors))

    def test_invalid_receipt_is_not_skipped(self):
        self.run_capture()
        (self.output/'variant_result.json').write_text('{truncated')
        self.assertTrue(self.run_capture()['success'])
        self.assertEqual(self.calls,2)

if __name__=='__main__':
    unittest.main()
