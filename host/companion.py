"""Windows companion. No listener, credentials, or shell commands cross the spool."""
import argparse
import http.client
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import time
import runpy
from urllib.parse import urlsplit
import uuid


def atomic(path, data):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data), encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 19:
                temp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)

def rpc(method):
    discovery = json.loads((Path.home() / '.mcpfabric/bridge.json').read_text())
    url = urlsplit(discovery['url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port:
        raise ValueError('Invalid local bridge')
    connection = http.client.HTTPConnection('127.0.0.1', url.port, timeout=2)
    try:
        connection.request('POST', '/rpc', json.dumps({'method': method, 'params': {}}),
                           {'Authorization': 'Bearer ' + discovery['token'], 'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = json.loads(response.read(2_000_000))
        if response.status != 200 or not body.get('ok'):
            raise ValueError('Minecraft unavailable')
        return body['result']
    finally:
        connection.close()

def lease_valid(root, token):
    try:
        lease = json.loads((root / 'host-lease.json').read_text())
        return bool(token) and lease.get('token') == token and lease.get('expires', 0) > time.time()
    except (OSError, ValueError):
        return False


class Companion:
    def __init__(self, root, host_token):
        self.root = root
        self.host_token = host_token
        dependencies = runpy.run_path(str(Path(__file__).with_name('dependencies.py')))
        self.node, self.server = dependencies['locate'](root)
        self.server = str(self.server)
        self.state = {'game': {}, 'player': {}, 'inventory': {}}

    def call(self, tool, params=None):
        result = subprocess.run([self.node, str(Path(__file__).with_name('mcp-call.mjs'))],
            input=json.dumps({'server': self.server, 'tool': tool, 'params': params or {}}),
            capture_output=True, text=True, encoding='utf-8', timeout=35,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('MCPFabric call failed; check the game and host MCP configuration')
        return json.loads(result.stdout)

    def publish(self):
        atomic(self.root / 'status.json', {**self.state, 'heartbeat': time.time(), 'host_token': self.host_token})

    def stop(self):
        for method in ('nav.stop', 'interact.stopBreaking', 'control.stop', 'control.stopUsing'):
            try:
                rpc(method)
            except (OSError, ValueError, KeyError, http.client.HTTPException):
                pass

    def run(self):
        (self.root / 'stopped').unlink(missing_ok=True)
        next_game = 0
        try:
            atomic(self.root / 'tools.json', self.call('list'))
            while (self.root / 'enabled').exists() and lease_valid(self.root, self.host_token):
                if (self.root / 'stop').exists():
                    self.stop()
                    (self.root / 'stop').unlink(missing_ok=True)
                if time.monotonic() >= next_game:
                    try:
                        self.state['game'] = rpc('info.status')
                    except (OSError, ValueError, KeyError, http.client.HTTPException):
                        self.state['game'] = {}
                    try:
                        self.state['player'] = rpc('player.getState')
                        inventory = rpc('player.getInventory')
                        self.state['inventory'] = inventory.get('data', inventory)
                    except (OSError, ValueError, KeyError, http.client.HTTPException):
                        self.state.update(player={}, inventory={})
                    next_game = time.monotonic() + 5
                for path in sorted(self.root.glob('rpc-*.json')):
                    if not lease_valid(self.root, self.host_token):
                        break
                    try:
                        request = json.loads(path.read_text(encoding='utf-8'))
                        path.unlink(missing_ok=True)
                        lease = json.loads((self.root / 'lease.json').read_text(encoding='utf-8'))
                    except (FileNotFoundError, ValueError):
                        continue
                    if time.time() > request.get('expires', 0):
                        continue
                    if request.get('run') != lease.get('run') or (self.root / 'stop').exists():
                        continue
                    try:
                        result = {'result': self.call(request['tool'], request.get('params', {}))}
                    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
                        result = {'error': 'Host tool call failed or timed out; verify game state before retrying'}
                    atomic(path.with_name(path.name.replace('rpc-', 'result-')), result)
                self.publish()
                time.sleep(0.25)
        finally:
            self.stop()
            (self.root / 'stopped').touch()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host-token', required=True)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with (root / 'worker.lock').open('a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        Companion(root, options.host_token).run()
