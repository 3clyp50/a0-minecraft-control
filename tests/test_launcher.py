import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,AsyncMock
import zlib
from usr.plugins.minecraft_control.helpers import launcher


def packet(value):
    raw=zlib.compress(json.dumps({'ok':True,'result':value}).encode())
    return {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(raw).decode()}

class LauncherTest(unittest.IsolatedAsyncioTestCase):
    def test_gateway_requires_exact_host_and_scopes(self):
        ready={'connected':True,'gateway':{'master_enabled':True,'scopes':{'files':True,'file_write':True,'code_execution':True}}}
        with patch.object(launcher.connector,'launcher_gateway_status',return_value=ready),patch.object(launcher.connector,'active_launcher_gateway_sid',return_value='host'):
            self.assertEqual(launcher.gateway_sid(),'host')
            ready['gateway']['scopes']['code_execution']=False;self.assertIsNone(launcher.gateway_sid())
            ready['gateway']['scopes']['code_execution']=True;ready['multiple_hosts']=True;self.assertIsNone(launcher.gateway_sid())
    async def test_no_gateway_never_dispatches(self):
        with patch.object(launcher,'ACTIVE',None),patch.object(launcher,'gateway_sid',return_value=None),patch.object(launcher,'exchange',new_callable=AsyncMock) as send:
            with self.assertRaises(ValueError):await launcher.connect()
            send.assert_not_awaited()
    async def test_old_disconnect_does_not_cancel_new_connection(self):
        new={'token':'new'}
        with patch.object(launcher,'ACTIVE',new),patch('usr.plugins.minecraft_control.helpers.runtime.cancel') as cancel:
            await launcher.disconnect({'token':'old'})
            cancel.assert_not_called();self.assertIs(launcher.ACTIVE,new)
    def test_host_code_needs_no_server_or_shared_path(self):
        code=launcher.host_code({'instance':'a'*32,'token':'b'*32},{'action':'tool','params':{'text':"quotes ' and ` $()"}},deploy=True)
        compile(code,'<host>','exec')
        self.assertIn('LOCALAPPDATA',code);self.assertNotIn('/a0/',code);self.assertNotIn('host_directory',code)
    def test_host_setup_deploys_and_runs_on_current_platform(self):
        code=launcher.host_code({'instance':'a'*32,'token':'b'*32},{'action':'setup'},deploy=True)
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp,'XDG_DATA_HOME':temp}),patch.object(Path,'home',return_value=Path(temp)),patch('subprocess.check_output',return_value='v22.22.3\n'):
            output=io.StringIO();scope={}
            with contextlib.redirect_stdout(output):exec(code,scope)
            data=json.loads(output.getvalue().split('=',1)[1])
            result=launcher.decode(data,base64.b64decode(data['data']))
            self.assertTrue(result['node']);self.assertFalse(result['server'])
            self.assertTrue(scope['root'].is_relative_to(Path(temp)))
            self.assertTrue(all((scope['root']/'host'/name).is_file() for name in launcher.HOST_FILES))
    def test_bad_digest_and_expansion_are_rejected(self):
        p=packet({'ok':1});raw=base64.b64decode(p['data'])
        self.assertEqual(launcher.decode(p,raw),{'ok':1})
        with self.assertRaises(ValueError):launcher.decode(p,raw+b'x')
        with patch.object(launcher,'MAX_RESULT',100):
            p=packet('a'*1000)
            with self.assertRaises(ValueError):launcher.decode(p,base64.b64decode(p['data']))
    async def test_large_result_is_chunked_verified_and_released(self):
        value=base64.b64encode(os.urandom(300000)).decode();p=packet(value);raw=base64.b64decode(p.pop('data'));p['transfer']='c'*32
        calls=[]
        async def exchange(conn,request,*args):
            calls.append(request['action'])
            if request['action']=='tool':return p
            if request['action']=='fetch':
                offset=request['offset'];return packet({'chunk':base64.b64encode(raw[offset:offset+48000]).decode()})
            return packet({'ok':True})
        with patch.object(launcher,'exchange',side_effect=exchange):
            self.assertEqual(await launcher.request({}, {'action':'tool'}),value)
        self.assertGreater(calls.count('fetch'),1);self.assertEqual(calls[-1],'release')
    async def test_failed_transfer_is_not_replayed(self):
        with patch.object(launcher,'exchange',new_callable=AsyncMock,side_effect=ValueError('timeout')) as call:
            with self.assertRaises(ValueError):await launcher.request({}, {'action':'tool'})
            self.assertEqual(call.await_count,1)

if __name__=='__main__':unittest.main()
