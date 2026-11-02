"""Exercise Office tag transitions, builds and startup with a fake Podman store."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTAINERS = ROOT / 'setup_library/files/containers'
LATEST = 'localhost/craft_apps:latest'
DISABLED = 'localhost/craft_apps:dontrun'
FAKE_PODMAN = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
p=Path(os.environ['OFFICE_TEST_STATE'])
s=json.loads(p.read_text()); a=sys.argv[1:]; s['calls'].append(a); rc=0
if a[:2] == ['image', 'exists']:
    rc=125 if os.environ.get('OFFICE_STORAGE_ERROR') else (0 if a[2] in s['images'] else 1)
elif a[0] == 'build':
    if os.environ.get('OFFICE_BUILD_ERROR') and 'craft_apps' in a[a.index('-t')+1]: rc=1
    else: s['images'][a[a.index('-t')+1]]='new-image'
elif a[0] == 'tag': s['images'][a[2]]=s['images'][a[1]]
elif a[0] == 'untag':
    if len(a)==2:
        image=s['images'][a[1]]
        s['images']={k:v for k,v in s['images'].items() if v!=image}
    else:
        for name in a[2:]: s['images'].pop(name,None)
elif a[0] == 'rmi': s['images'].pop(a[-1],None)
elif a[0] == 'stop': s['running']=False
elif a[0] == 'run': s['running']=True
elif a[0] != 'save': rc=99
p.write_text(json.dumps(s)); sys.exit(rc)
'''

class OfficeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state.json'
        self.state.write_text(json.dumps({'images': {LATEST: 'old-image'}, 'running': True, 'calls': []}))
        fake = self.root / 'podman'; fake.write_text(FAKE_PODMAN); fake.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.root)+os.pathsep+os.environ['PATH'],
                    'OFFICE_TEST_STATE': str(self.state), 'ANSIBLE_LOCAL_TEMP': str(self.root/'ansible')}
        for key in ['LIBRARY_OFFICE','OFFICE_BUILD_ERROR','OFFICE_STORAGE_ERROR']:
            self.env.pop(key, None)
        for app in ['craft_apps', 'meshtastic', 'meshflash']:
            (self.root/app).mkdir(); (self.root/app/'Containerfile').touch()
        helper = (CONTAINERS/'craft_apps/set-enabled.sh').read_text()
        # All Podman calls are mocked; bypass only the privilege guard in this fixture.
        (self.root/'craft_apps/set-enabled.sh').write_text(helper.replace('$EUID', '0'))
        for name in ['build_pods.sh', 'create_tar_pods.sh']:
            shutil.copy(CONTAINERS/name, self.root/name)

    def data(self): return json.loads(self.state.read_text())
    def images(self, images):
        s=self.data();s['images']=images;self.state.write_text(json.dumps(s))
    def run_script(self, script, *args, status=0):
        result=subprocess.run(['bash',str(self.root/script),*args],env=self.env,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,status,result.stdout+result.stderr)
        return self.data()

class OfficeTagTests(OfficeFixture):
    def test_disable_and_reenable_keep_same_image(self):
        s=self.run_script('craft_apps/set-enabled.sh','no')
        self.assertEqual(s['images'],{DISABLED:'old-image'});self.assertFalse(s['running'])
        s=self.run_script('craft_apps/set-enabled.sh','yes')
        self.assertEqual(s['images'],{LATEST:'old-image'})
        self.assertFalse(any(c[0]=='rmi' for c in s['calls']))
        self.assertTrue(all(len(c)==3 for c in s['calls'] if c[0]=='untag'))

    def test_disabling_preserves_other_aliases(self):
        backup='localhost/craft_apps:backup'
        self.images({LATEST:'image',backup:'image'})
        s=self.run_script('craft_apps/set-enabled.sh','no')
        self.assertEqual(s['images'],{DISABLED:'image',backup:'image'})
        s=self.run_script('craft_apps/set-enabled.sh','yes')
        self.assertEqual(s['images'],{LATEST:'image',backup:'image'})

    def test_both_tags_enable_keeps_new_latest(self):
        self.images({LATEST:'new',DISABLED:'old'})
        self.assertEqual(self.run_script('craft_apps/set-enabled.sh','yes')['images'],{LATEST:'new'})

    def test_missing_image_cannot_be_enabled(self):
        self.images({});self.run_script('craft_apps/set-enabled.sh','yes',status=1)
        s=self.run_script('craft_apps/set-enabled.sh','no');self.assertFalse(s['running'])

    def test_storage_error_is_not_treated_as_missing(self):
        self.env['OFFICE_STORAGE_ERROR']='1'
        s=self.run_script('craft_apps/set-enabled.sh','no',status=125)
        self.assertEqual(s['images'],{LATEST:'old-image'});self.assertTrue(s['running'])

    def test_declined_build_is_retained_but_cannot_start(self):
        self.env['LIBRARY_OFFICE']='no'
        s=self.run_script('build_pods.sh')
        self.assertNotIn(LATEST,s['images']);self.assertEqual(s['images'][DISABLED],'new-image')
        self.assertFalse(s['running'])

    def test_rebuild_preserves_disabled_choice(self):
        self.images({DISABLED:'old-image'})
        s=self.run_script('build_pods.sh')
        self.assertNotIn(LATEST,s['images']);self.assertEqual(s['images'][DISABLED],'new-image')

    def test_explicit_yes_reenables_on_rebuild(self):
        self.images({DISABLED:'old-image'});self.env['LIBRARY_OFFICE']='yes'
        s=self.run_script('build_pods.sh')
        self.assertNotIn(DISABLED,s['images']);self.assertEqual(s['images'][LATEST],'new-image')

    def test_failed_build_preserves_disabled_image(self):
        self.images({DISABLED:'old-image'});self.env['OFFICE_BUILD_ERROR']='1'
        s=self.run_script('build_pods.sh',status=1)
        self.assertNotIn(LATEST,s['images']);self.assertEqual(s['images'][DISABLED],'old-image')

    def test_export_retains_disabled_tag(self):
        self.images({DISABLED:'old', 'meshflash':'other', 'meshtastic':'other'})
        s=self.run_script('create_tar_pods.sh')
        self.assertIn(['save','-o','craft_apps.tar',DISABLED],s['calls'])

    def test_prompt_requires_yes_and_explains_input_devices(self):
        source=(ROOT/'bootstrap').read_text()
        functions='\n'.join(re.search(r'^'+name+r'\(\) \{\n.*?^\}',source,re.M|re.S).group()
                            for name in ['confirm','prompt_office_addon'])
        for answer,expected in [('yes','yes'),('y','yes'),('no','no'),('','no')]:
            result=subprocess.run(['bash','-c','msg_info() { echo "$1"; };\n'+functions+
                                   '\nprompt_office_addon\necho "CHOICE=$LIBRARY_OFFICE"'],
                                  input=answer+'\n',capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('CHOICE='+expected,result.stdout)
            self.assertIn('keyboard AND a pointing device',result.stdout)

@unittest.skipUnless(shutil.which('ansible-playbook'), 'Ansible is required')
class OfficeStartupTests(OfficeFixture):
    def exercise(self, images):
        self.images(images)
        source=yaml.safe_load((ROOT/'setup_library/files/start_library.yml').read_text())[0]
        task=copy.deepcopy(next(t for t in source['tasks'] if t.get('name')=='manage optional Office add-on'))
        startup=next(t for t in task['block'] if t['name']=='start optional Craft office desktop')
        for t in startup['block']:
            for module in ['ansible.builtin.file','ansible.builtin.stat']:
                if module in t:t[module]['path']=str(self.root/'documents')
            if 'ansible.builtin.uri' in t:
                t.clear();t.update({'name':'test service health','ansible.builtin.debug':{'msg':'healthy'}})
        play=[{'hosts':'localhost','gather_facts':False,'vars':{'craft_puid':'','craft_pgid':''},'tasks':[task]}]
        (self.root/'test.yml').write_text(yaml.safe_dump(play))
        result=subprocess.run(['ansible-playbook','-i','localhost,','-c','local',str(self.root/'test.yml')],
                              env=self.env,capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        return self.data()

    def test_latest_starts_https_only(self):
        s=self.exercise({LATEST:'image'});self.assertTrue(s['running'])
        run=next(c for c in s['calls'] if c[0]=='run')
        self.assertIn('3001:3001',run);self.assertNotIn('3000:6080',run)
        self.assertTrue((self.root/'documents').is_dir())

    def test_disabled_missing_and_both_tags_stop_and_skip(self):
        for images in [{DISABLED:'image'}, {}, {LATEST:'new',DISABLED:'old'}]:
            with self.subTest(images=images):
                s=self.data();s['calls']=[];s['running']=True;self.state.write_text(json.dumps(s))
                s=self.exercise(images)
                self.assertFalse(s['running']);self.assertFalse(any(c[0]=='run' for c in s['calls']))
                self.assertFalse((self.root/'documents').exists())

if __name__=='__main__': unittest.main()
