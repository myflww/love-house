"""Episodic memories select real evidence; they do not fabricate a life story."""
from copy import deepcopy
import time
import unittest

from nkb import Brain
from nkb.companion.memory import record_turn
from nkb.companion.retention import enable_temporal_retention,record_memory_use
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.model import OrganizerError
from nkb.organizer.rules import RULES_VERSION,SYSTEM_GUIDANCE
from nkb.organizer.state import build_input,validate_plan,apply_plan,review_candidate,rollback
from nkb.organizer.experiences import SCHEMA,render_experience,project_experience,rebind_experiences_after_import


class ExperienceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.brain=Brain.new(name='合成经历测试')
        self.brain.meta['library_id']='fish-one'
        enable_temporal_retention(self.brain)
        save_profile(self.brain,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE')
        self.profile=get_profile(self.brain)
        self.start=time.time()-3600
        self.number=0

    def tool(self,text,status='observed',stamp=None):
        self.number+=1
        return self.brain.add('来源观察'+str(self.number),text,kind='episode',event_at=self.start+self.number if stamp is None else stamp,
                              meta={'source':'tool_observation','speaker':'tool','outcome':status,
                                    'evidence':{'archive_receipt_id':'FAKE-receipt-'+str(self.number)}})

    def turn(self,user,assistant='保留助手原话。'):
        self.number+=1
        nid=record_turn(self.brain,user,assistant,'original-window',str(self.number))
        self.brain.nodes[nid]['event_at']=self.start
        return nid

    def material(self,ids):
        return build_input(self.brain,'fish-one',[{'raw_id':nid,'progress':'{}'} for nid in ids],self.profile)

    def ref(self,nid,role='tool',quote=None):
        node=self.brain.nodes[nid]
        value=node['meta'].get('assistant_reply','') if role=='assistant' else node['text']
        return {'id':nid,'role':role,'quote':value if quote is None else quote}

    def operation(self,refs,episode=None,**changes):
        op={'action':'remember','layer':'experience','key':'experience.seaside.weather','text':'查询海边天气的经历',
            'certainty':'clear','domain':'real','evidence':refs}
        if episode is not None:op['episode']=episode
        op.update(changes)
        return op

    def plan(self,ids,op,job='job'):
        payload,guards=self.material(ids)
        return validate_plan({'version':1,'operations':[op]},payload,guards,job,self.profile)

    def apply(self,ids,op,job='job'):
        result=apply_plan(self.brain,self.plan(ids,op,job),'fish-one')
        return result,self.brain.get(result['created'][0]) if result['created'] else None

    def sample(self):
        what=self.tool('在网页上查到了海边今天的天气。')
        reason=self.turn('因为朋友准备去海边，所以请查一下天气。')
        outcome=self.tool('天气资料显示今晚没有降雨。','success')
        refs=[self.ref(what),self.ref(reason,'user'),self.ref(outcome)]
        ep={'what':self.ref(what),'reason':self.ref(reason,'user'),'outcome':self.ref(outcome)}
        return [what,reason,outcome],self.operation(refs,ep)

    def test_real_event_reason_result_and_time_are_machine_readable_without_editing_sources(self):
        ids,op=self.sample();before={nid:deepcopy(self.brain.nodes[nid]) for nid in ids}
        result,node=self.apply(ids,op)
        self.assertEqual(len(result['created']),1)
        episode=node['meta']['experience']
        self.assertEqual(episode['schema'],SCHEMA);self.assertEqual(episode['library_id'],'fish-one')
        self.assertEqual(episode['status'],'success');self.assertEqual(episode['status_scope'],'quoted_result_report')
        self.assertFalse(episode['reason_verified'])
        self.assertEqual(episode['event_at'],self.brain.nodes[ids[0]]['event_at'])
        self.assertEqual(episode['outcome_at'],self.brain.nodes[ids[-1]]['event_at'])
        display=render_experience(episode)
        self.assertIn('在网页上查到了海边今天的天气。',display)
        self.assertIn('原因（用户原话）',display);self.assertIn('报告成功',display)
        self.assertNotIn('browser_call',display)
        self.assertEqual({nid:self.brain.nodes[nid] for nid in ids},before)
        self.assertEqual(project_experience(self.brain,node,'fish-one')['confirmation'],'source_attributed_material')

    def test_missing_reason_and_result_stay_unknown_not_invented(self):
        nid=self.tool('在群里看到了关于海边的消息。')
        _,node=self.apply([nid],self.operation([self.ref(nid)],{'what':self.ref(nid)}))
        ep=node['meta']['experience'];self.assertIsNone(ep['reason']);self.assertIsNone(ep['outcome'])
        self.assertEqual(ep['status'],'unknown')
        self.assertIn('原因：未提供',render_experience(ep));self.assertIn('结果：未提供',render_experience(ep))

    def test_unknown_historical_time_never_falls_back_to_organize_time(self):
        nid=self.tool('很久以前观察到了一次天气变化。')
        self.brain.nodes[nid]['meta']['source_time_unknown']=True
        _,node=self.apply([nid],self.operation([self.ref(nid)],{'what':self.ref(nid)}))
        ep=node['meta']['experience'];self.assertIsNone(ep['event_at']);self.assertEqual(ep['time_status'],'unknown')
        self.assertIsNotNone(ep['recorded_at'])

    def test_assistant_success_story_is_reported_and_needs_review_not_verified_completion(self):
        nid=self.turn('请保留记录。','我准备去网页上查一份资料。后来我说自己完成了。')
        what=self.ref(nid,'assistant','我准备去网页上查一份资料。')
        outcome=self.ref(nid,'assistant','后来我说自己完成了。')
        op=self.operation([what,outcome],{'what':what,'outcome':outcome})
        plan=self.plan([nid],op)
        ep=plan['operations'][0]['episode'];self.assertEqual(ep['status'],'reported')
        self.assertEqual(ep['what']['claim_type'],'stated_intent')
        self.assertTrue(plan['operations'][0]['requires_review'])
        result=apply_plan(self.brain,plan,'fish-one');self.assertEqual(result['created'],[])
        self.assertEqual(len(result['candidates']),1)

    def test_status_cannot_disagree_with_actual_failed_tool_result(self):
        nid=self.tool('此次查询没有完成，连接中断。','failed')
        ref=self.ref(nid)
        op=self.operation([ref],{'what':ref,'outcome':ref,'status':'success'})
        with self.assertRaises(OrganizerError):self.plan([nid],op)
        op['episode']['status']='failed'
        _,node=self.apply([nid],op)
        self.assertEqual(node['meta']['experience']['status'],'failed')

    def test_reason_free_text_time_library_and_undeclared_fields_are_rejected(self):
        nid=self.tool('观察到一条实际消息。');ref=self.ref(nid)
        episodes=[{'what':ref,'reason':'因为她孤独想找人陪。'},
                  {'what':ref,'event_at':0},{'what':ref,'library_id':'other'},
                  {'what':ref,'participants':['不存在的人']},
                  {'what':ref,'places':[ref]*7}, {'what':{**ref,'role':[]}}]
        before=deepcopy(self.brain.to_dict())
        for ep in episodes:
            with self.subTest(ep=ep),self.assertRaises(OrganizerError):self.plan([nid],self.operation([ref],ep))
        self.assertEqual(self.brain.to_dict(),before)

    def test_quotes_need_the_same_operation_role_and_verified_sentence(self):
        a=self.tool('查到了实际资料。');b=self.tool('另一个来源提供了其他资料。')
        what=self.ref(a)
        invalid=[self.ref(b),{**what,'role':'assistant'},self.ref(a,quote='她感觉到幸福。')]
        for ref in invalid:
            with self.subTest(ref=ref),self.assertRaises(OrganizerError):
                self.plan([a,b],self.operation([what],{'what':what,'reason':ref}))
        with self.assertRaises(OrganizerError):
            self.plan([a],self.operation([what],{'what':{**what,'id':'another-library-node'}}))

    def test_episode_is_not_accepted_on_non_experience_or_relation_only_operation(self):
        nid=self.tool('看到一份资料。');ref=self.ref(nid)
        with self.assertRaises(OrganizerError):self.plan([nid],self.operation([ref],{'what':ref},layer='fact'))
        op=self.operation([ref],{'what':ref},action='relate',target_id=nid)
        with self.assertRaises(OrganizerError):self.plan([nid],op)

    def test_same_words_on_different_occurrences_never_auto_merge(self):
        first=self.tool('在网页上观察到了当天的天气。')
        second=self.tool('在网页上观察到了当天的天气。',stamp=self.start+100)
        r1,n1=self.apply([first],self.operation([self.ref(first)],{'what':self.ref(first)}),'first')
        r2,n2=self.apply([second],self.operation([self.ref(second)],{'what':self.ref(second)}),'second')
        self.assertNotEqual(n1['id'],n2['id']);self.assertEqual(r2['merged'],[])
        result,_=self.apply([second],self.operation([self.ref(second)],{'what':self.ref(second)},action='merge',target_id=n1['id']),'badmerge')
        self.assertEqual(result['merged'],[]);self.assertEqual(len(result['candidates']),1)

    def test_same_occurrence_can_gain_a_result_without_overwriting_earlier_unknowns_or_raw(self):
        what=self.tool('在网页上查到了海边天气。')
        first,node=self.apply([what],self.operation([self.ref(what)],{'what':self.ref(what)}),'first')
        outcome=self.tool('天气资料显示今天没有降雨。','success')
        refs=[self.ref(what),self.ref(outcome)]
        result,_=self.apply([what,outcome],self.operation(refs,{'what':self.ref(what),'outcome':self.ref(outcome)},action='merge',target_id=node['id']),'enrich')
        self.assertEqual(result['merged'],[node['id']]);self.assertEqual(result['created'],[])
        episode=self.brain.nodes[node['id']]['meta']['experience']
        self.assertIsNone(episode['reason']);self.assertEqual(episode['outcome']['quote'],self.brain.nodes[outcome]['text'])
        self.assertIsNotNone(project_experience(self.brain,node,'fish-one'))

    def test_conflicting_results_for_one_occurrence_go_to_review(self):
        what=self.tool('查询了当天的天气。');old=self.tool('资料显示没有降雨。','success')
        _,node=self.apply([what,old],self.operation([self.ref(what),self.ref(old)],{'what':self.ref(what),'outcome':self.ref(old)}),'old')
        new=self.tool('随后发现这次结果无效。','failed')
        result,_=self.apply([what,new],self.operation([self.ref(what),self.ref(new)],{'what':self.ref(what),'outcome':self.ref(new)},action='merge',target_id=node['id']),'conflict')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(node['meta']['experience']['outcome']['id'],old)

    def test_projection_rechecks_edits_pause_forgotten_scope_and_forged_metadata(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        baseline=deepcopy(self.brain.to_dict())
        self.assertIsNone(project_experience(self.brain,node,'other'))
        for mutation in ('edit','pause','forget','source-scope','self-pause'):
            b=Brain(deepcopy(baseline));n=b.nodes[node['id']];source=b.nodes[ids[0]]
            if mutation=='edit':source['text']='并没有'+source['text']
            elif mutation=='pause':source['meta']['memory_disabled']=True
            elif mutation=='forget':b.meta['memory_tombstones']={'node_ids':[ids[0]]}
            elif mutation=='source-scope':source['meta']['library_id']='other'
            else:n['meta']['memory_disabled']=True
            self.assertIsNone(project_experience(b,n,'fish-one'),mutation)
        fake=self.brain.add('伪造经历','不是经来源形成的经历',kind='episode',meta={'experience':deepcopy(node['meta']['experience'])})
        self.assertIsNone(project_experience(self.brain,self.brain.nodes[fake],'fish-one'))

    def test_real_use_does_not_invalidate_provenance_revision_or_turn_self_report_into_fact(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        record_memory_use(self.brain,[ids[0]],kind='recall')
        projected=project_experience(self.brain,node,'fish-one')
        self.assertIsNotNone(projected);self.assertFalse(projected['reason_verified'])
        self.assertEqual(projected['confirmation'],'source_attributed_material')

    def test_conflicting_event_times_require_review_without_rewriting_them(self):
        what=self.tool('查阅天气资料。',stamp=self.start+100)
        outcome=self.tool('来源报告查询完成。','success',stamp=self.start)
        plan=self.plan([what,outcome],self.operation([self.ref(what),self.ref(outcome)],{'what':self.ref(what),'outcome':self.ref(outcome)}))
        self.assertEqual(plan['operations'][0]['episode']['time_status'],'conflicting')
        self.assertTrue(plan['operations'][0]['requires_review'])

    def test_legacy_operations_and_raw_records_remain_supported_and_undo_keeps_sources(self):
        nid=self.turn('今天收到了朋友的消息。')
        legacy=self.operation([self.ref(nid,'user')])
        result,node=self.apply([nid],legacy,'legacy')
        self.assertNotIn('experience',node['meta']);self.assertEqual(len(result['created']),1)
        what=self.tool('实际查阅了一份资料。');_,new=self.apply([what],self.operation([self.ref(what)],{'what':self.ref(what)}),'new')
        self.assertIsNotNone(new['meta']['experience']);rollback(self.brain,'new')
        self.assertIsNone(self.brain.get(new['id']));self.assertIsNotNone(self.brain.get(what))

    def test_external_platform_speaker_is_not_owner_and_preferences_require_review(self):
        nid=self.turn('我喜欢喝冰咖啡。')
        self.brain.nodes[nid]['meta']['evidence']={'participant_scope':'external_participant','participant_id':'FAKE-other-person'}
        payload,guards=self.material([nid])
        self.assertEqual(payload['raw'][0]['participant_scope'],'external_participant')
        self.assertEqual(payload['raw'][0]['participant_id'],'FAKE-other-person')
        ref=self.ref(nid,'user')
        op=self.operation([ref],layer='preference',key='drink.preference',atom={'subject':'user','predicate':'drink.preference','value':'冰咖啡'})
        plan=validate_plan({'version':1,'operations':[op]},payload,guards,'external-preference',self.profile)
        self.assertTrue(plan['operations'][0]['requires_review'])
        self.assertEqual(plan['operations'][0]['atom']['subject'],'platform_participant')
        result=apply_plan(self.brain,plan,'fish-one')
        self.assertEqual(result['created'],[]);self.assertEqual(len(result['candidates']),1)

    def test_external_experience_preserves_other_person_as_attributed_speaker(self):
        nid=self.turn('我今天去海边看了日落。','听起来是一次特别的经历。')
        self.brain.nodes[nid]['meta']['evidence']={'participant_scope':'external_participant','participant_id':'FAKE-visitor'}
        ref=self.ref(nid,'user')
        result,_=self.apply([nid],self.operation([ref],{'what':ref,'outcome':ref}),'external-experience')
        self.assertEqual(len(result['candidates']),1)
        accepted=review_candidate(self.brain,result['candidates'][0],'accept')
        node=self.brain.nodes[accepted['node_id']]
        ep=project_experience(self.brain,node,'fish-one')
        self.assertEqual(ep['what']['basis'],'platform_participant_statement')
        self.assertEqual(ep['what']['participant_id'],'FAKE-visitor')
        self.assertEqual(ep['status'],'reported')
        self.assertEqual(node['meta']['memory_atom']['subject'],'platform_participant')
        self.assertIn('对方原话',render_experience(ep))
        self.assertNotIn('报告成功',render_experience(ep))

    def test_user_review_of_uncertain_episode_keeps_evidence_based_structure(self):
        ids,op=self.sample();op['certainty']='uncertain'
        result,_=self.apply(ids,op,'review')
        self.assertEqual(len(result['candidates']),1)
        accepted=review_candidate(self.brain,result['candidates'][0],'accept')
        node=self.brain.nodes[accepted['node_id']]
        self.assertIsNotNone(project_experience(self.brain,node,'fish-one'))
        self.assertFalse(node['meta']['experience']['reason_verified'])

    def test_public_projection_is_read_only_and_rejects_malformed_metadata(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        before=deepcopy(self.brain.to_dict())
        project_experience(self.brain,node,'fish-one')
        self.assertEqual(self.brain.to_dict(),before)
        bad=deepcopy(node);bad['meta']['organizer_sources']={'not':'a list'}
        self.assertIsNone(project_experience(self.brain,bad,'fish-one'))
        bad=deepcopy(node);bad['meta']['experience']['what']['role']=[]
        self.assertIsNone(project_experience(self.brain,bad,'fish-one'))

    def test_clipped_source_needs_full_archive_before_quote_can_be_displayed(self):
        full='来源的完整资料。'*60+'\n实际查询获得了今日天气。'
        nid=self.tool('节点摘录；完整结果保存在事件档案。')
        self.brain.nodes[nid]['meta']['evidence']['content_truncated']=True
        receipt=self.brain.nodes[nid]['meta']['evidence']['archive_receipt_id']
        archive={'record':{'normalized':{'type':'tool','text':full}}}
        payload,guards=build_input(self.brain,'fish-one',[{'raw_id':receipt,'progress':'{}'}],self.profile,archives={receipt:archive})
        ref=self.ref(nid,quote='实际查询获得了今日天气。')
        plan=validate_plan({'version':1,'operations':[self.operation([ref],{'what':ref})]},payload,guards,'archive',self.profile)
        result=apply_plan(self.brain,plan,'fish-one');node=self.brain.nodes[result['created'][0]]
        self.assertIsNone(project_experience(self.brain,node,'fish-one'))
        checked=project_experience(self.brain,node,'fish-one',read_archive=lambda rid:archive if rid==receipt else None)
        self.assertIsNotNone(checked);self.assertIn('实际查询获得了今日天气。',render_experience(checked))

    def test_trusted_import_rebinds_to_new_identity_after_source_mapping(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        imported=Brain(deepcopy(self.brain.to_dict()))
        oldtext={nid:n['text'] for nid,n in imported.nodes.items()}
        self.assertIsNone(project_experience(imported,imported.nodes[node['id']],'fish-new'))
        result=rebind_experiences_after_import(imported,'fish-new')
        self.assertEqual(result,{'rebound':1,'withheld':0})
        ep=project_experience(imported,imported.nodes[node['id']],'fish-new')
        self.assertIsNotNone(ep);self.assertEqual(ep['library_id'],'fish-new')
        self.assertEqual({nid:n['text'] for nid,n in imported.nodes.items()},oldtext)
        self.assertEqual(self.brain.meta['library_id'],'fish-one')

    def test_import_cannot_resign_a_quote_inside_a_changed_negative_sentence(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        imported=Brain(deepcopy(self.brain.to_dict()))
        imported.nodes[ids[0]]['text']='并没有'+imported.nodes[ids[0]]['text']
        result=rebind_experiences_after_import(imported,'fish-new')
        self.assertEqual(result,{'rebound':0,'withheld':1})
        self.assertTrue(imported.nodes[node['id']]['meta']['experience_withheld'])
        self.assertIsNone(project_experience(imported,imported.nodes[node['id']],'fish-new'))
        self.assertIn('并没有',imported.nodes[ids[0]]['text'])

    def test_import_keeps_unverifiable_experience_as_withheld_material(self):
        ids,op=self.sample();_,node=self.apply(ids,op)
        imported=Brain(deepcopy(self.brain.to_dict()))
        imported.nodes[node['id']]['meta']['experience']['reason']['id']='missing-external-source'
        result=rebind_experiences_after_import(imported,'fish-new')
        self.assertEqual(result['withheld'],1);self.assertEqual(len(imported.nodes),len(self.brain.nodes))
        self.assertIsNone(project_experience(imported,imported.nodes[node['id']],'fish-new'))

    def test_autonomous_observation_with_attributed_agent_reason_can_be_organized(self):
        what=self.tool('在网页里查到了海边今天的天气。')
        reason=self.turn('任务备注。','我想把海边的天气资料分享给朋友。')
        outcome=self.tool('资料已整理到本次结果中。','success')
        refs=[self.ref(what),self.ref(reason,'assistant'),self.ref(outcome)]
        op=self.operation(refs,{'what':self.ref(what),'reason':self.ref(reason,'assistant'),'outcome':self.ref(outcome)})
        plan=self.plan([what,reason,outcome],op,'autonomous')
        normalized=plan['operations'][0]
        self.assertTrue(normalized['attributed_episode_observation']);self.assertFalse(normalized['requires_review'])
        result=apply_plan(self.brain,plan,'fish-one');self.assertEqual(len(result['created']),1);self.assertEqual(result['candidates'],[])
        node=self.brain.nodes[result['created'][0]];episode=project_experience(self.brain,node,'fish-one')
        self.assertEqual(episode['reason']['basis'],'agent_self_report');self.assertFalse(episode['reason_verified'])
        self.assertEqual(episode['status'],'success');self.assertEqual(episode['status_scope'],'quoted_result_report')
        self.assertFalse(node['meta']['confirmed']);self.assertFalse(node['meta']['important'])
        self.assertIn('原因（助手自述）',node['text']);self.assertNotIn('工具观察（',node['text'])
        self.assertNotIn('companion_profile',self.brain.meta)

    def test_autonomous_branch_does_not_bypass_intent_domain_hypothesis_or_non_experience_gates(self):
        what=self.tool('在网页上观察到真实资料。')
        reason=self.turn('任务备注。','我想继续了解这条资料。')
        refs=[self.ref(what),self.ref(reason,'assistant')]
        for domain in ('unknown','roleplay'):
            op=self.operation(refs,{'what':self.ref(what),'reason':self.ref(reason,'assistant')},domain=domain)
            self.assertTrue(self.plan([what,reason],op,'domain-'+domain)['operations'][0]['requires_review'])
        intent=self.tool('计划去网页上查一份资料。')
        op=self.operation([self.ref(intent)],{'what':self.ref(intent)})
        normalized=self.plan([intent],op,'intent')['operations'][0]
        self.assertFalse(normalized['attributed_episode_observation']);self.assertTrue(normalized['requires_review'])
        hypothetical=self.turn('假设这是小说里的一次活动。','我说自己想要查资料。')
        op=self.operation([self.ref(what),self.ref(hypothetical,'assistant')],{'what':self.ref(what),'reason':self.ref(hypothetical,'assistant')})
        self.assertTrue(self.plan([what,hypothetical],op,'hypothesis')['operations'][0]['requires_review'])
        ordinary=self.operation(refs,layer='fact')
        normalized=self.plan([what,reason],ordinary,'fact')['operations'][0]
        self.assertFalse(normalized['attributed_episode_observation']);self.assertTrue(normalized['requires_review'])
        forged=self.operation([self.ref(what)],{'what':self.ref(what)},attributed_episode_observation=True)
        with self.assertRaises(OrganizerError):self.plan([what],forged,'forged-program-flag')

    def test_autonomous_observation_cannot_overwrite_a_protected_experience(self):
        what=self.tool('观察到了一次真实的网页查询。')
        _,node=self.apply([what],self.operation([self.ref(what)],{'what':self.ref(what)}),'protected-old')
        node['meta']['important']=True
        reason=self.turn('任务备注。','我想保留这次查询的原因。')
        refs=[self.ref(what),self.ref(reason,'assistant')]
        op=self.operation(refs,{'what':self.ref(what),'reason':self.ref(reason,'assistant')},action='merge',target_id=node['id'])
        plan=self.plan([what,reason],op,'protected-new')
        self.assertFalse(plan['operations'][0]['requires_review'])
        result=apply_plan(self.brain,plan,'fish-one')
        self.assertEqual(result['merged'],[]);self.assertEqual(len(result['candidates']),1)
        self.assertIsNone(node['meta']['experience']['reason'])

    def test_guide_requests_evidence_refs_not_fabricated_motivation_or_tool_stack_diaries(self):
        self.assertIn('整理规则版本：'+RULES_VERSION,SYSTEM_GUIDANCE)
        self.assertIn('episode={what,reason,outcome,participants,places}',SYSTEM_GUIDANCE)
        self.assertIn('缺证据填null',SYSTEM_GUIDANCE)
        self.assertIn('工具名、函数参数或堆栈',SYSTEM_GUIDANCE)


if __name__=='__main__':unittest.main()
