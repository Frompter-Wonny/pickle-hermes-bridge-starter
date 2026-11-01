import json,tempfile,unittest
from pathlib import Path
from tools.enable_app_launch import enable

class LaunchOptInTests(unittest.TestCase):
    def test_consent_required_and_existing_settings_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.runtime').mkdir();p=root/'.runtime/delivery_preferences.json';p.write_text('{"native_window_restore_consent":true}');p.chmod(0o600);app=root/'Pickle.app';app.mkdir()
            with self.assertRaises(ValueError):enable(root,str(app))
            enable(root,str(app),True);v=json.loads(p.read_text());self.assertTrue(v['native_app_launch_consent']);self.assertFalse(v['native_launch_warmup_consent']);self.assertTrue(v['native_window_restore_consent']);self.assertEqual(p.stat().st_mode&0o777,0o600)
    def test_invalid_app_path_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):enable(d,'/missing/Pickle.app',True)

    def test_brief_activation_is_separate_explicit_optin(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'.runtime').mkdir();p=root/'.runtime/delivery_preferences.json';p.write_text('{}');p.chmod(0o600);app=root/'Pickle.app';app.mkdir()
            enable(root,str(app),True,allow_brief_activation=True)
            self.assertTrue(json.loads(p.read_text())['native_launch_warmup_consent'])
