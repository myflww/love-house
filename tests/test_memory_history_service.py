"""Real controller HTTP checks for history, live permissions and source directory."""
from copy import deepcopy
import json
import time
import unittest

from tests import test_memory_experience_service as fixture
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.state import apply_plan,build_input,fingerprint,validate_plan
from nkb.service.agent_client import event_from_hook


class MemoryHistoryServiceTests(unittest.TestCase):
    # Reuse setup/helpers without importing or inheriting another discoverable
    # TestCase: unittest discovery should execute each old test exactly once.
    tearDown=fixture.MemoryExperienceServiceTests.tearDown
    connection=fixture.MemoryExperienceServiceTests.connection
    request=fixture.MemoryExperienceServiceTests.request

    def setUp(self):
        fixture.MemoryExperienceServiceTests.setUp(self)
        self.raw=self.capture(self.cid,self.token,'window-a',
            '我以为朋友没有回信是因为生气了。','我当时也猜他在生气。','misunderstanding')
        self.old=self.host.transact(self.library,lambda b:b.add('朋友未回信的理解',
            '我以为朋友没有回信是因为生气了。',kind='fact',meta={
                'source':'organizer','library_id':self.library,'members':[self.raw],
                'organizer_evidence':[{'id':self.raw,'role':'user'}]}))
        status,result=self.request(f'/api/memories/{self.old}/correct',{
            'text':'朋友后来解释没有回信只是工作很忙，并没有生气。','label':'朋友回信的理解'})
        self.assertEqual(status,200,result)
        self.new=result['id']

    def capture(self,cid,token,window,user,assistant,turn,library=None):
        event=event_from_hook({'session_id':window,'turn_id':turn,'status':'complete',
                              'user':user,'assistant':assistant})
        status,result=self.request(f'/api/connections/{cid}/events',event,
            library=library,management=False,token=token)
        self.assertEqual(status,200,result)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            self.host.process_pending(library_id=library or self.library,receipt_id=result['receipt_id'])
            with self.host.connections.db() as db:
                row=db.execute('SELECT status,node_ids FROM receipts WHERE id=?',(result['receipt_id'],)).fetchone()
            if row and row['status']=='saved':return json.loads(row['node_ids'])[0]
            time.sleep(.01)
        self.fail('Synthetic HTTP event did not reach saved state')

    def context(self,cid=None,token=None,window='window-a',view='current',library=None,**extra):
        return self.request(f'/api/connections/{cid or self.cid}/context',{
            'session_id':window,'query':'朋友回信','max_chars':32000,'view':view,**extra},
            library=library,management=False,token=token or self.token)

    def tool(self,name,arguments=None,*,cid=None,token=None,library=None):
        return self.request(f'/api/connections/{cid or self.cid}/tool',{
            'name':name,'arguments':arguments or {}},library=library,
            management=False,token=token or self.token)

    def legacy(self):
        def downgrade(brain):
            for nid in (self.raw,self.old,self.new):brain.nodes[nid]['meta'].pop('memory_revision',None)
            brain.nodes[self.old]['meta']['memory_disabled']=True
        self.host.transact(self.library,downgrade)

    def test_versions_require_management_and_exact_library(self):
        path=f'/api/memories/{self.new}/versions'
        self.assertEqual(self.request(path,management=False)[0],401)
        self.assertEqual(self.request(path,management=False,token=self.token)[0],403)
        status,result=self.request(path,library=self.other)
        self.assertEqual(status,400,result)
        self.assertNotIn('工作很忙',json.dumps(result,ensure_ascii=False))
        self.assertEqual(self.request(path+'?limit=not-an-integer')[0],400)
        self.assertEqual(self.request(path+'?limit=0')[0],400)

    def test_versions_page_actual_chain_read_only_without_truth_judgement(self):
        before=deepcopy(self.host.snapshot(self.library))
        path=f'/api/memories/{self.new}/versions?limit=1'
        status,page=self.request(path);self.assertEqual(status,200,page)
        entries=list(page['entries'])
        while page['next_cursor']:
            status,page=self.request(path+'&cursor='+page['next_cursor'])
            self.assertEqual(status,200,page);entries.extend(page['entries'])
        self.assertEqual({r['id'] for r in entries},{self.raw,self.old,self.new})
        self.assertTrue(all(r['available'] for r in entries))
        self.assertEqual(page['current_id'],self.new)
        self.assertFalse(page['world_truth_assessed']);self.assertFalse(page['will_call_model'])
        old=next(r for r in entries if r['id']==self.old)
        self.assertEqual(old['revision']['state'],'historical')
        self.assertEqual(old['source']['evidence'][0]['id'],self.raw)
        self.assertEqual(self.host.snapshot(self.library),before)

    def test_legacy_history_restore_requires_exact_confirmation_and_preview_revision(self):
        self.legacy();path=f'/api/memories/{self.new}/history-restore'
        self.assertEqual(self.request(path+'-preview',management=False,body={})[0],401)
        self.assertEqual(self.request(path+'-preview',management=False,token=self.token,body={})[0],403)
        self.assertEqual(self.request(path+'-preview',{},library=self.other)[0],400)
        status,preview=self.request(path+'-preview',{})
        self.assertEqual(status,200,preview)
        self.assertEqual(preview['node_ids'],[self.old]);self.assertEqual(preview['source_ids'],[self.raw])
        for bad in ({'expected_revision':preview['expected_revision']},
                    {'confirm':1,'expected_revision':preview['expected_revision']},
                    {'confirm':True,'expected_revision':'stale'},
                    {'confirm':True,'expected_revision':preview['expected_revision'],'library_id':self.other}):
            self.assertEqual(self.request(path,bad)[0],400,bad)
        status,result=self.request(path,{'confirm':True,'expected_revision':preview['expected_revision']})
        self.assertEqual(status,200,result)
        self.assertEqual(set(result['historical_ids']),{self.raw,self.old})
        self.assertFalse(result['current_memory_restored'])
        current=self.context()[1]['memory_ids'];history=self.context(view='history')[1]['memory_ids']
        self.assertNotIn(self.old,current);self.assertNotIn(self.raw,current)
        self.assertTrue({self.raw,self.old,self.new}<=set(history))

    def test_legacy_preview_stales_on_pause_and_never_reenables_explicit_user_pause(self):
        self.legacy();path=f'/api/memories/{self.new}/history-restore'
        preview=self.request(path+'-preview',{})[1]
        self.assertEqual(self.request(f'/api/memories/{self.old}/enabled',{'enabled':False})[0],200)
        self.assertEqual(self.request(path,{'confirm':True,'expected_revision':preview['expected_revision']})[0],400)
        fresh=self.request(path+'-preview',{})[1]
        self.assertEqual(fresh['node_count'],0)
        self.assertEqual(self.request(path,{'confirm':True,'expected_revision':fresh['expected_revision']})[0],200)
        self.assertTrue(self.host.snapshot(self.library)['nodes'][self.old]['meta']['memory_disabled'])
        self.assertFalse({self.raw,self.old,self.new}&set(self.context(view='history')[1]['memory_ids']))

    def test_legacy_restore_keeps_valid_assistant_source_guards_without_resigning_edited_sources(self):
        def legacy_statement(brain):
            # Produce the real older assistant-only organizer schema, then
            # restore disabled settings before releasing this write transaction.
            source=brain.add('助手独立输出','我把这幅合成画作命名为纸月亮。',kind='episode',
                meta={'source':'agent_output','speaker':'assistant'})
            previous=get_profile(brain)
            try:
                save_profile(brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE')
                profile=get_profile(brain)
                payload,guards=build_input(brain,self.library,[{'raw_id':source,'progress':'{}'}],profile)
                plan=validate_plan({'version':1,'operations':[{'action':'remember','layer':'experience',
                    'key':'agent.drawing.name','text':'画作名字的助手陈述','certainty':'clear','domain':'real',
                    'evidence':[{'id':source,'role':'assistant','quote':brain.nodes[source]['text']}]}]},
                    payload,guards,'synthetic-legacy-output',profile)
                old=apply_plan(brain,plan,self.library)['created'][0]
            finally:
                save_profile(brain,**previous)
            return source,old
        source,old=self.host.transact(self.library,legacy_statement)
        status,changed=self.request(f'/api/memories/{old}/correct',{'text':'后来补充这幅画作的新名字。'})
        self.assertEqual(status,200,changed)
        def downgrade(brain):
            for nid in (source,old,changed['id']):brain.nodes[nid]['meta'].pop('memory_revision',None)
            brain.nodes[old]['meta']['memory_disabled']=True
            brain.nodes[old]['meta']['statement_source_revisions'][source]=fingerprint(brain.nodes[source])
            # This separately stale copy must remain stale after metadata-only
            # migration; no import or read may re-sign a previously bad guard.
            invalid=deepcopy(brain.nodes[old]);invalid['id']='synthetic-stale-statement'
            invalid['meta']['memory_disabled']=False
            invalid['meta']['statement_source_revisions'][source]='0'*64
            brain.nodes[invalid['id']]=invalid;brain._vec[invalid['id']]=brain._vec_for(invalid)
        self.host.transact(self.library,downgrade)
        path=f"/api/memories/{changed['id']}/history-restore"
        status,preview=self.request(path+'-preview',{});self.assertEqual(status,200,preview)
        self.assertIn(old,preview['node_ids']);self.assertIn(source,preview['source_ids'])
        status,result=self.request(path,{'confirm':True,'expected_revision':preview['expected_revision']})
        self.assertEqual(status,200,result)
        status,read=self.tool('memory_read',{'memory_id':old,'view':'history'})
        self.assertEqual(status,200,read);self.assertIn('纸月亮',read['text'])
        self.assertEqual(self.tool('memory_read',{'memory_id':old,'view':'current'})[0],400)
        status,stale=self.tool('memory_read',{'memory_id':'synthetic-stale-statement','view':'history'})
        self.assertEqual(status,400,stale)
        self.assertEqual(self.host.snapshot(self.library)['nodes']['synthetic-stale-statement']['meta']['statement_source_revisions'][source],'0'*64)

    def test_two_authorized_windows_retrieve_history_with_library_and_window_boundaries(self):
        second,second_token=self.connection(self.library,'window-c')
        for cid,token,window in ((self.cid,self.token,'window-a'),(second,second_token,'window-c')):
            status,current=self.context(cid,token,window);self.assertEqual(status,200,current)
            self.assertIn(self.new,current['memory_ids']);self.assertNotIn(self.old,current['memory_ids'])
            for view in ('history','comparison'):
                status,value=self.context(cid,token,window,view);self.assertEqual(status,200,value)
                self.assertTrue({self.raw,self.old,self.new}<=set(value['memory_ids']))
                records={r['id']:r for r in value['memory_context']['records']}
                self.assertEqual(records[self.old]['revision']['state'],'historical')
            status,read=self.tool('memory_read',{'memory_id':self.old,'view':'history'},cid=cid,token=token)
            self.assertEqual(status,200,read)
            self.assertIn('生气了',read['text'])
            self.assertEqual(self.tool('memory_read',{'memory_id':self.old,'view':'current'},cid=cid,token=token)[0],400)
        self.assertEqual(self.context(window='window-c')[0],400)
        self.assertEqual(self.context(cid=second,token=self.token,window='window-c')[0],403)
        self.assertEqual(self.context(library=self.other,view='history')[0],403)
        status,foreign=self.context(self.other_cid,self.other_token,'window-b','history',self.other)
        self.assertEqual(status,200,foreign)
        self.assertFalse({self.raw,self.old,self.new}&set(foreign['memory_ids']))
        self.assertNotIn('工作很忙',json.dumps(foreign,ensure_ascii=False))

    def test_explicit_disable_and_forget_never_leak_through_history_tools_or_versions(self):
        self.assertEqual(self.request(f'/api/memories/{self.old}/enabled',{'enabled':False})[0],200)
        for mode in ('current','history','comparison'):
            status,value=self.context(view=mode);self.assertEqual(status,200,value)
            self.assertFalse({self.raw,self.old,self.new}&set(value['memory_ids']))
            self.assertNotIn('工作很忙',json.dumps(value,ensure_ascii=False))
            self.assertNotIn('因为生气了',json.dumps(value,ensure_ascii=False))
            for nid in (self.raw,self.old,self.new):
                self.assertEqual(self.tool('memory_read',{'memory_id':nid,'view':mode})[0],400)
        versions=self.request(f'/api/memories/{self.new}/versions')[1]
        self.assertTrue(all(not r['available'] and 'text' not in r and 'label' not in r for r in versions['entries']))
        status,result=self.request(f'/api/memories/{self.old}/forget',{'confirm':True})
        self.assertEqual(status,200,result)
        self.assertEqual(self.request(f'/api/memories/{self.new}/versions')[0],400)
        for mode in ('history','comparison'):
            self.assertFalse({self.raw,self.old,self.new}&set(self.context(view=mode)[1]['memory_ids']))
            self.assertNotIn('工作很忙',json.dumps(self.tool('memory_list',{'view':mode})[1],ensure_ascii=False))

    def test_directory_tool_is_authenticated_local_and_rechecks_connection_authority(self):
        second,second_token=self.connection(self.library,'window-c')
        second_raw=self.capture(second,second_token,'window-c','今天讨论海盐咖啡。','记下实际讨论内容。','second-window')
        foreign=self.capture(self.other_cid,self.other_token,'window-b','另一库的秘密。','独立保存。','foreign',self.other)
        status,launched=self.request('/api/idle-review/run',{})
        self.assertEqual(status,200,launched)
        deadline=time.monotonic()+5
        directory={}
        while time.monotonic()<deadline:
            status,directory=self.tool('memory_directory',{'limit':100},cid=second,token=second_token)
            self.assertEqual(status,200,directory)
            if {self.raw,second_raw}<={r['id'] for r in directory['entries']}:break
            time.sleep(.01)
        self.assertTrue({self.raw,second_raw}<={r['id'] for r in directory['entries']},directory)
        self.assertNotIn(foreign,json.dumps(directory))
        self.assertFalse(directory['model_called']);self.assertFalse(directory['memory_use_recorded'])
        self.assertFalse(directory['complete_library'])
        original=next(row for row in directory['entries'] if row['id']==self.raw)
        status,source=self.tool(original['read_tool'],original['read_arguments'],cid=second,token=second_token)
        self.assertEqual(status,200,source)
        self.assertIn('我以为朋友没有回信',source['text'])
        self.assertEqual(self.request('/api/memory/directory',management=False)[0],401)
        self.assertEqual(self.request('/api/memory/directory',management=False,token=second_token)[0],403)
        self.assertEqual(self.tool('memory_directory',{'library_id':self.other})[0],400)
        self.assertEqual(self.tool('memory_directory',cid=second,token=self.token)[0],403)
        self.assertEqual(self.tool('memory_directory',library=self.other)[0],403)
        self.assertEqual(self.tool('memory_directory',token='synthetic-invalid-token')[0],400)
        self.host.connections.toggle(self.cid,False)
        status,after=self.tool('memory_directory',cid=second,token=second_token)
        self.assertEqual(status,200,after)
        self.assertNotIn(self.raw,{r['id'] for r in after['entries']})
        self.assertNotIn(foreign,json.dumps(after))
        self.assertEqual(self.request('/api/idle-review/run',{})[0],200)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status,after=self.tool('memory_directory',cid=second,token=second_token)
            self.assertEqual(status,200,after)
            if second_raw in {r['id'] for r in after['entries']}:break
            time.sleep(.01)
        self.assertIn(second_raw,{r['id'] for r in after['entries']},after)
        self.assertNotIn(self.raw,{r['id'] for r in after['entries']})
        self.assertEqual(self.request(f'/api/memories/{second_raw}/enabled',{'enabled':False})[0],200)
        self.assertNotIn(second_raw,{r['id'] for r in self.tool('memory_directory',cid=second,token=second_token)[1]['entries']})

    def test_source_directory_reads_continue_with_returned_revision_and_recheck_live_controls(self):
        original='这是需要分段读取的完整合成原文。'*700
        nid=self.capture(self.cid,self.token,'window-a',original,'这是实际保存的助手原文。','long-source')
        self.assertEqual(self.request('/api/idle-review/run',{})[0],200)
        deadline=time.monotonic()+5;entry=None
        while time.monotonic()<deadline:
            status,page=self.tool('memory_directory',{'limit':100})
            self.assertEqual(status,200,page)
            entry=next((row for row in page['entries'] if row['id']==nid),None)
            if entry:break
            time.sleep(.01)
        self.assertIsNotNone(entry,page)
        args={**entry['read_arguments'],'max_chars':4096}
        status,first=self.tool(entry['read_tool'],args)
        self.assertEqual(status,200,first);self.assertFalse(first['complete'])
        self.assertEqual(first['text'],original[:4096])
        continuation={**args,'revision':first['revision'],'offset':first['next_offset']}
        status,second=self.tool('memory_read',continuation)
        self.assertEqual(status,200,second)
        self.assertEqual(second['text'],original[4096:8192])
        status,bad=self.tool('memory_read',{**continuation,'revision':'record:'+'0'*64})
        self.assertEqual(status,400,bad);self.assertNotIn('合成原文',json.dumps(bad,ensure_ascii=False))
        self.host.connections.toggle(self.cid,False)
        status,paused=self.tool('memory_read',continuation)
        self.assertIn(status,(400,403),paused);self.assertNotIn('合成原文',json.dumps(paused,ensure_ascii=False))
        self.host.connections.toggle(self.cid,True)
        self.assertEqual(self.request(f'/api/memories/{nid}/enabled',{'enabled':False})[0],200)
        status,disabled=self.tool('memory_read',continuation)
        self.assertEqual(status,400,disabled);self.assertNotIn('合成原文',json.dumps(disabled,ensure_ascii=False))


if __name__=='__main__':unittest.main()
