import tempfile
import unittest
from pathlib import Path
from tools.check_public import check

class PublicationPrivacyTests(unittest.TestCase):
    def test_personal_name_in_text_or_path_is_rejected(self):
        private_name=''.join(chr(x) for x in [0xd074,0xb85c,0xb85c])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'README.md';p.write_text(private_name)
            self.assertTrue(check(root))
            p.unlink();(root/(private_name+'.md')).write_text('generic content')
            self.assertTrue(check(root))

    def test_regular_korean_path_word_and_generic_roles_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'README.md').write_text('Hermes 비서와 Pickle 비서. 지정 경로로 전달합니다.')
            self.assertEqual(check(root),[])

    def test_screenshots_remain_denied_without_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'demo.jpg').write_bytes(b'not reviewed')
            self.assertTrue(check(root))

if __name__=='__main__':unittest.main()
