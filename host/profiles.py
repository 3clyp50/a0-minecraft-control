import csv, io, json, hashlib, os, re, shutil, subprocess, tempfile, time, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor

HOSTS = {'api.modrinth.com', 'cdn.modrinth.com', 'meta.fabricmc.net', 'maven.fabricmc.net', 'piston-meta.mojang.com'}
MANIFEST = 'https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'
MODRINTH = 'https://api.modrinth.com/v2/project/'
USER_AGENT = 'AgentZero-Minecraft/0.5.0 (local Minecraft profile installer)'


def fetch(url, limit=8*1024*1024):
    def check(value):
        parsed=urlsplit(value)
        if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.port not in (None,443) or parsed.username or parsed.password:
            raise ValueError('Unexpected Minecraft download source')
    check(url)
    try:
        with urlopen(Request(url,headers={'User-Agent':USER_AGENT}),timeout=30) as response:
            check(response.url)
            data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Minecraft download exceeds its size limit')
        return data
    except OSError as error:
        raise ValueError('Could not download Minecraft components. Check your Windows internet connection and retry.') from error


def metadata(url):
    return json.loads(fetch(url))


def game_version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:1\.\d{2}|2\d)\.\d+(?:\.\d+)?',value):
        raise ValueError('Choose a supported Minecraft release')
    return value


def paths(root):
    instance=root.name
    if not re.fullmatch('[a-f0-9]{32}',instance):raise ValueError('Invalid plugin instance')
    base=(Path(os.environ['LOCALAPPDATA'])/'AgentZero/MinecraftProfiles').resolve()
    profiles=(base/instance).resolve()
    if profiles.parent!=base:raise ValueError('Invalid Minecraft profile path')
    return Path(os.environ['APPDATA'])/'.minecraft', profiles


def launcher_files(minecraft):
    return [p for p in (minecraft/'launcher_profiles.json',minecraft/'launcher_profiles_microsoft_store.json') if p.is_file()]


