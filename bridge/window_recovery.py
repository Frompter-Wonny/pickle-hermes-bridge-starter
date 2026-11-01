"""Opt-in background launch and minimized chat recovery for installed Pickle."""
import ctypes as C
import json
import os
import time
from pathlib import Path
from .store import Denied
from .screen_tools import name


class ProcessSerialNumber(C.Structure):
    _fields_=[('highLongOfPSN',C.c_uint32),('lowLongOfPSN',C.c_uint32)]


def frontmost_pid():
    # Workspace notifications can remain stale on Hermes worker threads.
    # Read the Window Manager's front process synchronously instead.
    carbon=C.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
    front=carbon.GetFrontProcess;front.argtypes=[C.POINTER(ProcessSerialNumber)];front.restype=C.c_int16
    getpid=carbon.GetProcessPID;getpid.argtypes=[C.POINTER(ProcessSerialNumber),C.POINTER(C.c_int)];getpid.restype=C.c_int16
    serial=ProcessSerialNumber();pid=C.c_int()
    if front(C.byref(serial)) or getpid(C.byref(serial),C.byref(pid)) or pid.value<=0:
        raise Denied('current_front_process_read_failed')
    return pid.value


def recover(api, pause=time.sleep, launch_allowed=False, restore_allowed=True, app_path=None, warmup_allowed=False):
    launched=False
    initial_front=api.front_pid()
    if launch_allowed and not api.running():
        api.launch(app_path)
        launched=True
        for _ in range(120):
            if api.front_pid()!=initial_front:raise Denied('focus_changed_during_pickle_launch')
            if api.running():
                try:ready=api.candidates()
                except Denied:ready=[]
                if ready:break
            pause(.25)
        else:raise Denied('pickle_launch_not_ready_login_or_update_may_be_required')
        if warmup_allowed:api.warmup(initial_front)
    rows=api.candidates()
    if len(rows)!=1:raise Denied('exactly_one_native_pickle_chat_required')
    row=rows[0]
    if row.get('bundle_id')!='com.pickle.client' or name(row.get('title')) not in {'pickle','피클'} or row.get('identifier')!='SceneWindow':
        raise Denied('native_pickle_chat_identity_required')
    before=api.front_pid()
    if api.front_pid()!=initial_front:raise Denied('focus_changed_during_pickle_recovery')
    if not api.minimized(row):return {'restored':False,'launched':launched,'startup_warmup':launched and warmup_allowed,'pid':row['pid'],'reason':'not_minimized','frontmost_unchanged':not (launched and warmup_allowed),'original_front_app_restored':True}
    if not restore_allowed:raise Denied('native_window_restore_consent_required')
    api.restore(row)
    for _ in range(20):
        if api.front_pid()!=before:raise Denied('focus_changed_during_pickle_recovery')
        if not api.minimized(row):
            return {'restored':True,'launched':launched,'startup_warmup':launched and warmup_allowed,'pid':row['pid'],'frontmost_unchanged':not (launched and warmup_allowed),'original_front_app_restored':True}
        pause(.1)
    raise Denied('pickle_window_restore_not_verified')


