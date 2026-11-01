"""One-process Telegram client. Never logs credential-bearing request URLs."""
import datetime
import email.utils
import json
import random
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(Exception):
    def __init__(self, code, retry_after=None):
        super().__init__('telegram_error_'+str(code))
        self.code=code
        self.retry_after=retry_after


def retry_seconds(value, now=None):
    if value is None:return None
    try:return max(0,float(value))
    except (TypeError,ValueError):
        try:
            date=email.utils.parsedate_to_datetime(value)
            if date.tzinfo is None:date=date.replace(tzinfo=datetime.timezone.utc)
            return max(0,date.timestamp()-(time.time() if now is None else now))
        except (TypeError,ValueError,OverflowError):return None


class TelegramAPI:
    def __init__(self,token,transport=None,sleep=time.sleep,clock=time.monotonic):
        self._token=token
        self._transport=transport or self._http
        self._sleep=sleep;self._clock=clock
        self._next=0.;self._lock=threading.Lock()
        self.metrics={'retries':0,'rate_limited':0,'backoff_seconds':0.}

    def _http(self,method,payload,timeout):
        req=Request('https://api.telegram.org/bot'+self._token+'/'+method,
                    json.dumps(payload).encode(),{'Content-Type':'application/json'})
        try:
            with urlopen(req,timeout=timeout) as r:body=json.load(r)
        except HTTPError as e:
            try:body=json.load(e)
            except (ValueError,OSError):body={}
            wait=retry_seconds(e.headers.get('Retry-After'))
            if wait is None:wait=retry_seconds(body.get('parameters',{}).get('retry_after'))
            raise TelegramError(e.code,wait) from None
        except (URLError,TimeoutError,OSError):
            raise TelegramError('network') from None
        if not body.get('ok'):
            raise TelegramError(body.get('error_code','unknown'),
                                retry_seconds(body.get('parameters',{}).get('retry_after')))
        return body['result']

    def call(self,method,payload,read_only=False,timeout=20,budget=30):
        start=self._clock()
        for attempt in range(4):
            with self._lock:
                delay=max(0,self._next-self._clock())
                if self._clock()-start+delay>=budget:raise TelegramError('retry_budget')
                self._sleep(delay)
                # Conservative 0.8 req/s, burst 1 across this bridge's calls.
                self._next=self._clock()+1.25
            try:
                return self._transport(method,payload,min(timeout,max(.1,budget-(self._clock()-start))))
            except TelegramError as e:
                if e.code==429:self.metrics['rate_limited']+=1
                retryable=e.code in {429,502,503,504,'network'}
                # sendMessage has no idempotency key: never retry ambiguous writes.
                if not read_only or not retryable or attempt==3:raise
                delay=e.retry_after if e.retry_after is not None else random.uniform(0,min(8,.25*2**attempt))
                if self._clock()-start+delay>=budget:raise
                self.metrics['retries']+=1;self.metrics['backoff_seconds']+=delay
                self._sleep(delay)
