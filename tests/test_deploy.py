import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge import deploy


class DeployTests(unittest.TestCase):
    def test_application_install_moves_private_state_once_without_copying_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'Documents/project';installed=base/'Application Support/PickleHermesBridge'
            (source/'bridge').mkdir(parents=True);(source/'bridge/__init__.py').write_text('')
            (source/'docs/fixtures').mkdir(parents=True);(source/'docs/fixtures/test.md').write_text('fiction only')
            (source/'README.md').write_text('fixture project')
            state=source/'.runtime';state.mkdir(mode=0o700)
            private=state/'ngrok.yml';private.write_text('fixture secret');private.chmod(0o600);inode=private.stat().st_ino
            vault=base/'private-vault';vault.mkdir();(vault/'private.md').write_text('never deploy')
            (state/'question_sources.json').write_text(json.dumps({'fixture':str(source/'docs/fixtures'),'vault':str(vault)}))
            with patch.multiple(deploy,ROOT=source,STATE=state,INSTALL_ROOT=installed),patch.object(deploy,'live',return_value=None):
                deploy.main();deploy.main()
            self.assertTrue(state.is_symlink());self.assertEqual(state.resolve(),(installed/'.runtime').resolve())
            self.assertEqual((state/'ngrok.yml').stat().st_ino,inode)
            self.assertEqual((state/'ngrok.yml').stat().st_mode&0o777,0o600)
            self.assertFalse((installed/'private-vault').exists())
            cfg=json.loads((state/'question_sources.json').read_text())
            self.assertEqual(cfg['vault'],str(vault));self.assertEqual(cfg['fixture'],str(installed/'docs/fixtures'))

    def test_live_state_is_never_moved(self):
        with patch.object(deploy,'live',return_value={'pid':1}):
            with self.assertRaises(SystemExit):deploy.main()


if __name__=='__main__':unittest.main()
