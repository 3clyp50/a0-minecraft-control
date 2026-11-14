from copy import deepcopy
from plugins._model_config.helpers import model_config

def resolve_models(parent, preset_name):
    if not isinstance(preset_name, str):
        raise ValueError('Model preset must be a name or inherit current chat')
    if not preset_name:
        return model_config.config_to_preset(
            deepcopy(model_config.get_effective_config(parent.agent0))), model_config.get_effective_preset_name(parent.agent0)
    preset = model_config.get_preset_by_name(preset_name)
    if preset is None:
        raise ValueError('Selected model preset no longer exists')
    return {'preset_name': preset['name']}, preset['name']
