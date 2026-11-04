"""Synthetic memory lifecycle acceptance: correction, follow-up and honest use evidence."""
from copy import deepcopy
from contextlib import closing
from html import unescape
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nkb import Brain
from nkb.companion.memory import build_context, remember, record_turn
from nkb.companion.lifecycle import (timeline, set_commitment_status, verify_citations, correction_candidates)
from nkb.companion.retention import enable_temporal_retention, record_memory_use, save_retention_policy
from nkb.companion.structured import build_structured_context
from nkb.errors import ValidationError
from nkb.service.controls import correct, verify_correction, forget, forget_plan
from nkb.service.usage import UsageJournal, DAY


class MemoryExperienceLifecycleTests(unittest.TestCase):
    def brain(self):
        brain=Brain.new();brain.meta['library_id']='default';enable_temporal_retention(brain)
        return brain

    def test_correct_replaces_current_fact_for_every_context_and_preserves_history(self):
        brain=self.brain();old=remember(brain,'我以前最喜欢甜咖啡',kind='preference',session_id='window-a')
        original=deepcopy(brain.nodes[old])
        derived=brain.add('咖啡习惯的旧归纳','喜欢甜咖啡',kind='fact',meta={'source':'organizer','members':[old]})
        result=correct(brain,old,'我现在喜欢不加糖的咖啡')
        new=result['id']
        self.assertTrue(result['verification']['selection_verified'])
        self.assertFalse(result['verification']['model_adoption_verified'])
        self.assertEqual(brain.nodes[old]['text'],original['text'])
        self.assertEqual(brain.nodes[old]['superseded_by'],new)
        self.assertTrue(brain.nodes[derived]['meta']['memory_disabled'])
        for session in ('window-a','window-b'):
            packet=build_context(brain,'咖啡偏好',session_id=session,library_id='default')
            self.assertIn(new,packet['memory_ids'])
            self.assertNotIn(old,packet['memory_ids']);self.assertNotIn(derived,packet['memory_ids'])
            self.assertNotIn('我以前最喜欢甜咖啡',packet['packet'])
        self.assertTrue(verify_correction(Brain(brain.to_dict()),old,new)['selection_verified'])
        with self.assertRaises(ValidationError):correct(brain,old,'不能从旧版本分叉为另一份当前事实')

    def test_correction_privacy_delete_removes_history_and_new_record_without_resurrection(self):
        brain=self.brain();old=remember(brain,'我的私人咖啡偏好是加两勺糖')
        result=correct(brain,old,'我的私人咖啡偏好改成了不加糖')
        plan=forget_plan(brain,old);forget(brain,plan)
        reopened=Brain(brain.to_dict())
        self.assertNotIn(old,reopened.nodes);self.assertNotIn(result['id'],reopened.nodes)
        self.assertEqual(timeline(reopened,library_id='default')['entries'],[])
        self.assertFalse(build_context(reopened,'私人咖啡偏好',library_id='default')['memory_ids'])

    def test_closed_commitments_are_history_not_pending_follow_up_and_can_be_reopened(self):
        brain=self.brain()
        record_turn(brain,'我们约定下周准备面试','到时我们再一起准备','window-a','plan')
        nid=brain.commit('我们约定下周准备面试',text='我们约定下周准备面试',meta={'source':'user_confirmed','confirmed':True,'speaker':'user'})
        self.assertTrue(set_commitment_status(brain,nid,'done','用户明确说面试已经结束')['changed'])
        self.assertFalse(set_commitment_status(brain,nid,'done','用户明确说面试已经结束')['changed'])
        self.assertNotIn(nid,build_context(brain,'现在有哪些约定待跟进',library_id='default')['memory_ids'])
        pending=build_context(brain,'现在有哪些约定待跟进',session_id='window-a',library_id='default')
        self.assertFalse(pending['history'])
        self.assertFalse(pending['memory_ids'])
        ordinary=build_structured_context(brain,'准备面试的约定',library_id='default')
        self.assertFalse(next(r for r in ordinary['memory_context']['records'] if r['id']==nid)['commitment']['follow_up'])
        history=build_context(brain,'以前准备面试后来完成了吗',library_id='default')
        self.assertIn(nid,history['memory_ids'])
        self.assertIn('"status": "done"',unescape(history['packet']))
        records=build_structured_context(brain,'以前面试的完成结果',library_id='default')['memory_context']['records']
        row=next(r for r in records if r['id']==nid)
        self.assertEqual(row['interpretation'],'historical_evidence');self.assertFalse(row['commitment']['follow_up'])
        self.assertEqual(timeline(brain,library_id='default',view='open')['total'],0)
        self.assertEqual(timeline(brain,library_id='default',view='closed')['entries'][0]['status'],'done')
        self.assertFalse(set_commitment_status(brain,nid,'cancelled')['follow_up'])
        self.assertTrue(set_commitment_status(brain,nid,'open')['follow_up'])
        self.assertIn(nid,build_context(brain,'准备面试的约定',library_id='default')['memory_ids'])

    def test_timeline_is_read_only_scoped_paged_attributed_and_rejects_stale_cursor(self):
        brain=self.brain()
        for i in range(3):record_turn(brain,'合成共同经历'+str(i),'历史助手自述','window-a',str(i))
        before=deepcopy(brain.to_dict())
        first=timeline(brain,library_id='default',limit=1)
        second=timeline(brain,library_id='default',limit=1,cursor=first['next_cursor'])
        self.assertNotEqual(first['entries'][0]['id'],second['entries'][0]['id'])
        self.assertEqual(before,brain.to_dict())
        self.assertEqual(first['entries'][0]['source']['basis'],'attributed_historical_material')
        with self.assertRaises(ValidationError):timeline(brain,library_id='other')
        record_turn(brain,'新记录使旧分页失效','新的历史自述','window-a','later')
        with self.assertRaises(ValidationError):timeline(brain,library_id='default',cursor=first['next_cursor'])

    def test_delivery_is_weaker_than_verified_citation_and_user_confirmation(self):
        levels={}
        for kind in ('recall','mention','cited','confirmed'):
            brain=self.brain();nid=remember(brain,'合成可核记忆内容')
            stamp=brain.nodes[nid]['created']+2*DAY
            record_memory_use(brain,[nid],kind=kind,now=stamp)
            usage=brain.nodes[nid]['meta']['memory_usage']
            levels[kind]=usage['traces'][0]['weight']
            self.assertEqual(record_memory_use(brain,[nid],kind=kind,now=stamp)['nodes'],0)
            brain.nodes[nid]['meta']['memory_disabled']=True
            self.assertEqual(record_memory_use(brain,[nid],kind=kind,now=stamp+DAY)['nodes'],0)
        self.assertLess(levels['recall'],levels['mention']);self.assertLess(levels['mention'],levels['cited'])
        self.assertLess(levels['cited'],levels['confirmed'])

    def test_chat_correction_is_only_a_review_hint_until_explicitly_selected_and_saved(self):
        brain=self.brain();old=remember(brain,'我喜欢加糖的甜咖啡',kind='preference')
        source=record_turn(brain,'我现在不喝加糖的咖啡了','好的','window-a','correction',
                          connection_id='connection-a',external_session_id='window-a',origin='agent_source_adapter')
        brain.nodes[source]['meta']['evidence']={'archive_receipt_id':'synthetic-receipt'}
        before=deepcopy(brain.to_dict())
        suggestions=correction_candidates(brain,library_id='default')
        self.assertEqual(before,brain.to_dict())
        self.assertEqual(suggestions[0]['source_id'],source)
        self.assertFalse(suggestions[0]['auto_applied'])
        self.assertIn(old,[item['id'] for item in suggestions[0]['candidates']])
        result=correct(brain,old,'我现在不喝加糖的咖啡',source_id=source)
        self.assertTrue(result['verification']['selection_verified'])
        self.assertEqual(correction_candidates(brain,library_id='default'),[])
        self.assertIn(result['id'],forget_plan(brain,source)['node_ids'])

    def test_quotes_imports_external_participants_and_assistant_output_do_not_suggest_owner_corrections(self):
        brain=self.brain();remember(brain,'我喜欢加糖的咖啡',kind='preference')
        cases=[('“我现在不喝加糖咖啡了”',{}),('> 我现在不喝加糖咖啡了',{}),
               ('```\n我现在不喝加糖咖啡了\n```',{}),('这是小说中的对白：\n我现在不喝加糖咖啡了',{}),
               ('我现在不喝加糖咖啡了',{'provenance':'imported_record'}),
               ('我现在不喝加糖咖啡了',{'participant_scope':'external_participant'})]
        for index,(text,meta) in enumerate(cases):
            source=record_turn(brain,text,'历史助手回答','window-a',str(index),connection_id='connection-a',origin='agent_source_adapter')
            brain.nodes[source]['meta'].update(meta,evidence={'archive_receipt_id':'synthetic-'+str(index)})
        brain.add('助手自述','我现在不喝加糖咖啡了',kind='episode',meta={'source':'agent_output'})
        proposals=correction_candidates(brain,library_id='default')
        self.assertEqual(len(proposals),1)
        self.assertEqual(proposals[0]['actor_scope'],'external_participant')
        self.assertTrue(proposals[0]['requires_identity_confirmation'])
        self.assertEqual(proposals[0]['candidates'],[])

    def test_all_strength_levels_honor_explicit_usage_opt_out(self):
        brain=self.brain();nid=remember(brain,'合成不会因反馈复活的记录')
        save_retention_policy(brain,{'usage_reinforcement':False})
        before=deepcopy(brain.to_dict())
        for kind in ('recall','mention','cited','confirmed'):
            self.assertEqual(record_memory_use(brain,[nid],kind=kind)['nodes'],0)
        self.assertEqual(brain.to_dict(),before)


class DeliveryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.stamp=20000*DAY
        self.journal=UsageJournal(self.temp.name,clock=lambda:self.stamp)
    def tearDown(self):self.temp.cleanup()

    def ticket(self):return self.journal.issue_delivery('default','connection-a','window-a',['memory-a'],binding_revision=3)

    def test_forged_feedback_wrong_scope_expiry_and_binding_are_rejected(self):
        ticket=self.ticket()
        for lib,cid,sid in [('other','connection-a','window-a'),('default','other','window-a'),('default','connection-a','other')]:
            with self.assertRaises(ValidationError):self.journal.delivery(ticket['id'],lib,cid,sid)
        with self.assertRaises(ValidationError):self.journal.delivery(ticket['id'],'default','connection-a','window-a',binding_revision=4)
        with self.assertRaises(ValidationError):self.journal.feedback(ticket['id'],'default','connection-a','window-a',['memory-a'],'confirmed',management=True,binding_revision=4)
        for ids,kind,extra in [(['memory-a'],'confirmed',{}),(['unprovided'],'cited',{'verified_cited_ids':['unprovided']}),(['memory-a'],'cited',{})]:
            with self.assertRaises(ValidationError):self.journal.feedback(ticket['id'],'default','connection-a','window-a',ids,kind,**extra)
        self.stamp+=DAY
        with self.assertRaises(ValidationError):self.journal.delivery(ticket['id'],'default','connection-a','window-a')

    def test_verified_feedback_is_durable_and_duplicate_does_not_reinforce_again(self):
        ticket=self.ticket()
        result=self.journal.feedback(ticket['id'],'default','connection-a','window-a',['memory-a'],'cited',verified_cited_ids=['memory-a'])
        self.assertEqual(result['recorded_ids'],['memory-a']);self.assertFalse(result['model_adoption_verified'])
        self.assertEqual(self.journal.feedback(ticket['id'],'default','connection-a','window-a',['memory-a'],'cited',verified_cited_ids=['memory-a'])['recorded_ids'],[])
        self.journal.feedback(ticket['id'],'default','connection-a','window-a',['memory-a'],'confirmed',management=True)
        reopened=UsageJournal(self.temp.name,clock=lambda:self.stamp)
        self.assertEqual({r['kind'] for r in reopened.pending('default')},{'cited','confirmed'})
        self.assertEqual(reopened.latest_delivery('default','connection-a')['binding_revision'],3)
        self.assertIsNone(reopened.latest_delivery('default','connection-a',binding_revision=4))
        reopened.forget('default',['memory-a'])
        with self.assertRaises(ValidationError):reopened.feedback(ticket['id'],'default','connection-a','window-a',['memory-a'],'confirmed',management=True)

    def test_legacy_journal_migrates_pending_metadata_without_touching_contents(self):
        root=Path(self.temp.name)/'legacy';root.mkdir()
        with closing(sqlite3.connect(root/'memory-usage.sqlite3')) as db, db:
            db.execute("CREATE TABLE memory_usage(library_id TEXT,node_id TEXT,kind TEXT CHECK(kind IN ('recall','mention')),last_at REAL,last_day INTEGER,pending_at REAL,pending_day INTEGER,applied_at REAL,PRIMARY KEY(library_id,node_id,kind))")
            db.execute('INSERT INTO memory_usage VALUES(?,?,?,?,?,?,?,?)',('default','a','recall',self.stamp,20000,self.stamp,20000,None))
        migrated=UsageJournal(root,clock=lambda:self.stamp)
        self.assertEqual(migrated.pending('default')[0]['kind'],'recall')
        migrated.enqueue('default',['a'],'confirmed')
        self.assertEqual({r['kind'] for r in migrated.pending('default')},{'recall','confirmed'})

    def test_citation_verification_uses_real_same_window_archive_spans_not_model_claim(self):
        brain=Brain.new();brain.meta['library_id']='default'
        nid=remember(brain,'我们约定周六一起去看海',kind='preference')
        delivery=self.journal.issue_delivery('default','connection-a','window-a',[nid],at=brain.nodes[nid]['created'])
        reply=record_turn(brain,'周六我们去哪里','记得我们约定周六一起去看海','internal-window','reply',connection_id='connection-a',external_session_id='window-a',origin='agent_hook')
        brain.nodes[reply]['meta']['evidence']={'archive_receipt_id':'synthetic-archive'}
        quote={'id':nid,'quote':'我们约定周六一起去看海'}
        self.assertEqual(verify_citations(brain,delivery,reply,[quote]),[nid])
        with self.assertRaises(ValidationError):verify_citations(brain,delivery,reply,[{'id':nid,'quote':'任意声称已经记住你的内容'}])
        wrong={**delivery,'connection_id':'connection-b'}
        with self.assertRaises(ValidationError):verify_citations(brain,wrong,reply,[quote])
        brain.nodes[reply]['meta']['evidence']['content_truncated']=True
        with self.assertRaises(ValidationError):verify_citations(brain,delivery,reply,[quote])
        self.assertEqual(verify_citations(brain,delivery,reply,[quote],archived_reply='记得我们约定周六一起去看海'),[nid])
        brain.nodes[nid]['meta']['memory_disabled']=True
        with self.assertRaises(ValidationError):verify_citations(brain,delivery,reply,[quote],archived_reply='记得我们约定周六一起去看海')


if __name__=='__main__':unittest.main()
