import os
from pathlib import Path
import sys


def data_root(kind):
    if sys.platform == 'win32':
        base = Path(os.environ['LOCALAPPDATA'])
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return (base / 'AgentZero' / kind).resolve()


def minecraft_dir():
    if sys.platform == 'win32':
        return Path(os.environ['APPDATA']) / '.minecraft'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/minecraft'
    return Path.home() / '.minecraft'
