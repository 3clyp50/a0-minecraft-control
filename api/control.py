from helpers.api import ApiHandler, Response
from usr.plugins.minecraft_control.helpers.runtime import status, submit
from plugins._model_config.helpers.model_config import get_presets, get_effective_preset_name
from helpers import plugins
from agent import AgentContext
from usr.plugins.minecraft_control.helpers import launcher

class Control(ApiHandler):
    async def process(self, input, request):
        if not isinstance(input, dict):
            return Response('Invalid request', status=400)
        action = input.get('action', 'status')
        if action == 'presets':
            return {'presets': [p['name'] for p in get_presets()]}
        if action == 'status':
            data = status()
            data['launcher'] = launcher.status()
            data['chat_alias'] = '@a0' if launcher.ACTIVE and launcher.chat_enabled(launcher.ACTIVE) else ''
            context_id = input.get('context_id', '')
            parent = AgentContext.get(context_id) if isinstance(context_id, str) else None
            config = plugins.get_plugin_config('minecraft_control', agent=parent.agent0 if parent else None) or {}
            data['model_label'] = config.get('model_preset') or (
                'Inherit · ' + get_effective_preset_name(parent.agent0) if parent else 'Inherit current chat')
            return data
        try:
            if action in ('profile_versions', 'install_profile', 'open_launcher'):
                from usr.plugins.minecraft_control.hooks import prepare_profile
                return await prepare_profile(action, input.get('version'))
            if action in ('setup', 'install_server'):
                from usr.plugins.minecraft_control.hooks import prepare_host
                return await prepare_host(install_server=action == 'install_server')
            if action == 'connect':
                context_id = input.get('context_id', '')
                if not isinstance(context_id, str): raise ValueError('Invalid chat context')
                return await launcher.connect(context_id)
            if action == 'disconnect':
                return await launcher.disconnect()
            return await submit(action, input.get('prompt', ''), input.get('context_id', ''))
        except ValueError as error:
            return Response(str(error), status=400)
