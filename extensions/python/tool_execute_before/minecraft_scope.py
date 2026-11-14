from helpers.extension import Extension
from helpers.errors import RepairableException

class MinecraftScope(Extension):
    async def execute(self, tool_name='', **kwargs):
        if self.agent and self.agent.context.get_data('minecraft_control'):
            if tool_name not in ('minecraft_control', 'response', 'vision_load'):
                raise RepairableException('Minecraft canvas tasks use minecraft_control, vision_load, and response only.')
