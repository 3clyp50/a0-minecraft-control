import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

if os.name == 'nt':
    spec = importlib.util.spec_from_file_location('companion', Path(__file__).parents[1] / 'host/companion.py')
    companion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(companion)

@unittest.skipUnless(os.name == 'nt', 'Windows host tests')
class HostTest(unittest.TestCase):
    def test_host_lease_rejects_expiry_and_another_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(companion.lease_valid(root, 'test'))
            (root / 'host-lease.json').write_text(json.dumps({'token':'test','expires':time.time()+30}))
            self.assertTrue(companion.lease_valid(root, 'test'))
            self.assertFalse(companion.lease_valid(root, 'another'))
            (root / 'host-lease.json').write_text(json.dumps({'token':'test','expires':time.time()-1}))
            self.assertFalse(companion.lease_valid(root, 'test'))

    def test_atomic_write_retries_windows_reader_lock(self):
        replace = os.replace
        attempts = []
        def locked_once(source, target):
            attempts.append(1)
            if len(attempts) == 1: raise PermissionError('reader holds file')
            replace(source, target)
        with tempfile.TemporaryDirectory() as temp, patch.object(companion.os, 'replace', side_effect=locked_once), patch.object(companion.time, 'sleep'):
            target = Path(temp) / 'status.json'
            companion.atomic(target, {'ok': True})
            self.assertEqual(json.loads(target.read_text()), {'ok': True})
        self.assertEqual(len(attempts), 2)

    def test_menu_keeps_connected_client_without_player(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'enabled').touch()
            host = companion.Companion.__new__(companion.Companion)
            host.root = root
            host.host_token = 'test'
            (root / 'host-lease.json').write_text(json.dumps({'token':'test','expires':time.time()+60}))
            host.state = {'game': {}, 'player': {}, 'inventory': {}}
            def rpc(method):
                if method == 'info.status': return {'minecraftVersion': '26.3'}
                raise ValueError('no player')
            with patch.object(host, 'call', return_value=[]), patch.object(companion, 'rpc', side_effect=rpc), patch.object(companion.time, 'sleep', side_effect=lambda _: (root / 'enabled').unlink(missing_ok=True)):
                host.run()
            data = json.loads((root / 'status.json').read_text())
            self.assertEqual(data['game']['minecraftVersion'], '26.3')
            self.assertEqual(data['player'], {})
            self.assertTrue((root / 'stopped').exists())

if __name__ == '__main__': unittest.main()
