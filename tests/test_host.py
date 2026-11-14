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

    def test_auto_resume_only_closes_pause_and_respects_ai_pause(self):
        for in_world,screen,ai_paused,expected in [(True,'pause',False,True), (True,'death',False,False),
                (True,'container',False,False), (True,'chat',False,False), (False,'pause',False,False),
                (True,'pause',True,False), (True,'none',False,False)]:
            calls=[]
            def rpc(method):
                calls.append(method)
                if method=='info.status':return {'aiPaused':ai_paused}
                if method=='screen.get':return {'inWorld':in_world,'screen':'none' if 'screen.close' in calls else screen}
                return {'ok':True}
            with patch.object(companion,'rpc',side_effect=rpc),patch.object(companion.time,'sleep'):
                companion.resume_pause()
            self.assertEqual('screen.close' in calls,expected)

    def test_failed_resume_stops_before_screenshot(self):
        with tempfile.TemporaryDirectory() as temp:
            host=companion.Companion.__new__(companion.Companion);host.root=Path(temp)
            (host.root/'lease.json').write_text(json.dumps({'auto_resume':True}))
            with patch.object(companion,'resume_pause',side_effect=ValueError('menu stayed open')),patch.object(companion.subprocess,'run') as run:
                with self.assertRaises(ValueError):host.call('screenshot')
                run.assert_not_called()

    def test_disabled_resume_and_agent_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            host=companion.Companion.__new__(companion.Companion);host.root=Path(temp);host.node='node';host.server='server'
            (host.root/'lease.json').write_text(json.dumps({'auto_resume':False}))
            from types import SimpleNamespace
            with patch.object(companion,'resume_pause') as resume,patch.object(companion.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{}')):
                host.call('screenshot');resume.assert_not_called()
                with self.assertRaises(ValueError):host.call('send_chat',{'message':'@a0 build something'})

    def test_only_own_a0_chat_is_a_request(self):
        base={'type':'chat','data':{'self':True,'kind':'chat','text':'<Player> @a0 build a marker'}}
        self.assertEqual(companion.tagged_request(base),'build a marker')
        for override in [{'self':False},{'self':'true'},{'kind':'whisper_in'},{'text':'@Codex build'},
                {'text':'@ai build'},{'text':'@a0evil build'},{'text':'@a0 '},{'text':'@a0 '+'x'*301},
                {'text':'@a0 line\nbreak'}]:
            self.assertIsNone(companion.tagged_request({'type':'chat','data':{**base['data'],**override}}))
        self.assertIsNone(companion.tagged_request({'type':'system_message','data':base['data']}))

    def test_chat_baseline_deduplication_disable_and_world_change(self):
        with tempfile.TemporaryDirectory() as temp:
            host=companion.Companion.__new__(companion.Companion);host.root=Path(temp);host.chat_cursor=None;host.state={'requests':[]}
            lease=host.root/'host-lease.json';lease.write_text(json.dumps({'chat_enabled':True}))
            def event(i):return {'id':i,'type':'chat','data':{'self':True,'kind':'chat','text':'@a0 check status'}}
            with patch.object(companion,'rpc',return_value={'events':[event(2)],'lastId':2}):host.read_chat()
            self.assertEqual(host.state['requests'],[])
            with patch.object(companion,'rpc',return_value={'events':[event(2),event(3)],'lastId':3}):
                host.read_chat();host.read_chat()
            self.assertEqual(host.state['requests'],[{'id':3,'text':'check status'}])
            old=host.state['chat_epoch']
            with patch.object(companion,'rpc',return_value={'events':[{'id':4,'type':'left_world'}],'lastId':4}):host.read_chat()
            self.assertEqual(host.state['requests'],[]);self.assertNotEqual(old,host.state['chat_epoch'])
            lease.write_text(json.dumps({'chat_enabled':False}));host.read_chat();self.assertIsNone(host.chat_cursor)

if __name__ == '__main__': unittest.main()
