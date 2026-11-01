import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.tunnel import settings,command,ngrok_ready_origin
from bridge.inbox import Inbox
from bridge.store import Store,Denied


class TunnelTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_opt_in_and_credential_free_command_with_inspection_off(self):
        self.assertEqual(settings(self.state),{'provider':'cloudflare'})
        (self.state/'tunnel.json').write_text(json.dumps({'provider':'ngrok','origin':'https://fixture.ngrok-free.dev'}))
        (self.state/'ngrok.yml').write_text('authtoken: secret-fixture-token')
        args=command(self.state,settings(self.state))
        self.assertIn('--inspect=false',args);self.assertNotIn('secret-fixture-token',' '.join(args))
        for origin in ['http://fixture.ngrok-free.dev','https://bad.example','https://fixture.ngrok-free.dev/private',
                       'https://secret@fixture.ngrok-free.dev','https://fixture.ngrok-free.dev:443']:
            (self.state/'tunnel.json').write_text(json.dumps({'provider':'ngrok','origin':origin}))
            with self.assertRaises(ValueError):settings(self.state)

    def test_readiness_requires_our_origin_upstream_and_disabled_inspection(self):
        cfg={'provider':'ngrok','origin':'https://fixture.ngrok-free.dev'}
        tunnel={'public_url':cfg['origin'],'config':{'addr':'http://127.0.0.1:8766','inspect':False}}
        def ready(row):
            with patch('bridge.tunnel.urlopen',return_value=io.BytesIO(json.dumps({'tunnels':[row]}).encode())):
                return ngrok_ready_origin(cfg)
        self.assertEqual(ready(tunnel),cfg['origin'])
        self.assertIsNone(ready(dict(tunnel,config={'addr':'http://127.0.0.1:8766','inspect':True})))
        self.assertIsNone(ready(dict(tunnel,public_url='https://other.ngrok-free.dev')))
        self.assertIsNone(ready(dict(tunnel,config={'addr':'http://127.0.0.1:9999','inspect':False})))

    def test_persistent_receive_channel_still_uses_expiring_question_grants(self):
        store=Store(self.state/'db');inbox=Inbox(store);cap=inbox.create_channel(ttl=None)
        q=inbox.submit(cap,'fixture','fictional?');rid=inbox.approve(q,'verified fixture permission')
        with store.db() as db:
            self.assertEqual(db.execute('SELECT expires FROM inbox_channels').fetchone()[0],0)
            expiry=db.execute('SELECT expires FROM grants').fetchone()[0]
            self.assertLessEqual(expiry,time.time()+900)
        with self.assertRaises(ValueError):inbox.approve('other','proof',ttl=86400)
        inbox.close_channel(cap)
        with self.assertRaises(Denied):store.answer(rid,'must not be released')


if __name__=='__main__':unittest.main()
