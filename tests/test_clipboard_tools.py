import copy
import unittest
from bridge.clipboard_tools import TemporaryClipboard,original_formats_preserved
from bridge.store import Denied


class Board:
    def __init__(self):
        self.items=[[('public.rtf',b'{rtf fixture}'),('public.utf8-plain-text',b'fixture text')]]
        self.count=7
    def change_count(self):return self.count
    def snapshot(self):return copy.deepcopy(self.items)
    def write_text(self,text):self.items=[[('public.utf8-plain-text',text.encode())]];self.count+=1
    def restore(self,items):self.items=copy.deepcopy(items);self.count+=1


class ClipboardTests(unittest.TestCase):
    def test_all_formats_restore_in_memory_after_success(self):
        b=Board();original=copy.deepcopy(b.items)
        with TemporaryClipboard(b,'fixture task') as guard:
            guard.ensure_unchanged()
            self.assertEqual(b.items,[[('public.utf8-plain-text',b'fixture task')]])
        self.assertEqual(b.items,original);self.assertTrue(guard.restored)
        self.assertIsNone(guard.original);self.assertIsNone(guard.text)

    def test_restore_also_happens_when_paste_fails(self):
        b=Board();original=copy.deepcopy(b.items)
        with self.assertRaises(OSError):
            with TemporaryClipboard(b,'fixture task'):raise OSError('menu refused')
        self.assertEqual(b.items,original)

    def test_never_overwrite_an_external_clipboard_change(self):
        b=Board()
        with TemporaryClipboard(b,'fixture task') as guard:
            b.write_text('new user copy')
            with self.assertRaises(Denied):guard.ensure_unchanged()
        self.assertEqual(b.items,[[('public.utf8-plain-text',b'new user copy')]])
        self.assertFalse(guard.restored);self.assertTrue(guard.external_change)

    def test_unpreservable_format_fails_before_writing(self):
        b=Board();count=b.count
        def fail():raise Denied('unavailable format')
        b.snapshot=fail
        with self.assertRaises(Denied):
            with TemporaryClipboard(b,'fixture task'):pass
        self.assertEqual(b.count,count)

    def test_failed_owned_write_is_rolled_back_before_paste(self):
        b=Board();original=copy.deepcopy(b.items)
        def fail(text):
            b.items=[];b.count+=1;b.last_owned_write_count=b.count
            raise OSError('failed write')
        b.write_text=fail
        with self.assertRaises(OSError):
            with TemporaryClipboard(b,'fixture task'):pass
        self.assertEqual(b.items,original)

    def test_native_reordering_and_extra_alias_do_not_mean_data_loss(self):
        original=[[('public.rtf',b'rtf'),('public.utf8-plain-text',b'text')]]
        observed=[[('NSStringPboardType',b'text'),('public.utf8-plain-text',b'text'),('public.rtf',b'rtf')]]
        self.assertTrue(original_formats_preserved(original,observed))
        self.assertFalse(original_formats_preserved(original,[[('public.rtf',b'changed'),('public.utf8-plain-text',b'text')]]))
        self.assertFalse(original_formats_preserved(original,[[('public.rtf',b'rtf')]]))
