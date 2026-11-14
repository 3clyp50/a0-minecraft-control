from types import SimpleNamespace
import unittest
from helpers.errors import RepairableException
from usr.plugins.minecraft_control.extensions.python.tool_execute_before.minecraft_scope import MinecraftScope

class ScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_canvas_blocks_shell_but_allows_game_and_vision(self):
        owner = SimpleNamespace(agent=SimpleNamespace(context=SimpleNamespace(get_data=lambda _: True)))
        with self.assertRaises(RepairableException):
            await MinecraftScope.execute(owner, tool_name='code_execution_tool')
        for tool in ('minecraft_control', 'vision_load', 'response'):
            await MinecraftScope.execute(owner, tool_name=tool)

    async def test_other_agent_zero_chats_are_unchanged(self):
        owner = SimpleNamespace(agent=SimpleNamespace(context=SimpleNamespace(get_data=lambda _: None)))
        await MinecraftScope.execute(owner, tool_name='code_execution_tool')

if __name__ == '__main__': unittest.main()
