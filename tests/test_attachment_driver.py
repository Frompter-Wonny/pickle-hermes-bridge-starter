import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from bridge.attachment_driver import Uploader
from bridge.store import Denied


class AttachmentDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'fixture.md'
        self.path.write_text('fictional content');self.calls=[];self.statuses=[]
        self.requests=SimpleNamespace(resolve=lambda q:{'path':str(self.path)},
            status=lambda q,s:self.statuses.append(s))
        self.backend=SimpleNamespace(list_windows=lambda:[{'pid':1,'window_id':2,'title':'Pickle','app_name':'Pickle'}],
            capture=lambda **kw:None)
        self.u=Uploader(self.backend,lambda *a:self.calls.append(a),lambda:99,self.requests,'fixture-id')
    def tearDown(self):self.tmp.cleanup()

    def test_existing_text_or_attachment_never_mutates_ui(self):
        base=[{'role':'AXTextArea','label':'메시지 보내기','value':''}]
        for rows in [[dict(base[0],value='user draft')],base+[{'role':'AXButton','label':'첨부 삭제'}],
                     base+[{'role':'AXSheet','label':'Open'}]]:
            self.u.snapshot=lambda:rows
            with self.assertRaises(Denied):self.u.run()
        self.assertFalse(self.calls);self.assertFalse(self.statuses)

    def test_focus_change_or_partial_capture_fails_before_any_action(self):
        self.u.target=(1,2);self.u.front_pid=lambda:123
        with self.assertRaises(Denied):self.u.snapshot()
        self.assertFalse(self.calls)

    def test_file_change_after_authorization_stops_upload(self):
        import hashlib
        self.u.path=self.path;self.u.fingerprint=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.path.write_text('changed file')
        with self.assertRaises(Denied):self.u.unchanged()

    def test_virtualized_history_does_not_hide_required_control_checks(self):
        data={'pid':1,'window_id':2,'snapshot_id':'s00000001','truncated':False,
              'elements_complete':False,'elements':[{'role':'AXTextArea','label':'메시지 보내기',
                  'element_index':7,'element_token':'s00000001:7','value':''}]}
        self.backend._session=SimpleNamespace(call_tool=lambda *args:{'structuredContent':data})
        self.u.target=(1,2)
        rows=self.u.snapshot()
        self.assertEqual(self.u.one(rows,'AXTextArea',{'메시지 보내기'})['value'],'')
        with self.assertRaises(Denied):self.u.one(rows,'AXButton',{'보내기'})
        data['truncated']=True
        with self.assertRaises(Denied):self.u.snapshot()

    def column_rows(self):
        return [{'element_index':1,'role':'AXBrowser'},
                {'element_index':2,'role':'AXList','parent_index':1,'frame':{'x':100,'w':200,'h':300}},
                {'element_index':3,'role':'AXTextField','label':'SharedName','parent_index':2},
                {'element_index':4,'role':'AXList','parent_index':1,'frame':{'x':300,'w':200,'h':300}},
                {'element_index':5,'role':'AXTextField','label':'SharedName','parent_index':4}]

    def test_duplicate_ancestor_folder_name_only_selects_current_column(self):
        rows=self.column_rows()
        with self.assertRaises(Denied):self.u.one(rows,'AXTextField',{'sharedname'})
        self.assertEqual(self.u.directory_entry(rows,{'sharedname'})['element_index'],5)

    def test_ancestor_match_is_not_a_fallback_for_missing_current_entry(self):
        rows=self.column_rows();rows[-1]['label']='DifferentFile'
        with self.assertRaises(Denied):self.u.directory_entry(rows,{'sharedname'})

    def test_ambiguous_current_column_and_entry_fail_closed(self):
        rows=self.column_rows();rows.append(dict(rows[-1],element_index=6))
        with self.assertRaises(Denied):self.u.directory_entry(rows,{'sharedname'})

        rows=self.column_rows();rows.append(dict(rows[-2],element_index=6))
        with self.assertRaises(Denied):self.u.directory_entry(rows,{'sharedname'})

    def test_cleanup_only_our_preupload_picker_not_uncertain_attachment(self):
        def fail():raise Denied('fixture navigation failure')
        self.u._run=fail;self.u.opened_panel=True
        rows=[{'role':'AXSheet','label':'열기'},
              {'role':'AXButton','label':'취소','element_index':7}]
        self.u.snapshot=lambda:rows
        self.u.click=lambda row:self.calls.append(row['element_index'])
        with self.assertRaises(Denied):self.u.run()
        self.assertEqual(self.calls,[7])
        self.calls.clear();self.u.upload_started=True
        with self.assertRaises(Denied):self.u.run()
        self.assertEqual(self.calls,[])

    def test_directory_ax_error_is_not_retried_and_requires_location_readback(self):
        self.backend._action=lambda action,args:self.calls.append((action,args)) or SimpleNamespace(ok=False)
        self.u.target=(1,2)
        row={'element_index':7,'element_token':'s00000001:7','actions':['AXOpen']}
        self.u.open_directory(row)
        actions=[x for x in self.calls if x[0]=='click' and x[1].get('action')=='open']
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0][1]['delivery_mode'],'background')
        self.assertNotIn('bring_to_front',actions[0][1])

    def test_scroll_uses_browser_viewport_not_full_list_height(self):
        rows=[{'element_index':1,'role':'AXBrowser','frame':{'x':0,'y':0,'w':100,'h':100}},
              {'element_index':2,'role':'AXList','parent_index':1,'frame':{'x':0,'y':0,'w':100,'h':500}},
              {'element_index':3,'role':'AXTextField','label':'Target','parent_index':2,
               'frame':{'x':10,'y':300,'w':60,'h':18}}]
        visible=[dict(e) for e in rows]
        visible[1]['frame']={'x':0,'y':-250,'w':100,'h':500}
        visible[2]['frame']={'x':10,'y':50,'w':60,'h':18}
        self.u.target=(1,2)
        self.backend._last_target={'pid':1,'window_id':2}
        self.backend._snapshot_tokens={2:'s00000001:2'}
        self.backend._session=SimpleNamespace(supports_input_property=lambda *args:True)
        self.backend._action=lambda action,args:self.calls.append((action,args)) or SimpleNamespace(ok=True)
        self.u.snapshot=lambda:visible
        _,row=self.u.visible_entry(rows,{'target'})
        self.assertEqual(row['element_index'],3)
        actions=[x for x in self.calls if x[0]=='scroll' and 'element_token' in x[1]]
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0][1]['direction'],'down')
        self.assertEqual(actions[0][1]['delivery_mode'],'background')

    def test_offscreen_entry_scroll_is_bounded_and_never_opens_file(self):
        rows=[{'element_index':1,'role':'AXBrowser','frame':{'x':0,'y':0,'w':100,'h':100}},
              {'element_index':2,'role':'AXList','parent_index':1,'frame':{'x':0,'y':0,'w':100,'h':500}},
              {'element_index':3,'role':'AXTextField','label':'Target','parent_index':2,
               'frame':{'x':10,'y':300,'w':60,'h':18}}]
        self.u.target=(1,2);self.u.snapshot=lambda:rows
        self.backend._last_target={'pid':1,'window_id':2};self.backend._snapshot_tokens={2:'s00000001:2'}
        self.backend._session=SimpleNamespace(supports_input_property=lambda *args:True)
        self.backend._action=lambda action,args:self.calls.append((action,args)) or SimpleNamespace(ok=True)
        with self.assertRaises(Denied):self.u.visible_entry(rows,{'target'})
        actions=[x for x in self.calls if 'element_token' in x[1]]
        self.assertEqual(len(actions),15)
        self.assertTrue(all(x[0]=='scroll' for x in actions))

    def test_observed_favorite_ordinal_is_scoped_to_favorites_section(self):
        rows=[{'role':'AXRow','element_index':1},{'role':'AXCell','element_index':2,'parent_index':1},
              {'role':'AXRow','element_index':3},
              {'role':'AXRow','element_index':4},{'role':'AXCell','element_index':5,'parent_index':4},
              {'role':'AXRow','element_index':6},{'role':'AXCell','element_index':7,'parent_index':6},
              {'role':'AXRow','element_index':8},
              {'role':'AXRow','element_index':9},{'role':'AXCell','element_index':10,'parent_index':9}]
        self.assertEqual(self.u.favorite_cell(rows,0)['element_index'],5)
        self.assertEqual(self.u.favorite_cell(rows,1)['element_index'],7)
        with self.assertRaises(Denied):self.u.favorite_cell(rows,2)
        with self.assertRaises(Denied):self.u.favorite_cell(rows,-1)

    def test_wrong_favorite_location_stops_before_any_file_open(self):
        self.u.open_directory=lambda row:self.calls.append('favorite')
        self.u.snapshot=lambda:[{'role':'AXPopUpButton','label':'위치:','value':'Wrong Folder'}]
        self.u.favorite_cell=lambda rows,n:{}
        with self.assertRaises(Denied):self.u.open_favorite([], (Path('/approved/operator/Staging'),{'ordinal':0}),'Disk',{})
        self.assertEqual(self.calls,['favorite'])

    def test_favorite_same_basename_different_parent_fails_full_path_check(self):
        self.u.open_directory=lambda row:self.calls.append('favorite')
        self.u.favorite_cell=lambda rows,n:{}
        menu=[{'role':'AXMenuItem','element_index':i,'label':label} for i,label in enumerate(['Staging','different-user','approved','Disk'])]
        self.u.snapshot=__import__('unittest.mock',fromlist=['Mock']).Mock(side_effect=[
            [{'role':'AXPopUpButton','label':'위치:','value':'Staging'}],menu])
        self.u.click=lambda row:self.calls.append('popup')
        with self.assertRaises(Denied):self.u.open_favorite([], (Path('/approved/operator/Staging'),{'ordinal':0}),'Disk',{})
        self.assertEqual(self.calls,['favorite','popup'])

if __name__=='__main__':unittest.main()
