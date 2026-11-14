import hashlib, importlib.util, io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('profiles',Path(__file__).parents[1]/'host/profiles.py')
profiles=importlib.util.module_from_spec(spec);spec.loader.exec_module(profiles)
ORIGINAL_FETCH=profiles.fetch

def jar(mod_id):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:z.writestr('fabric.mod.json',json.dumps({'id':mod_id}))
 return out.getvalue()

class ProfilesTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.root=self.base/('a'*32);self.root.mkdir()
  self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.base/'local'),'APPDATA':str(self.base/'roaming')});self.env.start();self.addCleanup(self.env.stop)
  self.minecraft,self.owned=profiles.paths(self.root);self.minecraft.mkdir(parents=True)
  self.original={'profiles':{'old':{'name':'My world','gameDir':'unchanged','lastVersionId':'1.21.1'}},'settings':{'keep':True},'version':3}
  self.config=self.minecraft/'launcher_profiles.json';self.config.write_text(json.dumps(self.original))
  self.original_bytes=self.config.read_bytes()
  self.blobs={};self.mods={}
  for slug,project in [('fabric-api','api'),('mcpfabric','bridge')]:
   data=jar(slug);url='https://cdn.modrinth.com/'+slug+'.jar';self.blobs[url]=data
   self.mods[slug]={'id':slug+'-version','project_id':project,'version_number':'1.0','files':[{'primary':True,'filename':slug+'.jar','url':url,'hashes':{'sha512':hashlib.sha512(data).hexdigest()},'size':len(data)}],'dependencies':[]}
  self.mods['mcpfabric']['dependencies']=[{'dependency_type':'required','project_id':'api','version_id':None}]
  vanilla=json.dumps({'id':'26.3','javaVersion':{'majorVersion':25,'component':'java-runtime-epsilon'}}).encode();self.blobs['https://piston-meta.mojang.com/version.json']=vanilla
  self.blobs['https://maven.fabricmc.net/test/loader/1/loader-1.jar']=b'loader'
  self.catalog={'versions':['26.3'],'recommended':'26.3','api':{'26.3':self.mods['fabric-api']},'bridge':{'26.3':self.mods['mcpfabric']},'vanilla':{'26.3':{'url':'https://piston-meta.mojang.com/version.json','sha1':hashlib.sha1(vanilla).hexdigest()}}}
  self.fabric={'id':'fabric','inheritsFrom':'26.3','mainClass':'net.fabricmc.loader.impl.launch.knot.KnotClient','libraries':[{'name':'test:loader:1','url':'https://maven.fabricmc.net/','sha256':hashlib.sha256(b'loader').hexdigest(),'size':6}]}
  def metadata(url):
   return self.fabric.copy() if url.endswith('/profile/json') else [{'loader':{'version':'0.20.1','stable':True}}]
  for item in [patch.object(profiles,'launcher_closed'),patch.object(profiles,'catalog',return_value=self.catalog),patch.object(profiles,'metadata',side_effect=metadata),patch.object(profiles,'fetch',side_effect=lambda url,*args:self.blobs[url])]:item.start();self.addCleanup(item.stop)
 def test_install_preserves_existing_profiles_and_backs_up(self):
  result=profiles.install(self.root,'26.3');updated=json.loads(self.config.read_bytes())
  self.assertEqual(updated['profiles']['old'],self.original['profiles']['old']);self.assertEqual(updated['settings'],self.original['settings'])
  self.assertEqual(len(updated['profiles']),2);self.assertEqual(next(self.minecraft.glob('*.bak')).read_bytes(),self.original_bytes)
  entry=next(v for k,v in updated['profiles'].items() if k!='old');self.assertEqual(Path(entry['gameDir']),self.owned/'26.3/game')
  self.assertEqual((Path(entry['gameDir'])/'options.txt').read_text(),'pauseOnLostFocus:false\n')
  self.assertTrue((Path(entry['gameDir'])/'mods/mcpfabric.jar').is_file());self.assertEqual(result['installed'][0]['name'],'Agent Zero 26.3')
  self.assertEqual(json.loads((self.minecraft/'versions'/entry['lastVersionId']/(entry['lastVersionId']+'.json')).read_bytes())['javaVersion']['majorVersion'],25)
 def test_repeat_install_keeps_worlds_and_does_not_duplicate(self):
  profiles.install(self.root,'26.3');world=self.owned/'26.3/game/saves/World/level.dat';world.parent.mkdir(parents=True);world.write_bytes(b'world')
  options=self.owned/'26.3/game/options.txt';options.write_text('pauseOnLostFocus:true\n')
  before=self.config.read_bytes();profiles.install(self.root,'26.3')
  self.assertEqual(options.read_text(),'pauseOnLostFocus:true\n')
  self.assertEqual(self.config.read_bytes(),before);self.assertEqual(world.read_bytes(),b'world');self.assertEqual(len(list(self.minecraft.glob('*.bak'))),1)
 def test_interrupted_registration_can_be_retried(self):
  with patch.object(profiles,'register',side_effect=ValueError('launcher opened')):
   with self.assertRaises(ValueError):profiles.install(self.root,'26.3')
  self.assertEqual(profiles.inspect(self.root)['installed'],[])
  result=profiles.install(self.root,'26.3');self.assertEqual(result['installed'][0]['name'],'Agent Zero 26.3')
 def test_checksum_failure_never_registers_or_leaves_profile(self):
  self.blobs['https://cdn.modrinth.com/mcpfabric.jar']=b'corrupt'
  with self.assertRaisesRegex(ValueError,'verification'):profiles.install(self.root,'26.3')
  self.assertEqual(self.config.read_bytes(),self.original_bytes);self.assertFalse((self.owned/'26.3').exists());self.assertEqual(list(self.owned.iterdir()),[])
 def test_modified_mod_is_preserved(self):
  profiles.install(self.root,'26.3');mod=self.owned/'26.3/game/mods/mcpfabric.jar';mod.write_bytes(b'user change')
  with self.assertRaisesRegex(ValueError,'modified'):profiles.install(self.root,'26.3')
  self.assertEqual(mod.read_bytes(),b'user change')
 def test_existing_unowned_folder_is_preserved(self):
  target=self.owned/'26.3';target.mkdir(parents=True);(target/'world').write_text('preserve')
  with self.assertRaisesRegex(ValueError,'already exists'):profiles.install(self.root,'26.3')
  self.assertEqual((target/'world').read_text(),'preserve')
 def test_bad_version_and_missing_launcher_do_not_write(self):
  for value in ('../outside','26.3/evil','26.4-snapshot-8',None):
   with self.assertRaises(ValueError):profiles.install(self.root,value)
  self.config.unlink()
  with self.assertRaisesRegex(ValueError,'open Java Edition'):profiles.install(self.root,'26.3')
  self.assertFalse(self.owned.exists())
 def test_launcher_race_keeps_new_user_settings(self):
  checks=[]
  def check():
   checks.append(True)
   if len(checks)==3:self.config.write_text(json.dumps({'profiles':{'new':{'name':'new user profile'}}}))
  with patch.object(profiles,'launcher_closed',side_effect=check):
   with self.assertRaisesRegex(ValueError,'changed during'):profiles.install(self.root,'26.3')
  self.assertIn('new',json.loads(self.config.read_bytes())['profiles'])
 def test_extra_required_dependency_rejected(self):
  self.mods['mcpfabric']['dependencies'].append({'dependency_type':'required','project_id':'unknown','version_id':None})
  with self.assertRaisesRegex(ValueError,'additional dependency'):profiles.install(self.root,'26.3')
  self.assertEqual(self.config.read_bytes(),self.original_bytes)
 def test_external_download_host_is_rejected(self):
  with patch.object(profiles,'fetch',wraps=ORIGINAL_FETCH):
   with self.assertRaisesRegex(ValueError,'source'):profiles.fetch('https://example.com/mod.jar')

