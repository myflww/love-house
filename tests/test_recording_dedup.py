"""Offline provenance dedup: repeated capture is not repeated human experience."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from nkb import Brain
from nkb.companion.memory import record_turn,history
from nkb.companion.ingestion import ingest_event,connected_session_id
from nkb.companion.dedup import (annotate_turn_recording,canonical_id,canonical_turns,confirm_duplicate,
                                 is_duplicate,possible_groups,reconcile_recordings,recording_version,separate_recordings)
from nkb.companion.persona import learn_from_dialogue,persona_state,propose_persona
from nkb.service.controls import forget,forget_plan,set_enabled
from nkb.errors import ValidationError


class RecordingDedupTests(unittest.TestCase):
    def setUp(self):self.brain=Brain.new()
    def manual(self,request='manual',window='window',user='我喜欢喝茶。',assistant='这是真实回复。',**kwargs):
        return record_turn(self.brain,user,assistant,window,request,origin='manual_harness',**kwargs)
    def passive(self,request='host',window='window',user='我喜欢喝茶。',assistant='这是真实回复。'):
        return ingest_event(self.brain,{'type':'turn','connection_id':'conn-a','session_id':window,
            'turn_id':request,'status':'complete','user':user,'assistant':assistant,'origin':'harness_hook',
            'evidence':{'archive_receipt_id':'receipt-'+request}})
    def assert_raw_retained(self,nid,user='我喜欢喝茶。',assistant='这是真实回复。'):
        self.assertEqual(self.brain.nodes[nid]['text'],user)
        self.assertEqual(self.brain.nodes[nid]['meta']['assistant_reply'],assistant)

    def test_manual_then_passive_is_one_primary_and_both_originals_remain(self):
        manual=self.manual();automatic=self.passive();primary=automatic['node_ids'][0]
        self.assertNotEqual(manual,primary);self.assertEqual(len(self.brain.nodes),2)
        self.assertTrue(is_duplicate(self.brain.nodes[manual],self.brain))
        self.assertFalse(is_duplicate(self.brain.nodes[primary],self.brain))
        self.assertEqual(canonical_id(self.brain,manual),primary)
        self.assertEqual(len(canonical_turns(self.brain)),1)
        self.assert_raw_retained(manual);self.assert_raw_retained(primary)
        sources=self.brain.nodes[primary]['meta']['recording_sources']
        self.assertEqual({s['channel'] for s in sources},{'manual','passive'})
        self.assertIn('receipt-host',{s.get('archive_receipt_id') for s in sources})
        self.assertEqual(self.brain.nodes[manual]['meta']['source_ids'],[primary])

    def test_passive_then_manual_preserves_stable_host_primary(self):
        primary=self.passive()['node_ids'][0];manual=self.manual()
        self.assertEqual(canonical_id(self.brain,manual),primary)
        self.assertEqual(len(canonical_turns(self.brain)),1)
        before=deepcopy(self.brain.to_dict())
        self.assertEqual(self.manual(),manual)
        self.assertEqual(self.passive()['node_ids'],[primary])
        self.assertEqual(before,self.brain.to_dict())
        with self.assertRaises(ValidationError):self.manual(assistant='换过的回复')

    def test_history_uses_alias_session_membership_without_double_feeding(self):
        self.manual();self.passive()
        for session in ('window',connected_session_id('conn-a','window')):
            rows=history(self.brain,session)
            self.assertEqual([r['content'] for r in rows],['我喜欢喝茶。','这是真实回复。'])

    def test_cross_window_or_different_reply_is_only_a_review_candidate(self):
        primary=self.passive()['node_ids'][0]
        other=self.manual(window='another-window')
        partial=self.manual(request='summary',assistant='这是摘要，非原回复。')
        self.assertFalse(is_duplicate(self.brain.nodes[other],self.brain))
        self.assertFalse(is_duplicate(self.brain.nodes[partial],self.brain))
        self.assertEqual(len(canonical_turns(self.brain)),3)
        groups=possible_groups(self.brain)
        self.assertEqual(len(groups),1);self.assertEqual(set(groups[0]['node_ids']),{primary,other,partial})

    def test_different_day_does_not_collapse_same_words_or_create_review_noise(self):
        primary=self.passive()['node_ids'][0]
        self.brain.nodes[primary]['created']-=86400
        manual=self.manual()
        self.assertEqual(canonical_id(self.brain,manual),manual)
        self.assertEqual(possible_groups(self.brain),[])

    def test_a_real_repeated_turn_gets_its_own_auto_manual_pair(self):
        a=self.passive('host-1')['node_ids'][0];m1=self.manual('manual-1')
        b=self.passive('host-2')['node_ids'][0];m2=self.manual('manual-2')
        self.assertEqual(canonical_id(self.brain,m1),a);self.assertEqual(canonical_id(self.brain,m2),b)
        self.assertNotEqual(a,b);self.assertEqual(len(canonical_turns(self.brain)),2)

    def test_two_ambiguous_automatic_matches_are_not_arbitrarily_selected(self):
        a=self.passive('host-1')['node_ids'][0];b=self.passive('host-2')['node_ids'][0]
        m=self.manual()
        self.assertEqual(canonical_id(self.brain,m),m)
        self.assertEqual(len(canonical_turns(self.brain)),3)
        self.assertEqual(set(possible_groups(self.brain)[0]['node_ids']),{a,b,m})

    def test_explicit_shared_event_id_can_bridge_a_delayed_same_event_capture(self):
        primary=self.passive('stable-event')['node_ids'][0]
        self.brain.nodes[primary]['created']-=86400
        manual=self.manual(source_event_id='stable-event')
        self.assertEqual(canonical_id(self.brain,manual),primary)
        self.assertEqual(self.brain.nodes[manual]['meta']['dedup_confirmation'],'same_source_event')

    def test_user_confirmed_candidate_keeps_full_source_variants_and_checks_staleness(self):
        primary=self.passive()['node_ids'][0];manual=self.manual(window='unknown',assistant='手动保存的摘要版本')
        group=possible_groups(self.brain)[0]
        stale=deepcopy(group['expected']);self.brain.nodes[manual]['text']='我已经改过这条记录。'
        with self.assertRaises(ValidationError):confirm_duplicate(self.brain,primary,[manual],stale)
        self.brain.nodes[manual]['text']='我喜欢喝茶。'
        expected={nid:recording_version(self.brain.nodes[nid]) for nid in (primary,manual)}
        result=confirm_duplicate(self.brain,primary,[manual],expected)
        self.assertTrue(result['confirmed']);self.assertEqual(result['raw_deleted'],0)
        self.assertTrue(is_duplicate(self.brain.nodes[manual],self.brain))
        self.assert_raw_retained(manual,assistant='手动保存的摘要版本')

    def test_editing_alias_or_primary_invalidates_the_old_collapse_guard(self):
        primary=self.passive()['node_ids'][0];manual=self.manual()
        self.brain.nodes[manual]['text']='用户明确修改过的正文'
        self.assertFalse(is_duplicate(self.brain.nodes[manual],self.brain))
        self.brain.nodes[manual]['text']='我喜欢喝茶。';self.brain.nodes[primary]['meta']['assistant_reply']='另一个新正文'
        self.assertFalse(is_duplicate(self.brain.nodes[manual],self.brain))

    def test_forget_closure_removes_aliases_and_old_event_cannot_revive(self):
        manual=self.manual();primary=self.passive()['node_ids'][0]
        plan=forget_plan(self.brain,primary);self.assertEqual(set(plan['node_ids']),{manual,primary})
        forget(self.brain,plan);self.assertEqual(self.brain.nodes,{})
        with self.assertRaises(ValidationError):self.manual()
        replay=self.passive();self.assertEqual(replay['status'],'forgotten');self.assertEqual(self.brain.nodes,{})

    def test_capacity_loss_has_safe_single_source_fallback_but_tombstone_does_not(self):
        primary=self.passive()['node_ids'][0];manual=self.manual()
        self.brain.remove(primary)
        self.assertEqual(canonical_id(self.brain,manual),manual)
        self.assertEqual(len(canonical_turns(self.brain)),1)
        self.brain.meta['memory_tombstones']={'node_ids':[primary]}
        self.assertTrue(is_duplicate(self.brain.nodes[manual],self.brain))
        self.assertEqual(canonical_turns(self.brain),[])

    def test_reconcile_legacy_metadata_and_roundtrip_are_idempotent(self):
        manual=self.manual();primary=self.passive()['node_ids'][0]
        for node in self.brain.nodes.values():
            for key in tuple(node['meta']):
                if key.startswith(('dedup_','recording_','possible_duplicate')) or key in ('duplicate_of','exclude_for_recall','source_ids'):
                    node['meta'].pop(key)
        self.brain.nodes[manual]['meta']['recorded_by']='harness'
        result=reconcile_recordings(self.brain);self.assertEqual(result['confirmed_aliases'],1)
        before=deepcopy(self.brain.to_dict());reconcile_recordings(self.brain);self.assertEqual(before,self.brain.to_dict())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'brain.json';self.brain.save(path);self.brain=Brain.open(path)
            self.assertEqual(len(canonical_turns(self.brain)),1)
            self.assertTrue(is_duplicate(self.brain.nodes[manual],self.brain))

    def test_duplicate_capture_is_not_two_persona_feedback_turns(self):
        user='我希望你说话温柔一点'
        self.manual(user=user);self.passive(user=user)
        self.assertEqual(persona_state(self.brain)['effective_persona'],'')
        self.assertEqual(persona_state(self.brain)['learned'],{})
        learn_from_dialogue(self.brain);self.assertEqual(persona_state(self.brain)['learned'],{})
        second=self.passive('other-turn',user=user,assistant='另一轮真实回复')
        self.assertTrue(persona_state(self.brain)['learned'])
        self.assertIn('温柔',persona_state(self.brain)['effective_persona'])

    def test_legacy_learned_style_stops_using_two_aliases_as_two_feedback_rounds(self):
        user='我希望你说话温柔一点'
        manual=self.manual(user=user);primary=self.passive(user=user)['node_ids'][0]
        state=persona_state(self.brain);state['enabled']=True
        state['learned']={'tone':{'value':'gentle','evidence_ids':[manual,primary]}}
        self.brain.meta['companion_persona']=state
        self.assertNotIn('温柔',persona_state(self.brain)['effective_persona'])
        other=self.passive('actual-second',user=user,assistant='另一轮回复')['node_ids'][0]
        learned=persona_state(self.brain)['learned']['tone']
        self.assertEqual(set(learned['evidence_ids']),{primary,other})
        self.assertIn('温柔',persona_state(self.brain)['effective_persona'])

    def test_merge_is_reversible_and_reconcile_respects_the_users_separation(self):
        primary=self.passive()['node_ids'][0];manual=self.manual()
        expected={i:recording_version(self.brain.nodes[i]) for i in (primary,manual)}
        result=separate_recordings(self.brain,primary,expected)
        self.assertTrue(result['separated']);self.assertEqual(len(canonical_turns(self.brain)),2)
        reconcile_recordings(self.brain)
        self.assertEqual(len(canonical_turns(self.brain)),2);self.assertEqual(possible_groups(self.brain),[])
        self.assert_raw_retained(manual);self.assert_raw_retained(primary)

    def test_persona_proposal_needs_independent_turns_not_two_source_aliases(self):
        manual=self.manual();primary=self.passive()['node_ids'][0]
        with self.assertRaises(ValidationError):propose_persona(self.brain,'温柔的人格',[manual,primary])

if __name__=='__main__':unittest.main()
