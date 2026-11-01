"""Independent memories may stay isolated; no provider or production data."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from nkb import Brain
from nkb.adapters import mcp
from nkb.cli.main import main as cli
from nkb.companion import record_turn,remember
from nkb.companion.retention import record_memory_use,save_retention_policy
from nkb.ingest.dialogues import plan_dialogues,import_dialogues
from nkb.ingest.markdown import ingest_text,ingest_dir
from nkb.ingest.notes import import_notes
from nkb.retrieval.encoders import bigram
from nkb.retrieval.scoring import dice
from nkb.organizer import Organizer,apply_plan,rollback,save_profile,review_candidate
from nkb.organizer.config import get_profile
from nkb.organizer.state import build_input,validate_plan
from nkb.organizer.model import OrganizerError


TEXTS=['火山喷发形成熔岩。','邮票收藏需要镊子。','钢琴调律校正音准。','酵母发酵烤制面包。',
       '望远镜捕捉土星光环。','剪裁棉布缝纫裙摆。','橙汁加入冰块。','证券收益波动风险。',
       '企鹅迁徙穿越冻原。','电池充放维持容量。']
PREFIX_TEXTS=['今天我读到火山喷发形成熔岩。','今天我研究邮票收藏使用镊子。','今天我学习钢琴调律校正音准。']


class IndependentMemoryLinkTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(all(dice(bigram(a),bigram(b))==0 for i,a in enumerate(TEXTS) for b in TEXTS[i+1:]))

    def test_autolink_ignores_only_bookkeeping_keeps_content_and_semantic_tags(self):
        for tags in ([],['导入'],['用户确认'],['原始对话'],['Harness记录']):
            with self.subTest(tags=tags):
                b=Brain.new()
                for text in TEXTS:
                    nid=b.add(text,text,tags=tags)
                    self.assertEqual(b.auto_link(nid),[])
                    self.assertEqual(b.auto_link(nid,floor=-1),[])
                self.assertEqual(b.edges,{})
        b=Brain.new();a=b.add('恒星观测','使用望远镜观测恒星。')
        c=b.add('恒星观测笔记','使用望远镜观测恒星表面。')
        self.assertEqual(b.auto_link(c)[0][0],a)
        b=Brain.new();a=b.add(TEXTS[0],TEXTS[0],tags=['地质研究'])
        c=b.add(TEXTS[1],TEXTS[1],tags=['地质研究'])
        self.assertEqual(b.auto_link(c)[0][0],a)  # Explicit user category.

    def test_autolink_filters_generated_titles_and_legacy_file_tags(self):
        b=Brain.new()
        for index,text in enumerate(TEXTS):
            nid=b.add(f'段落 {index+1}',text,tags=['导入'])
            self.assertEqual(b.auto_link(nid),[])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'同一批资料';folder.mkdir()
            (folder/'合并记录.md').write_text('\n\n'.join(TEXTS),encoding='utf8')
            b=Brain.new();self.assertEqual(ingest_dir(b,root,verbose=False)['added'],10)
            self.assertEqual(b.edges,{})

    def test_confirmed_and_legacy_imports_do_not_connect_independent_memories(self):
        b=Brain.new()
        for text in TEXTS:remember(b,text)
        self.assertEqual(b.edges,{})
        b=Brain.new();ingest_text(b,'\n\n'.join(TEXTS))
        self.assertEqual(len(b.nodes),10);self.assertEqual(b.edges,{})
        b=Brain.new();import_notes(b,[{'name':f'{i}.md','text':text} for i,text in enumerate(TEXTS)],mode='whole')
        self.assertEqual(b.edges,{})

    def test_normal_narration_prefix_does_not_create_edges_in_default_entrypoints(self):
        self.assertGreater(dice(bigram(PREFIX_TEXTS[0]),bigram(PREFIX_TEXTS[1])),0)
        for mode in ('remember','commit','record_turn','mcp'):
            with self.subTest(mode=mode):
                b=Brain.new();stamp=time.time()-10
                for index,text in enumerate(PREFIX_TEXTS):
                    if mode=='remember':remember(b,text,session_id='same-fish')
                    elif mode=='commit':b.commit(text)
                    elif mode=='record_turn':record_turn(b,text,'泡泡收到了。','same-fish',str(index),event_at=stamp)
                    else:
                        result=mcp.call_tool(b,'kb_add',{'label':text,'text':text,'session_id':'same-fish','event_at':stamp})
                        self.assertFalse(result.get('isError'),result)
                self.assertEqual(len(b.nodes),3);self.assertEqual(b.edges,{})

    def test_legacy_import_requires_explicit_boolean_opt_in(self):
        b=Brain.new();ingest_text(b,'\n\n'.join(PREFIX_TEXTS));self.assertEqual(b.edges,{})
        b=Brain.new();ingest_text(b,'\n\n'.join(PREFIX_TEXTS),link=True);self.assertGreater(len(b.edges),0)
        for value in ('true',1,None):
            b=Brain.new()
            with self.assertRaises(ValueError):ingest_text(b,'\n\n'.join(PREFIX_TEXTS),link=value)
            self.assertEqual(b.nodes,{})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'记录.md';path.write_text('\n\n'.join(PREFIX_TEXTS),encoding='utf8')
            b=Brain.new();ingest_dir(b,directory,verbose=False);self.assertEqual(b.edges,{})
            b=Brain.new();ingest_dir(b,directory,verbose=False,link=True);self.assertGreater(len(b.edges),0)

    def test_mcp_advanced_autolink_is_explicit_and_strictly_boolean(self):
        schema=next(tool for tool in mcp.TOOLS if tool['name']=='kb_add')['inputSchema']
        self.assertIs(schema['properties']['auto_link']['default'],False)
        b=Brain.new();mcp.call_tool(b,'kb_add',{'label':'恒星观测','text':'观察恒星光谱。'})
        before=deepcopy(b.to_dict())
        for value in ('true',1,None):
            response=mcp.call_tool(b,'kb_add',{'label':'恒星观测记录','text':'观察恒星光谱。','auto_link':value})
            self.assertTrue(response.get('isError'));self.assertEqual(b.to_dict(),before)
        response=mcp.call_tool(b,'kb_add',{'label':'恒星观测记录','text':'观察恒星光谱。','auto_link':True})
        self.assertFalse(response.get('isError'),response);self.assertEqual(len(b.edges),1)

    def test_cli_default_add_import_and_legacy_no_link_keep_isolates(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Path.cwd()
            try:
                os.chdir(directory)
                source=Path(directory)/'输入';source.mkdir()
                (source/'日记.md').write_text('\n\n'.join(PREFIX_TEXTS),encoding='utf8')
                for mode,args,expect_links in (('add',[],False),('add',['--auto-link'],True),
                        ('add',['--auto-link','--no-link'],False),('ingest',[],False),
                        ('ingest',['--auto-link'],True),('ingest',['--no-link'],False)):
                    with self.subTest(mode=mode,args=args):
                        filename='temporary.json';Brain.new(filename).save()
                        with redirect_stdout(io.StringIO()):
                            if mode=='add':
                                for text in PREFIX_TEXTS:cli(['-b',filename,'add',text,'--text',text,*args])
                            else:cli(['-b',filename,'ingest',str(source),*args])
                        b=Brain.open(filename);self.assertEqual(len(b.nodes),3)
                        self.assertEqual(bool(b.edges),expect_links)
            finally:os.chdir(old)

    def test_same_or_different_sessions_and_history_are_not_relationship_proof(self):
        for separate in (False,True):
            with self.subTest(separate=separate):
                b=Brain.new()
                for i,text in enumerate(TEXTS):record_turn(b,text,'收到。',str(i) if separate else 'same',str(i))
                self.assertEqual(b.edges,{})
                b.reinforce(list(b.nodes));self.assertEqual(b.edges,{})
                sessions=[{'id':str(i),'messages':[{'role':'user','content':text},{'role':'assistant','content':'收到。'}]}
                          for i,text in enumerate(TEXTS)]
                if not separate:sessions=[{'id':'same','messages':[m for s in sessions for m in s['messages']]}]
                b=Brain.new();content=json.dumps({'conversations':sessions},ensure_ascii=False)
                plan=plan_dialogues(b,content=content)
                import_dialogues(b,content=content,confirm=True,expected_fingerprint=plan['fingerprint'])
                self.assertEqual(len(b.nodes),10);self.assertEqual(b.edges,{})

    def test_reinforcement_changes_existing_weights_but_never_invents_pairs(self):
        for adaptive in (False,True):
            with self.subTest(adaptive=adaptive):
                b=Brain.new()
                if adaptive:save_retention_policy(b,{'mode':'adaptive'})
                ids=[b.add(text,text) for text in TEXTS[:3]]
                info=b.reinforce(ids)
                self.assertEqual(info['pairs'],0);self.assertEqual(b.edges,{})
                b.link(ids[0],ids[1],.2);key=b._key(ids[0],ids[1]);old=b.edges[key]['w']
                info=b.reinforce(ids,now=time.time()+86401 if adaptive else time.time())
                self.assertEqual(info['pairs'],1);self.assertEqual(len(b.edges),1)
                self.assertGreater(b.edges[key]['w'],old)

    def test_usage_feedback_never_builds_edges_and_anchor_context_is_preserved(self):
        b=Brain.new();save_retention_policy(b,{'mode':'adaptive'})
        ids=[b.add(text,text) for text in TEXTS[:3]]
        record_memory_use(b,ids,kind='recall');self.assertEqual(b.edges,{})
        record_memory_use(b,ids,kind='mention',now=time.time()+86401);self.assertEqual(b.edges,{})
        b=Brain.new();stamp=time.time()-100
        for i,text in enumerate(TEXTS[:3]):b.add(text,text,kind='episode',impact=.8 if i==1 else 0,
            session_id='same',event_at=stamp+i,id=str(i))
        self.assertEqual(len(b.edges),2)
        before={key:deepcopy(edge['anchor_relations']) for key,edge in b.edges.items()}
        b.reinforce(list(b.nodes))
        self.assertEqual(len(b.edges),2)
        self.assertTrue(all(edge['automatic_anchor'] for edge in b.edges.values()))
        self.assertEqual({key:edge['anchor_relations'] for key,edge in b.edges.items()},before)

    def test_mcp_learn_true_does_not_join_independent_retrieval_seeds(self):
        b=Brain.new();ids=[b.add(text,text) for text in TEXTS[:2]]
        response=mcp.call_tool(b,'kb_recall',{'query':' '.join(TEXTS[:2]),'k':2,'learn':True,'raw':True})
        self.assertFalse(response.get('isError'),response)
        result=json.loads(response['content'][0]['text'])
        self.assertEqual({item['id'] for item in result['hits']},set(ids))
        self.assertEqual(result['reinforced']['pairs'],0);self.assertEqual(b.edges,{})
        self.assertTrue(all(b.get(nid)['recalls']==1 for nid in ids))

    def test_explicit_wikilinks_and_existing_edges_are_not_removed(self):
        b=Brain.new();result=import_notes(b,[{'name':'火山.md','text':TEXTS[0]},
            {'name':'邮票.md','text':TEXTS[1]+'参见[[火山]]。'}],mode='whole')
        self.assertEqual(result['linked'],1);self.assertEqual(len(b.edges),1)
        edges=deepcopy(b.edges)
        other=b.add(TEXTS[2],TEXTS[2],tags=['导入']);b.auto_link(other)
        self.assertEqual(b.edges,edges)


class OrganizerIndependentRelationTests(unittest.TestCase):
    def setUp(self):
        self.brain=Brain.new()
        save_profile(self.brain,enabled=True,base_url='https://never-called.invalid/v1',model='OFFLINE',daily_call_limit=1)
        self.ids=[record_turn(self.brain,text,'收到。','separate-'+str(i),str(i)) for i,text in enumerate(TEXTS[:2])]

    def op(self,**updates):
        return {'action':'remember','layer':'fact','key':'event.subject','text':TEXTS[0],
                'certainty':'clear','domain':'real','evidence':[{'id':self.ids[0],'role':'user','quote':TEXTS[0]}],**updates}

    def plan(self,ops,job='audit',ids=None):
        profile=get_profile(self.brain)
        payload,guards=build_input(self.brain,'audit',[{'raw_id':nid,'progress':'{}'} for nid in (ids or self.ids)],profile)
        return validate_plan({'version':1,'operations':ops},payload,guards,job,profile)

    def test_optional_related_ids_are_ignored_while_facts_keep_real_source_edges(self):
        plan=self.plan([self.op(related_ids=[self.ids[1]])])
        self.assertEqual(plan['operations'][0]['related_ids'],[])
        result=apply_plan(self.brain,plan,'audit')
        self.assertEqual(len(result['created']),1)
        fact=result['created'][0]
        self.assertIn(self.brain._key(fact,self.ids[0]),self.brain.edges)
        self.assertNotIn(self.brain._key(fact,self.ids[1]),self.brain.edges)
        self.assertEqual(result['relations'],{'skipped_operations':0,'ignored_links':1,'reason':'explicit_confirmation_required'})
        self.assertEqual(len(self.brain.edges),1)
        replay=apply_plan(self.brain,plan,'audit');self.assertTrue(replay['duplicate'])
        self.assertEqual(replay['relations'],result['relations'])
        rollback(self.brain,'audit');self.assertEqual(self.brain.edges,{})

    def test_two_valid_quotes_same_agent_or_session_cannot_authorize_relate(self):
        for same_session in (False,True):
            with self.subTest(same_session=same_session):
                if same_session:
                    for node in self.brain.nodes.values():node['session_id']='same'
                refs=[{'id':nid,'role':'user','quote':TEXTS[i]} for i,nid in enumerate(self.ids)]
                plan=self.plan([self.op(action='relate',target_id=self.ids[0],related_ids=[self.ids[1]],evidence=refs)],job=str(same_session))
                self.assertEqual(plan['operations'],[])
                result=apply_plan(self.brain,plan,'audit')
                self.assertEqual(result['created'],[]);self.assertEqual(result['linked'],[])
                self.assertEqual(result['relations']['skipped_operations'],1)
                self.assertEqual(self.brain.edges,{})

    def test_merge_strips_extra_links_but_keeps_equivalent_fact_and_sources(self):
        first=apply_plan(self.brain,self.plan([self.op()],job='first'),'audit')['created'][0]
        new=record_turn(self.brain,TEXTS[0],'这是另一轮确认。','separate-c','c')
        merge=self.op(action='merge',target_id=first,related_ids=[self.ids[1]],
            evidence=[{'id':new,'role':'user','quote':TEXTS[0]}])
        result=apply_plan(self.brain,self.plan([merge],job='merge',ids=[new,self.ids[1]]),'audit')
        self.assertEqual(result['merged'],[first])
        self.assertIn(self.brain._key(first,new),self.brain.edges)
        self.assertNotIn(self.brain._key(first,self.ids[1]),self.brain.edges)
        self.assertEqual(result['relations']['ignored_links'],1)

    def test_old_cached_plan_is_filtered_without_model_or_budget_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            credential_calls=[];wire_calls=[]
            def never_credential(*args):credential_calls.append(1);raise AssertionError('No credential access')
            def never_wire(*args,**kwargs):wire_calls.append(1);raise AssertionError('No model request')
            worker=Organizer(directory,snapshot=lambda _:deepcopy(self.brain.to_dict()),
                apply=lambda library,plan:apply_plan(self.brain,plan,library),credential=never_credential,transport=never_wire)
            self.addCleanup(worker.stop)
            worker.enqueue('audit',self.ids)
            job=worker._claim('audit',get_profile(self.brain),True)
            old=self.plan([self.op()],job=job['id'])
            old.pop('relation_policy');old.pop('relation_counts')
            old['operations'][0]['related_ids']=[self.ids[1]]
            relation={**deepcopy(old['operations'][0]),'action':'relate','target_id':self.ids[0]}
            old['operations'].append(relation)
            with worker.db() as db:
                db.execute("UPDATE jobs SET status='retry',next_run=0,lease_until=0,plan_json=? WHERE id=?",(json.dumps(old),job['id']))
                db.execute('INSERT INTO calls VALUES(?,?,?,?)',('already-paid','audit',time.time(),1000))
            before=worker.status('audit')['usage_24h']
            result=worker.run_once('audit')
            self.assertEqual(result['status'],'done',result)
            self.assertEqual(len(result['result']['created']),1)
            self.assertEqual(result['result']['relations']['ignored_links'],2)
            self.assertEqual(result['result']['relations']['skipped_operations'],1)
            self.assertEqual(len(self.brain.edges),1)
            self.assertEqual(worker.status('audit')['usage_24h'],before)
            self.assertEqual(worker.status('audit')['jobs'][0]['relation_result'],result['result']['relations'])
            self.assertEqual(credential_calls,[]);self.assertEqual(wire_calls,[])

    def test_old_relate_candidate_cannot_be_approved_as_a_fact(self):
        operation=self.op(action='relate',target_id=self.ids[0],related_ids=[self.ids[1]])
        operation.update(verbatim_text=TEXTS[0],source_fiction=False)
        self.brain.meta['organizer_candidates']=[{'id':'old-candidate','status':'pending','operation':operation,'job_id':'old'}]
        before=deepcopy(self.brain.to_dict())
        with self.assertRaises(OrganizerError) as caught:review_candidate(self.brain,'old-candidate','accept')
        self.assertEqual(caught.exception.code,'manual_relation_required')
        self.assertEqual(self.brain.to_dict(),before)
        self.assertEqual(review_candidate(self.brain,'old-candidate','reject')['status'],'rejected')


if __name__=='__main__':unittest.main()
