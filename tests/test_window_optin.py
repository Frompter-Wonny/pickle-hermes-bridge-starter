import unittest,tempfile,json
from pathlib import Path
from tools.enable_window_recovery import enable

class WindowOptInTests(unittest.TestCase):
    def test_requires_consent_and_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.runtime';p.mkdir();p=p/'delivery_preferences.json';p.write_text('{"input_method":"context_paste"}');p.chmod(0o600)
            with self.assertRaises(ValueError):enable(d)
            enable(d,True);v=json.loads(p.read_text());self.assertTrue(v['native_window_restore_consent']);self.assertEqual(v['input_method'],'context_paste');self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_rejects_public_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'.runtime';p.mkdir();p=p/'delivery_preferences.json';p.write_text('{}');p.chmod(0o644)
            with self.assertRaises(ValueError):enable(d,True)
