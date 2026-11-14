import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

spec=importlib.util.spec_from_file_location('controller',Path(__file__).parents[1]/'host/controller.py')
controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)

class ControllerTest(unittest.TestCase):
    def test_missing_task_and_expired_connection_cannot_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);token='a'*32
            (root/'host-lease.json').write_text(json.dumps({'token':token,'expires':time.time()+30}))
            with patch.object(controller.runpy,'run_path',return_value={'atomic':lambda *args:None}):
                with self.assertRaisesRegex(ValueError,'task stopped'):
                    controller.dispatch(root,{'action':'tool','token':token,'params':{}})
                (root/'host-lease.json').write_text(json.dumps({'token':token,'expires':0}))
                with self.assertRaisesRegex(ValueError,'expired'):
                    controller.dispatch(root,{'action':'begin','token':token,'run':'b'*32})
            self.assertEqual(list(root.glob('rpc-*')),[])
    def test_cache_identity_cannot_escape_owned_folder(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}):
            self.assertEqual(controller.root_for('a'*32).name,'a'*32)
            for value in ('../outside','C:/other','',None):
                with self.assertRaises(ValueError):controller.root_for(value)
    def test_large_results_are_spooled_with_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);value=base64.b64encode(os.urandom(300000)).decode();out=io.StringIO()
            with patch.object(controller,'dispatch',return_value=value),contextlib.redirect_stdout(out):controller.respond(root,{})
            packet=json.loads(out.getvalue().split('=',1)[1]);self.assertNotIn('data',packet)
            raw=(root/('transfer-'+packet['transfer']+'.bin')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),packet['sha256'])
            self.assertEqual(json.loads(zlib.decompress(raw))['result'],value)
    def test_chunks_fit_single_gateway_response(self):
        out=io.StringIO();chunk={'chunk':base64.b64encode(os.urandom(48000)).decode()}
        with patch.object(controller,'dispatch',return_value=chunk),contextlib.redirect_stdout(out):controller.respond(Path('unused'),{})
        packet=json.loads(out.getvalue().split('=',1)[1]);self.assertIn('data',packet)
        self.assertLess(len(out.getvalue()),256*1024)

if __name__=='__main__':unittest.main()
