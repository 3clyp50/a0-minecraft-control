"""Host companion. No listener, credentials, or shell commands cross the spool."""
import argparse
import http.client
import json
import os
import re
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

def rpc(method, params=None):
    discovery = json.loads((Path.home() / '.mcpfabric/bridge.json').read_text())
    url = urlsplit(discovery['url'])
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port:
        raise ValueError('Invalid local bridge')
    connection = http.client.HTTPConnection('127.0.0.1', url.port, timeout=2)
    try:
        connection.request('POST', '/rpc', json.dumps({'method': method, 'params': params or {}}),
                           {'Authorization': 'Bearer ' + discovery['token'], 'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = json.loads(response.read(2_000_000))
        if response.status != 200 or not body.get('ok'):
            raise ValueError('Minecraft unavailable')
        return body['result']
    finally:
        connection.close()

ACTIVE_TOOLS = {'screenshot', 'look', 'look_at', 'set_movement', 'jump', 'navigate_to',
    'break_block', 'place_block', 'place_block_at', 'start_using_item', 'use_item',
    'use_entity', 'attack_entity', 'select_hotbar_slot', 'swap_slots', 'drop_slot', 'drop_held_item'}


def resume_pause():
    if rpc('info.status').get('aiPaused'):
        return
    screen = rpc('screen.get')
    if not screen.get('inWorld') or screen.get('screen') != 'pause':
        return
    rpc('screen.close')
    for _ in range(10):
        time.sleep(.1)
        if rpc('screen.get').get('screen') == 'none':
            time.sleep(.15)
            return
    raise ValueError('Minecraft paused again. Press F3+P in game once to disable Pause on lost focus, then retry. The action was not sent.')


def tagged_request(event):
    data = event.get('data')
    if event.get('type') != 'chat' or not isinstance(data, dict): return None
    if data.get('self') is not True or data.get('kind') != 'chat': return None
    text = data.get('text')
    if not isinstance(text, str): return None
    body = re.sub(r'^<[^>]{1,40}>\s*', '', text).strip()
    match = re.fullmatch(r'@a0[\s,:]+(.{1,300})', body, re.IGNORECASE)
    return match[1].strip() if match and match[1].isprintable() else None


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
        self.state = {'game': {}, 'player': {}, 'inventory': {}, 'requests': []}
        self.chat_cursor = None
        self.chat_epoch = uuid.uuid4().hex

    def call(self, tool, params=None):
        message = (params or {}).get('message')
        if tool == 'send_chat' and isinstance(message, str) and re.match(r'^@a0(?:[\s,:]|$)', message.strip(), re.IGNORECASE):
            raise ValueError('Use show_message for local replies; do not echo @a0 requests')
        if tool in ACTIVE_TOOLS:
            try: auto_resume = json.loads((self.root / 'lease.json').read_text()).get('auto_resume') is True
            except (OSError, ValueError): auto_resume = False
            if auto_resume: resume_pause()
        result = subprocess.run([self.node, str(Path(__file__).with_name('mcp-call.mjs'))],
            input=json.dumps({'server': self.server, 'tool': tool, 'params': params or {}}),
            capture_output=True, text=True, encoding='utf-8', timeout=35,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('MCPFabric call failed; check the game and host MCP configuration')
        return json.loads(result.stdout)

    def read_chat(self):
        lease = json.loads((self.root / 'host-lease.json').read_text())
        if lease.get('chat_enabled') is not True:
            self.chat_cursor = None
            self.state['requests'] = []
            return
        params = {'limit': 500}
        if self.chat_cursor is not None: params['sinceId'] = self.chat_cursor
        result = rpc('events.getRecent', params)
        last_id = result.get('lastId', 0)
        if type(last_id) is not int or last_id < 0: raise ValueError('Invalid game event cursor')
        if self.chat_cursor is None or last_id < self.chat_cursor:
            self.chat_cursor = last_id
            self.chat_epoch = uuid.uuid4().hex
            self.state.update(requests=[], chat_epoch=self.chat_epoch)
            return
        for event in result.get('events', []):
            if not isinstance(event, dict): continue
            event_id = event.get('id')
            if type(event_id) is not int or event_id <= self.chat_cursor: continue
            if event.get('type') == 'left_world':
                self.state['requests'] = []
                self.chat_epoch = uuid.uuid4().hex
                self.state['chat_epoch'] = self.chat_epoch
            text = tagged_request(event)
            if text: self.state['requests'].append({'id':event_id, 'text':text})
        self.chat_cursor = last_id
        self.state['requests'] = self.state['requests'][-20:]

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
            self.read_chat()
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
                    try: self.read_chat()
                    except (OSError, ValueError, KeyError, http.client.HTTPException):
                        self.state['requests'] = []
                        self.chat_cursor = None
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
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        Companion(root, options.host_token).run()
