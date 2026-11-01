import unittest
from bridge.window_recovery import recover
from bridge.store import Denied

class Fake:
    def __init__(self):
        self.rows=[{'pid':2,'bundle_id':'com.pickle.client','title':'피클','identifier':'SceneWindow'}]
        self.is_minimized=True;self.front=1;self.calls=0;self.change_focus=False;self.stuck=False
    def candidates(self):return self.rows
    def front_pid(self):return self.front
    def minimized(self,row):return self.is_minimized
    def restore(self,row):
        self.calls+=1
        if not self.stuck:self.is_minimized=False
        if self.change_focus:self.front=2

class RecoveryTests(unittest.TestCase):
    def test_restore_verifies_minimized_and_foreground(self):
        a=Fake();self.assertTrue(recover(a)['restored']);self.assertEqual(a.calls,1);self.assertEqual(a.front,1)
    def test_visible_window_is_untouched(self):
        a=Fake();a.is_minimized=False;self.assertFalse(recover(a)['restored']);self.assertEqual(a.calls,0)
    def test_missing_or_ambiguous_window_is_untouched(self):
        for rows in [[],[{},{}]]:
            a=Fake();a.rows=rows
            with self.assertRaises(Denied):recover(a)
            self.assertEqual(a.calls,0)
    def test_wrong_identity_is_untouched(self):
        for key,value in [('bundle_id','other.app'),('identifier','OtherWindow'),('title','Other')]:
            a=Fake();a.rows[0][key]=value
            with self.assertRaises(Denied):recover(a)
            self.assertEqual(a.calls,0)
    def test_focus_change_aborts(self):
        a=Fake();a.change_focus=True
        with self.assertRaisesRegex(Denied,'focus_changed'):recover(a)
    def test_failed_readback_aborts_without_repeating_mutation(self):
        a=Fake();a.stuck=True
        with self.assertRaisesRegex(Denied,'not_verified'):recover(a,lambda _:None)
        self.assertEqual(a.calls,1)

class LaunchFake(Fake):
    def __init__(self):
        super().__init__();self.is_running=False;self.launched=0;self.ready=True;self.is_minimized=False;self.warmups=0
    def warmup(self,previous):self.warmups+=1
    def running(self):return self.is_running
    def candidates(self):return self.rows if self.is_running and self.ready else []
    def launch(self,path):
        self.launched+=1;self.is_running=True
        if self.change_focus:self.front=2

class LaunchTests(unittest.TestCase):
    def test_closed_app_launches_once_and_preserves_focus(self):
        a=LaunchFake();r=recover(a,lambda _:None,launch_allowed=True,app_path='/Applications/Pickle.app')
        self.assertTrue(r['launched']);self.assertEqual(a.launched,1);self.assertEqual(a.calls,0)
    def test_running_app_is_not_relaunched(self):
        a=LaunchFake();a.is_running=True;r=recover(a,lambda _:None,launch_allowed=True)
        self.assertFalse(r['launched']);self.assertEqual(a.launched,0)
    def test_login_or_update_timeout_does_not_retry_launch(self):
        a=LaunchFake();a.ready=False
        with self.assertRaisesRegex(Denied,'not_ready'):recover(a,lambda _:None,launch_allowed=True)
        self.assertEqual(a.launched,1)
    def test_launch_focus_change_aborts(self):
        a=LaunchFake();a.change_focus=True
        with self.assertRaisesRegex(Denied,'focus_changed'):recover(a,lambda _:None,launch_allowed=True)
    def test_minimized_requires_separate_restore_consent(self):
        a=LaunchFake();a.is_running=True;a.is_minimized=True
        with self.assertRaisesRegex(Denied,'restore_consent'):recover(a,lambda _:None,launch_allowed=True,restore_allowed=False)
        self.assertEqual(a.calls,0)

    def test_warmup_requires_separate_consent_and_cold_launch(self):
        for consent,running,expected in [(False,False,0),(True,False,1),(True,True,0)]:
            a=LaunchFake();a.is_running=running
            result=recover(a,lambda _:None,launch_allowed=True,warmup_allowed=consent)
            self.assertEqual(a.warmups,expected)
            self.assertEqual(result['frontmost_unchanged'],not bool(expected))
    def test_warmup_failure_stops_before_delivery(self):
        a=LaunchFake()
        def fail(previous):raise Denied('warmup_failed')
        a.warmup=fail
        with self.assertRaisesRegex(Denied,'warmup_failed'):recover(a,lambda _:None,launch_allowed=True,warmup_allowed=True)

class FocusReadbackTests(unittest.TestCase):
    def test_front_process_is_read_synchronously_without_workspace_cache(self):
        from types import SimpleNamespace as Obj
        from unittest.mock import patch
        from bridge.window_recovery import frontmost_pid
        calls=[]
        def front(serial):calls.append('front');return 0
        def getpid(serial,pid):calls.append('pid');pid._obj.value=17;return 0
        with patch('bridge.window_recovery.C.CDLL',return_value=Obj(GetFrontProcess=front,GetProcessPID=getpid)):
            self.assertEqual(frontmost_pid(),17)
        self.assertEqual(calls,['front','pid'])
    def test_failed_front_process_read_stops(self):
        from types import SimpleNamespace as Obj
        from unittest.mock import patch
        from bridge.window_recovery import frontmost_pid
        def front(serial):return -1
        def getpid(serial,pid):raise AssertionError('must stop on failed read')
        with patch('bridge.window_recovery.C.CDLL',return_value=Obj(GetFrontProcess=front,GetProcessPID=getpid)):
            with self.assertRaises(Denied):frontmost_pid()
