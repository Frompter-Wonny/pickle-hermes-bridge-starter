import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.store import Store,Denied
from bridge.upload_local import LocalUpload,prepare,receipt,lookup_receipt
from tests.test_stage_local_file import staging


class LocalUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve()
        self.root=self.base/'UploadStaging';self.source=self.base/'image.jpg';self.source.write_bytes(b'fixture image')
        self.r=staging.stage(self.source,self.root);self.receipt=Path(self.r['receipt_path'])
        self.permission=self.base/'permission.txt';self.permission.write_text('Actual operator asks to send this fixture to Pickle.')
        self.permission.chmod(0o600)
        self.state=self.base/'state';self.store=Store(self.state/'db')
        self.task=self.base/'task.json';self.make(self.task,'first')
    def tearDown(self):self.tmp.cleanup()
    def make(self,path,request_id):
        return prepare(self.receipt,request_id,self.permission,path,self.root,'Test Volume')
    def uploader(self,path=None):return LocalUpload(self.store,path or self.task,self.root)

    def test_prepare_is_private_and_does_not_claim_or_upload(self):
        self.assertEqual(self.task.stat().st_mode&0o777,0o600)
        self.assertEqual(self.uploader().result()['status'],'not_started')
        self.assertEqual(self.uploader().resolve(self.uploader().qid)['path'],self.r['attachment_path'])
        with self.assertRaises(FileExistsError):self.make(self.task,'overwrite')

    def test_no_actual_user_source_cannot_prepare(self):
        self.permission.write_text('')
        with self.assertRaises(ValueError):self.make(self.base/'missing.json','missing')

    def test_file_and_receipt_tampering_fail_before_ui(self):
        u=self.uploader();Path(self.r['attachment_path']).write_bytes(b'changed')
        with self.assertRaises(Denied):u.resolve(u.qid)
        Path(self.r['attachment_path']).write_bytes(b'fixture image')
        self.receipt.write_text(self.receipt.read_text()+' ')
        with self.assertRaises(Denied):u.resolve(u.qid)

    def test_expired_or_changed_destination_task_denied(self):
        for key,value in [('expires',0),('destination','other_chat')]:
            data=json.loads(self.task.read_text());data[key]=value
            path=self.base/(key+'.json');path.write_text(json.dumps(data));path.chmod(0o600)
            u=self.uploader(path)
            with self.assertRaises(Denied):u.resolve(u.qid)

    def test_receipt_cannot_redirect_to_unrelated_file(self):
        data=json.loads(self.receipt.read_text());data['attachment_path']=str(self.source)
        self.receipt.write_text(json.dumps(data))
        with self.assertRaises(Denied):receipt(self.receipt,self.root)

    def test_attempt_and_ambiguous_send_cannot_be_replayed(self):
        u=self.uploader();u.begin();u.status(u.qid,'sent_unconfirmed')
        with self.assertRaises(Denied):u.begin()
        second=self.base/'second.json';self.make(second,'second')
        with self.assertRaises(Denied):self.uploader(second).begin()

    def test_generic_driver_uses_task_bound_volume_and_keeps_uncertain_state(self):
        u=self.uploader()
        def fail(*args,**kwargs):
            self.assertEqual(kwargs['root_volume_label'],'Test Volume')
            class Driver:
                def run(inner):u.status(u.qid,'sending');raise TimeoutError()
            return Driver()
        with patch('bridge.attachment_driver.Uploader',side_effect=fail):
            with self.assertRaises(TimeoutError):u.send(None,None,None)
        self.assertEqual(u.result()['status'],'sending')

    def test_preupload_failure_is_recorded_without_allowing_auto_retry(self):
        u=self.uploader()
        class Driver:
            def run(self):raise Denied('existing_draft')
        with patch('bridge.attachment_driver.Uploader',return_value=Driver()):
            with self.assertRaises(Denied):u.send(None,None,None)
        self.assertEqual(u.result()['status'],'failed_before_upload')
        with self.assertRaises(Denied):u.begin()

    def test_confirmation_requires_sent_state_and_private_actual_observation(self):
        u=self.uploader();proof=self.base/'proof.txt';proof.write_text('Visible outgoing attachment and assistant receipt observed.');proof.chmod(0o600)
        with self.assertRaises(Denied):u.confirm(proof)
        u.begin();u.status(u.qid,'sent_unconfirmed');u.confirm(proof)
        self.assertEqual(u.result()['status'],'confirmed')
        with self.assertRaises(Denied):u.begin()

    def test_lookup_identifies_previous_receipt_without_uploading_again(self):
        self.assertEqual(lookup_receipt(self.store,self.receipt,self.root),[])
        u=self.uploader();u.begin();u.status(u.qid,'sent_unconfirmed')
        result=lookup_receipt(self.store,self.receipt,self.root)
        self.assertEqual(result[0]['status'],'sent_unconfirmed')

if __name__=='__main__':unittest.main()
