import json
import unittest
import unicodedata
from bridge.screen_tools import Screen


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.rows=[{'app_name':unicodedata.normalize('NFD','피클'),'title':'Window','pid':10,'window_id':1},
                   {'app_name':unicodedata.normalize('NFD','피클'),'title':'피클','pid':10,'window_id':2},
                   {'app_name':'Telegram','title':'피클','pid':20,'window_id':3}]
        def call(args):
            self.calls.append(args)
            return json.dumps({'windows':self.rows}) if args['action']=='list_windows' else 'actual capture'
        self.screen=Screen(call)

    def test_only_the_real_pickle_window_is_disclosed_and_captured(self):
        self.assertEqual([w['window_id'] for w in self.screen.windows()],[2])
        self.assertEqual(self.screen.handle({'action':'capture','pid':10,'window_id':2}),'actual capture')
        self.assertEqual(self.calls[-1],{'action':'capture','pid':10,'window_id':2,'mode':'som'})

    def test_wrong_window_or_other_app_cannot_be_captured(self):
        for pid,wid in [(10,1),(20,3)]:
            self.assertIn('error',json.loads(self.screen.handle({'action':'capture','pid':pid,'window_id':wid})))
        self.assertTrue(all(a['action']=='list_windows' for a in self.calls))

    def test_no_input_focus_or_foreground_escalation_can_reach_the_driver(self):
        for args in [{'action':'focus_app'},{'action':'type'},{'action':'capture','pid':10,'window_id':2,'bring_to_front':True}]:
            self.assertIn('error',json.loads(self.screen.handle(args)))
        self.assertEqual(self.calls,[])

    def test_scroll_is_bounded_and_retargets_exact_chat_before_navigation(self):
        navigation=[];self.screen.navigate=lambda args:navigation.append(args)
        args={'action':'scroll','pid':10,'window_id':2,'element':8,'direction':'up'}
        for _ in range(6):self.assertEqual(self.screen.handle(args),'actual capture')
        self.assertIn('error',json.loads(self.screen.handle(args)))
        self.assertEqual(len(navigation),6)
        self.assertTrue(all(x=={'action':'scroll','element':8,'direction':'up','amount':3} for x in navigation))
        self.assertEqual(self.calls[1],{'action':'capture','pid':10,'window_id':2,'mode':'ax'})
        self.assertIn('error',json.loads(self.screen.handle(dict(args,window_id=1))))

    def test_recovery_runs_once_only_when_no_visible_chat_exists(self):
        self.rows=[];attempts=[]
        def restore():
            attempts.append(True)
            self.rows=[{'app_name':'피클','title':'피클','pid':10,'window_id':2}]
            return {'restored':True,'pid':10}
        self.screen.recover=restore
        self.assertEqual(self.screen.windows()[0]['pid'],10)
        self.screen.windows();self.assertEqual(len(attempts),1)

    def test_recovery_does_not_resolve_ambiguous_visible_windows(self):
        self.rows.append(dict(self.rows[1],window_id=9));attempts=[]
        self.screen.recover=lambda:attempts.append(True)
        self.assertEqual(len(self.screen.windows()),2);self.assertEqual(attempts,[])

    def test_recovery_rejects_wrong_restored_process(self):
        self.rows=[]
        def restore():
            self.rows=[{'app_name':'피클','title':'피클','pid':99,'window_id':2}]
            return {'restored':True,'pid':10}
        self.screen.recover=restore
        from bridge.store import Denied
        with self.assertRaises(Denied):self.screen.windows()

    def test_launched_window_requires_same_process_after_discovery(self):
        self.rows=[]
        def launch():
            self.rows=[{'app_name':'피클','title':'피클','pid':99,'window_id':2}]
            return {'restored':False,'launched':True,'pid':10}
        self.screen.recover=launch
        from bridge.store import Denied
        with self.assertRaises(Denied):self.screen.windows()
