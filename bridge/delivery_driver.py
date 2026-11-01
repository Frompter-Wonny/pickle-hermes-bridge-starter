"""Adapt a captured input element to the driver's targeted background insert."""
from .store import Denied
import re


def snapshot_token(backend,element):
    tokens=getattr(backend,'_snapshot_tokens',{})
    token=tokens.get(element)
    if token:return token
    # v0.38 may return only tree_markdown + snapshot_id, with no elements[]
    # tokens. The driver's documented token format is <snapshot_id>:<row>.
    snapshot=getattr(backend,'_snapshot_id',None)
    if (not tokens and isinstance(snapshot,str) and re.fullmatch(r's[0-9a-f]{8}',snapshot)
            and type(element) is int and element>=0):return snapshot+':'+str(element)
    raise Denied('captured_field_token_missing')


def targeted_action(backend,action,element,**extra):
    if action not in {'type_text','click','scroll'}:raise Denied('unsupported_targeted_action')
    allowed={'type_text':{'text'},'click':set(),'scroll':{'direction','amount'}}[action]
    if set(extra)-allowed:raise Denied('targeted_background_action_only')
    if not backend._session.supports_input_property(action,'element_token'):
        raise Denied('targeted_action_not_supported')
    target=getattr(backend,'_last_target',{}) or {}
    if not target.get('pid') or not target.get('window_id'):raise Denied('captured_target_required')
    return backend._action(action,{'pid':target['pid'],'window_id':target['window_id'],
              'element_token':snapshot_token(backend,element),'delivery_mode':'background',**extra})


def insert(backend,args):
    if (args.get('action')!='insert' or args.get('delivery_mode')!='background'
            or set(args)-{'action','element','text','pid','window_id','delivery_mode'}):
        raise Denied('targeted_background_insert_only')
    target=getattr(backend,'_last_target',{}) or {}
    if (target.get('pid'),target.get('window_id'))!=(args.get('pid'),args.get('window_id')):
        raise Denied('captured_target_changed')
    if not isinstance(args.get('text'),str) or not args['text']:
        raise Denied('nonempty_server_message_required')
    return targeted_action(backend,'type_text',args.get('element'),text=args['text'])


def paste_menu(backend,args,board_factory):
    """The operator must separately consent before this function is exposed."""
    if (args.get('action')!='paste_menu' or args.get('delivery_mode')!='background'
            or set(args)-{'action','element','text','pid','window_id','delivery_mode'}):
        raise Denied('background_menu_paste_only')
    target=getattr(backend,'_last_target',{}) or {}
    if (target.get('pid'),target.get('window_id'))!=(args.get('pid'),args.get('window_id')):
        raise Denied('captured_target_changed')
    if not backend._session.supports_input_property('invoke_menu','path'):
        raise Denied('native_menu_not_supported')
    if not isinstance(args.get('text'),str) or not args['text']:
        raise Denied('nonempty_server_message_required')
    from .clipboard_tools import TemporaryClipboard
    import time
    with TemporaryClipboard(board_factory(),args['text']) as guard:
        guard.ensure_unchanged()
        result=backend._action('invoke_menu',{'pid':target['pid'],'window_id':target['window_id'],
                                            'path':['편집','붙여넣기']})
        # AXPress may return just before the app consumes the menu selector.
        # This only settles one paste; the entire composer is verified later.
        time.sleep(.1)
        guard.ensure_unchanged()
    result.meta['clipboard_guard']={'restored_and_read_back':guard.restored,
              'external_change':guard.external_change,'contents_exposed_to_model':False}
    return result


def context_menu(backend,args):
    if (args.get('delivery_mode')!='background' or args.get('action')!='context_menu'
            or set(args)-{'action','element','pid','window_id','delivery_mode'}):
        raise Denied('background_context_menu_only')
    target=getattr(backend,'_last_target',{}) or {}
    if (target.get('pid'),target.get('window_id'))!=(args.get('pid'),args.get('window_id')):
        raise Denied('captured_target_changed')
    if not backend._session.supports_input_property('click','action'):
        raise Denied('native_context_menu_not_supported')
    return backend._action('click',{'pid':target['pid'],'window_id':target['window_id'],
            'element_token':snapshot_token(backend,args['element']),'action':'show_menu','delivery_mode':'background'})


