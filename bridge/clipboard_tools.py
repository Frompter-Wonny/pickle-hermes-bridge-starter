"""Optional, not yet enabled: preserve clipboard formats around native Paste.

AppKit is loaded only when explicitly enabled by the operator. No contents are
logged, written to disk, or returned to the model. Tests use an in-memory board.
"""
from .store import Denied


def original_formats_preserved(original,observed):
    # macOS may reorder type names and synthesize extra legacy aliases. Every
    # original item/type must nevertheless retain exactly its original bytes.
    return (len(original)==len(observed) and all(
        all(dict(actual).get(kind)==data for kind,data in expected)
        for expected,actual in zip(original,observed)))


class TemporaryClipboard:
    def __init__(self,board,text):
        self.board=board;self.text=text;self.original=None;self.written_count=None
        self.restored=False;self.external_change=False

    def __enter__(self):
        count=self.board.change_count()
        self.original=self.board.snapshot()
        validate=getattr(self.board,'validate_snapshot',None)
        if validate:validate(self.original)
        if self.board.change_count()!=count:
            self.original=None;raise Denied('clipboard_changed_before_paste')
        try:self.board.write_text(self.text)
        except Exception:
            # Roll back only a mutation the board adapter can still attribute
            # to this write; never overwrite a later user copy.
            owned=getattr(self.board,'last_owned_write_count',None)
            if owned is not None and self.board.change_count()==owned:
                self.board.restore(self.original);self.restored=True
            self.original=None;self.text=None
            raise
        self.written_count=self.board.change_count()
        return self

    def ensure_unchanged(self):
        if self.board.change_count()!=self.written_count:
            self.external_change=True;raise Denied('clipboard_changed_during_paste')

    def __exit__(self,*_):
        try:
            if self.board.change_count()==self.written_count:
                self.board.restore(self.original)
                if not original_formats_preserved(self.original,self.board.snapshot()):
                    raise Denied('clipboard_restore_readback_failed')
                self.restored=True
            else:self.external_change=True
        finally:self.original=None;self.text=None


class AppKitBoard:
    def __init__(self):
        # This is a native clipboard API, not keyboard synthesis or app focus.
        # Do not instantiate without the user's explicit native-helper consent.
        from AppKit import NSPasteboard,NSPasteboardItem
        from Foundation import NSData
        self.board=NSPasteboard.generalPasteboard()
        self.item_class=NSPasteboardItem;self.data_class=NSData

    def change_count(self):return int(self.board.changeCount())

    def snapshot(self):
        result=[]
        for item in self.board.pasteboardItems() or []:
            formats=[]
            for type_name in item.types():
                data=item.dataForType_(type_name)
                if data is None:raise Denied('clipboard_format_cannot_be_preserved')
                formats.append((str(type_name),bytes(data)))
            result.append(formats)
        return result

    def write_text(self,text):
        item=self.item_class.alloc().init()
        if not item.setString_forType_(text,'public.utf8-plain-text'):
            raise Denied('clipboard_write_failed')
        self.last_owned_write_count=int(self.board.clearContents())
        if not self.board.writeObjects_([item]):raise Denied('clipboard_write_failed')
        self.last_owned_write_count=self.change_count()

    def restore(self,snapshot):
        items=self.validate_snapshot(snapshot)
        self.board.clearContents()
        if items and not self.board.writeObjects_(items):raise Denied('clipboard_restore_failed')

    def validate_snapshot(self,snapshot):
        items=[]
        for formats in snapshot:
            item=self.item_class.alloc().init()
            for type_name,data in formats:
                native=self.data_class.dataWithBytes_length_(data,len(data))
                if not item.setData_forType_(native,type_name):raise Denied('clipboard_restore_failed')
            items.append(item)
        return items
