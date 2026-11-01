import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/pickle-delegation/scripts/stage_local_file.py'
spec = importlib.util.spec_from_file_location('stage_local_file', SCRIPT)
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


class StageLocalFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        cache = self.base / '.cache' / 'telegram'
        cache.mkdir(parents=True)
        self.source = cache / 'phone-photo.jpg'
        self.data = b'\xff\xd8\xff' + bytes(range(256)) * 20
        self.source.write_bytes(self.data)
        self.root = self.base / 'UploadStaging'

    def tearDown(self):
        self.temp.cleanup()

    def test_hidden_source_is_copied_without_changing_bytes_or_original(self):
        before = self.source.stat()
        result = staging.stage(self.source, self.root)
        target = Path(result['attachment_path'])
        self.assertEqual(target.read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(staging.fingerprint(self.source.stat()), staging.fingerprint(before))
        self.assertFalse(any(p.startswith('.') for p in target.parts))
        for path, mode in [(self.root, 0o700), (target.parent, 0o700),
                           (target, 0o600), (Path(result['receipt_path']), 0o600)]:
            self.assertEqual(path.stat().st_mode & 0o777, mode)

    def test_two_attempts_never_overwrite_each_other(self):
        first = staging.stage(self.source, self.root)
        second = staging.stage(self.source, self.root)
        self.assertNotEqual(first['attachment_path'], second['attachment_path'])
        self.assertEqual(first['sha256'], second['sha256'])

    def test_default_uses_plain_home_folder_not_library_or_hidden_cache(self):
        with patch.object(staging.Path, 'home', return_value=self.base):
            result = staging.stage(self.source)
        target = Path(result['attachment_path'])
        self.assertEqual(target.parent.parent, self.base / 'PickleUploadStaging')
        self.assertNotIn('Library', target.relative_to(self.base).parts)

    def test_hidden_destination_and_nonprivate_root_are_rejected(self):
        with self.assertRaises(ValueError):staging.stage(self.source, self.base / '.cache' / 'stage')
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        with self.assertRaises(ValueError):staging.stage(self.source, self.root)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)

    def test_failed_verification_removes_only_its_copy(self):
        with patch.object(staging, 'digest_file', return_value='mismatch'):
            with self.assertRaises(ValueError):staging.stage(self.source, self.root)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), self.data)


if __name__ == '__main__':unittest.main()
