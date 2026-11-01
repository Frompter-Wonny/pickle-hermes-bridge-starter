"""Deliver only operator-authorized task links to the actual Pickle chat.

The facade constructs every mutating operation. It is not a general approval
unlock: the private authorization file names one explicit request-id prefix.
"""
import hashlib
import json
import os
import time
from pathlib import Path
from .handoff import Handoffs
from .screen_tools import Screen, name
from .store import Denied


class Delivery:
    def __init__(self, store, state, call, act, cache_root=None, diagnose=None, composer=None, recover=None):
        self.handoffs=Handoffs(store);self.state=Path(state)
        self.call=call;self.act=act;self.prepared={}
        self.cache_root=Path(cache_root or Path.home()/'.hermes/cache/computer_use').resolve()
        self.diagnose=diagnose
        self.composer=composer
        self.screen=Screen(self.call,recover=recover)

    def prepared_capture(self,target,expected):
        raw=self.capture(target,mode='som')[1]
        if self.composer is None:raise Denied('live_composer_reader_required')
        actual=self.composer(target)
        if actual['text']!=expected:raise Denied('composer_text_does_not_match_published_task')
        text=json.dumps({'live_composer_text':actual['text'],'source':actual['source']},ensure_ascii=False)
        if isinstance(raw,dict) and raw.get('_multimodal'):
            raw['content'].append({'type':'text','text':text})
            raw['text_summary']=raw.get('text_summary','')+'\n'+text
            return raw
        return json.dumps({'screen_capture':raw,'live_composer_text':actual['text'],
                           'source':actual['source']},ensure_ascii=False)

    def task(self,cap,require_pending=True):
        task=self.handoffs.get(cap)
        if require_pending and task['status']!='pending':raise Denied('task_is_not_pending')
        authorization=json.loads((self.state/'delivery_authorization.json').read_text())
        import time
        if authorization['expires']<=time.time():raise Denied('delivery_authorization_expired')
        prefixes=authorization.get('request_prefixes',[])
        with self.handoffs.store.db() as db:
            row=db.execute('SELECT request_id FROM handoffs WHERE digest=?',(self.handoffs.digest(cap),)).fetchone()
        if (row['request_id'] not in authorization.get('request_ids',[]) and
                not any(isinstance(p,str) and p and row['request_id'].startswith(p) for p in prefixes)):
            raise Denied('task_not_in_authorized_delivery_scope')
        direct=authorization.get('fixture_questions',{}).get(row['request_id'])
        if direct is not None:
            if direct=='그건 Hermes 비서한테 물어봐':
                qid=authorization.get('fixture_permission_question_id')
                with self.handoffs.store.db() as db:
                    q=db.execute('SELECT question,status,client_id FROM inbox_requests WHERE id=?',(qid,)).fetchone()
                if (q is None or q['status']!='draft' or not q['question'].startswith('가상 ')
                        or not q['client_id'].startswith('dialogue-')):
                    raise Denied('live_synthetic_question_required_for_fixture_permission')
                return '그건 Hermes 비서한테 물어봐. 이 가상 질문(BRIDGE-Q:'+qid+')만 허락해.'
            if not isinstance(direct,str) or not direct.startswith('Hermes 비서한테 가상 ') or not direct.endswith('물어봐줘') or len(direct)>500:
                raise Denied('invalid_authorized_fixture_question')
            return direct
        origin=json.loads((self.state/'active_probe.json').read_text())['public_url'].split('/probe/')[0]
        return '이 링크를 HTTP GET해서 task.instruction만 실행하고 result_url에 실제 결과를 JSON POST해 줘: '+origin+'/work/'+cap

    def capture(self,target=None,mode='ax'):
        windows=self.screen.windows()
        if len(windows)!=1:raise Denied('exactly_one_pickle_chat_window_required')
        current=(windows[0]['pid'],windows[0]['window_id'])
        if target and current!=target:raise Denied('pickle_window_changed')
        raw=self.call({'action':'capture','pid':current[0],'window_id':current[1],'mode':mode})
        return current,raw

    def elements(self,raw):
        data=json.loads(raw) if isinstance(raw,str) else raw
        if not isinstance(data,dict) or 'error' in data:raise Denied('capture_failed')
        if data.get('truncated_elements'):
            file=Path(data.get('elements_file','')).resolve(strict=True)
            if not file.is_relative_to(self.cache_root) or not file.name.startswith('elements_') or file.suffix!='.json':
                raise Denied('capture_elements_artifact_required')
            full=json.loads(file.read_text())
            rows=full.get('elements') if isinstance(full,dict) else full
            if not isinstance(rows,list) or len(rows)!=data.get('total_elements'):
                raise Denied('full_chat_state_required')
            return rows
        return data.get('elements',[])

    @staticmethod
    def button(elements):
        return [e for e in elements if e['role']=='AXButton' and name(e['label']) in {'보내기','send'}]

    def ledger(self,cap):return self.state/('delivery-'+hashlib.sha256(cap.encode()).hexdigest()+'.json')

    def record(self,cap,status):
        fd=os.open(self.ledger(cap),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'status':status},f)

    def handle(self,args,**_):
        try:
            if set(args)-{'action','capability','observed_message','wait_seconds'}:raise Denied('invalid_delivery_arguments')
            action=args.get('action');cap=args.get('capability')
            if action=='inspect':return self.capture(mode='som')[1]
            if action=='diagnose':
                self.capture()
                return json.dumps(self.diagnose() if self.diagnose else {'error':'diagnostics_unavailable'})
            if not isinstance(cap,str):raise Denied('task_capability_required')
            if action=='result':
                self.task(cap,require_pending=False)
                wait=args.get('wait_seconds',0)
                if type(wait) not in {int,float} or not 0<=wait<=20:raise Denied('bounded_result_wait_required')
                deadline=time.monotonic()+wait
                while True:
                    row=self.handoffs.get(cap)
                    if row['status']!='pending' or time.monotonic()>=deadline:
                        if row['status']!='pending' and self.ledger(cap).exists():
                            delivery=json.loads(self.ledger(cap).read_text())
                            if delivery.get('status')=='sent_unconfirmed':self.record(cap,'confirmed')
                        return json.dumps({k:row[k] for k in ['status','result']},ensure_ascii=False)
                    time.sleep(.2)
            message=self.task(cap)
            if action=='resume':
                if not self.ledger(cap).exists() or json.loads(self.ledger(cap).read_text()).get('status')!='prepared':
                    raise Denied('only_a_prepared_unsent_delivery_can_resume')
                target,_=self.capture()
                raw=self.prepared_capture(target,message)
                self.prepared[cap]=(target,message)
                return raw
            if action=='diagnose_context':
                target,raw=self.capture();elements=self.elements(raw)
                fields=[e for e in elements if e['role']=='AXTextArea' and name(e['label']) in {'메시지 보내기','message'}]
                if len(fields)!=1 or self.button(elements):raise Denied('nonempty_or_ambiguous_composer')
                self.act({'action':'context_menu','element':fields[0]['index'],'pid':target[0],
                          'window_id':target[1],'delivery_mode':'background'})
                return self.capture(target,mode='som')[1]
            if action=='prepare':
                if self.ledger(cap).exists():raise Denied('delivery_already_attempted_inspect_before_recovery')
                target,raw=self.capture();elements=self.elements(raw)
                fields=[e for e in elements if e['role']=='AXTextArea' and name(e['label']) in {'메시지 보내기','message'}]
                if len(fields)!=1 or self.button(elements):raise Denied('nonempty_or_ambiguous_composer')
                if self.composer is None:raise Denied('live_composer_reader_required')
                # Direct AX insertion avoids clicking/focusing the composer or
                # typing into a process-wide focused element. No key shortcuts.
                authorization=json.loads((self.state/'delivery_authorization.json').read_text())
                method=authorization.get('input_method','insert')
                if method not in {'insert','paste_menu','context_paste'}:raise Denied('unknown_input_method')
                if method in {'paste_menu','context_paste'} and authorization.get('native_clipboard_consent') is not True:
                    raise Denied('explicit_native_clipboard_consent_required')
                # Record before any input. An uncertain operation is not repeated.
                self.record(cap,'preparing')
                self.act({'action':method,'element':fields[0]['index'],'text':message,
                          'pid':target[0],'window_id':target[1],'delivery_mode':'background'})
                self.prepared[cap]=(target,message)
                self.record(cap,'prepared')
                return self.prepared_capture(target,message)
            if action=='send':
                target,expected=self.prepared.get(cap,(None,None))
                if expected is None or args.get('observed_message')!=expected:
                    raise Denied('read_full_composer_message_before_send')
                if json.loads(self.ledger(cap).read_text())['status']!='prepared':raise Denied('delivery_already_attempted')
                self.capture(target)
                if self.composer is None:raise Denied('live_composer_reader_required')
                actual=self.composer(target)
                if actual['text']!=expected:raise Denied('composer_changed_after_model_review')
                if actual.get('send_element') is None:raise Denied('send_button_not_unique')
                self.record(cap,'sending')
                self.act({'action':'click','element':actual['send_element'],
                          'delivery_mode':'background'})
                self.record(cap,'sent_unconfirmed')
                self.prepared.pop(cap,None)
                return self.capture(target,mode='som')[1]
            raise Denied('unsupported_delivery_action')
        except (Denied,KeyError,ValueError,OSError,TypeError) as error:
            return json.dumps({'error':str(error) if isinstance(error,Denied) else 'delivery_configuration_or_driver_failure'})


SCHEMA={'name':'pickle_bridge_pickle_delivery',
 'description':'Background-only delivery of an operator-authorized bridge task to Pickle. Never raise the window or escalate to foreground. prepare inserts only into an empty composer and returns the actual full live_composer_text plus screenshot. Read that real accessibility value even if the screenshot is clipped; then send with the exact observed_message. resume only re-reads an existing prepared unsent composer without retyping. send rechecks the live value again. Never retry uncertain sends. result reads only this authorized task.',
 'parameters':{'type':'object','properties':{'action':{'type':'string','enum':['inspect','diagnose','diagnose_context','prepare','resume','send','result']},
 'capability':{'type':'string'},'observed_message':{'type':'string'},
 'wait_seconds':{'type':'number','minimum':0,'maximum':20}},'required':['action'],'additionalProperties':False}}


def action_result(result):
    """Transport success is not proof of input; never ignore explicit refusal."""
    data=json.loads(result) if isinstance(result,str) else result
    if not isinstance(data,dict) or data.get('error') or data.get('ok') is not True:
        raise Denied('driver_action_failed')
    if data.get('effect')=='suspected_noop' or data.get('verified') is False:
        raise Denied('driver_did_not_verify_input_no_foreground_fallback')
    return data
