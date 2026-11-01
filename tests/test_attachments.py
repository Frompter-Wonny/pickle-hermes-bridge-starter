import json
import tempfile
import unittest
from pathlib import Path
from bridge.attachments import Attachments
from bridge.inbox import Inbox
from bridge.store import Store, Denied


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.store=Store(self.root/'db');self.inbox=Inbox(self.store)
        self.cap=self.inbox.create_channel();self.files=Attachments(self.store)
        self.allowed=self.root/'approved';self.allowed.mkdir()
        (self.allowed/'fixture.md').write_text('fictional file')
        self.policy={'enabled':True,'destination':'pickle_own_chat','channel_digest':self.inbox.digest(self.cap),
                     'collections':[{'id':'fixture','root':str(self.allowed),'filename_pattern':'.*',
                                     'extensions':['.md'],'recursive':True}]}
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):self.files.policy_path.write_text(json.dumps(self.policy))
    def submit(self):
        fid=self.files.listed(self.cap)[0]['id']
        return self.files.submit(self.cap,'one',fid)

    def test_no_policy_or_wrong_channel_cannot_list(self):
        other=self.inbox.create_channel()
        with self.assertRaises(Denied):self.files.listed(other)
        self.files.policy_path.unlink()
        with self.assertRaises(Denied):self.files.listed(self.cap)

    def test_catalog_never_exposes_paths_or_follows_symlinks(self):
        outside=self.root/'private.md';outside.write_text('not allowed')
        (self.allowed/'escape.md').symlink_to(outside)
        (self.allowed/'secret-directory').symlink_to(self.root,target_is_directory=True)
        listed=self.files.listed(self.cap)
        self.assertEqual([x['name'] for x in listed],['fixture.md'])
        self.assertNotIn('path',listed[0])
        with self.assertRaises(ValueError):self.files.submit(self.cap,'bad','../private.md')

    def test_staged_request_idempotent_but_different_file_conflicts(self):
        qid=self.submit();self.assertEqual(qid,self.submit());self.assertFalse(self.files.pending())
        (self.allowed/'second.md').write_text('fixture')
        other=next(x['id'] for x in self.files.listed(self.cap) if x['name']=='second.md')
        with self.assertRaises(Denied):self.files.submit(self.cap,'one',other)
        self.files.activate(self.cap,qid);self.assertEqual(len(self.files.pending()),1)

    def test_revoke_before_activation_and_wrong_cap_denied(self):
        qid=self.submit();other=self.inbox.create_channel()
        with self.assertRaises(Denied):self.files.get(qid,other)
        self.policy['enabled']=False;self.save()
        with self.assertRaises(Denied):self.files.activate(self.cap,qid)

    def test_revoke_after_queue_never_calls_model_or_uploader(self):
        qid=self.submit();self.files.activate(self.cap,qid);q=self.files.pending()[0]
        self.policy['enabled']=False;self.save()
        self.files.process(q,type('NoTools',(),{})())
        self.assertEqual(self.files.get(qid)['status'],'failed')

    def test_unverified_marker_never_uploads(self):
        qid=self.submit();self.files.activate(self.cap,qid)
        class Hermes:
            def verify_attachment(self,*args):return False
            def attach(self,*args):raise AssertionError('must not upload')
        self.files.process(self.files.pending()[0],Hermes())
        self.assertEqual(self.files.get(qid)['status'],'denied')

    def test_ambiguous_send_is_not_retried_on_restart_or_new_id(self):
        qid=self.submit();self.files.activate(self.cap,qid);q=self.files.pending()[0]
        files=self.files;calls=[]
        class Hermes:
            def verify_attachment(self,*args):return True
            def attach(self,qid):
                calls.append(qid);files.status(qid,'sending');raise TimeoutError()
        self.files.process(q,Hermes());self.files.process(q,Hermes())
        self.assertEqual(calls,[qid]);self.assertEqual(self.files.get(qid)['status'],'sending')
        with self.assertRaises(Denied):self.files.submit(self.cap,'different',q['file_id'])

    def test_unicode_filename_normalization(self):
        import unicodedata
        p=self.allowed/unicodedata.normalize('NFD','테스트.md');p.write_text('fixture')
        self.assertIn('테스트.md',[x['name'] for x in self.files.listed(self.cap)])

    def test_explicit_manifest_does_not_enumerate_or_allow_path_escape(self):
        from unittest.mock import patch
        rule=self.policy['collections'][0]
        rule['files']=['fixture.md','../private.md','/etc/hosts']
        (self.root/'private.md').write_text('outside')
        self.save()
        with patch.object(Path,'iterdir',side_effect=PermissionError('directory listing unavailable')):
            self.assertEqual([x['name'] for x in self.files.listed(self.cap)],['fixture.md'])

    def test_refresh_keeps_existing_scope_and_finds_new_matching_file(self):
        from bridge.attachment_policy import refresh
        self.policy['collections'][0]['files']=[];self.save()
        (self.allowed/'second.md').write_text('new approved source')
        (self.allowed/'unapproved.txt').write_text('excluded')
        self.assertEqual(refresh(self.files.policy_path),2)
        after=json.loads(self.files.policy_path.read_text())
        for field in ['root','filename_pattern','extensions','recursive']:
            self.assertEqual(after['collections'][0][field],self.policy['collections'][0][field])
        self.assertEqual(self.files.policy_path.stat().st_mode & 0o777,0o600)
        self.assertEqual(len(self.files.listed(self.cap)),2)

    def test_file_route_stages_without_reading_or_returning_file_contents(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from bridge.server import make_handler
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,{},handoffs_enabled=True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        def call(path,data=None):
            request=Request(origin+path,None if data is None else json.dumps(data).encode(),{'Content-Type':'application/json'})
            with urlopen(request) as response:return json.load(response)
        try:
            base='/inbox/'+self.cap+'/files'
            catalog=call(base);fid=catalog['files'][0]['id']
            self.assertNotIn(str(self.root),json.dumps(catalog))
            result=call(base,{'client_request_id':'http','file_id':fid})
            self.assertEqual(self.files.pending(),[])
            self.assertEqual(result['marker'],'BRIDGE-F:'+result['id'])
            self.assertEqual(result['filename'],'fixture.md')
            call(result['activate_url'],{})
            self.assertEqual(call(result['result_url'])['status'],'queued')
            self.assertNotIn('fictional file',json.dumps(call(result['result_url'])))
            self.assertEqual(self.store.summary()['questions'],0)
        finally:server.shutdown();server.server_close();thread.join()

    def test_busy_delivery_leaves_request_queued_without_model_calls(self):
        import fcntl,os
        qid=self.submit();self.files.activate(self.cap,qid)
        fd=os.open(self.root/'delivery.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertFalse(self.files.process(self.files.pending()[0],object()))
            self.assertEqual(self.files.get(qid)['status'],'queued')
        finally:os.close(fd)

    def test_symlink_root_and_expired_request_fail_closed(self):
        qid=self.submit()
        with self.store.db() as db:db.execute('UPDATE attachment_requests SET created=0 WHERE id=?',(qid,))
        with self.assertRaises(Denied):self.files.activate(self.cap,qid)
        self.policy['collections'][0]['root']=str(self.root/'link')
        (self.root/'link').symlink_to(self.allowed,target_is_directory=True);self.save()
        with self.assertRaises(Denied):self.files.listed(self.cap)

if __name__=='__main__':unittest.main()
