import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.preflight import report,Host,main
from bridge.permission_phrases import save

class FakeHost:
    def __init__(self):self.os='Darwin';self.mac='14.5';self.arm=True;self.version=[3,11,9];self.cocoa='13.0';self.ports=set()
    def system(self):return self.os
    def mac_version(self):return self.mac
    def apple_silicon(self):return self.arm
    def python_info(self,p):return {'version':self.version,'cocoa':self.cocoa}
    def port_open(self,p):return p in self.ports

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.root=self.base/'source';self.root.mkdir();self.host=FakeHost()
        self.hermes=self.base/'hermes';self.hermes.mkdir()
        definitions={'cli.py':'','tools/registry.py':'','toolsets.py':'def create_custom_toolset():pass\ndef resolve_multiple_toolsets():pass\n',
          'tools/computer_use/tool.py':'def set_approval_callback():pass\ndef _request_approval():pass\ndef _get_backend():pass\n',
          'tools/computer_use/cua_backend.py':'def _action():pass\ndef _set_active_target():pass\ndef _clear_active_target():pass\n','tools/computer_use/cua_backend_capture.py':'def _gws_args():pass\ndef _fetch_or_refetch():pass\n'}
        for f,text in definitions.items():
            p=self.hermes/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        p=self.hermes/'venv/bin/python';p.parent.mkdir(parents=True);p.write_text('fixture, never executed');p.chmod(0o700)
        self.app=self.base/'Example.app';(self.app/'Contents').mkdir(parents=True)
        with (self.app/'Contents/Info.plist').open('wb') as f:plistlib.dump({'CFBundleIdentifier':'com.pickle.client'},f)
    def tearDown(self):self.tmp.cleanup()
    def run_report(self,**kw):return report(self.root,self.hermes,self.app,host=self.host,**kw)
    def statuses(self,r):return {x['id']:x['status'] for x in r['checks']}
    def private(self,path,value):path.write_text(json.dumps(value));path.chmod(0o600)
    def configure(self):
        state=self.root/'.runtime';state.mkdir(mode=0o700)
        notes=self.base/'notes';notes.mkdir()
        self.private(state/'question_sources.json',{'fixture':str(notes)})
        self.private(state/'tunnel.json',{'provider':'ngrok','origin':'https://fixture.ngrok-free.dev'})
        self.private(state/'ngrok.yml',{'authtoken':'PRIVATE_SENTINEL_DO_NOT_OUTPUT'})
        p=state/'ngrok';p.write_text('fixture');p.chmod(0o700)
        save(state,{'version':1,'following_phrases':['이 질문만 확인해줘'],'direct_templates':[]})
        return state
    def test_valid_prerequisites_still_do_not_claim_actual_connection(self):
        r=self.run_report();self.assertEqual(r['automatic_blockers'],0)
        self.assertFalse(r['end_to_end_verified']);self.assertTrue(r['read_only'])
        self.assertEqual(self.statuses(r)['os_permissions'],'manual')
    def test_unsupported_os_hardware_and_version_block(self):
        for attr,value,key in [('os','Linux','macos'),('arm',False,'apple_silicon'),('mac','13.6','macos_version')]:
            with self.subTest(attr=attr):
                old=getattr(self.host,attr);setattr(self.host,attr,value)
                self.assertEqual(self.statuses(self.run_report())[key],'block');setattr(self.host,attr,old)
    def test_hermes_python_310_or_missing_source_block(self):
        self.host.version=[3,10,9];self.assertEqual(self.statuses(self.run_report())['hermes_python'],'block')
        (self.hermes/'cli.py').unlink();self.assertEqual(self.statuses(self.run_report())['hermes_source'],'block')
    def test_internal_api_missing_blocks_and_snapshot_unknown_warns(self):
        (self.hermes/'tools/computer_use/tool.py').write_text('def _get_backend():pass')
        (self.hermes/'tools/computer_use/cua_backend_capture.py').write_text('pass')
        statuses=self.statuses(self.run_report());self.assertEqual(statuses['hermes_interfaces'],'block');self.assertEqual(statuses['snapshot_support'],'warn')
    def test_original_capture_without_local_snapshot_patch_is_adapter_ready(self):
        statuses=self.statuses(self.run_report())
        self.assertEqual(statuses['hermes_interfaces'],'pass')
        self.assertEqual(statuses['snapshot_support'],'pass')
    def test_missing_native_dependency_blocks_configured_phase(self):
        self.host.cocoa=None
        self.assertEqual(self.statuses(self.run_report())['native_dependency'],'warn')
        self.assertEqual(self.statuses(self.run_report(phase='configured'))['native_dependency'],'block')
    def test_wrong_app_bundle_rejected_without_launch(self):
        with (self.app/'Contents/Info.plist').open('wb') as f:plistlib.dump({'CFBundleIdentifier':'other.fixture'},f)
        self.assertEqual(self.statuses(self.run_report())['pickle_app'],'block')
    def test_ios_wrapper_bundle_is_detected(self):
        (self.app/'Contents/Info.plist').unlink();p=self.app/'Wrapper/Example.app/Info.plist';p.parent.mkdir(parents=True)
        with p.open('wb') as f:plistlib.dump({'CFBundleIdentifier':'com.pickle.client'},f)
        self.assertEqual(self.statuses(self.run_report())['pickle_app'],'pass')
    def test_occupied_ports_block_new_install_and_require_existing_review(self):
        self.host.ports={8766,4041}
        self.assertEqual(self.statuses(self.run_report())['port_8766'],'block')
        self.configure();self.assertEqual(self.statuses(self.run_report())['port_8766'],'manual')
    def test_configured_state_validates_sources_auth_and_permission_rules(self):
        state=self.configure();r=self.run_report(phase='configured');self.assertEqual(r['automatic_blockers'],0)
        self.assertEqual(self.statuses(r)['permission_phrases'],'pass')
        (state/'question_permissions.json').unlink();self.assertEqual(self.statuses(self.run_report(phase='configured'))['permission_phrases'],'block')
    def test_world_readable_and_scalar_settings_do_not_crash_or_pass(self):
        state=self.configure();p=state/'delivery_preferences.json';self.private(p,[])
        self.assertEqual(self.statuses(self.run_report())['delivery_preferences'],'block')
        p.chmod(0o644);self.assertEqual(self.statuses(self.run_report())['delivery_preferences'],'block')
        state.chmod(0o755);self.assertEqual(self.statuses(self.run_report())['private_state'],'block')
    def test_favorites_validate_paths_and_coverage_but_require_real_ui(self):
        state=self.configure();home=self.base/'home';home.mkdir();staging=home/'PickleUploadStaging';staging.mkdir()
        self.private(state/'file_picker_favorites.json',{'favorites':[{'root':str(staging),'ordinal':0}]})
        with patch('tools.preflight.Path.home',return_value=home):
            statuses=self.statuses(self.run_report(phase='configured',files=True))
        self.assertEqual(statuses['favorite_bindings'],'pass');self.assertEqual(statuses['staging_favorite'],'pass');self.assertEqual(statuses['favorite_ui'],'manual')
        self.private(state/'file_picker_favorites.json',{'favorites':[{'root':str(staging),'ordinal':True}]})
        self.assertEqual(self.statuses(self.run_report(phase='configured',files=True))['favorite_bindings'],'block')
    def test_automatic_delivery_never_enables_or_invents_consent(self):
        state=self.configure();self.assertEqual(self.statuses(self.run_report(phase='configured',automatic=True))['automatic_delivery_consent'],'block')
        self.assertFalse((state/'delivery_preferences.json').exists())
    def test_report_does_not_disclose_private_values_paths_or_names(self):
        state=self.configure();secret='PRIVATE_SENTINEL_DO_NOT_OUTPUT'
        self.private(state/'tunnel.json',{'provider':'ngrok','origin':secret})
        self.private(state/'file_picker_favorites.json',{'favorites':[{'root':secret,'ordinal':0}]})
        text=json.dumps(self.run_report(phase='configured',files=True),ensure_ascii=False)
        self.assertNotIn(secret,text);self.assertNotIn(str(self.base),text);self.assertNotIn('authtoken',text)
    def test_report_leaves_config_contents_and_mtimes_unchanged(self):
        self.configure();before={str(p): (p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.run_report(phase='configured',files=True,automatic=True)
        after={str(p): (p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_standing_file_root_without_favorite_coverage_is_blocked(self):
        state=self.configure();approved=self.base/'approved';approved.mkdir();other=self.base/'other';other.mkdir()
        self.private(state/'file_picker_favorites.json',{'favorites':[{'root':str(approved),'ordinal':0}]})
        self.private(state/'attachment_policy.json',{'enabled':True,'destination':'pickle_own_chat','collections':[{'root':str(other)}]})
        self.assertEqual(self.statuses(self.run_report(phase='configured',files=True))['standing_file_policy'],'block')

    def test_symlink_and_invalid_config_are_rejected_without_reading_target(self):
        state=self.configure();p=state/'question_permissions.json';target=self.base/'secret.json';self.private(target,{'private':'DO_NOT_PRINT'})
        p.unlink();p.symlink_to(target)
        self.assertEqual(self.statuses(self.run_report(phase='configured'))['permission_phrases'],'block')
        self.private(state/'question_sources.json',{'vault':str(self.base/'absent')})
        self.assertEqual(self.statuses(self.run_report(phase='configured'))['note_sources'],'block')

    def test_cli_sanitizes_os_errors_and_returns_blocked_json(self):
        import contextlib,io
        output=io.StringIO()
        with patch('tools.preflight.report',side_effect=PermissionError('PRIVATE_ERROR_SENTINEL')),patch('sys.argv',['preflight','--json']),contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:main()
        self.assertEqual(raised.exception.code,1);self.assertNotIn('PRIVATE_ERROR_SENTINEL',output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['automatic_blockers'],1)

if __name__=='__main__':unittest.main()
