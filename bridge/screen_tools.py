"""A read-only, Pickle-window-only facade for Hermes computer_use."""
import json
import unicodedata


def name(value):
    return unicodedata.normalize('NFC',str(value)).strip().casefold()


class Screen:
    def __init__(self,call,navigate=None,recover=None):
        self.call=call
        self.navigate=navigate
        self.scrolls=0
        self.recover=recover
        self.recovery_attempted=False

    def windows(self):
        def listed():
            data=self.call({'action':'list_windows'})
            if isinstance(data,str):data=json.loads(data)
            return [w for w in data.get('windows',[])
                    if name(w.get('app_name')) in {'pickle','피클'}
                    and name(w.get('title')) in {'pickle','피클'}
                    and not w.get('off_screen')]
        windows=listed()
        if not windows and self.recover is not None and not self.recovery_attempted:
            self.recovery_attempted=True
            result=self.recover()
            windows=listed()
            if result and (result.get('restored') or result.get('launched')):
                if len(windows)!=1 or windows[0]['pid']!=result['pid']:
                    from bridge.store import Denied
                    raise Denied('restored_pickle_window_not_visible_or_changed')
        return windows

    def handle(self,args,**_):
        if set(args)-{'action','mode','pid','window_id','element','direction'}:
            return json.dumps({'error':'read_only_pickle_capture_required'})
        action=args.get('action')
        if action not in {'capture','list_windows','scroll'}:
            return json.dumps({'error':'read_only_pickle_capture_required'})
        windows=self.windows()
        if action=='list_windows':return json.dumps({'windows':windows})
        if not any((args.get('pid'),args.get('window_id'))==(w['pid'],w['window_id']) for w in windows):
            return json.dumps({'error':'select_a_listed_pickle_chat_window'})
        if action=='scroll':
            if (self.navigate is None or self.scrolls>=6 or args.get('direction') not in {'up','down'}
                    or type(args.get('element')) is not int or args['element']<0):
                return json.dumps({'error':'bounded_chat_scroll_required'})
            self.call({'action':'capture','pid':args['pid'],'window_id':args['window_id'],'mode':'ax'})
            self.scrolls+=1
            result=self.navigate({'action':'scroll','direction':args['direction'],
                                 'amount':3,'element':args['element']})
            if isinstance(result,str) and '"error"' in result:return result
        return self.call({'action':'capture','pid':args['pid'],'window_id':args['window_id'],
                          'mode':args.get('mode','som')})


SCHEMA={'name':'pickle_bridge_verify_screen',
        'description':'Inspect the actual Pickle chat. First list_windows then capture exact pid/window_id. If the user permission is above the viewport, scroll its chat container using an element from capture (at most six calls). No typing, clicking, focus, other applications, or sharing-indicator windows.',
        'parameters':{'type':'object','properties':{
            'action':{'type':'string','enum':['list_windows','capture','scroll']},
            'element':{'type':'integer'},'direction':{'type':'string','enum':['up','down']},
            'pid':{'type':'integer'},'window_id':{'type':'integer'},
            'mode':{'type':'string','enum':['som','vision','ax']}},'required':['action'],
            'additionalProperties':False}}
