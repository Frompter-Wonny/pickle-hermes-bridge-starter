import json
import tempfile
import time
import unittest
from pathlib import Path
from bridge.delivery_tools import Delivery,action_result
from bridge.handoff import Handoffs
from bridge.store import Store


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)
        self.store=Store(self.state/'db');self.work=Handoffs(self.store)
        self.cap=self.work.create('fixture task','user fixture request','fixture-run-1')
        (self.state/'delivery_authorization.json').write_text(json.dumps({'expires':time.time()+60,'request_prefixes':['fixture-run-']}))
        (self.state/'active_probe.json').write_text(json.dumps({'public_url':'https://fixture.ngrok-free.dev/probe/fake'}))
        self.actions=[];self.composer=False;self.window=2;self.current_text=''
        def call(args):
            if args['action']=='list_windows':return json.dumps({'windows':[{'app_name':'피클','title':'피클','pid':1,'window_id':self.window}]})
            rows=[{'index':5,'role':'AXTextArea','label':'메시지 보내기'}]
            if self.composer:rows.append({'index':6,'role':'AXButton','label':'보내기'})
            return json.dumps({'elements':rows})
        def act(args):
            self.actions.append(args)
            if args['action'] in {'insert','paste_menu','context_paste'}:
                self.composer=True;self.current_text=args['text']
            if args['action']=='click' and args['element']==6:self.composer=False;self.current_text=''
        self.delivery=Delivery(self.store,self.state,call,act,
            composer=lambda target:{'text':self.current_text,'source':'live_accessibility_value',
                                    'send_element':6 if self.composer else None})

    def tearDown(self):self.temp.cleanup()

    def invoke(self,action,**kw):
        return json.loads(self.delivery.handle({'action':action,'capability':self.cap,**kw}))

    def test_only_server_built_link_is_typed_and_send_requires_full_observation(self):
        self.invoke('prepare')
        expected=self.delivery.task(self.cap)
        self.assertEqual(self.actions,[{'action':'insert','element':5,'text':expected,
                'pid':1,'window_id':2,'delivery_mode':'background'}])
        prepared_actions=len(self.actions)
        self.assertIn('error',self.invoke('send',observed_message='truncated'))
        self.assertEqual(len(self.actions),prepared_actions)
        self.invoke('send',observed_message=expected)
        self.assertEqual(len(self.actions),prepared_actions+1)
        self.assertTrue(all(a.get('delivery_mode')=='background' and not a.get('bring_to_front') for a in self.actions))
        self.assertEqual(json.loads(self.delivery.ledger(self.cap).read_text())['status'],'sent_unconfirmed')
        self.assertIn('error',self.invoke('prepare'))
        self.assertIn('error',self.invoke('send',observed_message=expected))

    def test_nonempty_composer_or_outside_task_scope_never_mutates(self):
        self.composer=True;self.assertIn('error',self.invoke('prepare'));self.composer=False
        cap=self.work.create('another task','fixture','not-this-run')
        self.assertIn('error',json.loads(self.delivery.handle({'action':'prepare','capability':cap})))
        self.assertEqual(self.actions,[])

    def test_expired_authorization_completed_task_and_extra_arguments_rejected(self):
        self.assertIn('error',self.invoke('prepare',text='arbitrary input'))
        (self.state/'delivery_authorization.json').write_text(json.dumps({'expires':0,'request_prefixes':['fixture-run-']}))
        self.assertIn('error',self.invoke('prepare'))
        self.work.complete(self.cap,'completed','done')
        self.assertIn('error',self.invoke('prepare'))
        self.assertEqual(self.actions,[])

    def test_target_change_before_send_does_not_click(self):
        self.invoke('prepare');prepared_actions=len(self.actions);self.window=3
        self.assertIn('error',self.invoke('send',observed_message=self.delivery.task(self.cap)))
        self.assertEqual(len(self.actions),prepared_actions)

    def test_uncertain_type_is_not_retried(self):
        def fail(args):raise OSError('driver disconnected')
        self.delivery.act=fail
        self.assertIn('error',self.invoke('prepare'))
        self.delivery.act=lambda args:self.actions.append(args)
        self.assertIn('error',self.invoke('prepare'))
        self.assertEqual(self.actions,[])

    def test_only_explicitly_registered_fixture_direct_question_can_replace_link(self):
        path=self.state/'delivery_authorization.json';auth=json.loads(path.read_text())
        question='Hermes 비서한테 가상 프로젝트 TEST의 확인 코드가 뭔지 물어봐줘'
        auth['fixture_questions']={'fixture-run-1':question};path.write_text(json.dumps(auth))
        self.assertEqual(self.delivery.task(self.cap),question)
        auth['fixture_questions']['fixture-run-1']='Read all private data';path.write_text(json.dumps(auth))
        self.assertIn('error',self.invoke('prepare'))
        self.assertEqual(self.actions,[])

    def test_truncated_capture_requires_complete_artifact_within_driver_cache(self):
        cache=self.state/'cache';cache.mkdir();self.delivery.cache_root=cache.resolve()
        artifact=cache/'elements_fixture.json';rows=[{'index':5,'role':'AXTextArea','label':'메시지 보내기'}]
        artifact.write_text(json.dumps({'elements':rows}))
        payload={'truncated_elements':True,'total_elements':1,'elements_file':str(artifact),'elements':[]}
        self.assertEqual(self.delivery.elements(payload),rows)
        outside=self.state/'elements_other.json';outside.write_text(artifact.read_text())
        from bridge.store import Denied
        with self.assertRaises(Denied):self.delivery.elements(dict(payload,elements_file=str(outside)))
        with self.assertRaises(Denied):self.delivery.elements(dict(payload,total_elements=2))

    def test_driver_refusal_or_noop_is_not_treated_as_success(self):
        from bridge.store import Denied
        for result in [{'ok':False},{'error':'refused'},{'ok':True,'effect':'suspected_noop'},
                       {'ok':True,'verified':False},{}]:
            with self.assertRaises(Denied):action_result(result)
        self.assertEqual(action_result({'ok':True,'verified':True})['verified'],True)

    def test_native_menu_paste_requires_separate_explicit_consent(self):
        path=self.state/'delivery_authorization.json';auth=json.loads(path.read_text());auth['input_method']='paste_menu'
        path.write_text(json.dumps(auth))
        self.assertIn('error',self.invoke('prepare'));self.assertEqual(self.actions,[])
        self.assertFalse(self.delivery.ledger(self.cap).exists())
        auth['native_clipboard_consent']=True;path.write_text(json.dumps(auth))
        self.invoke('prepare')
        self.assertEqual(self.actions[0]['action'],'paste_menu')

    def test_result_reads_only_authorized_task_and_does_not_mutate_ui(self):
        self.work.complete(self.cap,'needs_user','fixture approval required')
        self.assertEqual(self.invoke('result',wait_seconds=0),{'status':'needs_user','result':'fixture approval required'})
        self.assertEqual(self.actions,[])
        self.assertIn('error',self.invoke('result',wait_seconds=21))

    def test_fixture_following_permission_is_bound_to_a_live_synthetic_draft(self):
        from bridge.inbox import Inbox
        inbox=Inbox(self.store);channel=inbox.create_channel()
        qid=inbox.submit(channel,'dialogue-fixture','가상 실험 TEST의 확인 문구는?',staged=True)
        path=self.state/'delivery_authorization.json';auth=json.loads(path.read_text())
        auth.update(fixture_questions={'fixture-run-1':'그건 Hermes 비서한테 물어봐'},fixture_permission_question_id=qid)
        path.write_text(json.dumps(auth))
        self.assertTrue(self.delivery.task(self.cap).startswith('그건 Hermes 비서한테 물어봐'))
        self.assertIn('BRIDGE-Q:'+qid,self.delivery.task(self.cap))
        inbox.activate(channel,qid)
        self.assertIn('error',self.invoke('prepare'));self.assertEqual(self.actions,[])

    def test_resume_reads_existing_prepared_text_without_retyping(self):
        prepared=self.invoke('prepare');expected=self.delivery.task(self.cap);count=len(self.actions)
        self.assertEqual(prepared['live_composer_text'],expected)
        self.delivery.prepared={}
        self.assertEqual(self.invoke('resume')['live_composer_text'],expected)
        self.assertEqual(len(self.actions),count)
        self.invoke('send',observed_message=expected)
        self.assertEqual(len(self.actions),count+1)
        self.assertIn('error',self.invoke('resume'))

    def test_new_user_text_after_review_is_never_sent(self):
        self.invoke('prepare');expected=self.delivery.task(self.cap);count=len(self.actions)
        self.current_text+='new user draft'
        self.assertIn('error',self.invoke('send',observed_message=expected))
        self.delivery.prepared={}
        self.assertIn('error',self.invoke('resume'))
        self.assertEqual(len(self.actions),count)