class CatalogTest(unittest.TestCase):
 def test_only_matching_stable_releases_are_offered(self):
  def mod(game,kind='release'):
   return {'date_published':'2026-01-01','version_type':kind,'loaders':['fabric'],'game_versions':[game]}
  vanilla={'versions':[{'id':'26.4-snapshot-8','type':'snapshot'},{'id':'26.3','type':'release'},{'id':'26.2','type':'release'}]}
  bridge=[mod('26.4-snapshot-8','beta'),mod('26.3'),mod('26.2')]
  api=[mod('26.4-snapshot-8','beta'),mod('26.3')]
  def get(url):return vanilla if url==profiles.MANIFEST else (bridge if '/mcpfabric/' in url else api)
  with tempfile.TemporaryDirectory() as temp,patch.object(profiles,'metadata',side_effect=get):
   data=profiles.catalog(Path(temp));self.assertEqual(data['versions'],['26.3']);self.assertEqual(data['recommended'],'26.3')
 def test_running_launcher_is_rejected(self):
  from types import SimpleNamespace
  for name in ('MinecraftLauncher.exe','Minecraft.exe'):
   with patch.object(profiles.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(profiles.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='"'+name+'","123"')):
    with self.assertRaisesRegex(ValueError,'Close Minecraft Launcher'):profiles.launcher_closed()

if __name__=='__main__':unittest.main()
