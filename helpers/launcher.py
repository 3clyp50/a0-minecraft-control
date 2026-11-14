import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
import zlib
from helpers import defer, plugins
from helpers.ws_manager import get_shared_ws_manager
from plugins._a0_connector.helpers import ws_runtime as connector
from usr.plugins.minecraft_control.helpers.state import ROOT

LOCK = threading.RLock()
SESSIONS = [threading.Lock() for _ in range(3)]
ACTIVE = LAST = WATCHER = None
SETUP, GAME, TOOLS, RECEIVED = {}, {}, [], 0
MAX_RESULT = 32 * 1024 * 1024
HOST_FILES = ('companion.py', 'controller.py', 'dependencies.py', 'profiles.py', 'mcp-call.mjs', 'allowed.json')


def gateway_sid():
    status = connector.launcher_gateway_status()
    gateway = status.get('gateway') or {}
    scopes = gateway.get('scopes') or {}
    if (status.get('connected') and not status.get('multiple_hosts') and gateway.get('master_enabled') and
            all(scopes.get(k) for k in ('files', 'file_write', 'code_execution'))):
        return connector.active_launcher_gateway_sid()
    return None


def status():
    gateway = connector.launcher_gateway_status()
    return {'ready':bool(gateway_sid()), 'connected':gateway.get('connected', False),
            'multiple_hosts':gateway.get('multiple_hosts', False)}


def snapshot():
    with LOCK:
        online = bool(ACTIVE and ACTIVE.get('online') and gateway_sid() == ACTIVE['sid'] and time.monotonic()-RECEIVED < 30)
        return {**deepcopy(GAME if online else {}), 'online':online, 'setup':deepcopy(SETUP)}


def identity():
    value = json.loads((ROOT / 'instance.json').read_text())['id']
    if not re.fullmatch('[a-f0-9]{32}', value): raise ValueError('Invalid plugin instance identity')
    return value


def host_code(connection, request, deploy=False):
    payload = base64.b64encode(json.dumps({**request, 'token':connection['token']}).encode()).decode()
    code = ['import os,json,base64,zlib,runpy', 'from pathlib import Path',
            "assert os.name=='nt', 'Minecraft host requires Windows'",
            "base=(Path(os.environ['LOCALAPPDATA'])/'AgentZero/Minecraft').resolve()",
            f"root=(base/{connection['instance']!r}).resolve()",
            "assert root.parent==base, 'Invalid Minecraft cache path'"]
    if deploy:
        files = {name:(Path(__file__).parents[1] / 'host' / name).read_text(encoding='utf-8') for name in HOST_FILES}
        bundle = base64.b64encode(zlib.compress(json.dumps(files).encode())).decode()
        code += ["root.mkdir(parents=True,exist_ok=True)", "(root/'host').mkdir(exist_ok=True)",
                 f"files=json.loads(zlib.decompress(base64.b64decode({bundle!r})))",
                 "for name,source in files.items():",
                 "    target=root/'host'/name",
                 "    if not target.exists() or target.read_text(encoding='utf-8')!=source:",
                 "        target.write_text(source,encoding='utf-8')"]
    code += [f"request=json.loads(base64.b64decode({payload!r}))",
             "module=runpy.run_path(str(root/'host/controller.py'))", "module['respond'](root,request)"]
    return '\n'.join(code)


async def exchange(connection, operation, session=0, deploy=False, timeout=60):
    lock = SESSIONS[session]
    while not lock.acquire(blocking=False): await asyncio.sleep(.05)
    op = uuid.uuid4().hex
    try:
        if gateway_sid() != connection['sid']:
            raise ValueError('Launcher disconnected or its required Host access changed')
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        connector.store_pending_exec_op(op, sid=connection['sid'], future=future, loop=loop, context_id='_minecraft_control')
        await connector.emit_connector_event(connection['sid'], 'connector_exec_op', {
            'op_id':op, 'context_id':'_minecraft_control', 'session':session, 'runtime':'python',
            'code':host_code(connection, operation, deploy),
            'timeouts':{'first_output_timeout':timeout, 'between_output_timeout':timeout,
                        'max_exec_timeout':timeout, 'dialog_timeout':timeout},
        }, handler_id=__name__, manager=get_shared_ws_manager())
        result = await asyncio.wait_for(future, timeout+15)
        if not result.get('ok'): raise ValueError('Launcher host operation failed; check Host access')
        output = (result.get('result') or {}).get('output', '')
        matches = re.findall(r'^A0_MINECRAFT_RESULT=(\{[^\r\n]+\})\s*$', output, re.M)
        if len(matches) != 1:
            raise ValueError('Launcher returned an incomplete result. Check setup; verify the game before repeating an action')
        return json.loads(matches[0])
    except asyncio.TimeoutError as error:
        raise ValueError('Launcher request timed out; verify game state before retrying') from error
    finally:
        connector.clear_pending_exec_op(op)
        lock.release()


def decode(packet, raw):
    if type(packet.get('size')) is not int or not 0 <= packet['size'] <= MAX_RESULT:
        raise ValueError('Invalid result size')
    if len(raw) != packet['size'] or hashlib.sha256(raw).hexdigest() != packet.get('sha256'):
        raise ValueError('Incomplete Minecraft transfer')
    inflater = zlib.decompressobj()
    data = inflater.decompress(raw, MAX_RESULT+1)
    if len(data) > MAX_RESULT or not inflater.eof or inflater.unused_data:
        raise ValueError('Minecraft result exceeds the transfer limit')
    response = json.loads(data)
    if not response.get('ok'): raise ValueError(response.get('error', 'Windows operation failed'))
    return response['result']


