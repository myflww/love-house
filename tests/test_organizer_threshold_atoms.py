"""Strict N-record triggers, bounded drains and evidence-bound machine atoms; offline only."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nkb import Brain
from nkb.companion import record_turn
from nkb.organizer import Organizer,apply_plan,get_profile,save_profile
from nkb.organizer.atoms import SCHEMA
from nkb.errors import ValidationError


class OrganizerThresholdAtomTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.brains={'a':Brain.new(),'b':Brain.new()};self.calls=[];self.credential_calls=[]
        self.reply=lambda payload:{'version':1,'operations':[]}
        self.transport_failed=False
        for brain in self.brains.values():save_profile(brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE',auto_trigger_count=3,batch_size=2)
        self.organizer=self.make();self.addCleanup(self.organizer.stop)
    def make(self):
        def credential(lid,profile):self.credential_calls.append(lid);return 'FAKE-NO-NETWORK'
        def send(request,*,timeout):
            payload=json.loads(json.loads(request.data)['messages'][1]['content']);self.calls.append(payload)
            if self.transport_failed:raise TimeoutError('offline simulated timeout')
            return {'choices':[{'message':{'content':json.dumps(self.reply(payload),ensure_ascii=False)},'finish_reason':'stop'}]}
        return Organizer(self.tmp.name,snapshot=lambda lid:deepcopy(self.brains[lid].to_dict()),
                         apply=lambda lid,plan:apply_plan(self.brains[lid],plan,lid),credential=credential,transport=send)
    def raw(self,text='我住在北京。',lid='a'):
        brain=self.brains[lid];rid=record_turn(brain,text,'这是一条助手回复。','test-session',str(len(brain.nodes)))
        brain.nodes[rid]['meta']['evidence']={'archive_receipt_id':'receipt-'+rid}
        # Use direct node IDs here; production uses receipt IDs and read_archive.
        self.organizer.enqueue(lid,[rid]);return rid
    def drain(self,lid='a',limit=60):
        result=None
        for _ in range(limit):
            result=self.organizer.run_once(lid,flush=False)
            if result['status']!='done':return result
        self.failTest('bounded fake workload did not drain')
    def op(self,payload,**fields):
        source=payload['raw'][0]
        return {'action':'remember','layer':'fact','key':'home.city','text':'用户住在北京',
                'certainty':'clear','domain':'real','evidence':[{'id':source['id'],'role':'user','quote':source['roles']['user']}],
                'atom':{'subject':'user','predicate':'home.city','value':'北京'},**fields}
    def fact_reply(self,payload):return {'version':1,'operations':[self.op(payload)]}
    def facts(self,lid='a'):return [n for n in self.brains[lid].nodes.values() if n['meta'].get('source')=='organizer']

    def test_strict_thresholds_one_three_twenty_do_not_use_thirty_second_fallback(self):
        for threshold in (1,3,20):
            with self.subTest(threshold=threshold):
                lid='case-'+str(threshold);self.brains[lid]=Brain.new()
                save_profile(self.brains[lid],enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE',auto_trigger_count=threshold,batch_size=6)
                before=len(self.calls)
                for i in range(threshold-1):self.raw('第'+str(i)+'条原文。',lid)
                with self.organizer.db() as db:db.execute('UPDATE items SET created=created-3600 WHERE library_id=?',(lid,))
                waiting=self.organizer.run_once(lid,flush=False)
                self.assertIn(waiting['status'],('waiting_threshold','waiting'))
                self.assertEqual(len(self.calls),before)
                self.raw('达到阈值的原文。',lid);self.drain(lid)
                self.assertEqual(self.organizer.status(lid)['counts'].get('done'),threshold)
                self.assertGreater(len(self.calls),before)
                self.assertTrue(all(len(p['raw'])<=6 for p in self.calls[before:]))

    def test_trigger_snapshot_drains_its_tail_but_later_arrival_waits_for_next_threshold(self):
        ids=[self.raw(str(i)+'。') for i in range(3)]
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.raw('稍后才来的第四条。')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        state=self.organizer.status('a');self.assertEqual(state['counts'].get('done'),3);self.assertEqual(state['counts'].get('pending'),1)
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'waiting_threshold')
        self.assertEqual({r['id'] for p in self.calls for r in p['raw']},set(ids))

    def test_manual_flush_bypasses_threshold_and_auto_finishes_that_snapshot(self):
        save_profile(self.brains['a'],auto_trigger_count=20,batch_size=1)
        self.raw();self.raw('另一个原文。')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'waiting_threshold')
        self.assertEqual(self.organizer.run_once('a',flush=True)['status'],'done')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.assertEqual(self.organizer.status('a')['counts'].get('done'),2)

    def test_cycle_membership_survives_worker_restart_and_budget_pause(self):
        save_profile(self.brains['a'],daily_call_limit=1)
        for i in range(3):self.raw(str(i)+'。')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'budget_limited')
        self.assertTrue(self.organizer.status('a')['trigger']['draining'])
        self.organizer.stop();restored=self.make();self.addCleanup(restored.stop)
        with restored.db() as db:db.execute('UPDATE calls SET at=at-86401')
        self.assertEqual(restored.run_once('a',flush=False)['status'],'done')
        self.assertEqual(restored.status('a')['counts'].get('done'),3)

    def test_failed_batch_does_not_block_cycle_tail_or_lose_failed_originals(self):
        save_profile(self.brains['a'],max_attempts=1)
        ids=[self.raw(str(i)+'。') for i in range(3)];self.transport_failed=True
        failed=self.organizer.run_once('a',flush=False);self.assertEqual(failed['status'],'failed')
        self.transport_failed=False
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.assertEqual(self.organizer.status('a')['counts'].get('failed'),2)
        self.organizer.retry(failed['job_id'])
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.assertEqual(self.organizer.status('a')['counts'].get('done'),3)
        self.assertTrue(all(i in self.brains['a'].nodes for i in ids))

    def test_long_partial_from_legacy_mode_finishes_below_a_new_strict_threshold(self):
        save_profile(self.brains['a'],auto_trigger_count=0,batch_size=1,max_input_chars=3000)
        rid=self.raw('真实长原文。'*1000)
        self.assertEqual(self.organizer.run_once('a',flush=True)['status'],'done')
        self.assertEqual(self.organizer.status('a')['counts'].get('pending'),1)
        save_profile(self.brains['a'],auto_trigger_count=20)
        result=self.drain();self.assertEqual(result['status'],'waiting_threshold')
        self.assertEqual(self.organizer.status('a')['counts'].get('done'),1)
        self.assertEqual(self.brains['a'].nodes[rid]['text'],'真实长原文。'*1000)

    def test_strict_waiting_library_and_budget_limited_library_do_not_starve_others(self):
        self.raw(lid='a')
        for i in range(3):self.raw(str(i)+'。',lid='b')
        self.assertEqual(self.organizer.run_once(flush=False)['library_id'],'b')
        self.assertEqual(self.organizer.run_once(flush=False)['library_id'],'b')
        self.assertEqual(self.credential_calls,['b','b'])

    def test_status_and_preview_show_threshold_without_credentials_or_model_calls(self):
        self.raw();before=deepcopy(self.brains['a'].to_dict())
        state=self.organizer.status('a');self.assertEqual(state['trigger']['threshold'],3);self.assertEqual(state['trigger']['below_threshold'],2)
        preview=self.organizer.preview('a');self.assertEqual(preview['status'],'waiting_threshold');self.assertFalse(preview['will_call_model'])
        self.assertEqual(self.calls,[]);self.assertEqual(self.credential_calls,[]);self.assertEqual(before,self.brains['a'].to_dict())
        for value in (-1,501,True,'3'):
            with self.assertRaises(ValidationError):save_profile(self.brains['a'],auto_trigger_count=value)
        with self.assertRaises(ValidationError):save_profile(self.brains['a'],base_url='http://127.0.0.1:8768/connections/local-agent/v1')
        save_profile(self.brains['a'],cadence='session',auto_trigger_count=20)
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')

    def test_machine_atom_is_plain_json_sourced_and_times_come_from_program(self):
        self.reply=self.fact_reply;raw=self.raw();original=deepcopy(self.brains['a'].nodes[raw])
        self.assertEqual(self.organizer.run_once('a')['status'],'done')
        node=self.facts()[0];atom=node['meta']['memory_atom']
        self.assertEqual(atom['schema'],SCHEMA);self.assertEqual(atom['library_id'],'a')
        self.assertEqual((atom['subject'],atom['predicate'],atom['value']),('user','home.city','北京'))
        self.assertEqual(atom['qualifiers']['polarity'],'affirmed')
        self.assertEqual(atom['valid_from'],node['valid_from']);self.assertEqual(atom['recorded_at'],node['created'])
        self.assertEqual(atom['evidence'][0]['id'],raw);self.assertEqual(atom['evidence'][0]['receipt_id'],'receipt-'+raw)
        self.assertEqual(node['text'],'我住在北京。');self.assertEqual(self.brains['a'].nodes[raw],original)
        json.dumps(atom,ensure_ascii=False,allow_nan=False)

    def test_same_atom_from_different_phrasing_merges_and_keeps_all_source_references(self):
        self.reply=self.fact_reply
        sources=[]
        for i in range(28):
            sources.append(self.raw('我住在北京。' if i==0 else '我的家在北京。'))
            self.assertEqual(self.organizer.run_once('a')['status'],'done')
        self.assertEqual(len(self.facts()),1);node=self.facts()[0]
        self.assertEqual(node['text'],'我住在北京。');self.assertEqual(len(node['meta']['organizer_evidence']),24)
        self.assertEqual({e['id'] for e in node['meta']['organizer_sources']},set(sources))
        self.assertEqual({e['id'] for e in node['meta']['memory_atom']['evidence']},set(sources))
        self.assertTrue(all(i in self.brains['a'].nodes for i in sources))
        self.assertEqual({i for i,w in self.brains['a'].neighbors(node['id'])},set(sources))

    def test_invalid_optional_atoms_are_withheld_as_literal_candidates_without_retrying_job(self):
        for atom in ({'subject':'user','predicate':'home.city','value':'上海'},
                     {'subject':'user','predicate':'home.city','value':'北京','created':1},
                     {'subject':'user','predicate':'home.city','value':'北京','qualifiers':{'event_at':1}},
                     {'subject':'unknown invented entity','predicate':'home.city','value':'北京'},
                     {'subject':'user','predicate':'run this code()','value':'北京'}):
            with self.subTest(atom=atom):
                lid='bad-'+str(len(self.brains));self.brains[lid]=Brain.new();save_profile(self.brains[lid],enabled=True,base_url='https://offline.invalid/v1',model='FAKE')
                self.reply=lambda p,atom=atom:{'version':1,'operations':[self.op(p,atom=atom)]}
                self.raw(lid=lid);result=self.organizer.run_once(lid)
                self.assertEqual(result['status'],'done');self.assertEqual(self.facts(lid),[])
                candidates=self.brains[lid].meta['organizer_candidates'];self.assertEqual(len(candidates),1)
                self.assertEqual(candidates[0]['reason_code'],'invalid_atom_verbatim_fallback')
                self.assertEqual(candidates[0]['operation']['atom']['relation_status'],'verbatim_fallback')
                self.assertEqual(candidates[0]['operation']['text'],'我住在北京。')

    def test_negation_cannot_be_converted_to_a_positive_machine_fact(self):
        self.reply=lambda p:{'version':1,'operations':[self.op(p,layer='preference',atom={'subject':'user','predicate':'likes','value':'咖啡','qualifiers':{'polarity':'affirmed'}})]}
        self.raw('我不喜欢咖啡。');self.organizer.run_once('a')
        self.assertEqual(self.facts(),[]);self.assertEqual(len(self.brains['a'].meta['organizer_candidates']),1)
        self.reply=lambda p:{'version':1,'operations':[self.op(p,layer='preference',atom={'subject':'user','predicate':'likes','value':'咖啡','qualifiers':{'polarity':'negated'}})]}
        self.raw('我不喜欢咖啡。');self.organizer.run_once('a')
        self.assertEqual(self.facts()[0]['meta']['memory_atom']['qualifiers']['polarity'],'negated')

    def test_merge_different_values_is_reviewed_and_supersede_closes_old_atom_validity(self):
        self.reply=self.fact_reply;self.raw();self.organizer.run_once('a');old=self.facts()[0]
        self.reply=lambda p:{'version':1,'operations':[self.op(p,action='merge',target_id=old['id'],atom={'subject':'user','predicate':'home.city','value':'上海'})]}
        self.raw('我住在上海。');self.organizer.run_once('a');self.assertEqual(len(self.facts()),1)
        self.assertEqual(len(self.brains['a'].meta['organizer_candidates']),1)
        self.reply=lambda p:{'version':1,'operations':[self.op(p,action='supersede',target_id=old['id'],atom={'subject':'user','predicate':'home.city','value':'上海'})]}
        self.raw('我现在住在上海。');self.organizer.run_once('a')
        self.assertIsNotNone(old['valid_to']);self.assertEqual(old['meta']['memory_atom']['valid_to'],old['valid_to'])

    def test_confirmed_aliases_do_not_count_toward_trigger_or_call_the_model(self):
        from nkb.companion import ingest_event
        from nkb.companion.dedup import is_duplicate
        brain=self.brains['a']
        manual=record_turn(brain,'我喜欢喝茶。','真实回复。','window','manual',origin='manual_harness')
        self.organizer.enqueue('a',[manual])
        passive=ingest_event(brain,{'type':'turn','connection_id':'test-connection','session_id':'window','turn_id':'host',
                         'user':'我喜欢喝茶。','assistant':'真实回复。','origin':'harness_hook'})['node_ids'][0]
        self.organizer.enqueue('a',[passive])
        self.assertTrue(is_duplicate(brain.nodes[manual],brain))
        waiting=self.organizer.run_once('a',flush=False)
        self.assertEqual(waiting['status'],'waiting_threshold');self.assertEqual(self.calls,[])
        state=self.organizer.status('a');self.assertEqual(state['counts'].get('done_alias'),1);self.assertEqual(state['trigger']['pending'],1)
        self.assertEqual(len(brain.nodes),2);self.assertEqual(len(brain.nodes[passive]['meta']['recording_sources']),2)

    def test_mixed_retry_batch_omits_confirmed_alias_material_but_finishes_other_raw(self):
        from nkb.companion import ingest_event
        brain=self.brains['a'];save_profile(brain,auto_trigger_count=0,batch_size=2)
        manual=record_turn(brain,'我喜欢喝茶。','真实回复。','window','manual',origin='manual_harness')
        self.organizer.enqueue('a',[manual]);other=self.raw('这是另一个独立事实。')
        self.transport_failed=True;failed=self.organizer.run_once('a')
        self.assertEqual(failed['status'],'retry')
        passive=ingest_event(brain,{'type':'turn','connection_id':'test-connection','session_id':'window','turn_id':'host',
                         'user':'我喜欢喝茶。','assistant':'真实回复。','origin':'harness_hook'})['node_ids'][0]
        self.organizer.enqueue('a',[passive]);self.transport_failed=False;self.organizer.retry(failed['job_id'])
        result=self.organizer.run_once('a',flush=False);self.assertEqual(result['status'],'done')
        self.assertEqual([r['id'] for r in self.calls[-1]['raw']],[other])
        self.assertEqual(self.organizer.status('a')['counts'].get('done_alias'),1)
        self.assertTrue(all(n in brain.nodes for n in (manual,other,passive)))

    def test_old_retry_wholly_aliased_is_finished_without_a_second_call(self):
        from nkb.companion import ingest_event
        brain=self.brains['a']
        manual=record_turn(brain,'我喜欢喝茶。','真实回复。','window','manual',origin='manual_harness')
        self.organizer.enqueue('a',[manual]);self.transport_failed=True;failed=self.organizer.run_once('a')
        self.assertEqual(len(self.calls),1)
        ingest_event(brain,{'type':'turn','connection_id':'test-connection','session_id':'window','turn_id':'host',
                         'user':'我喜欢喝茶。','assistant':'真实回复。','origin':'harness_hook'})
        self.transport_failed=False;self.organizer.retry(failed['job_id']);self.organizer.run_once('a',flush=False)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.organizer.status('a')['jobs'][0]['status'],'aliased')

    def test_user_review_keeps_a_failed_tool_observation_as_an_observation(self):
        from nkb.organizer import review_candidate
        brain=self.brains['a'];rid=brain.add('工具观察','权限不足',kind='episode',meta={'source':'tool_observation','outcome':'failed'})
        self.organizer.enqueue('a',[rid])
        self.reply=lambda p:{'version':1,'operations':[{'action':'candidate','layer':'fact','key':'browser.result','text':'浏览器返回权限不足',
            'domain':'real','certainty':'clear','evidence':[{'id':p['raw'][0]['id'],'role':'tool','quote':'权限不足'}],
            'atom':{'subject':'tool','predicate':'browser.result','value':'权限不足'}}]}
        self.organizer.run_once('a');candidate=brain.meta['organizer_candidates'][0]
        result=review_candidate(brain,candidate['id'],'accept');node=brain.nodes[result['node_id']]
        self.assertEqual(node['kind'],'episode');self.assertEqual(node['meta']['outcome'],'failed')
        self.assertEqual(node['meta']['memory_atom']['outcome'],'failed');self.assertEqual(node['meta']['memory_atom']['layer'],'experience')
        self.assertIn('failed',node['text']);self.assertEqual(brain.nodes[rid]['text'],'权限不足')

    def test_legacy_model_output_is_still_a_verbatim_machine_record(self):
        self.reply=lambda p:{'version':1,'operations':[{k:v for k,v in self.op(p).items() if k!='atom'}]}
        self.raw();self.organizer.run_once('a');atom=self.facts()[0]['meta']['memory_atom']
        self.assertEqual(atom['relation_status'],'verbatim_fallback');self.assertEqual(atom['value'],'我住在北京。')
        self.assertEqual(atom['qualifiers']['polarity'],'unknown')

if __name__=='__main__':unittest.main()
