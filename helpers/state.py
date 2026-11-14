import json
import os
from pathlib import Path
import uuid

ROOT = Path('/a0/usr/plugins/minecraft_control/.state')


def write(path, value):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value), encoding='utf-8')
    os.replace(temp, path)
