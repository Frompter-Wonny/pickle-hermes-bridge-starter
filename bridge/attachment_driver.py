"""Fixed, background-only computer-use sequence for one approved attachment.

The native open panel is an AXSheet under the Pickle chat's AXWindow.
Its separate CGWindowID is not an actionable AXWindow; never retarget to it.
"""
import hashlib
import time
from pathlib import Path
from .attachments import normalized
from .screen_tools import name
from .store import Denied
from .delivery_driver import targeted_action


class Uploader:
    def __init__(self, backend, approve, front_pid, requests, qid, root_volume_label=None):
        self.backend=backend; self.approve=approve; self.front_pid=front_pid
        self.requests=requests; self.qid=qid; self.target=None
        self.original_front=front_pid(); self.path=None; self.fingerprint=None
        self.opened_panel=False;self.upload_started=False
        self.root_volume_label=root_volume_label

    def snapshot(self):
        if self.front_pid()!=self.original_front:
            raise Denied('active_app_changed_during_attachment')
        pid,wid=self.target
        raw=self.backend._session.call_tool('get_window_state',{
            'pid':pid,'window_id':wid,'tree_format':'elements','include_screenshot':False,
            'max_elements':4000,'timeout_ms':10000})
        data=raw.get('structuredContent') or {}
        # Pickle marks virtualized offscreen chat history incomplete even
        # when all visible composer controls are present. Actual walk
        # truncation is rejected; each required control is checked below.
        if (data.get('pid'),data.get('window_id'))!=self.target or data.get('truncated'):
            raise Denied('complete_attachment_snapshot_required')
        rows=data.get('elements')
        if not rows or not data.get('snapshot_id'):
            raise Denied('attachment_surface_unresolved')
        self.backend._snapshot_id=data['snapshot_id']
        self.backend._snapshot_tokens={e['element_index']:e['element_token'] for e in rows if e.get('element_token')}
        return rows

    @staticmethod
    def one(rows, role, labels):
        found=[e for e in rows if e.get('role')==role and name(e.get('label')) in labels and e.get('enabled') is not False]
        if len(found)!=1: raise Denied('attachment_control_not_unique:'+','.join(sorted(labels)))
        return found[0]

    @classmethod
    def directory_entry(cls, rows, labels):
        """Search the current column, never a same-named ancestor column.

        In the supported macOS LTR column view, opening a directory exposes
        its contents in the rightmost AXList under the AXBrowser. The path
        popup is verified after every open before this function is called.
        """
        browsers=[e for e in rows if e.get('role')=='AXBrowser']
        if len(browsers)!=1:raise Denied('file_browser_not_unique')
        columns=[e for e in rows if e.get('role')=='AXList'
                 and e.get('parent_index')==browsers[0]['element_index']
                 and isinstance(e.get('frame'),dict)
                 and e['frame'].get('w',0)>0 and e['frame'].get('h',0)>0
                 and isinstance(e['frame'].get('x'),(int,float))]
        if not columns:raise Denied('directory_column_unavailable')
        right=max(e['frame']['x'] for e in columns)
        current=[e for e in columns if e['frame']['x']==right]
        if len(current)!=1:raise Denied('directory_column_not_unique')
        index=current[0]['element_index'];by_id={e['element_index']:e for e in rows}
        def belongs(row):
            seen=set()
            while row.get('parent_index') in by_id:
                parent=row['parent_index']
                if parent in seen:return False
                if parent==index:return True
                seen.add(parent);row=by_id[parent]
            return False
        return cls.one([e for e in rows if belongs(e)],'AXTextField',labels)

    def click(self, row):
        if self.front_pid()!=self.original_front:raise Denied('active_app_changed_during_attachment')
        args={'action':'click','element':row['element_index'],'pid':self.target[0],
              'window_id':self.target[1],'delivery_mode':'background'}
        self.approve('click',args)
        result=targeted_action(self.backend,'click',row['element_index'])
        if not result.ok: raise Denied('attachment_click_failed')

    def open_directory(self, row):
        if self.front_pid()!=self.original_front:raise Denied('active_app_changed_during_attachment')
        if 'AXOpen' not in row.get('actions',[]):
            raise Denied('directory_open_action_unavailable')
        args={'action':'click','element':row['element_index'],'ax_action':'open',
              'pid':self.target[0],'window_id':self.target[1],'delivery_mode':'background'}
        self.approve('click',args)
        result=self.backend._action('click',{'pid':self.target[0],'window_id':self.target[1],
                'element_token':row['element_token'],'action':'open','delivery_mode':'background'})
        # NSOpenPanel may return AXError(-25205) after actually opening a
        # directory. Never repeat the action: the caller must verify the
        # resulting exact location before taking another step.
        return result

    def visible_entry(self, rows, labels):
        """Bring the exact current-column row into view before AXOpen.

        NSOpenPanel exposes offscreen filename nodes with 2x2 frames; AXOpen
        on those nodes can silently do nothing. Scroll only that column.
        """
        for attempt in range(16):
            row=self.directory_entry(rows,labels)
            by_id={e['element_index']:e for e in rows}
            column=row;seen=set()
            while column.get('role')!='AXList':
                parent=column.get('parent_index')
                if parent not in by_id or parent in seen:raise Denied('file_entry_column_missing')
                seen.add(parent);column=by_id[parent]
            f=row.get('frame') or {};c=column.get('frame') or {}
            # AXList's height can span all contents, not the visible viewport.
            # Its AXBrowser ancestor is the clipping rectangle in column view.
            ancestor=column;parents=set()
            while ancestor.get('role')!='AXBrowser':
                parent=ancestor.get('parent_index')
                if parent not in by_id or parent in parents:raise Denied('file_browser_clip_missing')
                parents.add(parent);ancestor=by_id[parent]
            clip=ancestor.get('frame') or {}
            top=max(c.get('y',0),clip.get('y',0))
            bottom=min(c.get('y',0)+c.get('h',0),clip.get('y',0)+clip.get('h',0))
            if (f.get('w',0)>3 and f.get('h',0)>3
                    and top<=f.get('y',-1)
                    and f.get('y',0)+f.get('h',0)<=bottom):
                return rows,row
            if attempt==15:raise Denied('file_entry_not_visible_after_bounded_scroll')
            direction='up' if f.get('h',0)>3 and f.get('y',0)<top else 'down'
            args={'action':'scroll','element':column['element_index'],'direction':direction,
                  'amount':3,'pid':self.target[0],'window_id':self.target[1],'delivery_mode':'background'}
            if self.front_pid()!=self.original_front:raise Denied('active_app_changed_during_attachment')
            self.approve('scroll',args)
            result=targeted_action(self.backend,'scroll',column['element_index'],direction=direction,amount=3)
            if not result.ok:raise Denied('file_column_background_scroll_failed:'+str(result.code))
            rows=self.snapshot()
        raise Denied('file_entry_not_visible')

    @staticmethod
    def favorite_cell(rows, ordinal):
        """Use the operator-observed favorite position, then verify its path.

        Some driver versions omit attributed sidebar row names. Do not guess
        names or try multiple favorites: pick one configured row, validate the
        full location ancestry before any file can be opened.
        """
        if type(ordinal) is not int or ordinal<0:raise Denied('invalid_favorite_ordinal')
        groups=[];current=None
        for row in sorted((e for e in rows if e.get('role')=='AXRow'),key=lambda e:e['element_index']):
            cells=[e for e in rows if e.get('role')=='AXCell' and e.get('parent_index')==row['element_index']]
            if not cells:
                current=[];groups.append(current)
            elif current is not None:
                if len(cells)!=1:raise Denied('favorite_cell_not_unique')
                current.append(cells[0])
        if not groups or ordinal>=len(groups[0]):raise Denied('configured_favorite_not_visible')
        return groups[0][ordinal]

    def favorite_binding(self):
        import json
        config=getattr(self.requests,'favorites_path',None)
        if config is None or not Path(config).is_file():return None
        candidates=[]
        for item in json.loads(Path(config).read_text()).get('favorites',[]):
            root=Path(item['root'])
            if root!=root.resolve(strict=True) or not root.is_dir():raise Denied('favorite_root_must_be_real_directory')
            if self.path.is_relative_to(root):candidates.append((root,item))
        if not candidates:return None
        candidates.sort(key=lambda pair:len(pair[0].parts),reverse=True)
        if len(candidates)>1 and candidates[0][0]==candidates[1][0]:raise Denied('favorite_binding_not_unique')
        return candidates[0]

    def open_favorite(self,rows,binding,root_label,aliases):
        root,item=binding
        self.open_directory(self.favorite_cell(rows,item['ordinal']))
        rows=self.snapshot()
        popup=self.one(rows,'AXPopUpButton',{'위치:','where:'})
        if name(popup.get('value'))!=name(root.name):raise Denied('favorite_location_changed')
        self.click(popup);rows=self.snapshot()
        entries=sorted((e for e in rows if e.get('role')=='AXMenuItem'),key=lambda e:e['element_index'])
        expected=[aliases.get(part,{name(part)}) for part in reversed(root.parts[1:])]+[{name(root_label)}]
        if len(entries)<len(expected) or any(name(e.get('label')) not in allowed for e,allowed in zip(entries,expected)):
            raise Denied('favorite_full_path_not_verified')
        self.click(entries[0]);rows=self.snapshot()
        return rows,root

    def navigate(self, rows):
        import json
        root_label=self.root_volume_label
        if root_label is None:
            policy=json.loads(self.requests.policy_path.read_text())
            root_label=policy.get('root_volume_label')
        if not isinstance(root_label,str) or not root_label:raise Denied('root_volume_label_required')
        # Translate only OS-localized path components. Other names are exact.
        aliases={'Users':{'users','사용자'},'Documents':{'documents','문서'},
                 'Desktop':{'desktop','데스크탑'},'Library':{'library','라이브러리'},
                 'Applications':{'applications','응용 프로그램'}}
        binding=self.favorite_binding()
        if binding:
            rows,root=self.open_favorite(rows,binding,root_label,aliases)
            parts=self.path.relative_to(root).parts[:-1]
        else:
            if getattr(self.requests,'require_favorite',False):raise Denied('configured_staging_favorite_required')
            self.click(self.one(rows,'AXPopUpButton',{'위치:','where:'}))
            rows=self.snapshot()
            self.click(self.one(rows,'AXMenuItem',{name(root_label)}))
            rows=self.snapshot()
            popup=self.one(rows,'AXPopUpButton',{'위치:','where:'})
            if name(popup.get('value'))!=name(root_label):raise Denied('root_volume_not_verified')
            parts=self.path.parts[1:-1]
        for part in parts:
            labels=aliases.get(part,{name(part)})
            rows,row=self.visible_entry(rows,labels)
            self.open_directory(row)
            rows=self.snapshot()
            popup=self.one(rows,'AXPopUpButton',{'위치:','where:'})
            # AXOpen can return before NSOpenPanel finishes switching its
            # current directory. Observe completion; never repeat AXOpen.
            for _ in range(10):
                if name(popup.get('value')) in labels:break
                time.sleep(.1);rows=self.snapshot()
                popup=self.one(rows,'AXPopUpButton',{'위치:','where:'})
            if name(popup.get('value')) not in labels:
                raise Denied('directory_navigation_not_verified:'+part+':'+str(popup.get('value')))
        # The location was verified after every exact directory open. AXPress
        # on an NSOpenPanel filename does not select it reliably; AXOpen is
        # the native file-open action and may upload immediately.
        rows,_=self.visible_entry(rows,{name(self.path.name)})
        return rows

    def unchanged(self):
        item=self.requests.resolve(self.qid)
        path=Path(item['path'])
        if path!=self.path or hashlib.sha256(path.read_bytes()).hexdigest()!=self.fingerprint:
            raise Denied('attachment_file_changed')

    def run(self):
        try:return self._run()
        except Exception:
            # Only our own pre-upload picker may be dismissed. Once AXOpen
            # could have uploaded a file, preserve the uncertain state.
            if self.opened_panel and not self.upload_started:
                try:
                    rows=self.snapshot()
                    self.one(rows,'AXSheet',{'열기','open'})
                    self.click(self.one(rows,'AXButton',{'취소','cancel'}))
                    self.snapshot()
                except Exception:pass  # Focus/user changes prohibit cleanup too.
            raise

    def _run(self):
        item=self.requests.resolve(self.qid)
        self.path=Path(item['path'])
        self.fingerprint=hashlib.sha256(self.path.read_bytes()).hexdigest()
        windows=[w for w in self.backend.list_windows() if name(w.get('app_name')) in {'피클','pickle'}
                 and name(w.get('title')) in {'피클','pickle'} and not w.get('off_screen')]
        if len(windows)!=1: raise Denied('pickle_chat_not_unique')
        self.target=(windows[0]['pid'],windows[0]['window_id'])
        self.backend.capture(mode='ax',pid=self.target[0],window_id=self.target[1])
        rows=self.snapshot()
        field=self.one(rows,'AXTextArea',{'메시지 보내기','message'})
        if field.get('value','') or any(e.get('role')=='AXSheet' or
                (e.get('role')=='AXButton' and name(e.get('label')) in {'첨부 삭제','remove attachment','보내기','send'}) for e in rows):
            raise Denied('existing_draft_attachment_or_sheet')
        self.click(self.one(rows,'AXButton',{'첨부 추가','add attachment'}))
        rows=self.snapshot()
        self.click(self.one(rows,'AXButton',{'파일','file','files'}))
        self.opened_panel=True
        rows=self.snapshot()
        self.one(rows,'AXSheet',{'열기','open'})
        rows=self.navigate(rows)
        self.unchanged()
        self.requests.status(self.qid,'opening')
        self.upload_started=True
        self.open_directory(self.directory_entry(rows,{name(self.path.name)}))
        rows=self.snapshot()
        if any(e.get('role')=='AXSheet' for e in rows):
            selected=[e for e in rows if e.get('role')=='AXTextField' and e.get('selected') is True
                      and normalized(e.get('value',e.get('label','')))==normalized(self.path.name)]
            if len(selected)!=1:raise Denied('exact_selected_file_not_verified')
            self.unchanged()
            self.click(self.one(rows,'AXButton',{'열기','open'}))
            rows=self.snapshot()
        for _ in range(20):
            if any(e.get('role')=='AXButton' and name(e.get('label')) in {'첨부 삭제','remove attachment'} for e in rows):break
            time.sleep(.25); rows=self.snapshot()
        removes=[e for e in rows if e.get('role')=='AXButton' and name(e.get('label')) in {'첨부 삭제','remove attachment'}]
        if len(removes)!=1 or any(e.get('role')=='AXSheet' for e in rows):
            raise Denied('single_attachment_draft_required')
        field=self.one(rows,'AXTextArea',{'메시지 보내기','message'})
        if field.get('value',''):raise Denied('user_draft_appeared')
        self.requests.status(self.qid,'attached')
        self.unchanged()
        # Re-capture once more immediately before the single send click.
        rows=self.snapshot()
        if self.one(rows,'AXTextArea',{'메시지 보내기','message'}).get('value',''):
            raise Denied('user_draft_appeared')
        self.one(rows,'AXButton',{'첨부 삭제','remove attachment'})
        send=self.one(rows,'AXButton',{'보내기','send'})
        self.requests.status(self.qid,'sending')
        self.click(send)
        self.requests.status(self.qid,'sent_unconfirmed')
        # Do not equate disappearing draft with actual receipt. The worker
        # separately checks the visible outgoing card/assistant receipt.
        self.snapshot()
        return {'status':'sent_unconfirmed'}
