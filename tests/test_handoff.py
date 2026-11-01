import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from bridge.handoff import Handoffs
from bridge.server import make_handler
from bridge.store import Store, Denied


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state.db')
        self.h=Handoffs(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_capability_isolated_expires_revokes_and_no_duplicate_task(self):
        cap=self.h.create('fictional work','trusted operator','one')
        self.assertNotIn('source',self.h.get(cap))
        self.assertEqual(Handoffs(Store(self.store.path)).get(cap)['status'],'pending')
        with self.assertRaises(Denied):self.h.get('forged')
        with self.assertRaises(Denied):self.h.create('duplicate','operator','one')
        self.h.revoke(cap)
        with self.assertRaises(Denied):self.h.get(cap)
        expired=self.h.create('expired','operator','two',ttl=.001)
        time.sleep(.01)
        with self.assertRaises(Denied):self.h.complete(expired,'completed','late')

    def test_results_are_idempotent_and_cannot_be_replaced(self):
        cap=self.h.create('work','operator','one')
        self.assertFalse(self.h.complete(cap,'completed','actual result')['duplicate'])
        self.assertTrue(self.h.complete(cap,'completed','actual result')['duplicate'])
        with self.assertRaises(Denied):self.h.complete(cap,'completed','altered result')
        with self.assertRaises(ValueError):self.h.complete(cap,'approved','invalid')
        self.assertEqual(self.h.get(cap)['result'],'actual result')

    def test_waiting_task_can_finish_after_clarification_but_terminal_result_is_immutable(self):
        cap=self.h.create('work awaiting a question','operator','resume-one')
        self.h.complete(cap,'needs_user','question one')
        self.assertTrue(self.h.complete(cap,'needs_user','question one')['duplicate'])
        self.h.complete(cap,'needs_user','question two')
        self.h.complete(cap,'completed','actual finished work')
        self.assertEqual(self.h.get(cap)['status'],'completed')
        with self.assertRaises(Denied):self.h.complete(cap,'needs_user','reopen')
        failed=self.h.create('other work','operator','failed-one')
        self.h.complete(failed,'failed','cannot finish')
        with self.assertRaises(Denied):self.h.complete(failed,'completed','late replacement')

    def test_expiry_and_revocation_still_block_a_waiting_task_resume(self):
        cap=self.h.create('waiting work','operator','revoked-wait')
        self.h.complete(cap,'needs_user','need clarification');self.h.revoke(cap)
        with self.assertRaises(Denied):self.h.complete(cap,'completed','not allowed')

    def test_http_opt_in_boundary_and_result_roundtrip(self):
        cap=self.h.create('fictional task','operator private provenance','one')
        for enabled in [False,True]:
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,{},handoffs_enabled=enabled))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            origin='http://127.0.0.1:'+str(server.server_port)
            try:
                if not enabled:
                    with self.assertRaises(HTTPError) as ctx:urlopen(origin+'/work/'+cap)
                    self.assertEqual(ctx.exception.code,404)
                    continue
                with urlopen(origin+'/work/'+cap) as r:task=json.load(r)
                self.assertEqual(task['task']['instruction'],'fictional task')
                self.assertNotIn('operator private provenance',json.dumps(task))
                req=Request(origin+task['result_url'],data=json.dumps({'status':'needs_user','result':'May I ask Hermes?'}).encode(),headers={'Content-Type':'application/json'})
                with urlopen(req) as r:self.assertEqual(json.load(r)['status'],'recorded')
                self.assertEqual(self.h.get(cap)['status'],'needs_user')
                with self.assertRaises(HTTPError) as ctx:urlopen(origin+'/v1/tasks/pending')
                self.assertEqual(ctx.exception.code,404)
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
