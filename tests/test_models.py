from types import SimpleNamespace
from unittest.mock import patch
import unittest
from usr.plugins.minecraft_control.helpers.models import resolve_models
from plugins._model_config.helpers import model_config

class ModelsTest(unittest.TestCase):
    def test_inherit_copies_every_slot_without_mutating_chat(self):
        config = {name + '_model': {'provider': 'test', 'name': name} for name in ('chat', 'utility', 'vision', 'embedding')}
        parent = SimpleNamespace(agent0=object())
        with patch.object(model_config, 'get_effective_config', return_value=config), patch.object(model_config, 'get_effective_preset_name', return_value='Current'):
            override, name = resolve_models(parent, '')
        self.assertEqual(name, 'Current')
        self.assertEqual(set(override), {'name', 'chat', 'utility', 'vision', 'embedding'})
        override['chat']['name'] = 'changed'
        self.assertEqual(config['chat_model']['name'], 'chat')

    def test_named_preset_uses_native_reference(self):
        with patch.object(model_config, 'get_preset_by_name', return_value={'name': 'Efficiency'}):
            self.assertEqual(resolve_models(None, 'Efficiency'), ({'preset_name': 'Efficiency'}, 'Efficiency'))

    def test_unknown_preset_fails_instead_of_charging_default(self):
        with patch.object(model_config, 'get_preset_by_name', return_value=None):
            with self.assertRaises(ValueError):
                resolve_models(None, 'missing')

if __name__ == '__main__':
    unittest.main()
