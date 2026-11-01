import copy
import unittest
from types import SimpleNamespace
from bridge.backend_compat import adapt_backend,remember_snapshot
from bridge.delivery_driver import snapshot_token,targeted_action,context_paste
from bridge.store import Denied

class Backend:
    """The original capture stores element tokens but not the snapshot ID."""
    def __init__(self,modified=False):
        self.modified=modified;self._last_target={'pid':1,'window_id':2};self._snapshot_tokens={}
        self._session=SimpleNamespace(supports_input_property=lambda *a:True)
        self.stage='field';self.fetches=[];self.actions=[];self.counter=0;self.bad=None
    def _gws_args(self):return dict(self._last_target)
    def _set_active_target(self,target):self._clear_active_target();self._last_target=dict(target)
    def _clear_active_target(self):self._snapshot_tokens={};self._last_target={}
    def _fetch_or_refetch(self,tool,args,*a,**kw):
        self.fetches.append((tool,dict(args)));self.counter+=1;snapshot='s%08x'%self.counter
        rows=[{'element_index':5,'role':'AXTextArea','label':'message','value':''}]
        if self.stage=='menu':rows.append({'element_index':7,'role':'AXMenuItem','label':'Paste'})
        data=dict(self._last_target,snapshot_id=snapshot,elements=rows)
        if self.bad:data.update(self.bad)
        return {'structuredContent':data}
    def capture(self,mode='ax',pid=1,window_id=2):
        self._set_active_target({'pid':pid,'window_id':window_id})
        raw=self._fetch_or_refetch('get_window_state',self._gws_args());data=raw['structuredContent']
        self._snapshot_tokens={r['element_index']:r['element_token'] for r in data['elements'] if r.get('element_token')}
        if self.modified:self._snapshot_id=data['snapshot_id']
        return SimpleNamespace(elements=[SimpleNamespace(index=r['element_index'],role=r['role'],label=r['label']) for r in data['elements']])
    def _action(self,tool,args):
        self.actions.append((tool,dict(args)))
        if args.get('action')=='show_menu':self.stage='menu'
        return SimpleNamespace(ok=True,meta={})

class BackendCompatibilityTests(unittest.TestCase):
    def test_original_missing_snapshot_is_reproduced_and_both_variants_adapt(self):
        original=Backend();original.capture()
        with self.assertRaises(Denied):snapshot_token(original,5)
        for modified in [False,True]:
            b=adapt_backend(Backend(modified));b.capture()
            self.assertEqual(snapshot_token(b,5),'s00000001:5')
    def test_capture_uses_one_response_for_elements_and_tokens(self):
        b=adapt_backend(Backend());state=b.capture()
        self.assertEqual(len(b.fetches),1);self.assertEqual(b.fetches[0][1]['tree_format'],'elements')
        self.assertEqual(state.elements[0].index,5);self.assertEqual(b._bridge_snapshot_indices,{5})
        self.assertEqual(snapshot_token(b,state.elements[0].index),'s00000001:5')
    def test_adapter_is_idempotent_and_does_not_patch_class_or_other_instance(self):
        a=Backend();other=Backend();class_method=Backend._gws_args
        adapt_backend(a);wrapped=a._fetch_or_refetch
        self.assertIs(adapt_backend(a),a);self.assertIs(a._fetch_or_refetch,wrapped)
        self.assertIs(Backend._gws_args,class_method);self.assertNotIn('tree_format',other._gws_args())
    def test_target_switch_and_failed_capture_disarm_old_snapshot(self):
        b=adapt_backend(Backend());b.capture();b._set_active_target({'pid':3,'window_id':4})
        with self.assertRaises(Denied):snapshot_token(b,5)
        b.bad={'snapshot_id':'bad'}
        with self.assertRaises(Denied):b.capture(pid=3,window_id=4)
        self.assertIsNone(b._snapshot_id);self.assertEqual(b._snapshot_tokens,{})
    def test_missing_or_forged_element_cannot_borrow_valid_snapshot_id(self):
        b=adapt_backend(Backend());b.capture()
        with self.assertRaises(Denied):targeted_action(b,'click',99)
        self.assertEqual(b.actions,[])
    def test_wrong_window_truncation_and_missing_rows_fail_closed(self):
        for bad in [{'pid':9},{'truncated':True},{'elements':[]},{'snapshot_id':None}]:
            b=adapt_backend(Backend());b.bad=bad
            with self.assertRaises(Denied):b.capture()
            self.assertIsNone(b._snapshot_id);self.assertEqual(b.actions,[])
    def test_unsupported_schema_and_hooks_have_no_legacy_fallback(self):
        with self.assertRaises(Denied):adapt_backend(SimpleNamespace())
        b=adapt_backend(Backend());b._session.supports_input_property=lambda *a:False
        with self.assertRaises(Denied):b.capture()
        self.assertEqual(b.fetches,[]);self.assertEqual(b.actions,[])
    def test_background_context_paste_works_with_both_original_and_modified_capture(self):
        from tests.test_clipboard_tools import Board
        for modified in [False,True]:
            b=adapt_backend(Backend(modified));board=Board();before=board.snapshot()
            args={'action':'context_paste','element':5,'pid':1,'window_id':2,'delivery_mode':'background','text':'fictional test'}
            result=context_paste(b,args,lambda:board,lambda:99)
            self.assertTrue(result.ok);self.assertEqual(board.snapshot(),before)
            self.assertEqual(len(b.actions),3)
            self.assertTrue(all(a['delivery_mode']=='background' and 'element_index' not in a for _,a in b.actions))
            self.assertEqual([a['element_token'] for _,a in b.actions],['s00000001:5','s00000002:5','s00000003:7'])
    def test_rejected_capture_never_sends_or_leaves_clipboard_changed(self):
        from tests.test_clipboard_tools import Board
        b=adapt_backend(Backend());b.bad={'window_id':88};board=Board();before=board.snapshot()
        with self.assertRaises(Denied):context_paste(b,{'action':'context_paste','element':5,'pid':1,'window_id':2,'delivery_mode':'background','text':'fictional'},lambda:board,lambda:99)
        self.assertEqual(board.snapshot(),before);self.assertEqual(b.actions,[])
    def test_raw_response_validation_and_partial_tokens_are_same_snapshot(self):
        b=Backend();raw={'structuredContent':{'pid':1,'window_id':2,'snapshot_id':'s1234abcd','elements':[
            {'element_index':1,'element_token':'s1234abcd:1'},{'element_index':2}]}}
        remember_snapshot(b,raw,(1,2));self.assertEqual(snapshot_token(b,2),'s1234abcd:2')
        for bad in [None,{'isError':True}, {'structuredContent':{'pid':1,'window_id':2,'snapshot_id':'s1234abcd','elements':[{'element_index':True}]}},
                    {'structuredContent':{'pid':1,'window_id':2,'snapshot_id':'s1234abcd','elements':[{'element_index':1},{'element_index':1}]}}]:
            with self.assertRaises(Denied):remember_snapshot(b,bad,(1,2))
            self.assertIsNone(b._snapshot_id)

if __name__=='__main__':unittest.main()
