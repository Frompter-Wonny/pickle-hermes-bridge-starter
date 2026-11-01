import json,tempfile,unittest
from pathlib import Path
from tools.enable_native_delivery import enable

class NativeOptInTests(unittest.TestCase):
    def test_no_default_consent_and_existing_setting_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.runtime').mkdir(mode=0o700)
            with self.assertRaises(ValueError):enable(root)
            self.assertFalse((root/'.runtime/delivery_preferences.json').exists())
            file=enable(root,consent=True)
            self.assertEqual(file.stat().st_mode&0o777,0o600)
            self.assertEqual(json.loads(file.read_text())['mode'],'background_only')
            with self.assertRaises(FileExistsError):enable(root,consent=True)