def context_paste(backend,args,board_factory,foreground_pid=None):
    """Paste through the real input control, never the disabled app menu."""
    if (args.get('delivery_mode')!='background' or args.get('action')!='context_paste'
            or set(args)-{'action','element','text','pid','window_id','delivery_mode'}):
        raise Denied('background_context_paste_only')
    target=(args.get('pid'),args.get('window_id'))
    if not all(type(x) is int and x>0 for x in target):raise Denied('captured_target_required')
    if not isinstance(args.get('text'),str) or not args['text']:raise Denied('nonempty_server_message_required')
    from .clipboard_tools import TemporaryClipboard
    from .screen_tools import name
    import time
    original_front=foreground_pid() if foreground_pid else None

    def capture():
        current=getattr(backend,'_last_target',{}) or {}
        if (current.get('pid'),current.get('window_id'))!=target:raise Denied('captured_target_changed')
        state=backend.capture(mode='ax',pid=target[0],window_id=target[1])
        if any(e.role=='AXButton' and name(e.label) in {'보내기','send'} for e in state.elements):
            raise Denied('composer_changed_before_paste')
        return state.elements

    with TemporaryClipboard(board_factory(),args['text']) as guard:
        rows=capture()
        paste=[e for e in rows if e.role=='AXMenuItem' and name(e.label) in {'붙여넣기','paste'}]
        if not paste:
            fields=[e for e in rows if e.role=='AXTextArea' and name(e.label) in {'메시지 보내기','message'}]
            if len(fields)!=1:raise Denied('composer_not_unique')
            # A newly launched UIKit-on-Mac composer may ignore AXShowMenu
            # until selected within its own app. This is a targeted background
            # click, never a global mouse/key event or app activation.
            selected=targeted_action(backend,'click',fields[0].index)
            if not selected.ok:return selected
            if foreground_pid and foreground_pid()!=original_front:
                raise Denied('focus_changed_selecting_composer')
            rows=capture()
            fields=[e for e in rows if e.role=='AXTextArea' and name(e.label) in {'메시지 보내기','message'}]
            if len(fields)!=1:raise Denied('composer_not_unique')
            opened=context_menu(backend,{'action':'context_menu','element':fields[0].index,
                         'pid':target[0],'window_id':target[1],'delivery_mode':'background'})
            if not opened.ok:return opened
            # On a fresh app launch, AXShowMenu may finish before the menu is
            # exposed. Observe only; never repeat opening, paste, or send.
            for _ in range(10):
                rows=capture()
                paste=[e for e in rows if e.role=='AXMenuItem' and name(e.label) in {'붙여넣기','paste'}]
                if paste:break
                guard.ensure_unchanged()
                if foreground_pid and foreground_pid()!=original_front:
                    raise Denied('focus_changed_waiting_for_context_menu')
                time.sleep(.1)
        if len(paste)!=1:raise Denied('native_paste_item_not_unique')
        if foreground_pid and original_front!=target[0] and foreground_pid()==target[0]:
            raise Denied('background_context_menu_activated_app')
        guard.ensure_unchanged()
        result=targeted_action(backend,'click',paste[0].index)
        time.sleep(.1)
        guard.ensure_unchanged()
    result.meta['clipboard_guard']={'restored_and_read_back':guard.restored,
                   'external_change':guard.external_change,'contents_exposed_to_model':False}
    result.meta['target_app_became_frontmost']=(foreground_pid() == target[0] and original_front!=target[0]) if foreground_pid else None
    return result


