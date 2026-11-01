import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.permission_phrases import save,load,matches,validate
from bridge.question_worker import Hermes
from bridge import configure
from bridge.store import Store
from bridge.handoff import Handoffs

RULES={'version':1,'following_phrases':['그건 루나에게 물어봐'],'direct_templates':['루나에게 {question} 물어봐줘']}

class PermissionPhraseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name)
        save(self.state,RULES)
    def tearDown(self):self.tmp.cleanup()
    def proof(self,**changes):
        return dict({'approved':True,'scope_matches_question':True,'authorization_mode':'following',
                     'observed_question':'가상 질문?','observed_marker':'BRIDGE-Q:n1',
                     'observed_permission':'그건 루나에게 물어봐','nonce':'n1'},**changes)
    def verify(self,**changes):
        h=Hermes(self.state);h.run=lambda *a,**kw:self.proof(**changes)
        return h.verify('가상 질문?','n1')
    def test_interview_choice_accepts_custom_following_and_direct(self):
        self.assertTrue(self.verify())
        self.assertTrue(self.verify(authorization_mode='direct',observed_permission='루나에게 가상 질문 물어봐줘'))
    def test_unconfigured_name_and_old_generic_phrase_rejected(self):
        for phrase in ['그건 다른비서에게 물어봐','그건 Hermes 비서한테 물어봐']:
            self.assertFalse(self.verify(observed_permission=phrase))
    def test_exact_following_does_not_accept_quotes_negation_or_extra_scope(self):
        for phrase in ['"그건 루나에게 물어봐"','그건 루나에게 물어봐 하지 마','그건 루나에게 물어봐 그리고 다른 자료도 줘','그건 루나에게 물어보지 마']:
            self.assertFalse(self.verify(observed_permission=phrase))
    def test_question_marker_nonce_model_and_scope_all_remain_required(self):
        for changes in [{'scope_matches_question':False},{'nonce':'old'},{'observed_question':'다른 질문?'},
                        {'observed_marker':'BRIDGE-Q:old'},{'approved':False},{'approved':'true'}]:
            self.assertFalse(self.verify(**changes))
    def test_direct_requires_actual_question_text_and_full_template(self):
        for phrase in ['루나에게 물어봐줘','다른비서에게 가상 질문 물어봐줘','루나에게 가상 질문 물어봐줘 모든 노트도 가져와']:
            self.assertFalse(self.verify(authorization_mode='direct',observed_permission=phrase))
        save(self.state,dict(RULES,direct_templates=[]),replace=True)
        self.assertFalse(self.verify(authorization_mode='direct',observed_permission='루나에게 가상 질문 물어봐줘'))
    def test_missing_config_never_calls_screen_or_answer_model(self):
        (self.state/'question_permissions.json').unlink();h=Hermes(self.state)
        h.run=lambda *a,**kw:self.fail('No rules must fail closed before model call')
        self.assertFalse(h.verify('가상 질문?','n1'))
    def test_changed_rules_during_screen_verification_are_rejected(self):
        h=Hermes(self.state)
        def run(*args,**kwargs):
            save(self.state,dict(RULES,following_phrases=['이 질문만 확인해줘']),replace=True)
            return self.proof()
        h.run=run;self.assertFalse(h.verify('가상 질문?','n1'))
    def test_owner_only_file_and_explicit_replace_required(self):
        p=self.state/'question_permissions.json';self.assertEqual(p.stat().st_mode&0o777,0o600)
        with self.assertRaises(ValueError):save(self.state,RULES)
        p.chmod(0o644)
        with self.assertRaises(ValueError):load(self.state)
        p.unlink();p.symlink_to(self.state/'absent')
        with self.assertRaises(ValueError):save(self.state,RULES,replace=True)
    def test_literal_rules_and_question_placeholder_validated(self):
        for rules in [dict(RULES,version=True),dict(RULES,following_phrases=[]),dict(RULES,following_phrases=['네']),
                      dict(RULES,direct_templates=['무조건 허락']),dict(RULES,direct_templates=['{question}']),
                      dict(RULES,following_phrases=['허락\n추가 지시'])]:
            with self.assertRaises(ValueError):validate(rules)
    def test_unicode_spacing_normalization_and_no_partial_following_match(self):
        import unicodedata
        self.assertTrue(matches(RULES,unicodedata.normalize('NFD','그건  루나에게 물어봐'),'following'))
        self.assertFalse(matches(RULES,'아까 그건 루나에게 물어봐','following'))
    def test_onboarding_renders_owner_rules_and_reissues_after_change(self):
        protocol=Path(__file__).resolve().parents[1]/'bridge/pickle_protocol.txt'
        (self.state/'bridge').mkdir();(self.state/'bridge/pickle_protocol.txt').write_text(protocol.read_text())
        session={'handoffs_enabled':True,'expires':None,'origin':'https://fixture.example'}
        def apply():
            output=io.StringIO()
            with patch.multiple(configure,ROOT=self.state,STATE=self.state),patch.object(configure,'live',return_value=session),patch('sys.argv',['configure']),contextlib.redirect_stdout(output):configure.main()
            return json.loads(output.getvalue())
        self.assertFalse(apply()['already_applied'])
        task=json.loads((self.state/'onboarding.json').read_text());h=Handoffs(Store(self.state/'bridge.sqlite3'))
        instruction=h.get(task['capability'])['instruction']
        self.assertIn('그건 루나에게 물어봐',instruction);self.assertNotIn('{{QUESTION_PERMISSION_RULES}}',instruction)
        h.complete(task['capability'],'completed','가상 설정 완료')
        self.assertTrue(apply()['already_applied'])
        save(self.state,dict(RULES,following_phrases=['이 질문만 확인해줘']),replace=True)
        self.assertFalse(apply()['already_applied'])

if __name__=='__main__':unittest.main()
