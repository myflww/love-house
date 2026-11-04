"""Real share/backup imports rebind faithful statements, never forged evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nkb import Brain
from nkb.companion.structured import build_structured_context
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.experiences import rebind_experiences_after_import
from nkb.organizer.state import apply_plan,build_input,fingerprint,validate_plan
from nkb.service.controls import forget,forget_plan,set_enabled
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost


class StatementPortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.host=MemoryHost(Path(self.temp.name),key_store=KeyStore(allow_keychain=False))
        config=self.host.new_connection({'name':'合成来源','host':'agent','library_id':'default','session_scope':'connection'})
        self.cid=config['connection']['id'];token=self.host.connections.get(self.cid,secret=True)['token']
        self.ids={};self.sources={}
        for key,text,reply,role,certainty,domain in (
                ('uncertain','我猜朋友生气了。','我还不确定。','user','uncertain','unknown'),
                ('roleplay','小说里我住在火星，这只是设定。','这是故事。','user','clear','roleplay'),
                ('assistant','请记录助手的猜想。','我猜朋友暂时在忙。','assistant','uncertain','unknown')):
            self.host.accept(self.cid,token,{'session_id':'合成窗口','event_id':key,'normalized':{
                'type':'turn','turn_id':key,'status':'complete','user':text,'assistant':reply}})
            def organize(brain):
                nid=next(n['id'] for n in brain.nodes.values() if n['text']==text)
                # This identity/receipt metadata changes during portable import.
                brain.nodes[nid]['meta']['library_id']='default'
                save_profile(brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='offline')
                profile=get_profile(brain)
                body=brain.nodes[nid]['text'] if role=='user' else brain.nodes[nid]['meta']['assistant_reply']
                op={'action':'remember','layer':'fact','key':key+'.statement','text':'未采用的模型摘要',
                    'certainty':certainty,'domain':domain,'evidence':[{'id':nid,'role':role,'quote':body}]}
                payload,guards=build_input(brain,'default',[{'raw_id':nid,'progress':'{}'}],profile)
                plan=validate_plan({'version':1,'operations':[op]},payload,guards,'portability-'+key,profile)
                derived=apply_plan(brain,plan,'default')['created'][0]
                save_profile(brain,enabled=False)
                return nid,derived
            raw,derived=self.host.transact('default',organize);self.sources[key]=raw;self.ids[key]=derived
        def legacy(brain):
            raw=brain.add('独立助手输出','我把画作命名为纸月亮。',kind='episode',meta={
                'source':'agent_output','speaker':'assistant','library_id':'default','connection_id':self.cid})
            save_profile(brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='offline')
            profile=get_profile(brain)
            payload,guards=build_input(brain,'default',[{'raw_id':raw,'progress':'{}'}],profile)
            op={'action':'remember','layer':'experience','key':'drawing.name','text':'助手输出',
                'certainty':'clear','domain':'real','evidence':[{'id':raw,'role':'assistant','quote':brain.nodes[raw]['text']}]}
            plan=validate_plan({'version':1,'operations':[op]},payload,guards,'portability-legacy',profile)
            derived=apply_plan(brain,plan,'default')['created'][0]
            save_profile(brain,enabled=False)
            return raw,derived
        self.sources['legacy'],self.ids['legacy']=self.host.transact('default',legacy)

    def tearDown(self):
        self.host.stop();self.temp.cleanup()

    def records(self,lid,ids=None):
        brain=Brain(self.host.snapshot(lid))
        packet=build_structured_context(brain,'原话',{'memory_ids':list(ids or self.ids.values())},
            library_id=lid,max_chars=32000,view='history')['memory_context']
        return {r['id']:r for r in packet['records']}

    def assert_valid(self,lid):
        records=self.records(lid);self.assertEqual(set(records),set(self.ids.values()))
        self.assertEqual(records[self.ids['uncertain']]['certainty'],'uncertain')
        self.assertEqual(records[self.ids['roleplay']]['domain'],'roleplay')
        self.assertEqual(records[self.ids['assistant']]['subject'],'agent')
        self.assertEqual(records[self.ids['legacy']]['subject'],'agent')
        imported=Brain(self.host.snapshot(lid))
        for nid in self.ids.values():
            meta=imported.nodes[nid]['meta']
            self.assertFalse(meta.get('statement_withheld'))
            self.assertEqual(meta['memory_atom']['library_id'],lid)
            for source,revision in meta['statement_source_revisions'].items():
                self.assertEqual(revision,fingerprint(imported.nodes[source]))
        self.assertEqual(self.host.connections.list(lid),[])

    def test_share_roundtrip_rebinds_uncertain_roleplay_and_both_assistant_kinds(self):
        before=self.host.snapshot('default')
        downloaded=self.host.sharing.download('default')
        imported=self.host.sharing.import_file(downloaded['content'],name='逐字材料分享')
        self.assertEqual(imported['statement_import']['statements_rebound'],4)
        self.assertEqual(imported['statement_import']['statements_withheld'],0)
        self.assert_valid(imported['library']['id'])
        self.assertEqual(self.host.snapshot('default'),before)

    def test_backup_roundtrip_rebinds_atoms_and_changed_archive_receipts(self):
        before=self.host.snapshot('default');backup=self.host.backups.create('default')
        restored=self.host.backups.restore(backup['id'],'default',name='逐字材料恢复')
        self.assertEqual(restored['statement_import']['statements_rebound'],4)
        lid=restored['library']['id'];self.assert_valid(lid)
        after=self.host.snapshot(lid)
        raw=self.sources['uncertain']
        self.assertNotEqual(before['nodes'][raw]['meta']['evidence']['archive_receipt_id'],
                            after['nodes'][raw]['meta']['evidence']['archive_receipt_id'])
        self.assertEqual(self.host.snapshot('default'),before)

    def test_import_never_resigns_missing_negated_or_role_forged_sources(self):
        for mutation in ('missing','negated','role','derived_source','forged_complete','atom_source'):
            with self.subTest(mutation=mutation):
                package=json.loads(self.host.sharing.download('default')['content'])
                nodes=package['memory']['nodes'];nid=self.ids['uncertain'];raw=self.sources['uncertain']
                if mutation=='missing':del nodes[raw];package['memory']['edges']={}
                elif mutation=='negated':nodes[raw]['text']='我并没有说：'+nodes[raw]['text']
                elif mutation=='role':nodes[nid]['meta']['organizer_evidence'][0]['role']='assistant'
                elif mutation=='derived_source':nodes[raw]['meta']['source']='organizer'
                elif mutation=='forged_complete':nodes[nid]['meta']['source_excerpt']=True
                else:nodes[nid]['meta']['memory_atom']['evidence'][0]['id']=self.sources['roleplay']
                result=self.host.sharing.import_file(json.dumps(package,ensure_ascii=False),name='不匹配的导入材料')
                lid=result['library']['id'];brain=Brain(self.host.snapshot(lid))
                self.assertTrue(brain.nodes[nid]['meta']['statement_withheld'])
                self.assertEqual(result['statement_import']['statements_withheld'],1)
                self.assertIn('warning',result)
                if mutation=='missing':self.assertFalse(result['statement_import']['can_reorganize'])
                self.assertNotIn(nid,self.records(lid))
                self.assertIn(nid,brain.nodes)  # Original material is not deleted.

    def test_paused_and_forgotten_sources_are_not_resurrected_by_either_importer(self):
        self.host.transact('default',lambda b:set_enabled(b,self.sources['uncertain'],False))
        self.host.transact('default',lambda b:forget(b,forget_plan(b,self.sources['roleplay'])))
        content=self.host.sharing.download('default')['content'];backup=self.host.backups.create('default')
        results=(self.host.sharing.import_file(content),self.host.backups.restore(backup['id'],'default'))
        for result in results:
            lid=result['library']['id'];brain=Brain(self.host.snapshot(lid));records=self.records(lid)
            self.assertTrue(brain.nodes[self.sources['uncertain']]['meta']['memory_disabled'])
            self.assertTrue(brain.nodes[self.ids['uncertain']]['meta']['statement_withheld'])
            self.assertFalse(result['statement_import']['can_reorganize'])
            self.assertNotIn(self.ids['uncertain'],records)
            self.assertNotIn(self.sources['roleplay'],brain.nodes)
            self.assertNotIn(self.ids['roleplay'],brain.nodes)

    def test_everyday_reads_never_resign_a_changed_source(self):
        self.host.transact('default',lambda b:b.nodes[self.sources['uncertain']].update(text='我没有猜朋友生气。'))
        before=self.host.snapshot('default')
        self.assertNotIn(self.ids['uncertain'],self.records('default'))
        self.assertEqual(self.host.snapshot('default'),before)

    def test_failed_rebind_is_explicit_and_fragment_flag_cannot_claim_full_sentence(self):
        brain=Brain(self.host.snapshot('default'));nid=self.ids['uncertain'];raw=self.sources['uncertain']
        brain.nodes[raw]['text']='不是'+brain.nodes[raw]['text']
        before=deepcopy(brain.nodes[raw]['text'])
        result=rebind_experiences_after_import(brain,'new-copy')
        self.assertGreaterEqual(result['statements_withheld'],1)
        self.assertIn(nid,result['statements_withheld_ids'])
        self.assertTrue(result['can_reorganize'])
        self.assertEqual(brain.nodes[raw]['text'],before)
        self.assertTrue(brain.nodes[nid]['meta']['statement_withheld'])


if __name__=='__main__':unittest.main()