def read_composer(backend,target):
    """Read the real, untruncated AXValue and send control in one snapshot."""
    current=getattr(backend,'_last_target',{}) or {}
    if (current.get('pid'),current.get('window_id'))!=target:raise Denied('captured_target_changed')
    if not backend._session.supports_input_property('get_window_state','tree_format'):
        raise Denied('live_composer_value_not_supported')
    raw=backend._session.call_tool('get_window_state',{'pid':target[0],'window_id':target[1],
            'tree_format':'elements','include_screenshot':False,'max_elements':2000,'timeout_ms':5000})
    data=raw.get('structuredContent') or {}
    if raw.get('isError'):raise Denied('live_composer_read_failed')
    if (data.get('pid'),data.get('window_id'))!=target:raise Denied('composer_snapshot_target_mismatch')
    rows=data.get('elements')
    if not isinstance(rows,list):raise Denied('structured_composer_elements_required')
    from .screen_tools import name
    fields=[e for e in rows if e.get('role')=='AXTextArea' and name(e.get('label')) in {'메시지 보내기','message'}]
    buttons=[e for e in rows if e.get('role')=='AXButton' and name(e.get('label')) in {'보내기','send'}]
    if len(fields)!=1 or len(buttons)>1:raise Denied('composer_controls_not_unique')
    value=fields[0].get('value')
    if value is None:value=''
    if not isinstance(value,str):raise Denied('composer_value_not_text')
    snapshot=data.get('snapshot_id')
    if not isinstance(snapshot,str) or not re.fullmatch(r's[0-9a-f]{8}',snapshot):
        raise Denied('composer_snapshot_id_required')
    backend._snapshot_id=snapshot
    backend._snapshot_tokens={e['element_index']:e['element_token'] for e in rows
             if type(e.get('element_index')) is int and isinstance(e.get('element_token'),str)}
    index=buttons[0].get('element_index') if buttons else None
    if index is not None and (type(index) is not int or index<0):raise Denied('live_send_control_required')
    # A long, virtualized chat history may be truncated after these controls.
    # The composer value must still match the entire server-built message;
    # missing/ambiguous controls or a clipped value never pass the send check.
    return {'text':value,'send_element':index,'source':'live_accessibility_value',
            'unrelated_history_truncated':bool(data.get('truncated') or data.get('elements_complete') is False)}


def initialize_startup_composer(backend,pid):
    """One observed-field click during separately authorized startup activation.

    No keyboard, clipboard, message input, send, or application activation.
    The caller must already hold the startup-only activation scope and restore
    the original application before ordinary delivery.
    """
    import math
    from .screen_tools import name
    windows=[w for w in backend.list_windows() if w.get('pid')==pid
             and name(w.get('app_name')) in {'pickle','피클'}
             and name(w.get('title')) in {'pickle','피클'} and not w.get('off_screen')]
    if len(windows)!=1:raise Denied('startup_chat_window_not_unique')
    wid=windows[0]['window_id']
    raw=backend._session.call_tool('get_window_state',{'pid':pid,'window_id':wid,
        'tree_format':'elements','include_screenshot':True,'max_elements':250,'timeout_ms':5000,
        **({'session':backend._session_id} if getattr(backend,'_session_id',None) else {})})
    data=raw.get('structuredContent') or {}
    if raw.get('isError') or (data.get('pid'),data.get('window_id'))!=(pid,wid) or not data.get('screenshot_frame_valid'):
        raise Denied('startup_composer_snapshot_required')
    rows=data.get('elements',[])
    fields=[e for e in rows if e.get('role')=='AXTextArea' and name(e.get('label')) in {'메시지 보내기','message'}]
    if len(fields)!=1 or fields[0].get('value') not in {None,''} or any(e.get('role')=='AXButton' and name(e.get('label')) in {'보내기','send'} for e in rows):
        raise Denied('startup_empty_composer_required')
    frame=fields[0].get('frame',{});bounds=data.get('window_bounds',{})
    try:
        x,y,w,h=(float(frame[k]) for k in ['x','y','w','h'])
        bx,by,bw,bh=(float(bounds[k]) for k in ['x','y','width','height'])
        sw,sh=float(data['screenshot_width']),float(data['screenshot_height'])
        if not all(math.isfinite(v) for v in [x,y,w,h,bx,by,bw,bh,sw,sh]) or min(w,h,bw,bh,sw,sh)<=0:raise ValueError()
        if x<bx or y<by or x+w>bx+bw+1 or y+h>by+bh+1:raise ValueError()
        px=(x+w/2-bx)*sw/bw;py=(y+h/2-by)*sh/bh
        if not (0<=px<sw and 0<=py<sh):raise ValueError()
    except (KeyError,TypeError,ValueError):raise Denied('startup_composer_geometry_required')
    capture=data.get('capture_id')
    if not isinstance(capture,str) or not capture:raise Denied('startup_fresh_capture_required')
    result=backend._action('click',{'pid':pid,'window_id':wid,'x':px,'y':py,
                                   'capture_id':capture,'delivery_mode':'background'})
    if not result.ok:raise Denied('startup_composer_selection_failed:'+str(getattr(result,'code',None))+':'+str(getattr(result,'message',''))[:250])
    return {'initialized':True}
