import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from bridge.server import make_handler
from bridge.store import Denied, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def request(self):
        gid=self.store.grant('fixture-task','fictional preference?','fixture notes only')
        return {'client_request_id':'request-1','grant_id':gid,
                'task_id':'fixture-task','question':'fictional preference?'}

    def test_unapproved_and_modified_questions_denied(self):
        payload=self.request()
        for field,value in [('grant_id','forged'),('task_id','different'),('question','all notes?')]:
            with self.assertRaises(Denied):
                self.store.ask(dict(payload,**{field:value}))
        self.assertEqual(self.store.summary()['questions'],0)

    def test_concurrent_retry_consumes_grant_once(self):
        payload=self.request()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.store.ask(payload),range(12)))
        self.assertEqual(len({r['id'] for r in results}),1)
        self.assertEqual(self.store.summary()['questions'],1)
        with self.assertRaises(Denied):
            self.store.ask(dict(payload,client_request_id='second-request'))

    def test_revoke_blocks_answer_and_result(self):
        payload=self.request(); row=self.store.ask(payload)
        self.store.revoke(payload['grant_id'])
        with self.assertRaises(Denied): self.store.answer(row['id'],'not shared')
        with self.assertRaises(Denied): self.store.result(row['id'])

    def test_expired_grant_denied(self):
        payload=self.request()
        with self.store.db() as db:
            db.execute('UPDATE grants SET expires=?',(time.time()-1,))
        with self.assertRaises(Denied): self.store.ask(payload)

    def test_restart_keeps_answer_and_duplicate_mapping(self):
        payload=self.request(); row=self.store.ask(payload)
        self.store.answer(row['id'],'approved fixture answer')
        after=Store(self.store.path)
        self.assertEqual(after.ask(payload)['id'],row['id'])
        self.assertEqual(after.result(row['id'])['answer'],'approved fixture answer')

    def test_rules_persist_and_cancel(self):
        rule=self.store.rule('fixture-research','use fictional data only','trusted operator test')
        task=self.store.task('task-1',rule,'find fictional museums')
        self.assertEqual(Store(self.store.path).tasks()[0]['id'],task['id'])
        self.store.disable_rule(rule)
        with self.assertRaises(Denied): self.store.task('task-2',rule,'next task')
        self.store.task_update(task['id'],'accepted')
        self.store.task_update(task['id'],'completed','synthetic result')
        self.assertEqual(self.store.tasks(),[])

    def test_task_never_grants_question_access(self):
        rule=self.store.rule('fixture','test','operator')
        task=self.store.task('task-1',rule,'test')
        with self.assertRaises(Denied):
            self.store.ask({'client_request_id':'q','grant_id':task['id'],
                            'task_id':task['id'],'question':'private data?'})

    def test_probe_requires_exact_actual_answer(self):
        pid=self.store.create_probe()
        first=self.store.ask_probe(pid,'fictional question')
        self.assertEqual(self.store.ask_probe(pid,'retry')['answer'],first['answer'])
        with self.assertRaises(Denied): self.store.confirm_probe(pid,'made up')
        self.assertEqual(self.store.confirm_probe(pid,first['answer'])['completed'],1)

    def test_telegram_probe_sent_once_and_ambiguous_failure_never_retried(self):
        pid=self.store.create_probe();self.store.ask_probe(pid,'synthetic')
        calls=[]
        def send(answer):calls.append(answer);return 42
        self.assertEqual(self.store.deliver_probe(pid,send)['message_id'],42)
        self.store.deliver_probe(pid,send)
        self.assertEqual(len(calls),1)
        other=self.store.create_probe();self.store.ask_probe(other,'synthetic')
        def fail(answer):raise OSError('ambiguous')
        with self.assertRaises(Denied):self.store.deliver_probe(other,fail)
        self.assertEqual(self.store.deliver_probe(other,send)['status'],'unknown')
        self.assertEqual(len(calls),1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state.sqlite3')
        self.servers=[]

    def tearDown(self):
        for server,thread in self.servers:
            server.shutdown(); server.server_close(); thread.join()
        self.tmp.cleanup()

    def server(self,public=True,telegram_probe=None):
        s=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,{'cloro':'c','hermes':'r'},public,telegram_probe))
        t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
        self.servers.append((s,t))
        return 'http://127.0.0.1:'+str(s.server_port)

    def call(self,url,data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        req=Request(url,json.dumps(data).encode() if data is not None else None,headers)
        try:
            with urlopen(req,timeout=3) as r: return r.status,json.load(r)
        except HTTPError as e:
            return e.code,json.load(e)

    def test_public_listener_never_exposes_queue_or_grants(self):
        base=self.server()
        for path in ['/v1/tasks/pending','/v1/questions/guess','/admin','/v1/grants']:
            self.assertEqual(self.call(base+path,token='c')[0],404)
        self.assertEqual(self.call(base+'/v1/questions',{'approved':True},'c')[0],404)
        self.assertFalse(self.call(base+'/health')[1]['vault_connected'])

    def test_api_probe_round_trip(self):
        base=self.server();pid=self.store.create_probe()
        code,body=self.call(base+'/probe/'+pid+'/api',{'question':'fictional only'})
        self.assertEqual(code,200)
        self.assertEqual(self.call(base+body['confirm_url'],{'answer':'wrong'})[0],403)
        self.assertEqual(self.call(base+body['confirm_url'],{'answer':body['answer']})[1]['status'],'confirmed')

    def test_short_handoff_fetch_then_full_json_round_trip(self):
        import hashlib
        base=self.server();pid=self.store.create_probe()
        code,body=self.call(base+'/t/'+pid)
        self.assertEqual(code,200)
        task=body['task']
        self.assertEqual(body['task_sha256'],hashlib.sha256(json.dumps(task,ensure_ascii=False,sort_keys=True).encode()).hexdigest())
        self.assertEqual(task['mode'],'synthetic_only')
        code,response=self.call(base+task['request']['path'],task['request']['body'])
        self.assertEqual(code,200)
        self.assertEqual(self.call(base+response['confirm_url'],{'answer':response['answer']})[0],200)
        self.assertEqual(self.call(base+'/t/nonexistent')[0],403)

    def test_public_telegram_route_allows_one_fixed_synthetic_delivery(self):
        pid=self.store.create_probe();other=self.store.create_probe();sent=[]
        def deliver(answer):sent.append(answer);return 9
        base=self.server(telegram_probe={'probe_id':pid,'deliver':deliver})
        self.assertEqual(self.call(base+'/probe/'+other+'/telegram',{'question':'other'})[0],403)
        payload={'question':'do not forward this arbitrary text'}
        first=self.call(base+'/probe/'+pid+'/telegram',payload)
        self.assertEqual(first[0],200)
        self.assertEqual(first[1]['message_id'],9)
        self.call(base+'/probe/'+pid+'/telegram',payload)
        self.assertEqual(len(sent),1)
        self.assertNotIn(payload['question'],sent[0])

    def test_poll_trial_empty_then_new_task_and_exact_result(self):
        base=self.server();trial=self.store.create_poll_trial();url=base+'/poll/'+trial
        code,body=self.call(url)
        self.assertEqual(code,200);self.assertIsNone(body['task'])
        self.assertFalse(body['stop_after_this_run'])
        expected=self.store.queue_trial_task(trial)
        code,body=self.call(url)
        self.assertEqual(body['task']['code'],expected)
        self.assertEqual(self.call(base+body['result_url'],{'result':'wrong'})[0],403)
        self.assertEqual(self.call(base+body['result_url'],{'result':expected})[0],200)
        self.assertTrue(self.call(url)[1]['stop_after_this_run'])

    def test_auth_and_grant_separate_and_roles_isolated(self):
        base=self.server(False)
        payload={'client_request_id':'c1','grant_id':'fake','task_id':'t1','question':'test'}
        self.assertEqual(self.call(base+'/v1/questions',payload)[0],403)
        self.assertEqual(self.call(base+'/v1/questions',payload,'c')[0],403)
        payload['grant_id']=self.store.grant('t1','test','fixture')
        self.assertEqual(self.call(base+'/v1/questions',payload,'r')[0],403)
        self.assertEqual(self.call(base+'/v1/questions',payload,'c')[0],202)
        self.assertEqual(self.call(base+'/v1/tasks',{},'c')[0],403)
        self.assertEqual(self.call(base+'/v1/tasks/pending',token='r')[0],403)

    def test_revocation_applies_over_http(self):
        base=self.server(False)
        gid=self.store.grant('t','q','fixture')
        code,body=self.call(base+'/v1/questions',{'client_request_id':'c','grant_id':gid,'task_id':'t','question':'q'},'c')
        self.assertEqual(code,202)
        self.store.answer(body['request_id'],'approved synthetic answer')
        self.assertEqual(self.call(base+body['result_url'],token='c')[1]['answer'],'approved synthetic answer')
        self.store.revoke(gid)
        self.assertEqual(self.call(base+body['result_url'],token='c')[0],403)


if __name__=='__main__':
    unittest.main()