def launcher_closed():
    result=subprocess.run(['tasklist.exe','/FI','IMAGENAME eq Minecraft*','/FO','CSV','/NH'],capture_output=True,text=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise ValueError('Could not check Minecraft Launcher. Close it and retry.')
    if any(row and row[0].lower() in ('minecraftlauncher.exe','minecraft.exe') for row in csv.reader(io.StringIO(result.stdout))):
        raise ValueError('Close Minecraft Launcher, then click Install profile again.')


def inspect(root):
    minecraft, profiles=paths(root)
    registrations=[]
    for file in launcher_files(minecraft):
        try: registrations.append(json.loads(file.read_bytes()).get('profiles',{}))
        except (OSError,ValueError):pass
    installed=[]
    for file in sorted(profiles.glob('*/profile.json')):
        try:
            value=json.loads(file.read_text(encoding='utf-8'))
            if value['game_version']==file.parent.name and registrations and all(
                    entries.get(value['profile_id'],{}).get('lastVersionId')==value['version_id'] and
                    entries.get(value['profile_id'],{}).get('gameDir')==str(file.parent/'game') for entries in registrations):
                installed.append({'game_version':value['game_version'],'name':value['name'],'path':str(file.parent/'game')})
        except (OSError,ValueError,KeyError):pass
    return {'launcher_ready':bool(launcher_files(minecraft)), 'installed':installed}


def catalog(root):
    cache=root/'profile-catalog.json'
    if cache.exists() and time.time()-cache.stat().st_mtime<3600:
        return json.loads(cache.read_text(encoding='utf-8'))
    query=urlencode({'loaders':'["fabric"]','include_changelog':'false'})
    urls=[MANIFEST,MODRINTH+'mcpfabric/version?'+query,MODRINTH+'fabric-api/version?'+query]
    with ThreadPoolExecutor(max_workers=3) as pool: vanilla,bridge,api=list(pool.map(metadata,urls))
    def releases(rows):
        result={}
        for item in sorted(rows,key=lambda v:v['date_published'],reverse=True):
            if item['version_type']!='release' or 'fabric' not in item['loaders']:continue
            for version in item['game_versions']:result.setdefault(version,item)
        return result
    bridge,api=releases(bridge),releases(api)
    versions=[v['id'] for v in vanilla['versions'] if v['type']=='release' and v['id'] in bridge and v['id'] in api and re.fullmatch(r'(?:1\.\d{2}|2\d)\.\d+(?:\.\d+)?',v['id'])]
    if not versions:raise ValueError('No matching stable Minecraft, Fabric API, and MCPFabric releases are available.')
    result={'versions':versions,'recommended':versions[0],'bridge':{v:bridge[v] for v in versions},'api':{v:api[v] for v in versions},'vanilla':{v['id']:v for v in vanilla['versions'] if v['id'] in versions}}
    cache.write_text(json.dumps(result),encoding='utf-8')
    return result


def setup(root):
    data=catalog(root)
    return {**inspect(root),'versions':data['versions'],'recommended':data['recommended']}


def download(url, path, digest, algorithm, size=None):
    if not isinstance(digest,str) or not re.fullmatch('[a-fA-F0-9]{'+str(hashlib.new(algorithm).digest_size*2)+'}',digest):
        raise ValueError('Missing Minecraft download checksum')
    if path.exists():
        if hashlib.new(algorithm,path.read_bytes()).hexdigest()!=digest.lower():
            raise ValueError('An existing Minecraft file differs from the official download; it was left unchanged.')
        return
    data=fetch(url,32*1024*1024)
    if (size is not None and len(data)!=size) or hashlib.new(algorithm,data).hexdigest()!=digest.lower():
        raise ValueError('Minecraft download verification failed; nothing was registered in the launcher.')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(data)


def install_mod(item, directory, expected_id):
    files=[f for f in item['files'] if f.get('primary')] or item['files'][:1]
    file=files[0];name=file['filename']
    if not re.fullmatch(r'[A-Za-z0-9_.+\-]+\.jar',name):raise ValueError('Invalid mod filename')
    path=directory/name
    download(file['url'],path,file['hashes']['sha512'],'sha512',file['size'])
    with zipfile.ZipFile(path) as jar:
        if jar.getinfo('fabric.mod.json').file_size>1024*1024:raise ValueError('Invalid Fabric mod metadata')
        mod=json.loads(jar.read('fabric.mod.json'))
    if mod.get('id')!=expected_id:raise ValueError('The downloaded mod has an unexpected identity')
    return {'file':name,'sha512':file['hashes']['sha512'],'version':item['version_number']}


def register(minecraft, record, game_dir):
    launcher_closed()
    files=launcher_files(minecraft)
    if not files:raise ValueError('Install Minecraft Launcher, open Java Edition once, then close the launcher and retry.')
    prepared=[]
    for path in files:
        raw=path.read_bytes();data=json.loads(raw)
        if not isinstance(data.get('profiles'),dict):raise ValueError('Minecraft Launcher profile settings are not recognized; no settings were changed.')
        existing=data['profiles'].get(record['profile_id'])
        expected={'name':record['name'],'type':'custom','gameDir':str(game_dir),'lastVersionId':record['version_id']}
        if existing:
            if any(existing.get(k)!=v for k,v in expected.items()):raise ValueError('This Agent Zero profile was changed in Minecraft Launcher; it was left unchanged.')
            continue
        data['profiles'][record['profile_id']]={**expected,'icon':'Furnace','created':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
        prepared.append((path,raw,json.dumps(data,indent=2).encode('utf-8')))
    launcher_closed()
    for path,raw,updated in prepared:
        if path.read_bytes()!=raw:raise ValueError('Minecraft Launcher settings changed during setup. Close the launcher and retry.')
        backup=path.with_name(path.name+'.agent-zero-'+uuid.uuid4().hex+'.bak')
        with backup.open('xb') as stream:stream.write(raw)
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_bytes(updated)
            if path.read_bytes()!=raw:raise ValueError('Minecraft Launcher settings changed during setup. Retry with the launcher closed.')
            os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)


def install(root, version):
    version=game_version(version)
    minecraft,profiles=paths(root)
    if not launcher_files(minecraft):raise ValueError('Install Minecraft Launcher, open Java Edition once, then close the launcher and retry.')
    launcher_closed()
    folder=(profiles/version).resolve()
    if folder.parent!=profiles:raise ValueError('Invalid Minecraft profile path')
    record_file=folder/'profile.json'
    if record_file.is_file():
        record=json.loads(record_file.read_text(encoding='utf-8'))
        if record.get('game_version')!=version:raise ValueError('Existing profile metadata does not match; no files were changed.')
        for mod in record['mods']:
            path=folder/'game/mods'/mod['file']
            if not path.is_file() or hashlib.sha512(path.read_bytes()).hexdigest()!=mod['sha512']:
                raise ValueError('This profile has modified or missing mods. Existing files were preserved; use another Minecraft version or repair the profile manually.')
        register(minecraft,record,folder/'game')
        return setup(root)
    if folder.exists():raise ValueError('The profile folder already exists without an installation record; it was left unchanged.')
    data=catalog(root)
    if version not in data['versions']:raise ValueError('This Minecraft release has no matching stable MCPFabric and Fabric API files.')
    api,bridge=data['api'][version],data['bridge'][version]
    for item in (api,bridge):
        for dep in item.get('dependencies',[]):
            if dep['dependency_type']=='required' and (dep.get('project_id')!=api['project_id'] or dep.get('version_id') not in (None,api['id'])):
                raise ValueError('This release needs an additional dependency; use the manual setup guide.')
    loaders=metadata('https://meta.fabricmc.net/v2/versions/loader/'+version)
    loader=next((v['loader']['version'] for v in loaders if v['loader']['stable'] and re.fullmatch(r'\d+\.\d+\.\d+',v['loader']['version']) and tuple(map(int,v['loader']['version'].split('.'))) >= (0,19,5)),None)
    if not loader:raise ValueError('No compatible stable Fabric Loader is available.')
    fabric=metadata(f'https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/profile/json')
    if fabric.get('inheritsFrom')!=version or fabric.get('mainClass')!='net.fabricmc.loader.impl.launch.knot.KnotClient':raise ValueError('Unexpected Fabric launch metadata')
    profile_id='agent-zero-'+root.name+'-'+version
    version_id=profile_id+'-fabric-'+loader
    fabric['id']=version_id
    profiles.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.install-',dir=profiles))
    try:
        mods=stage/'game/mods';mods.mkdir(parents=True)
        installed=[install_mod(api,mods,'fabric-api'),install_mod(bridge,mods,'mcpfabric')]
        vanilla=data['vanilla'][version]
        base_json=stage/'vanilla.json'
        download(vanilla['url'],base_json,vanilla['sha1'],'sha1')
        base=json.loads(base_json.read_bytes())
        if base['id']!=version:raise ValueError('Unexpected Minecraft version metadata')
        fabric['javaVersion']=base['javaVersion']
        for lib in fabric['libraries']:
            parts=lib['name'].split(':')
            if len(parts)!=3 or any(not re.fullmatch(r'[A-Za-z0-9_.+\-]+',p) for p in parts):raise ValueError('Unexpected Fabric library coordinates')
            group,artifact,number=parts
            relative=group.replace('.','/')+'/'+artifact+'/'+number+'/'+artifact+'-'+number+'.jar'
            url=lib['url']+relative
            digest=lib.get('sha256') or fetch(url+'.sha256',1024).decode().strip().split()[0]
            download(url,minecraft/'libraries'/relative,digest,'sha256',lib.get('size'))
        vanilla_dir=minecraft/'versions'/version;vanilla_dir.mkdir(parents=True,exist_ok=True)
        vanilla_path=vanilla_dir/(version+'.json')
        if not vanilla_path.exists():
            with vanilla_path.open('xb') as stream:stream.write(base_json.read_bytes())
        target=minecraft/'versions'/version_id;target.mkdir(parents=True,exist_ok=True)
        version_file=target/(version_id+'.json')
        if version_file.exists():
            previous=json.loads(version_file.read_bytes())
            for key in ('inheritsFrom','mainClass','libraries','javaVersion'):
                if previous.get(key)!=fabric.get(key):raise ValueError('Existing Fabric version differs; it was left unchanged.')
        else:
            with version_file.open('x',encoding='utf-8') as stream:json.dump(fabric,stream,indent=2)
        record={'name':'Agent Zero '+version,'game_version':version,'loader':loader,'java':base['javaVersion']['majorVersion'],'profile_id':profile_id,'version_id':version_id,'mods':installed}
        (stage/'profile.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        base_json.unlink()
        stage.rename(folder)
        register(minecraft,record,folder/'game')
    finally:
        if stage.exists() and stage.resolve().parent==profiles and stage.name.startswith('.install-'):shutil.rmtree(stage)
    return setup(root)


def open_launcher():
    candidates=[Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Minecraft Launcher/MinecraftLauncher.exe',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Minecraft Launcher/MinecraftLauncher.exe']
    for exe in candidates:
        if exe.is_file():subprocess.Popen([str(exe)]);return {'ok':True}
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Classes\ActivatableClasses\Package') as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                if winreg.EnumKey(key,index).startswith('Microsoft.4297127D64EC6_'):
                    subprocess.Popen(['explorer.exe',r'shell:AppsFolder\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft']);return {'ok':True}
    except FileNotFoundError:pass
    raise ValueError('Install Minecraft Launcher from minecraft.net/download, then open Java Edition once.')
