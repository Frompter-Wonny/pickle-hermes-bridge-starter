import unittest
from unittest.mock import patch
from subprocess import CompletedProcess
from bridge import session


class SessionTests(unittest.TestCase):
    def test_stop_cannot_pretend_success_while_launchd_would_restart(self):
        with patch.object(session,'live',return_value={'pid':123}),patch.object(session.subprocess,'run',return_value=CompletedProcess([],0,'','')),patch.object(session.os,'kill') as kill,patch('sys.argv',['session','stop']):
            with self.assertRaisesRegex(SystemExit,'bridge.service stop'):session.main()
            kill.assert_not_called()


if __name__=='__main__':unittest.main()
