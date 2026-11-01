import unittest
from bridge.telegram_api import TelegramAPI, TelegramError, retry_seconds


class TelegramTests(unittest.TestCase):
    def test_retry_after_seconds_and_http_date(self):
        self.assertEqual(retry_seconds('3'),3)
        self.assertEqual(retry_seconds('Thu, 01 Jan 1970 00:00:10 GMT',now=4),6)
        self.assertIsNone(retry_seconds('invalid'))

    def test_never_retries_ambiguous_message_send(self):
        calls=[]
        def transport(*args):
            calls.append(args)
            raise TelegramError('network')
        api=TelegramAPI('not-real',transport,sleep=lambda _:None)
        with self.assertRaises(TelegramError):api.call('sendMessage',{},read_only=False)
        self.assertEqual(len(calls),1)

    def test_429_wait_obeyed_for_read(self):
        now=[0.];waits=[];calls=[]
        def sleep(n):now[0]+=n;waits.append(n)
        def transport(*args):
            calls.append(args)
            if len(calls)==1:raise TelegramError(429,4)
            return {'ok':True}
        api=TelegramAPI('not-real',transport,sleep,lambda:now[0])
        self.assertEqual(api.call('getMe',{},True),{'ok':True})
        self.assertIn(4,waits)
        self.assertEqual(api.metrics['retries'],1)

    def test_permanent_error_and_retry_budget(self):
        for code,wait in [(401,None),(429,90)]:
            calls=[]
            def transport(*args):
                calls.append(args);raise TelegramError(code,wait)
            api=TelegramAPI('not-real',transport,sleep=lambda _:None)
            with self.assertRaises(TelegramError):api.call('getMe',{},True,budget=5)
            self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
