import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('dependencies',Path(__file__).parents[1]/'host/dependencies.py')
deps=importlib.util.module_from_spec(spec);spec.loader.exec_module(deps)

class DependenciesTest(unittest.TestCase):
    def test_owned_server_needs_no_codex_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);server=root/'mcp/node_modules/mcpfabric-mcp-server/dist/index.js'
            server.parent.mkdir(parents=True);server.write_text('')
            with patch.object(deps.shutil,'which',return_value='node'),patch.object(deps.Path,'home',side_effect=AssertionError('must not read Codex')):
                self.assertEqual(deps.locate(root)[1],server)
    def test_installer_is_pinned_scoped_and_disables_scripts(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(deps,'inspect',return_value={'can_install':True}),patch.object(deps,'locate',return_value=('node',Path('unused'))),patch.object(deps.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(deps.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            deps.install(Path(temp));args=run.call_args.args[0]
            self.assertIn('mcpfabric-mcp-server@0.10.0',args);self.assertIn('--ignore-scripts',args)
            self.assertIn(str(Path(temp)/'mcp'),args);self.assertIn('--registry=https://registry.npmjs.org',args)
    def test_missing_node_does_not_start_install(self):
        with patch.object(deps,'inspect',return_value={'can_install':False}),patch.object(deps.subprocess,'run') as run:
            with self.assertRaises(ValueError):deps.install(Path('unused'))
            run.assert_not_called()

if __name__=='__main__':unittest.main()
