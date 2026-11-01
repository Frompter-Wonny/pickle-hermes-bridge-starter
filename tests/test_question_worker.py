import tempfile
import unittest
from pathlib import Path
from bridge.inbox import Inbox
from bridge.question_worker import Worker, Hermes, response_json
from bridge.store import Store
from bridge.permission_phrases import save as save_permission_rules


class FakeHermes:
    def __init__(self,approved=True):self.approved=approved;self.calls=[]
    def verify(self,q,nonce):self.calls.append('verify');return self.approved
    def answer(self,q):self.calls.append('answer');return 'approved fixture preference'


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'db')
        save_permission_rules(self.tmp.name,{'version':1,'following_phrases':['그건 Hermes 비서한테 물어봐'],'direct_templates':['Hermes 비서한테 {question} 물어봐줘']})
        self.i=Inbox(self.s);self.cap=self.i.create_channel()
        self.id=self.i.submit(self.cap,'one','fictional preference?');self.q=self.i.pending()[0]
    def tearDown(self):self.tmp.cleanup()

    def test_no_visual_authorization_never_calls_answer_model(self):
        r=FakeHermes(False);w=Worker(self.s,r);w.process(self.q)
        self.assertEqual(r.calls,['verify']);self.assertEqual(self.i.result(self.cap,self.id)['status'],'denied')
        self.assertEqual(self.s.summary()['questions'],0)

    def test_one_verified_question_answered_once_even_after_worker_restart(self):
        r=FakeHermes();Worker(self.s,r).process(self.q);Worker(self.s,r).process(self.q)
        self.assertEqual(r.calls,['verify','answer'])
        self.assertEqual(self.i.result(self.cap,self.id)['answer'],'approved fixture preference')

    def test_revocation_during_search_prevents_release(self):
        r=FakeHermes();original=r.answer
        def revoke(q):self.i.deny(self.id);return original(q)
        r.answer=revoke;Worker(self.s,r).process(self.q)
        self.assertEqual(self.i.result(self.cap,self.id)['status'],'denied')

    def test_model_output_must_be_one_json_object(self):
        self.assertEqual(response_json('```json\n{"answer":"fixture"}\n```')['answer'],'fixture')
        for text in ['banner {"answer":"x"}','["x"]','{"answer":"x"} extra']:
            with self.assertRaises(ValueError):response_json(text)

    def test_visual_proof_requires_exact_question_marker_nonce_and_permission(self):
        good={'approved':True,'scope_matches_question':True,'observed_question':'fixture?','observed_marker':'BRIDGE-Q:nonce',
              'observed_permission':'그건 Hermes 비서한테 물어봐','nonce':'nonce'}
        r=Hermes(self.tmp.name)
        r.run=lambda *a,**kw:good.copy()
        self.assertTrue(r.verify('fixture?','nonce'))
        for key,value in [('approved','true'),('observed_question','different?'),('observed_marker','BRIDGE-Q:old'),
                          ('nonce','old'),('observed_permission','허락하지 마')]:
            r.run=lambda *a,**kw:dict(good,**{key:value})
            self.assertFalse(r.verify('fixture?','nonce'))

    def test_notification_failure_never_retries_or_revokes_completed_answer(self):
        calls=[]
        def ambiguous(status):calls.append(status);raise TimeoutError()
        w=Worker(self.s,FakeHermes(),ambiguous);w.process(self.q);w.notify(self.id,'completed')
        self.assertEqual(calls,['completed'])
        self.assertEqual(self.i.result(self.cap,self.id)['status'],'completed')
        with self.s.db() as db:
            self.assertEqual(db.execute('SELECT status FROM inbox_notifications').fetchone()[0],'unknown')

    def test_direct_request_counts_as_scoped_permission_not_a_second_reply(self):
        evidence={'approved':True,'authorization_mode':'direct','scope_matches_question':True,
                  'observed_question':'fixture?','observed_marker':'BRIDGE-Q:nonce',
                  'observed_permission':'Hermes 비서한테 fixture 언제인지 물어봐줘','nonce':'nonce'}
        r=Hermes(self.tmp.name);r.run=lambda *a,**kw:evidence.copy()
        self.assertTrue(r.verify('fixture?','nonce'))
        r.run=lambda *a,**kw:dict(evidence,scope_matches_question=False)
        self.assertFalse(r.verify('fixture?','nonce'))
        r.run=lambda *a,**kw:dict(evidence,observed_permission='내가 알아서 할게')
        self.assertFalse(r.verify('fixture?','nonce'))

    def test_same_direct_command_cannot_be_replayed_with_another_request(self):
        r=FakeHermes();r.last_proof={'authorization_mode':'direct','observed_permission':'Hermes 비서한테 fixture 물어봐줘'}
        w=Worker(self.s,r);w.process(self.q)
        next_id=self.i.submit(self.cap,'replay','different private question?')
        w.process(next(q for q in self.i.pending() if q['id']==next_id))
        self.assertEqual(r.calls,['verify','answer','verify'])
        self.assertEqual(self.i.result(self.cap,next_id)['status'],'denied')


if __name__=='__main__':unittest.main()
