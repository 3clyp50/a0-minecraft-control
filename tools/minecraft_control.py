import json
from helpers.tool import Tool, Response
from usr.plugins.minecraft_control.helpers.runtime import call_tool

class MinecraftControl(Tool):
    async def execute(self, tool='list', params=None, **kwargs):
        try:
            result = await call_tool(self.agent.context, tool, params or {})
            if isinstance(result, dict):
                from helpers import chat_media
                for item in result.get('content', []):
                    if item.get('type') == 'image':
                        saved = chat_media.save_image_data_url(
                            context_id=self.agent.context.id,
                            data_url=f"data:{item['mimeType']};base64,{item['data']}",
                            category='screenshots', source='minecraft_control', preferred_name='minecraft.png')
                        item.clear()
                        item.update(type='text', text=f'Minecraft screenshot: {saved.a0_path}. Use vision_load to inspect it.')
            return Response(message=json.dumps({'untrusted': True, 'data': result}), break_loop=False)
        except ValueError as error:
            return Response(message=str(error), break_loop=False)
