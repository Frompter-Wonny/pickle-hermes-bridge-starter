import unittest
from types import SimpleNamespace
from bridge.delivery_driver import insert,targeted_action,paste_menu,context_menu,context_paste,read_composer
from bridge.store import Denied


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.backend=SimpleNamespace(_last_target={'pid':1,'window_id':2},_snapshot_tokens={5:'s00000001:5'},
            _session=SimpleNamespace(supports_input_property=lambda *a:True),
            _action=lambda name,args:self.calls.append((name,args)))
        self.args={'action':'insert','element':5,'pid':1,'window_id':2,'text':'fixture message','delivery_mode':'background'}

    def test_insert_uses_exact_captured_field_and_never_focus_or_click(self):
        insert(self.backend,self.args)
        self.assertEqual(self.calls,[('type_text',{'pid':1,'window_id':2,'element_token':'s00000001:5',
                    'text':'fixture message','delivery_mode':'background'})])

    def test_target_drift_stale_element_and_foreground_are_rejected(self):
        for updates in [{'pid':3},{'window_id':9},{'element':99},{'delivery_mode':'foreground'},{'bring_to_front':True}]:
            with self.assertRaises(Denied):insert(self.backend,dict(self.args,**updates))
        self.assertEqual(self.calls,[])

    def test_unsupported_driver_does_not_fallback_to_keyboard(self):
        self.backend._session.supports_input_property=lambda *a:False
        with self.assertRaises(Denied):insert(self.backend,self.args)
        self.assertEqual(self.calls,[])

    def test_markdown_only_snapshot_uses_documented_token_format(self):
        self.backend._snapshot_tokens={};self.backend._snapshot_id='s1234abcd'
        insert(self.backend,self.args)
        self.assertEqual(self.calls[-1][1]['element_token'],'s1234abcd:5')
        self.backend._snapshot_id='unknown'
        with self.assertRaises(Denied):insert(self.backend,self.args)

    def test_send_and_scroll_never_emit_legacy_index_or_foreground(self):
        targeted_action(self.backend,'click',5)
        targeted_action(self.backend,'scroll',5,direction='up',amount=3)
        for action,args in self.calls:
            self.assertEqual(args['element_token'],'s00000001:5')
            self.assertEqual(args['delivery_mode'],'background')
            self.assertNotIn('element_index',args)
        with self.assertRaises(Denied):targeted_action(self.backend,'click',5,bring_to_front=True)

    def test_menu_paste_uses_native_selector_and_restores_every_clipboard_format(self):
        from tests.test_clipboard_tools import Board
        board=Board();original=board.snapshot()
        def action(name,args):
            self.calls.append((name,args))
            self.assertEqual(board.items,[[('public.utf8-plain-text',b'fixture message')]])
            return SimpleNamespace(meta={})
        self.backend._action=action
        result=paste_menu(self.backend,dict(self.args,action='paste_menu'),lambda:board)
        self.assertEqual(board.items,original)
        self.assertTrue(result.meta['clipboard_guard']['restored_and_read_back'])
        self.assertEqual(self.calls,[('invoke_menu',{'pid':1,'window_id':2,'path':['편집','붙여넣기']})])

    def test_menu_failure_restores_clipboard_and_no_keyboard_fallback(self):
        from tests.test_clipboard_tools import Board
        board=Board();original=board.snapshot()
        def fail(name,args):raise OSError('native menu disabled')
        self.backend._action=fail
        with self.assertRaises(OSError):paste_menu(self.backend,dict(self.args,action='paste_menu'),lambda:board)
        self.assertEqual(board.items,original)

    def test_context_menu_is_exact_ax_action_without_pixel_or_keyboard_fallback(self):
        args={k:v for k,v in self.args.items() if k!='text'};args['action']='context_menu'
        context_menu(self.backend,args)
        self.assertEqual(self.calls,[('click',{'pid':1,'window_id':2,'element_token':'s00000001:5',
                      'action':'show_menu','delivery_mode':'background'})])
        with self.assertRaises(Denied):context_menu(self.backend,dict(args,delivery_mode='foreground'))

    def context_fixture(self,visible=True,draft=False):
        self.visible=visible
        def capture(**_):
            rows=[SimpleNamespace(role='AXTextArea',label='메시지 보내기',index=5)]
            if self.visible:rows.append(SimpleNamespace(role='AXMenuItem',label='붙여넣기',index=30))
            if draft:rows.append(SimpleNamespace(role='AXButton',label='보내기',index=7))
            self.backend._snapshot_tokens={e.index:'s00000001:'+str(e.index) for e in rows}
            return SimpleNamespace(elements=rows)
        def action(name,args):
            self.calls.append((name,args))
            if args.get('action')=='show_menu':self.visible=True
            return SimpleNamespace(ok=True,meta={})
        self.backend.capture=capture;self.backend._action=action

    def test_context_paste_uses_existing_input_menu_without_activating_app(self):
        from tests.test_clipboard_tools import Board
        board=Board();original=board.snapshot();self.context_fixture()
        result=context_paste(self.backend,dict(self.args,action='context_paste'),lambda:board,lambda:99)
        self.assertEqual(board.items,original)
        self.assertEqual(self.calls,[('click',{'pid':1,'window_id':2,'element_token':'s00000001:30','delivery_mode':'background'})])
        self.assertFalse(result.meta['target_app_became_frontmost'])
        self.assertTrue(result.meta['clipboard_guard']['restored_and_read_back'])

    def test_context_paste_opens_only_input_control_then_selects_paste(self):
        from tests.test_clipboard_tools import Board
        self.context_fixture(visible=False)
        context_paste(self.backend,dict(self.args,action='context_paste'),Board,lambda:99)
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.calls[0][1]['element_token'],'s00000001:5')
        self.assertEqual(self.calls[1][1]['action'],'show_menu')
        self.assertEqual(self.calls[2][1]['element_token'],'s00000001:30')
        self.assertTrue(all(a['delivery_mode']=='background' for _,a in self.calls))

    def test_app_activation_or_new_user_draft_aborts_before_paste(self):
        from tests.test_clipboard_tools import Board
        board=Board();original=board.snapshot();self.context_fixture()
        fronts=iter([99,1])
        with self.assertRaises(Denied):context_paste(self.backend,dict(self.args,action='context_paste'),lambda:board,lambda:next(fronts))
        self.assertEqual(board.items,original);self.assertEqual(self.calls,[])
        self.context_fixture(draft=True)
        with self.assertRaises(Denied):context_paste(self.backend,dict(self.args,action='context_paste'),lambda:board,lambda:99)
        self.assertEqual(board.items,original);self.assertEqual(self.calls,[])

    def test_live_composer_returns_full_value_and_fresh_send_token(self):
        text='full input '+('x'*1000)+' URL-END'
        self.live_state={'pid':1,'window_id':2,'snapshot_id':'s87654321','elements_complete':True,
            'elements':[{'role':'AXTextArea','label':'메시지 보내기','value':text,'element_index':5,'element_token':'s87654321:5'},
                        {'role':'AXButton','label':'보내기','element_index':9,'element_token':'s87654321:9'}]}
        def call(name,args):
            self.assertEqual(name,'get_window_state');self.assertEqual(args['tree_format'],'elements')
            self.assertFalse(args['include_screenshot'])
            return {'structuredContent':self.live_state}
        self.backend._session.call_tool=call
        actual=read_composer(self.backend,(1,2))
        self.assertEqual(actual['text'],text);self.assertEqual(actual['send_element'],9)
        targeted_action(self.backend,'click',actual['send_element'])
        self.assertEqual(self.calls[-1][1]['element_token'],'s87654321:9')
        self.live_state.update(truncated=True,elements_complete=False)
        self.assertEqual(read_composer(self.backend,(1,2))['text'],text)
        self.live_state['elements']=[]
        with self.assertRaises(Denied):read_composer(self.backend,(1,2))
        self.live_state['window_id']=3
        with self.assertRaises(Denied):read_composer(self.backend,(1,2))


