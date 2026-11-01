"""Hermes CLI entry for explicitly authorized, task-scoped Pickle delivery."""
import sys
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(os.environ.get('PICKLE_BRIDGE_HERMES_ROOT',str(Path.home()/'.hermes/hermes-agent'))).expanduser()))
from bridge.delivery_tools import Delivery,SCHEMA,action_result
from bridge.delivery_driver import insert,targeted_action,paste_menu,context_menu,context_paste,read_composer,initialize_startup_composer
from bridge.store import Store
from bridge.window_recovery import optional_recovery,frontmost_pid
from tools.computer_use import tool as computer_tool
from bridge.backend_compat import adapt_backend
def bridge_backend():return adapt_backend(computer_tool._get_backend())
def bridge_call(args,**kwargs):
    bridge_backend()
    return computer_tool.handle_computer_use(args,**kwargs)
from tools.registry import registry
from toolsets import create_custom_toolset,resolve_multiple_toolsets


def act(args):
    if args.get('delivery_mode')!='background' or args.get('bring_to_front') or args.get('action') not in {'click','insert','paste_menu','context_menu','context_paste'}:
        raise ValueError('Only background Pickle composer operations are allowed')
    previous=computer_tool._approval_callback
    def approve(action,received,summary):
        expected='type' if args['action'] in {'insert','paste_menu','context_paste'} else 'click'
        return 'approve_once' if received==args and action==expected else 'deny'
    try:
        computer_tool.set_approval_callback(approve)
        if args['action']=='context_menu':
            if computer_tool._request_approval('click',args):raise ValueError('Background context menu was not authorized')
            result=computer_tool._text_response(context_menu(bridge_backend(),args))
        elif args['action'] in {'paste_menu','context_paste'}:
            import json
            consent=json.loads((ROOT/'.runtime/delivery_authorization.json').read_text())
            if consent.get('native_clipboard_consent') is not True:raise ValueError('Native helper consent missing')
            if computer_tool._request_approval('type',args):raise ValueError('Background paste was not authorized')
            from bridge.clipboard_tools import AppKitBoard
            if args['action']=='context_paste':
                foreground_pid=frontmost_pid
                native=context_paste(bridge_backend(),args,AppKitBoard,foreground_pid)
            else:native=paste_menu(bridge_backend(),args,AppKitBoard)
            result=computer_tool._text_response(native)
        elif args['action']=='insert':
            if computer_tool._request_approval('type',args):raise ValueError('Background insert was not authorized')
            result=computer_tool._text_response(insert(bridge_backend(),args))
        else:
            if computer_tool._request_approval('click',args):raise ValueError('Background send was not authorized')
            result=computer_tool._text_response(targeted_action(bridge_backend(),'click',args['element']))
        import json,os,time
        data=json.loads(result) if isinstance(result,str) else result
        if isinstance(data,dict):
            # Never record input arguments or clipboard contents. Click failures
            # may include the driver's explanation for private diagnosis only.
            receipt={k:data.get(k) for k in ['ok','verified','effect','code','path','degraded','delivery_mode','verdict']}
            if args['action'] in {'click','paste_menu','context_menu','context_paste'} and (data.get('ok') is not True or data.get('error')):
                receipt['failure_message']=str(data.get('message') or data.get('error') or '')[:1200]
            if args['action'] in {'paste_menu','context_paste'}:
                receipt['clipboard_guard']=(data.get('meta') or {}).get('clipboard_guard')
                receipt['target_app_became_frontmost']=(data.get('meta') or {}).get('target_app_became_frontmost')
            receipt.update(action=args['action'],at=time.time())
            fd=os.open(ROOT/'.runtime/delivery-actions.jsonl',os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
            with os.fdopen(fd,'w') as f:f.write(json.dumps(receipt)+'\n')
        return action_result(result)
    finally:computer_tool.set_approval_callback(previous)


def diagnose():
    b=bridge_backend();s=b._session
    result={'snapshot_token_count':len(getattr(b,'_snapshot_tokens',{})),
            'snapshot_id_present':bool(getattr(b,'_snapshot_id',None)),
            'driver_type_properties':sorted(getattr(s,'_tool_schemas',{}).get('type_text',{}).get('properties',{}))}
    raw=s.call_tool('get_window_state',b._gws_args())
    result['raw_top_keys']=list(raw)
    for key in ['structuredContent','data']:
        value=raw.get(key)
        if isinstance(value,dict):
            result[key+'_keys']=list(value)
            rows=value.get('elements')
            if isinstance(rows,list) and rows:
                result[key+'_element_keys']=list(rows[0])
                result[key+'_element_count']=len(rows)
    clip=s.call_tool('clipboard_read',{'include_text':False})
    for key in ['structuredContent','data']:
        value=clip.get(key)
        if isinstance(value,dict):
            result['clipboard_'+key+'_keys']=list(value)
            result['clipboard_'+key+'_types']=value.get('types')
    return result


delivery=Delivery(Store(ROOT/'.runtime/bridge.sqlite3'),ROOT/'.runtime',bridge_call,act,
                 diagnose=diagnose,composer=lambda target:read_composer(bridge_backend(),target),
                 recover=lambda:optional_recovery(ROOT,lambda pid:initialize_startup_composer(bridge_backend(),pid)))
registry.register(name='pickle_bridge_pickle_delivery',toolset='pickle_bridge-pickle-delivery',schema=SCHEMA,handler=delivery.handle)
create_custom_toolset('pickle_bridge-pickle-delivery','Explicit task-scope Pickle delivery only',tools=['pickle_bridge_pickle_delivery'])
if set(resolve_multiple_toolsets(['pickle_bridge-pickle-delivery']))!={'pickle_bridge_pickle_delivery'}:
    raise SystemExit('Unexpected delivery toolset expansion')

if __name__=='__main__':
    from hermes_cli.main import main
    main()