async def request(connection, operation, session=0, deploy=False, timeout=60):
    packet = await exchange(connection, operation, session, deploy, timeout)
    if 'data' in packet:
        return decode(packet, base64.b64decode(packet['data'], validate=True))
    transfer = packet.get('transfer', '')
    if not re.fullmatch('[a-f0-9]{32}', transfer) or type(packet.get('size')) is not int or not 0 < packet['size'] <= MAX_RESULT:
        raise ValueError('Invalid Minecraft transfer')
    raw = bytearray()
    try:
        while len(raw) < packet['size']:
            part = await exchange(connection, {'action':'fetch','transfer':transfer,'offset':len(raw)}, session)
            chunk = decode(part, base64.b64decode(part['data'], validate=True))
            data = base64.b64decode(chunk['chunk'], validate=True)
            if not data or len(data) > 48000: raise ValueError('Invalid transfer chunk')
            raw.extend(data)
        return decode(packet, bytes(raw))
    finally:
        try: await exchange(connection, {'action':'release','transfer':transfer}, session)
        except Exception: pass


def new_connection():
    sid = gateway_sid()
    if not sid: raise ValueError('Open this instance in Launcher and enable Files, Read & write, and Code execution')
    return {'sid':sid, 'token':uuid.uuid4().hex, 'instance':identity(), 'online':False}


async def setup(install=False):
    global SETUP, LAST
    with LOCK:
        if ACTIVE: raise ValueError('Disconnect before changing setup')
        connection = new_connection()
        LAST = connection
    result = await request(connection, {'action':'install' if install else 'setup'}, deploy=True, timeout=180 if install else 20)
    with LOCK: SETUP = {**SETUP, **result}
    return {'ok':True, 'setup':result}


async def profile_operation(action, version=None):
    global SETUP, LAST
    if action not in ('profile_versions', 'install_profile', 'open_launcher'):
        raise ValueError('Invalid profile operation')
    with LOCK:
        if ACTIVE: raise ValueError('Disconnect before changing setup')
        connection = new_connection()
        LAST = connection
    result = await request(connection, {'action':action, 'version':version}, deploy=True, timeout=240 if action == 'install_profile' else 90)
    if action != 'open_launcher':
        with LOCK: SETUP = result
    return {'ok':True, 'setup':deepcopy(SETUP)}


async def connect(context_id=''):
    global ACTIVE, LAST, WATCHER, GAME, TOOLS, SETUP, RECEIVED
    with LOCK:
        if ACTIVE: raise ValueError('Minecraft is already connected or starting')
        connection = new_connection()
        connection['context_id'] = context_id
        ACTIVE = connection
        LAST = connection
    try:
        SETUP = {**SETUP, **await request(connection, {'action':'setup'}, deploy=True, timeout=20)}
        if not SETUP.get('node') or not SETUP.get('server'):
            with LOCK:
                if ACTIVE is connection: ACTIVE = None
            return {'ok':False, 'setup':SETUP}
        result = await request(connection, {'action':'connect', 'chat_enabled':chat_enabled(connection)}, timeout=25)
        with LOCK:
            if ACTIVE is not connection: raise ValueError('Connection cancelled')
            connection['online'] = True
            LAST = connection
            GAME, TOOLS, RECEIVED = result['state'], result['tools'], time.monotonic()
            WATCHER = defer.DeferredTask().start_task(maintain, connection)
        from usr.plugins.minecraft_control.helpers import runtime
        with runtime.LOCK:
            if not runtime.STATE['busy']: runtime.STATE['phase'] = 'Idle'
        return {'ok':True}
    except BaseException:
        await disconnect(connection)
        raise


def chat_enabled(connection):
    from agent import AgentContext
    parent = AgentContext.get(connection.get('context_id', ''))
    return bool(parent and (plugins.get_plugin_config('minecraft_control', agent=parent.agent0) or {}).get('chat_relay', True) is True)


async def maintain(connection):
    global GAME, RECEIVED
    try:
        while ACTIVE is connection:
            await asyncio.sleep(5)
            if ACTIVE is not connection: return
            if 'minecraft_control' not in plugins.get_enabled_plugins(None): return
            result = await request(connection, {'action':'pulse', 'chat_enabled':chat_enabled(connection)}, session=1, timeout=10)
            with LOCK:
                if ACTIVE is connection: GAME, RECEIVED = result, time.monotonic()
            from usr.plugins.minecraft_control.helpers import runtime
            await runtime.receive_chat(connection, result)
    finally:
        await disconnect(connection)


async def disconnect(expected=None, uninstall=False):
    global ACTIVE
    from usr.plugins.minecraft_control.helpers import runtime
    with LOCK:
        if expected is not None and ACTIVE is not expected: return {'ok':True}
        connection = ACTIVE or (LAST if uninstall else None)
        ACTIVE = None
        runtime.cancel()
    if connection:
        try:
            await request(connection, {'action':'uninstall' if uninstall else 'disconnect'}, session=2)
        except Exception:
            return {'ok':True, 'pending':True}
    return {'ok':True}


async def game_operation(operation, session=0):
    connection = ACTIVE
    if not connection or not snapshot()['online']: raise ValueError('Connect Minecraft first')
    result = await request(connection, operation, session=session)
    if ACTIVE is not connection: raise ValueError('Connection changed during the operation')
    return result


async def stop_game(run=None):
    if ACTIVE and ACTIVE.get('online'):
        return await game_operation({'action':'stop','run':run}, session=2)
