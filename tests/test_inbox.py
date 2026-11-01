import tempfile
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pathlib import Path
from bridge.inbox import Inbox
from bridge.store import Store, Denied
from bridge.server import make_handler


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db')
        self.i=Inbox(self.store);self.cap=self.i.create_channel()

    def tearDown(self):self.tmp.cleanup()

    def test_receipt_never_grants_access_and_changed_question_rejected(self):
        q=self.i.submit(self.cap,'one','fictional preference?')
        self.assertEqual(self.i.submit(self.cap,'one','fictional preference?'),q)
        self.assertEqual(self.i.result(self.cap,q),{'status':'awaiting_user_authorization'})
        with self.assertRaises(Denied):self.i.submit(self.cap,'one','all user notes?')
        with self.assertRaises(Denied):self.i.result(self.i.create_channel(),q)
        self.assertEqual(self.store.summary()['questions'],0)

    def test_verified_approval_binds_exact_question_then_returns_minimal_answer(self):
        q=self.i.submit(self.cap,'one','fictional preference?')
        with self.assertRaises(ValueError):self.i.approve(q,'')
        rid=self.i.approve(q,'fixture authenticated operator approval')
        self.assertEqual(self.store.result(rid)['question'],'fictional preference?')
        self.store.answer(rid,'fictional science museum')
        self.assertEqual(self.i.result(self.cap,q),{'status':'completed','answer':'fictional science museum'})
        with self.assertRaises(Denied):self.i.approve(q,'repeat')
        self.i.deny(q)
        self.assertEqual(self.i.result(self.cap,q),{'status':'denied'})
        with self.assertRaises(Denied):self.store.result(rid)

    def test_stale_questions_and_expired_or_revoked_channels_fail_closed(self):
        q=self.i.submit(self.cap,'one','fictional?')
        with self.store.db() as db:db.execute('UPDATE inbox_requests SET created=0 WHERE id=?',(q,))
        with self.assertRaises(Denied):self.i.approve(q,'late')
        self.assertEqual(self.i.result(self.cap,q)['status'],'expired')
        with self.store.db() as db:db.execute('UPDATE inbox_channels SET revoked=1')
        with self.assertRaises(Denied):self.i.submit(self.cap,'two','new')
        with self.assertRaises(Denied):self.i.result(self.cap,q)

    def test_untrusted_question_flood_is_bounded_without_ai_calls(self):
        for n in range(3):self.i.submit(self.cap,str(n),'fictional?')
        with self.assertRaises(Denied):self.i.submit(self.cap,'four','fictional?')

    def test_http_staging_requires_activation_and_cannot_approve_or_change_question(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,{},handoffs_enabled=True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        def post(path,body):
            req=Request(origin+path,json.dumps(body).encode(),{'Content-Type':'application/json'})
            with urlopen(req) as r:return json.load(r)
        try:
            receipt=post('/inbox/'+self.cap,{'client_request_id':'http','question':'fictional?','approved':True})
            self.assertEqual(self.i.pending(),[])
            self.assertEqual(receipt['marker'],'BRIDGE-Q:'+receipt['id'])
            post(receipt['activate_url'],{})
            self.assertEqual(self.i.pending()[0]['question'],'fictional?')
            self.assertEqual(self.i.result(self.cap,receipt['id'])['status'],'awaiting_user_authorization')
            self.assertEqual(self.store.summary()['questions'],0)
            with self.assertRaises(HTTPError) as ctx:post('/v1/grants',{'approved':True})
            self.assertEqual(ctx.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_channel_close_revokes_approved_request_and_pending_work(self):
        q=self.i.submit(self.cap,'close','fictional?');rid=self.i.approve(q,'fixture real user proof')
        self.i.close_channel(self.cap)
        self.assertEqual(self.i.pending(),[])
        with self.assertRaises(Denied):self.store.answer(rid,'must not release')
        with self.assertRaises(Denied):self.i.result(self.cap,q)


if __name__=='__main__':unittest.main()
