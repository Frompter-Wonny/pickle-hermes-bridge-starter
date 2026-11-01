import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.handoff import main,Handoffs
from bridge.store import Store


class HandoffFileTests(unittest.TestCase):
    def test_new_capability_file_is_private_and_not_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state';state.mkdir()
            (state/'active_probe.json').write_text(json.dumps({'public_url':'https://fixture.ngrok-free.dev/probe/fake','session_expires_at':time.time()+60}))
            instruction=root/'task.txt';instruction.write_text('fictional task only');output=root/'task.json'
            argv=['bridge.handoff','--state',str(state),'create','--instruction-file',str(instruction),
                  '--source','fixture user request','--request-id','fixture-1','--output-file',str(output)]
            response=io.BytesIO(b'{"handoffs_enabled":true}');stdout=io.StringIO()
            with patch('sys.argv',argv),patch('bridge.handoff.urlopen',return_value=response),contextlib.redirect_stdout(stdout):main()
            task=json.loads(output.read_text());self.assertIn('capability',task)
            self.assertNotIn(task['capability'],stdout.getvalue());self.assertNotIn(task['url'],stdout.getvalue())
            self.assertEqual(output.stat().st_mode&0o777,0o600)
            self.assertEqual(Handoffs(Store(state/'bridge.sqlite3')).get(task['capability'])['status'],'pending')
            argv[argv.index('fixture-1')]='fixture-2'
            with patch('sys.argv',argv),patch('bridge.handoff.urlopen',return_value=io.BytesIO(b'{"handoffs_enabled":true}')):
                with self.assertRaises(FileExistsError):main()
            with Store(state/'bridge.sqlite3').db() as db:self.assertEqual(db.execute('SELECT count(*) FROM handoffs').fetchone()[0],1)