class MacWindows:
    def __init__(self,initialize=None):
        self.initialize=initialize
        from AppKit import NSRunningApplication,NSWorkspace
        self.apps=NSRunningApplication;self.workspace=NSWorkspace.sharedWorkspace();self.refs=[]
        self.cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.ax=C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
        def bind(lib,n,args,result):
            fn=getattr(lib,n);fn.argtypes=args;fn.restype=result;return fn
        ptr=C.c_void_p; i=C.c_int; lng=C.c_long
        self.create=bind(self.ax,'AXUIElementCreateApplication',[i],ptr)
        self.copy=bind(self.ax,'AXUIElementCopyAttributeValue',[ptr,ptr,C.POINTER(ptr)],i)
        self.set=bind(self.ax,'AXUIElementSetAttributeValue',[ptr,ptr,ptr],i)
        self.string=bind(self.cf,'CFStringCreateWithCString',[ptr,C.c_char_p,C.c_uint32],ptr)
        self.readstring=bind(self.cf,'CFStringGetCString',[ptr,C.c_void_p,lng,C.c_uint32],C.c_bool)
        self.count=bind(self.cf,'CFArrayGetCount',[ptr],lng)
        self.item=bind(self.cf,'CFArrayGetValueAtIndex',[ptr,lng],ptr)
        self.boolean=bind(self.cf,'CFBooleanGetValue',[ptr],C.c_bool)
        self.typeid=bind(self.cf,'CFGetTypeID',[ptr],C.c_ulong)
        self.stringtype=bind(self.cf,'CFStringGetTypeID',[],C.c_ulong)()
        self.booltype=bind(self.cf,'CFBooleanGetTypeID',[],C.c_ulong)()
        self.arraytype=bind(self.cf,'CFArrayGetTypeID',[],C.c_ulong)()
        self.release=bind(self.cf,'CFRelease',[ptr],None)
        self.false=ptr.in_dll(self.cf,'kCFBooleanFalse')

    def close(self):
        for ref in reversed(self.refs):self.release(ref)
        self.refs=[]

    def attr(self,element,key):
        keyref=self.string(None,key.encode(),0x08000100);value=C.c_void_p()
        try:error=self.copy(element,keyref,C.byref(value))
        finally:self.release(keyref)
        if error:raise Denied('native_window_attribute_unavailable_'+key)
        self.refs.append(value);return value

    def text(self,element,key):
        value=self.attr(element,key)
        if self.typeid(value)!=self.stringtype:raise Denied('native_window_string_required')
        buf=C.create_string_buffer(4096)
        if not self.readstring(value,buf,len(buf),0x08000100):raise Denied('native_window_text_unavailable')
        return buf.value.decode('utf-8')

    def candidates(self):
        rows=[]
        for app in self.apps.runningApplicationsWithBundleIdentifier_('com.pickle.client'):
            if app.isTerminated():continue
            pid=int(app.processIdentifier());element=self.create(pid);self.refs.append(element)
            windows=self.attr(element,'AXWindows')
            if self.typeid(windows)!=self.arraytype:raise Denied('native_window_array_required')
            for index in range(self.count(windows)):
                window=self.item(windows,index)
                # No chat text or unrelated application content is read.
                if self.text(window,'AXRole')!='AXWindow':continue
                title=self.text(window,'AXTitle')
                if name(title) not in {'pickle','피클'}:continue
                if self.text(window,'AXIdentifier')!='SceneWindow':continue
                rows.append({'pid':pid,'bundle_id':str(app.bundleIdentifier()),'title':title,
                             'identifier':'SceneWindow','ref':window})
        return rows

    def running(self):
        return any(not app.isTerminated() for app in self.apps.runningApplicationsWithBundleIdentifier_('com.pickle.client'))

    def launch(self,app_path):
        from Foundation import NSBundle
        import subprocess
        path=Path(app_path or '').expanduser()
        # Use an explicitly selected installed bundle; never download or guess a URL.
        if not path.is_absolute() or not path.is_dir() or path.suffix!='.app':raise Denied('installed_pickle_app_path_required')
        bundle=NSBundle.bundleWithPath_(str(path))
        if bundle is None or str(bundle.bundleIdentifier())!='com.pickle.client':raise Denied('installed_pickle_bundle_identity_required')
        result=subprocess.run(['/usr/bin/open','-g','-a',str(path)],capture_output=True,timeout=15)
        if result.returncode:raise Denied('pickle_background_launch_failed')

    def warmup(self,previous_pid):
        from AppKit import NSApplicationActivateIgnoringOtherApps
        if self.front_pid()!=previous_pid:raise Denied('front_app_changed_before_startup_warmup')
        apps=[a for a in self.apps.runningApplicationsWithBundleIdentifier_('com.pickle.client') if not a.isTerminated()]
        previous=self.apps.runningApplicationWithProcessIdentifier_(previous_pid)
        if len(apps)!=1 or previous is None or previous.isTerminated():raise Denied('startup_warmup_restore_target_required')
        target=apps[0];pid=int(target.processIdentifier())
        try:
            if not target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps):raise Denied('startup_activation_refused')
            for _ in range(20):
                if self.front_pid()==pid:break
                time.sleep(.05)
            else:raise Denied('startup_activation_not_verified')
            # Let the newly launched UIKit input system initialize, without
            # typing, pasting, or sending while this app is foreground.
            if self.initialize is None:raise Denied('startup_composer_initializer_required')
            self.initialize(pid)
            time.sleep(.5)
            if self.front_pid()!=pid:raise Denied('user_changed_front_app_during_startup')
        finally:
            if self.front_pid()==pid:
                previous.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                for _ in range(20):
                    if self.front_pid()==previous_pid:break
                    time.sleep(.05)
        if self.front_pid()!=previous_pid:raise Denied('startup_previous_app_restore_not_verified')

    def front_pid(self):return frontmost_pid()

    def minimized(self,row):
        value=self.attr(row['ref'],'AXMinimized')
        if self.typeid(value)!=self.booltype:raise Denied('native_minimized_boolean_required')
        return bool(self.boolean(value))

    def restore(self,row):
        key=self.string(None,b'AXMinimized',0x08000100)
        try:error=self.set(row['ref'],key,self.false)
        finally:self.release(key)
        if error:raise Denied('native_pickle_restore_refused')


def configured_recovery(root,initialize=None):
    root=Path(root);prefs=json.loads((root/'.runtime/delivery_preferences.json').read_text())
    restore=prefs.get('native_window_restore_consent') is True
    launch=prefs.get('native_app_launch_consent') is True
    if not restore and not launch:raise Denied('native_window_recovery_consent_required')
    api=MacWindows(initialize)
    try:
        result=recover(api,launch_allowed=launch,restore_allowed=restore,app_path=prefs.get('pickle_app_path'),warmup_allowed=prefs.get('native_launch_warmup_consent') is True)
        if result.get('restored') or result.get('launched'):
            fd=os.open(root/'.runtime/window-recovery.jsonl',os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
            with os.fdopen(fd,'w') as f:f.write(json.dumps({'event':'pickle_recovered','restored':result.get('restored',False),'launched':result.get('launched',False),'startup_warmup':result.get('startup_warmup',False),'original_front_app_restored':True,'at':time.time()})+'\n')
        return result
    finally:api.close()


def optional_recovery(root,initialize=None):
    path=Path(root)/'.runtime/delivery_preferences.json'
    if not path.exists():return None
    prefs=json.loads(path.read_text())
    if not any(prefs.get(k) is True for k in ['native_window_restore_consent','native_app_launch_consent']):return None
    return configured_recovery(root,initialize)
