import json,tempfile,unittest
from pathlib import Path
from tools.setup_local import initialize
from tools.check_public import check

class SetupTests(unittest.TestCase):
    def test_private_initialization_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);vault=root/'notes';vault.mkdir()
            binary=root/'fixture';binary.write_text('fixture');binary.chmod(0o700)
            state=initialize(root,vault,binary,'https://fixture.ngrok-free.dev','fake-test-value')
            self.assertEqual(state.stat().st_mode&0o777,0o700)
            for name in ['ngrok.yml','tunnel.json','question_sources.json','active_probe.json','bridge.sqlite3']:
                self.assertEqual((state/name).stat().st_mode&0o777,0o600)
            self.assertTrue(json.loads((state/'active_probe.json').read_text())['probe_path'].startswith('/probe/'))
            with self.assertRaises(ValueError):initialize(root,vault,binary,'https://fixture.ngrok-free.dev','new-fake-value')
            self.assertEqual(json.loads((state/'ngrok.yml').read_text())['authtoken'],'fake-test-value')
    def test_bad_origin_is_rejected_before_secret_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);binary=root/'fixture';binary.touch();binary.chmod(0o700)
            with self.assertRaises(ValueError):initialize(root,root,binary,'http://bad.example','fake-test-value')
            self.assertFalse((root/'.runtime').exists())
    def test_public_guard_flags_runtime_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.runtime').mkdir();(root/'.runtime/token.json').write_text('{}')
            (root/'state-link').symlink_to(root/'.runtime',target_is_directory=True)
            self.assertEqual(len(check(root)),2)
