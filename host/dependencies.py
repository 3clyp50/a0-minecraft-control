import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

PACKAGE = 'mcpfabric-mcp-server@0.10.0'


def locate(root):
    node = shutil.which('node') or (str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'nodejs/node.exe') if os.name == 'nt' else 'node')
    server = root / 'mcp/node_modules/mcpfabric-mcp-server/dist/index.js'
    if not server.is_file():
        try:
            entry = tomllib.loads((Path.home() / '.codex/config.toml').read_text())['mcp_servers']['mcpfabric']
            candidate = Path(entry['args'][0])
            if candidate.is_file() and candidate.name == 'index.js' and candidate.parent.parent.name == 'mcpfabric-mcp-server':
                server = candidate
            command = Path(entry['command'])
            if not Path(node).is_file() and command.is_file() and command.name.lower() in ('node', 'node.exe'):
                node = str(command)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            pass
    return node, server


def npm_cli(node):
    candidate = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
    if candidate.is_file():
        return candidate
    npm = shutil.which('npm')
    return Path(npm).resolve() if npm else candidate


def inspect(root):
    node, server = locate(root)
    version = ''
    try:
        version = subprocess.check_output([node, '--version'], text=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    numbers = re.match(r'v(\d+)\.(\d+)', version)
    node_ready = bool(numbers and tuple(map(int, numbers.groups())) >= (22, 16))
    npm = npm_cli(node)
    return {'node': node_ready, 'node_version': version, 'server': server.is_file(),
            'can_install': node_ready and npm.is_file(), 'package': PACKAGE,
            'discovery': (Path.home() / '.mcpfabric/bridge.json').is_file()}


def install(root):
    status = inspect(root)
    if not status['can_install']:
        raise ValueError('Install Node.js 22.16 or newer with npm, restart Launcher, then check setup again')
    node, _ = locate(root)
    npm = npm_cli(node)
    result = subprocess.run([node, str(npm), 'install', '--prefix', str(root / 'mcp'), '--ignore-scripts',
                             '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org', PACKAGE],
                            capture_output=True, text=True, timeout=150, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        (root / 'install.log').write_text(result.stderr[-16000:], encoding='utf-8')
        raise ValueError('MCP server installation failed; see install.log in the host plugin cache')
    return inspect(root)
