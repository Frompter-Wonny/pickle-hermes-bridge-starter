"""Register a process-local read-only toolset, preserving normal Hermes config."""
import sys
import os
import json
from pathlib import Path

HERMES=Path(os.environ.get('PICKLE_BRIDGE_HERMES_ROOT',str(Path.home()/'.hermes/hermes-agent'))).expanduser()
sys.path.insert(0,str(HERMES))
from toolsets import create_custom_toolset, resolve_multiple_toolsets
from tools.registry import registry
from note_tools import Notes

screen_verify=os.environ.get('PICKLE_BRIDGE_SCREEN_VERIFY')=='1'
notes=None if screen_verify else Notes(json.loads(Path(os.environ['PICKLE_BRIDGE_NOTE_SOURCES']).read_text()))
sources=[] if screen_verify else list(notes.roots)

def search(args,**_):
    try:return json.dumps(notes.search(**args),ensure_ascii=False)
    except (ValueError,KeyError,OSError,TimeoutError):return json.dumps({'error':'invalid_or_unavailable_note_query'})

def read(args,**_):
    try:return json.dumps(notes.read(**args),ensure_ascii=False)
    except (ValueError,KeyError,OSError):return json.dumps({'error':'note_outside_allowed_source_or_unavailable'})

source={'type':'string','enum':sources}
registry.register(name='pickle_bridge_search_notes',toolset='pickle_bridge-vault-readonly',
    schema={'name':'pickle_bridge_search_notes','description':'Search only configured Markdown sources. Start with filenames; use content if needed. Sources: '+', '.join(sources),
            'parameters':{'type':'object','properties':{'source':source,'query':{'type':'string'},'mode':{'type':'string','enum':['filename','content']},'offset':{'type':'integer'},'max_results':{'type':'integer'}},'required':['source','query']}},handler=search)
registry.register(name='pickle_bridge_read_note',toolset='pickle_bridge-vault-readonly',
    schema={'name':'pickle_bridge_read_note','description':'Read a selected Markdown note within a configured source; paths are source-relative. Page through line ranges if needed.',
            'parameters':{'type':'object','properties':{'source':source,'path':{'type':'string'},'start_line':{'type':'integer'},'line_count':{'type':'integer'}},'required':['source','path']}},handler=read)

create_custom_toolset('pickle_bridge-vault-readonly','Approved Pickle question: read and search only',
                      tools=['pickle_bridge_read_note','pickle_bridge_search_notes'])
if set(resolve_multiple_toolsets(['pickle_bridge-vault-readonly']))!={'pickle_bridge_read_note','pickle_bridge_search_notes'}:
    raise SystemExit('Unexpected read-only toolset expansion; refusing to start.')

if screen_verify:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from bridge.delivery_driver import targeted_action,initialize_startup_composer
    from bridge.window_recovery import optional_recovery
    from bridge.delivery_tools import action_result
    from screen_tools import Screen,SCHEMA
    from tools.computer_use import tool as computer_tool
    def navigate(args):
        # The user authorized inspecting this chat. Only the facade's fixed,
        # bounded scroll operation is approved; never unlock general input.
        previous=computer_tool._approval_callback
        def approve(action,received,summary):
            return 'approve_once' if action=='scroll' and received==args else 'deny'
        try:
            computer_tool.set_approval_callback(approve)
            if computer_tool._request_approval('scroll',args):raise ValueError('Chat scroll was not authorized')
            result=computer_tool._text_response(targeted_action(computer_tool._get_backend(),'scroll',args['element'],
                      direction=args['direction'],amount=args['amount']))
            action_result(result)
            return result
        finally:computer_tool.set_approval_callback(previous)
    screen=Screen(computer_tool.handle_computer_use,navigate,
                  recover=lambda:optional_recovery(Path(__file__).resolve().parents[1],
                      lambda pid:initialize_startup_composer(computer_tool._get_backend(),pid)))
    registry.register(name='pickle_bridge_verify_screen',toolset='pickle_bridge-screen-readonly',schema=SCHEMA,handler=screen.handle)
    create_custom_toolset('pickle_bridge-screen-readonly','Actual Pickle chat verification; capture only',tools=['pickle_bridge_verify_screen'])
    if set(resolve_multiple_toolsets(['pickle_bridge-screen-readonly']))!={'pickle_bridge_verify_screen'}:
        raise SystemExit('Unexpected screen toolset expansion; refusing to start.')

if __name__=='__main__':
    from hermes_cli.main import main
    main()
