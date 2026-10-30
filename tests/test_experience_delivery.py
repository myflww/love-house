"""Episode portability, presentation and the private-free AstrBot package."""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from urllib.error import HTTPError
from urllib.request import Request
import zipfile

from tests import test_fish_life_workflow as fish_workflow

ROOT=Path(__file__).resolve().parents[1]
PLUGIN_FILES={'__init__.py','main.py','bridge.py','source_client.py','metadata.yaml','_conf_schema.json','README.md','LICENSE'}


class ExperienceDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.life=fish_workflow.FishLifeWorkflowTests()
        self.life.setUp()
        try:self.life.test_one_cross_platform_life_event_is_readable_and_recalled_without_technical_logs_or_other_fish()
        except BaseException:self.life.tearDown();raise
        self.host=self.life.host

    def tearDown(self):self.life.tearDown()

    def original(self):return deepcopy(self.host.snapshot('default'))

    def assert_rebound(self,new_id):
        self.assertNotEqual(new_id,'default')
        view=self.host.experiences_view(new_id)
        self.assertEqual(view['total'],1,view)
        episode=view['entries'][0]['episode']
        self.assertEqual(episode['library_id'],new_id)
        self.assertIn('海边周六的天气',episode['what']['quote'])
        self.assertIn('因为朋友',episode['reason']['quote'])
        self.assertIn('没有降雨',episode['outcome']['quote'])
        self.assertEqual(episode['reason']['basis'],'platform_participant_statement')
        self.assertFalse(episode['reason_verified'])
        self.assertFalse(self.host.sources.list(new_id))
        self.assertFalse(self.host.connections.list(new_id))
        self.assertFalse(self.host.organizer_view(new_id)['settings']['enabled'])

    def test_sharing_import_rebinds_episode_to_new_fish_without_live_sources_tokens_or_source_mutation(self):
        before=self.original()
        downloaded=self.host.sharing.download('default',format='json')
        for connection in self.host.connections.list('default'):
            token=self.host.connections.get(connection['id'],secret=True)['token']
            self.assertNotIn(token,downloaded['content'])
        package=json.loads(downloaded['content'])
        self.assertFalse(package['privacy']['includes_connections']);self.assertFalse(package['privacy']['includes_keys'])
        result=self.host.sharing.import_file(downloaded['content'],name='经历分享导入')
        self.assert_rebound(result['library']['id'])
        self.assertEqual(self.original(),before)

    def test_backup_restore_rebinds_episode_without_rebinding_source_connections_or_touching_original(self):
        before=self.original();backup=self.host.backups.create('default')
        text=self.host.backups.path(backup['id']).read_text()
        for connection in self.host.connections.list('default'):
            self.assertNotIn(self.host.connections.get(connection['id'],secret=True)['token'],text)
        result=self.host.backups.restore(backup['id'],'default',name='经历备份恢复')
        self.assert_rebound(result['library']['id'])
        self.assertEqual(self.original(),before)

    def test_import_cannot_resign_a_stale_quote_hidden_inside_a_new_negated_statement(self):
        before=self.original();package=json.loads(self.host.sharing.download('default')['content'])
        nodes=package['memory']['nodes']
        episode_node=next(n for n in nodes.values() if isinstance(n.get('meta',{}).get('experience'),dict))
        what_id=episode_node['meta']['experience']['what']['id']
        nodes[what_id]['text']='并没有'+nodes[what_id]['text']
        result=self.host.sharing.import_file(json.dumps(package,ensure_ascii=False),name='带冲突的外来资料')
        view=self.host.experiences_view(result['library']['id'])
        self.assertEqual(view['total'],0,view)
        self.assertEqual(view['unavailable_experiences'],1)
        self.assertEqual(self.original(),before)

    def test_package_endpoint_contains_only_allowlisted_sources_and_current_sdk(self):
        request=Request(self.life.base+'/api/adapters/astrbot/package')
        with self.life.http.open(request,timeout=10) as response:
            self.assertEqual(response.status,200)
            self.assertIn('application/zip',response.headers['Content-Type'])
            raw=response.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names=archive.namelist()
            self.assertEqual(len(names),8)
            self.assertEqual(set(names),{'astrbot_plugin_love_house/'+name for name in PLUGIN_FILES})
            self.assertEqual(archive.read('astrbot_plugin_love_house/source_client.py'),(ROOT/'nkb/service/source_client.py').read_bytes())
            self.assertFalse(any('config.json' in n or 'sqlite' in n or 'outbox' in n or n.endswith('.pyc') for n in names))
            for c in self.host.connections.list('default'):
                token=self.host.connections.get(c['id'],secret=True)['token'].encode()
                self.assertTrue(all(token not in archive.read(n) for n in names))

    def test_registered_source_bearer_cannot_download_management_plugin_zip(self):
        source=self.host.sources.list('default')[0]
        token=self.host.connections.get(source['connection_id'],secret=True)['token']
        request=Request(self.life.base+'/api/adapters/astrbot/package',headers={'Authorization':'Bearer '+token})
        with self.assertRaises(HTTPError) as caught:self.life.http.open(request,timeout=10)
        self.assertEqual(caught.exception.code,403)


class ExperiencePresentationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node optional for browser helper behavior')
    def test_real_index_presentation_hides_technical_sources_without_mutating_or_deleting_records(self):
        script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[1],'utf8');
const match=html.match(/function memoryPresentationMatches\(n\)\{[^\n]+/);assert(match);
const S={isDemo:false,mode:'serve',memoryDisplay:'memories',selected:null,focus:null,active:new Set(),adj:new Map()};
const raw={id:'technical',meta:{source:'tool_observation'},text:'一条实际观察原文'};
const turn={id:'dialogue',meta:{source:'conversation_turn'},text:'保留完整原话'};
const episode={id:'organized',meta:{source:'organizer',experience:{schema:'love-house-experience/v1'}},text:'整理的真实经历'};
S.nodes=[raw,turn,episode];const before=JSON.stringify(S.nodes);
const visible=vm.runInNewContext(match[0]+';memoryPresentationMatches',{S});
assert.equal(visible(raw),false);assert.equal(visible(turn),true);assert.equal(visible(episode),true);
S.memoryDisplay='all';assert.equal(visible(raw),true);S.memoryDisplay='memories';
S.selected='technical';assert.equal(visible(raw),true);S.selected=null;
S.active.add('technical');assert.equal(visible(raw),true);S.active.clear();
S.focus='organized';S.adj.set('organized',[{id:'technical'}]);assert.equal(visible(raw),true);S.focus=null;
S.isDemo=true;assert.equal(visible(raw),true);S.isDemo=false;S.mode='embedded';assert.equal(visible(raw),true);
assert.equal(JSON.stringify(S.nodes),before);assert.equal(S.nodes.length,3);
console.log('presentation is a pure display filter, not a memory deletion');
'''
        result=subprocess.run([shutil.which('node'),'-e',script,str(ROOT/'nkb/viz/web/index.html')],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('pure display filter',result.stdout)


if __name__=='__main__':unittest.main()