class DelayedMenuTests(unittest.TestCase):
    setUp=DriverTests.setUp
    context_fixture=DriverTests.context_fixture
    def test_delayed_menu_is_observed_without_reopening(self):
        from tests.test_clipboard_tools import Board
        self.context_fixture();self.visible=False;base=self.backend.capture;count=[0]
        def delayed(**kwargs):
            count[0]+=1
            if count[0]<4:
                self.visible=False
            else:self.visible=True
            return base(**kwargs)
        self.backend.capture=delayed
        result=context_paste(self.backend,dict(self.args,action='context_paste'),Board,lambda:99)
        self.assertTrue(result.ok)
        self.assertEqual(sum(a[1].get('action')=='show_menu' for a in self.calls),1)

    def test_background_selection_focus_change_aborts_before_menu_or_paste(self):
        from tests.test_clipboard_tools import Board
        self.context_fixture(visible=False);front=[99]
        action=self.backend._action
        def changed(name,args):
            result=action(name,args);front[0]=1;return result
        self.backend._action=changed
        with self.assertRaisesRegex(Denied,'focus_changed_selecting'):context_paste(self.backend,dict(self.args,action='context_paste'),Board,lambda:front[0])
        self.assertEqual(len(self.calls),1)

class StartupSelectionTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self.data={'pid':1,'window_id':2,'screenshot_frame_valid':True,'capture_id':'capture-test',
                   'screenshot_width':600,'screenshot_height':1000,
                   'window_bounds':{'x':100,'y':200,'width':300,'height':500},
                   'elements':[{'role':'AXTextArea','label':'메시지 보내기','frame':{'x':120,'y':630,'w':100,'h':20}}]}
        self.backend=SimpleNamespace(list_windows=lambda:[{'pid':1,'window_id':2,'app_name':'피클','title':'피클'}],
            _session=SimpleNamespace(call_tool=lambda *args:{'structuredContent':self.data}),
            _action=lambda action,args:self.calls.append((action,args)) or SimpleNamespace(ok=True))
    def test_selects_observed_composer_once_in_scaled_capture(self):
        from bridge.delivery_driver import initialize_startup_composer
        initialize_startup_composer(self.backend,1)
        self.assertEqual(self.calls,[('click',{'pid':1,'window_id':2,'x':140.,'y':880.,'capture_id':'capture-test','delivery_mode':'background'})])
    def test_existing_draft_never_clicked(self):
        from bridge.delivery_driver import initialize_startup_composer
        self.data['elements'][0]['value']='user draft'
        with self.assertRaises(Denied):initialize_startup_composer(self.backend,1)
        self.assertEqual(self.calls,[])
    def test_out_of_window_geometry_rejected(self):
        from bridge.delivery_driver import initialize_startup_composer
        self.data['elements'][0]['frame']['x']=1
        with self.assertRaises(Denied):initialize_startup_composer(self.backend,1)
        self.assertEqual(self.calls,[])
    def test_stale_or_other_window_capture_rejected(self):
        from bridge.delivery_driver import initialize_startup_composer
        self.data['pid']=99
        with self.assertRaises(Denied):initialize_startup_composer(self.backend,1)
        self.assertEqual(self.calls,[])
    def test_snapshot_uses_the_same_driver_session_as_the_click(self):
        from bridge.delivery_driver import initialize_startup_composer
        reads=[];self.backend._session_id='fixture-session'
        self.backend._session.call_tool=lambda tool,args:reads.append(args) or {'structuredContent':self.data}
        initialize_startup_composer(self.backend,1)
        self.assertEqual(reads[0]['session'],'fixture-session')
