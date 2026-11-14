from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from usr.plugins.minecraft_control import hooks

class HooksTest(unittest.TestCase):
    def test_install_preserves_identity_and_cleanup_is_owned(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'owned';shared=Path(temp)/'shared.txt';shared.write_text('preserve')
            with patch.object(hooks,'ROOT',root),patch.object(hooks.defer,'DeferredTask',return_value=MagicMock()):
                hooks.install();identity=(root/'instance.json').read_text();hooks.install()
                self.assertEqual((root/'instance.json').read_text(),identity)
                self.assertFalse((root/'host').exists())
                hooks.pre_update();hooks.uninstall();hooks.uninstall()
            self.assertFalse(root.exists());self.assertEqual(shared.read_text(),'preserve')

class HostPreparationTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_server_uses_lifecycle_installation(self):
        missing={'setup':{'can_install':True,'server':False}}
        ready={'setup':{'server':True}}
        with patch('usr.plugins.minecraft_control.helpers.launcher.setup',new_callable=AsyncMock,side_effect=[missing,ready]) as setup:
            self.assertEqual(await hooks.prepare_host(True),ready)
            self.assertEqual(setup.await_count,2)
            self.assertEqual(setup.call_args.kwargs,{'install':True})
    async def test_missing_node_leaves_actionable_setup(self):
        missing={'setup':{'can_install':False,'server':False}}
        with patch('usr.plugins.minecraft_control.helpers.launcher.setup',new_callable=AsyncMock,return_value=missing) as setup:
            self.assertEqual(await hooks.prepare_host(True),missing)
            self.assertEqual(setup.await_count,1)

class ProfilePreparationTest(unittest.IsolatedAsyncioTestCase):
    async def test_profile_install_also_installs_missing_server(self):
        result={'setup':{'can_install':True,'server':False}}
        ready={'setup':{'can_install':True,'server':True}}
        with patch('usr.plugins.minecraft_control.helpers.launcher.profile_operation',new_callable=AsyncMock,side_effect=[result,ready]) as operation,patch.object(hooks,'prepare_host',new_callable=AsyncMock) as prepare:
            self.assertEqual(await hooks.prepare_profile('install_profile','26.3'),ready)
            prepare.assert_awaited_once_with(True)
            self.assertEqual(operation.call_args.args,('profile_versions',))
    async def test_catalog_does_not_install_packages(self):
        with patch('usr.plugins.minecraft_control.helpers.launcher.profile_operation',new_callable=AsyncMock,return_value={'setup':{'can_install':True,'server':False}}),patch.object(hooks,'prepare_host',new_callable=AsyncMock) as prepare:
            await hooks.prepare_profile('profile_versions')
            prepare.assert_not_awaited()

if __name__=='__main__':unittest.main()
