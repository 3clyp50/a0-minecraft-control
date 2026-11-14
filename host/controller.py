import base64
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import time
import uuid
import zlib

MAX_RESULT = 32 * 1024 * 1024
CHUNK = 48000


def root_for(instance):
    if not isinstance(instance, str) or not re.fullmatch('[a-f0-9]{32}', instance):
        raise ValueError('Invalid plugin instance')
    base = (Path(os.environ['LOCALAPPDATA']) / 'AgentZero/Minecraft').resolve()
    root = (base / instance).resolve()
    if root.parent != base:
        raise ValueError('Invalid plugin cache path')
    return root


def read(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def dispatch(root, request):
    companion = runpy.run_path(str(root / 'host/companion.py'))
    write = companion['atomic']
    action = request.get('action')
    token = request.get('token')
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('Invalid connection token')
    dependencies = runpy.run_path(str(root / 'host/dependencies.py'))
    if action in ('profile_versions', 'install_profile', 'open_launcher'):
        lease = read(root / 'host-lease.json', {})
        if lease.get('expires', 0) > time.time() and not (root / 'stopped').exists():
            raise ValueError('Disconnect Minecraft before changing setup')
        write(root / 'owner.json', {'token':token})
        profiles = runpy.run_path(str(root / 'host/profiles.py'))
        if action == 'open_launcher': return profiles['open_launcher']()
        result = profiles['install'](root, request.get('version')) if action == 'install_profile' else profiles['setup'](root)
        return {**dependencies['inspect'](root), 'profiles':result}
    if action in ('setup', 'install'):
        lease = read(root / 'host-lease.json', {})
        if lease.get('expires', 0) > time.time() and not (root / 'stopped').exists():
            raise ValueError('Disconnect Minecraft before changing setup')
        write(root / 'owner.json', {'token':token})
        return dependencies['install' if action == 'install' else 'inspect'](root)
    if action == 'connect':
        previous = read(root / 'host-lease.json', {})
        if previous.get('expires', 0) > time.time() and not (root / 'stopped').exists():
            raise ValueError('This Windows companion is already connected')
        if not dependencies['inspect'](root)['server']:
            raise ValueError('Install the MCP server in Setup first')
        if (root / 'worker.lock').exists() and not (root / 'stopped').exists():
            raise ValueError('The previous companion is still stopping; try again shortly')
        for pattern in ('rpc-*.json', 'result-*.json', 'transfer-*.bin'):
            for file in root.glob(pattern): file.unlink(missing_ok=True)
        (root / 'lease.json').unlink(missing_ok=True)
        (root / 'stop').unlink(missing_ok=True)
        (root / 'stopped').unlink(missing_ok=True)
        write(root / 'host-lease.json', {'token':token, 'expires':time.time()+30})
        write(root / 'owner.json', {'token':token})
        (root / 'enabled').touch()
        with (root / 'host.log').open('w', encoding='utf-8') as log:
            subprocess.Popen([sys.executable, str(root / 'host/companion.py'), '--host-token', token],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            state = read(root / 'status.json', {})
            if state.get('host_token') == token:
                return {'state':state, 'tools':read(root / 'tools.json', [])}
            if (root / 'stopped').exists(): break
            time.sleep(.25)
        (root / 'enabled').unlink(missing_ok=True)
        raise ValueError('Companion startup failed; check host.log in the Windows plugin cache')

    lease = read(root / 'host-lease.json', {})
    if action == 'uninstall' and not lease and read(root / 'owner.json', {}).get('token') == token:
        shutil.rmtree(root)
        return {'ok':True}
    if lease.get('token') != token:
        raise ValueError('Connection was replaced')
    if action not in ('disconnect', 'uninstall', 'stop') and lease.get('expires', 0) <= time.time():
        raise ValueError('Connection expired; reconnect from the Minecraft panel')
    if action == 'pulse':
        if (root / 'stopped').exists(): raise ValueError('Windows companion stopped')
        write(root / 'host-lease.json', {'token':token, 'expires':time.time()+30})
        return read(root / 'status.json', {})
    if action in ('stop', 'disconnect', 'uninstall'):
        task = read(root / 'lease.json', {})
        if action == 'stop' and request.get('run') and task.get('run') != request['run']:
            return {'ok':True}
        (root / 'lease.json').unlink(missing_ok=True)
        (root / 'stop').touch()
        for file in root.glob('rpc-*.json'): file.unlink(missing_ok=True)
        if action != 'stop':
            (root / 'enabled').unlink(missing_ok=True)
            for _ in range(180):
                if (root / 'stopped').exists(): break
                time.sleep(.25)
            else: raise ValueError('Companion is still stopping; its lease will expire automatically')
            (root / 'host-lease.json').unlink(missing_ok=True)
            for file in root.glob('transfer-*.bin'): file.unlink(missing_ok=True)
            if action == 'uninstall': shutil.rmtree(root)
        return {'ok':True}
    if action == 'begin':
        if (root / 'stop').exists(): raise ValueError('Minecraft controls are still stopping; try again shortly')
        run = request.get('run')
        if not isinstance(run, str) or not re.fullmatch('[a-f0-9]{32}', run): raise ValueError('Invalid task')
        write(root / 'lease.json', {'run':run})
        return {'ok':True}
    if action == 'tool':
        run = request.get('run')
        if (not isinstance(run, str) or not re.fullmatch('[a-f0-9]{32}', run) or
                run != read(root / 'lease.json', {}).get('run') or (root / 'stop').exists()):
            raise ValueError('Minecraft task stopped')
        allowed = read(root / 'host/allowed.json', [])
        if request.get('tool') not in allowed or not isinstance(request.get('params'), dict):
            raise ValueError('Invalid Minecraft tool')
        call_id = uuid.uuid4().hex
        path, result = root / f'rpc-{call_id}.json', root / f'result-{call_id}.json'
        write(path, {**request, 'expires':time.time()+40})
        try:
            for _ in range(180):
                if result.exists():
                    response = read(result)
                    if response.get('error'): raise ValueError(response['error'])
                    return response['result']
                if (root / 'stopped').exists(): raise ValueError('Windows companion stopped')
                time.sleep(.25)
            raise ValueError('Minecraft call timed out; verify game state before retrying')
        finally:
            path.unlink(missing_ok=True)
            result.unlink(missing_ok=True)
    if action in ('fetch', 'release'):
        transfer = request.get('transfer', '')
        if not isinstance(transfer, str) or not re.fullmatch('[a-f0-9]{32}', transfer): raise ValueError('Invalid transfer')
        path = root / f'transfer-{transfer}.bin'
        if action == 'release':
            path.unlink(missing_ok=True)
            return {'ok':True}
        offset = request.get('offset')
        if type(offset) is not int or offset < 0 or offset > MAX_RESULT: raise ValueError('Invalid offset')
        with path.open('rb') as stream:
            stream.seek(offset)
            return {'chunk':base64.b64encode(stream.read(CHUNK)).decode()}
    raise ValueError('Unknown host operation')


def respond(root, request):
    try:
        result = {'ok':True, 'result':dispatch(root, request)}
    except Exception as error:
        result = {'ok':False, 'error':str(error) if isinstance(error, ValueError) else 'Windows operation failed; check plugin host logs'}
    raw = json.dumps(result).encode()
    if len(raw) > MAX_RESULT:
        raw = json.dumps({'ok':False,'error':'Minecraft result exceeds the transfer limit'}).encode()
    compressed = zlib.compress(raw)
    packet = {'size':len(compressed), 'sha256':hashlib.sha256(compressed).hexdigest()}
    if len(compressed) <= 96000:
        packet['data'] = base64.b64encode(compressed).decode()
    else:
        transfer = uuid.uuid4().hex
        (root / f'transfer-{transfer}.bin').write_bytes(compressed)
        packet['transfer'] = transfer
    print('A0_MINECRAFT_RESULT=' + json.dumps(packet), flush=True)
