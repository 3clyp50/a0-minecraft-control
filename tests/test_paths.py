import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('host_paths', Path(__file__).parents[1] / 'host/paths.py')
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


class PathsTest(unittest.TestCase):
    def test_platform_directories(self):
        home = Path('/test/home')
        for system, data, minecraft in [
            ('linux', home / '.local/share', home / '.minecraft'),
            ('darwin', home / 'Library/Application Support', home / 'Library/Application Support/minecraft'),
            ('win32', home / 'local', home / 'roaming/.minecraft'),
        ]:
            with self.subTest(system=system), patch.object(paths, 'sys', SimpleNamespace(platform=system)), patch.object(paths.Path, 'home', return_value=home), patch.dict(paths.os.environ, {'LOCALAPPDATA':str(home / 'local'), 'APPDATA':str(home / 'roaming'), 'XDG_DATA_HOME':''}):
                self.assertEqual(paths.data_root('Minecraft'), (data / 'AgentZero/Minecraft').resolve())
                self.assertEqual(paths.minecraft_dir(), minecraft)

    def test_xdg_data_override(self):
        with patch.object(paths, 'sys', SimpleNamespace(platform='linux')), patch.dict(paths.os.environ, {'XDG_DATA_HOME':'/test/data'}):
            self.assertEqual(paths.data_root('MinecraftProfiles'), Path('/test/data/AgentZero/MinecraftProfiles').resolve())


if __name__ == '__main__': unittest.main()
