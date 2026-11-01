import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from bridge.note_tools import Notes


class NoteToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        root=self.base/'allowed';root.mkdir();self.root=root
        (root/'profile.md').write_text('# Fixture\nPreference: bookbinding\nThird line\n')
        (self.base/'private.md').write_text('must not read')
        (root/'escape.md').symlink_to(self.base/'private.md')
        self.notes=Notes({'fixture':str(root)})
    def tearDown(self):self.tmp.cleanup()

    def test_search_returns_paths_only_then_scoped_line_read(self):
        result=self.notes.search('fixture','bookbinding',mode='content')
        self.assertEqual(result['paths'],['profile.md']);self.assertNotIn('Preference',str(result))
        self.assertEqual(self.notes.read('fixture','profile.md',2,1)['text'],'Preference: bookbinding')
        self.assertEqual(self.notes.search('fixture','profile')['paths'],['profile.md'])

    def test_symlinks_traversal_unknown_sources_and_non_notes_denied(self):
        (self.root/'credentials.json').write_text('{}')
        for path in ['../private.md','escape.md','credentials.json',str(self.base/'private.md')]:
            with self.assertRaises(ValueError):self.notes.read('fixture',path)
        with self.assertRaises(KeyError):self.notes.read('unknown','profile.md')
        self.assertEqual(self.notes.search('fixture','private')['paths'],[])

    def test_queries_cannot_become_shell_or_rg_options(self):
        self.assertEqual(self.notes.search('fixture','--files',mode='content')['paths'],[])
        self.assertEqual(self.notes.search('fixture','$(touch broken)',mode='content')['paths'],[])
        self.assertFalse((self.root/'broken').exists())

    def test_background_without_rg_preserves_search_and_path_boundary(self):
        with patch('bridge.note_tools.shutil.which',return_value=None),patch('bridge.note_tools.subprocess.run') as execute:
            self.assertEqual(self.notes.search('fixture','bookbinding',mode='content')['paths'],['profile.md'])
            self.assertEqual(self.notes.search('fixture','profile')['paths'],['profile.md'])
            self.assertEqual(self.notes.search('fixture','must not read',mode='content')['paths'],[])
            self.assertEqual(self.notes.search('fixture','--files',mode='content')['paths'],[])
            execute.assert_not_called()


if __name__=='__main__':unittest.main()
