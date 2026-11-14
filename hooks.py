import shutil
import uuid
from helpers import defer
from usr.plugins.minecraft_control.helpers.state import ROOT, write


def install():
    ROOT.mkdir(parents=True, exist_ok=True)
    if not (ROOT / 'instance.json').exists():
        write(ROOT / 'instance.json', {'id':uuid.uuid4().hex})
    from usr.plugins.minecraft_control.helpers import launcher
    if launcher.gateway_sid():
        task = defer.DeferredTask().start_task(prepare_host, True)
        task.result_sync(timeout=210)


async def prepare_host(install_server=False):
    from usr.plugins.minecraft_control.helpers import launcher
    result = await launcher.setup()
    setup = result['setup']
    if install_server and setup.get('can_install') and not setup.get('server'):
        result = await launcher.setup(install=True)
    return result


async def prepare_profile(action, version=None):
    from usr.plugins.minecraft_control.helpers import launcher
    result = await launcher.profile_operation(action, version)
    if action == 'install_profile' and result['setup'].get('can_install') and not result['setup'].get('server'):
        await prepare_host(True)
        result = await launcher.profile_operation('profile_versions')
    return result


def pre_update():
    from usr.plugins.minecraft_control.helpers import launcher
    task = defer.DeferredTask().start_task(launcher.disconnect)
    task.result_sync(timeout=80)


def uninstall():
    from usr.plugins.minecraft_control.helpers import launcher
    task = defer.DeferredTask().start_task(launcher.disconnect, uninstall=True)
    task.result_sync(timeout=80)
    if ROOT.exists(): shutil.rmtree(ROOT)
