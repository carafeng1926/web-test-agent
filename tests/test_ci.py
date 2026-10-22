import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import ci

class CloudTests(unittest.TestCase):
    def test_demo_plan_and_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ci, 'PLAN_DIR', Path(tmp)):
                with patch.dict(os.environ, {'TEST_MODE':'demo','GITHUB_SHA':'commit-a',
                        'GITHUB_OUTPUT':'','GITHUB_STEP_SUMMARY':''}):
                    env = ci.prepare()
                    self.assertEqual(len(env['payload']['plan']['cases']), 1)
                    self.assertEqual(env['payload']['plan']['cases'][0]['id'], 'LOGIN_PASS')
                    token = env['approval_hash']
                    with patch.dict(os.environ, {'APPROVED_PLAN_HASH':token,
                                                'EXPECTED_PLAN_HASH':token}):
                        self.assertEqual(ci.verify(), env['payload'])
                        with patch.dict(os.environ, {'GITHUB_SHA':'commit-b'}):
                            with self.assertRaises(ValueError): ci.verify()
                        for invalid in ['0'*64, '']:
                            with patch.dict(os.environ, {'APPROVED_PLAN_HASH':invalid}):
                                with self.assertRaises(ValueError): ci.verify()
                        obj = json.loads((Path(tmp)/'plan.json').read_text())
                        obj['payload']['plan']['base_url']='https://changed.invalid'
                        (Path(tmp)/'plan.json').write_text(json.dumps(obj))
                        with self.assertRaises(ValueError): ci.verify()

    def test_paths_stay_in_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'examples').mkdir()
            (root/'examples'/'ok.xlsx').write_bytes(b'placeholder')
            (root/'outside.xlsx').write_bytes(b'placeholder')
            self.assertEqual(ci.approved_source('examples/ok.xlsx',root).name,'ok.xlsx')
            for value in ['outside.xlsx','examples/../outside.xlsx','examples/no.xlsx']:
                with self.assertRaises(ValueError): ci.approved_source(value,root)

    def test_custom_requires_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ci, 'PLAN_DIR', Path(tmp)):
                with patch.dict(os.environ, {'TEST_MODE':'custom','TEST_BASE_URL':''}):
                    with self.assertRaises(ValueError): ci.prepare()
