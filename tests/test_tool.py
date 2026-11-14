from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest
from usr.plugins.minecraft_control.tools.minecraft_control import MinecraftControl

class ToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_images_use_native_media_without_base64_in_history(self):
        tool = MinecraftControl.__new__(MinecraftControl)
        tool.agent = SimpleNamespace(context=SimpleNamespace(id='test'))
        result = {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': 'image-bytes'}]}
        with patch('usr.plugins.minecraft_control.tools.minecraft_control.call_tool', AsyncMock(return_value=result)), patch('helpers.chat_media.save_image_data_url', return_value=SimpleNamespace(a0_path='/a0/tmp/test.png')) as save:
            response = await tool.execute(tool='screenshot')
        save.assert_called_once()
        self.assertNotIn('image-bytes', response.message)
        self.assertIn('/a0/tmp/test.png', response.message)
        self.assertIn('vision_load', response.message)

if __name__ == '__main__': unittest.main()
