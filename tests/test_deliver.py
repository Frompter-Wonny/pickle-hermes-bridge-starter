import json
import tempfile
import time
import unittest
from pathlib import Path
from bridge.deliver import prepare,task_status
from bridge.handoff import Handoffs
from bridge.store import Store,Denied


class DeliverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=self.root/'.runtime';self.state.mkdir(mode=0o700)
        self.h=Handoffs(Store(self.state/'bridge.sqlite3'))
        self.cap=self.h.create('fixture only','fixture user request','fixture-exact-job')
        self.file=self.state/'task.json';self.file.write_text(json.dumps({'capability':self.cap}));self.file.chmod(0o600)
        self.preferences=self.state/'delivery_preferences.json'
        self.preferences.write_text(json.dumps({'native_clipboard_consent':True,'input_method':'context_paste','source':'fixture explicit consent'}))

    def tearDown(self):self.temp.cleanup()

    def test_runner_grants_only_exact_task_and_keeps_query_private(self):
        folder,query=prepare(self.root,self.file)
        a=json.loads((self.state/'delivery_authorization.json').read_text())
        self.assertEqual(a['request_ids'],['fixture-exact-job']);self.assertEqual(a['request_prefixes'],[])
        self.assertTrue(time.time()<a['expires']<=time.time()+900)
        self.assertEqual(a['mode'],'background_only')
        self.assertEqual(query.stat().st_mode&0o777,0o600)
        self.assertEqual(folder.stat().st_mode&0o777,0o700)
        self.assertIn(self.cap,query.read_text())

    def test_missing_consent_world_readable_file_and_completed_task_refused(self):
        self.file.chmod(0o644)
        with self.assertRaises(Denied):prepare(self.root,self.file)
        self.file.chmod(0o600)
        self.preferences.write_text(json.dumps({'input_method':'context_paste'}))
        with self.assertRaises(Denied):prepare(self.root,self.file)
        self.preferences.write_text(json.dumps({'native_clipboard_consent':True,'input_method':'context_paste'}))
        self.h.complete(self.cap,'completed','fixture done')
        with self.assertRaises(Denied):prepare(self.root,self.file)
        self.assertFalse((self.state/'delivery_authorization.json').exists())

    def test_uncertain_existing_delivery_is_not_restarted(self):
        (self.state/('delivery-'+self.h.digest(self.cap)+'.json')).write_text('{"status":"sending"}')
        with self.assertRaises(Denied):prepare(self.root,self.file)

    def test_prepared_unsent_delivery_uses_read_only_resume(self):
        (self.state/('delivery-'+self.h.digest(self.cap)+'.json')).write_text('{"status":"prepared"}')
        folder,query=prepare(self.root,self.file)
        self.assertIn('resume(capability)',query.read_text())

    def test_process_exit_is_not_confused_with_actual_task_completion(self):
        status=task_status(self.root,self.file)
        self.assertEqual(status['task_status'],'pending');self.assertEqual(status['delivery_status'],'not_started')
        self.h.complete(self.cap,'needs_user','fixture needs approval')
        status=task_status(self.root,self.file)
        self.assertEqual(status['task_status'],'needs_user');self.assertEqual(status['result'],'fixture needs approval')
