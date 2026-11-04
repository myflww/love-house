"""Continuous memory retention with synthetic data only; no real libraries."""
from copy import deepcopy
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.config import Config
from nkb.errors import ValidationError
from nkb.companion.retention import (MAX_TRACES, adaptive_strength, enable_temporal_retention,
    get_retention_policy, match_mentions, record_memory_use, save_retention_policy)
from nkb.utils import DAY

T0 = 1700000000.0
CLOCK = 'nkb.core.brain._now'


class AdaptiveRetentionTests(unittest.TestCase):
    def brain(self, **kw):
        b = Brain.new(config=Config(**kw))
        enable_temporal_retention(b)
        return b

    def add(self, b, text='我们约定周六一起看海', **kw):
        with patch(CLOCK, return_value=T0):
            return b.add(text, text, kind='episode', **kw)

    def test_policy_read_is_pure_and_migration_is_explicit_without_days(self):
        b = Brain.new(); before = deepcopy(b.to_dict())
        self.assertFalse(get_retention_policy(b)['enabled'])
        self.assertEqual(before, b.to_dict())
        self.assertTrue(enable_temporal_retention(b)['changed'])
        self.assertFalse(enable_temporal_retention(b)['changed'])
        self.assertIsNone(b.config.max_nodes)
        self.assertTrue(b.meta['long_term_archive'])
        for wrong in ({'recent_days':30}, {'recovery_days':200}, {'mode':'expiry'},
                      {'usage_reinforcement':1}, {'forgetting_pace':'unknown'}):
            state = deepcopy(b.to_dict())
            with self.assertRaises(ValidationError):save_retention_policy(b, wrong)
            self.assertEqual(state, b.to_dict())

    def test_none_capacity_roundtrips_and_legacy_explicit_limit_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            b=self.brain();b.path=Path(directory)/'test.json';self.add(b);b.persist()
            reopened=Brain.open(b.path)
            self.assertIsNone(reopened.config.max_nodes)
            self.assertTrue(get_retention_policy(reopened)['enabled'])
        legacy=Brain.new(config=Config(max_nodes=1))
        first=self.add(legacy,'普通旧记录')
        second=self.add(legacy,'兼容数量实验')
        self.assertEqual(set(legacy.nodes),{second});self.assertNotIn(first,legacy.nodes)

    def test_environment_count_cap_cannot_revive_for_adaptive_snapshot(self):
        b=self.brain();self.add(b)
        with patch.dict(os.environ,{'NKB_MAX_NODES':'1'}):
            reopened=Brain(b.to_dict())
            self.assertIsNone(reopened.config.max_nodes)
            self.add(reopened,'不会被环境数量限制挤掉')
            self.assertEqual(len(reopened.nodes),2)
            self.assertEqual(Brain.new().config.max_nodes,1)

    def test_over_ten_thousand_same_day_nodes_do_not_evict_any_record(self):
        b=self.brain();template=self.add(b)
        node=deepcopy(b.nodes.pop(template));vector=b._vec.pop(template)
        for i in range(10001):
            nid='same_day_'+str(i);b.nodes[nid]={**deepcopy(node),'id':nid};b._vec[nid]=vector.copy()
        old_ids=set(b.nodes)
        added=self.add(b,'同一天第一万零二条仍保留')
        self.assertEqual(len(b.nodes),10002)
        self.assertTrue(old_ids<=set(b.nodes));self.assertIn(added,b.nodes)
        self.assertNotIn('capacity_evictions',b.meta)
        view=b.export(as_of=T0+1)
        self.assertIsNone(view['stats']['capacity'])
        self.assertIsNone(view['stats']['capacity_remaining'])

    def test_count_of_other_messages_does_not_reduce_strength(self):
        b=self.brain();target=self.add(b)
        before=adaptive_strength(b,b.nodes[target],T0+DAY)
        template=deepcopy(b.nodes[target])
        for i in range(1000):b.nodes['other_'+str(i)]={**deepcopy(template),'id':'other_'+str(i)}
        self.assertEqual(before,adaptive_strength(b,b.nodes[target],T0+DAY))

    def test_fading_edges_remain_stored_and_read_projection_does_not_double_decay(self):
        b=self.brain();a=self.add(b,'一起看海的真实经历');c=self.add(b,'海边带上热奶茶的约定')
        with patch(CLOCK,return_value=T0):b.link(a,c,.5)
        stored=deepcopy(b.edges)
        b.forget(now=T0+10000*DAY);b.forget(now=T0+10000*DAY)
        self.assertEqual(stored,b.edges)
        self.assertEqual(len(b.nodes),2)

    def test_editing_prose_does_not_double_decay_or_count_as_practice(self):
        for practised in (False,True):
            with self.subTest(practised=practised):
                b=self.brain();nid=self.add(b,salience=.55);node=b.nodes[nid]
                if practised:record_memory_use(b,[nid],now=T0+10*DAY)
                before=deepcopy(node)
                strength=adaptive_strength(b,node,T0+30*DAY)
                with patch(CLOCK,return_value=T0+30*DAY):
                    b.update(nid,text='用户主动修正显示文字',meta=deepcopy(node['meta']))
                self.assertEqual(node['salience'],before['salience'])
                self.assertEqual(node['reinforced'],before['reinforced'])
                self.assertEqual(node['recalls'],before['recalls'])
                self.assertEqual(node['meta'].get('memory_usage'),before['meta'].get('memory_usage'))
                self.assertEqual(adaptive_strength(b,node,T0+30*DAY),strength)

    def test_explicit_new_salience_changes_base_but_preserves_practice(self):
        b=self.brain();nid=self.add(b,salience=.55);node=b.nodes[nid]
        record_memory_use(b,[nid],now=T0+10*DAY)
        usage=deepcopy(node['meta']['memory_usage'])
        score=adaptive_strength(b,node,T0+30*DAY)
        with patch(CLOCK,return_value=T0+30*DAY):
            b.update(nid,salience=.2,meta=deepcopy(node['meta']))
        self.assertEqual(node['salience'],.2)
        self.assertNotIn('base_salience',node['meta']['memory_usage'])
        self.assertNotIn('base_at',node['meta']['memory_usage'])
        self.assertEqual(node['meta']['memory_usage']['traces'],usage['traces'])
        self.assertEqual(node['meta']['memory_usage']['recall_count'],usage['recall_count'])
        self.assertEqual(node['reinforced'],T0+10*DAY)
        self.assertLess(adaptive_strength(b,node,T0+30*DAY),score)

    def test_continuous_decay_has_no_day_or_lifetime_expiry_cliff(self):
        b=self.brain();nid=self.add(b,salience=.55);node=b.nodes[nid]
        self.assertAlmostEqual(adaptive_strength(b,node,T0),.55)
        strengths=[b._node_state(node,T0+d*DAY)['effective_salience'] for d in (0,1,7,30,200,10000)]
        self.assertEqual(strengths,sorted(strengths,reverse=True))
        for days in (1,7,30,200):
            a=adaptive_strength(b,node,T0+days*DAY-1)
            c=adaptive_strength(b,node,T0+days*DAY+1)
            self.assertLess(abs(a-c),.0001)
        state=b._node_state(node,T0+10000*DAY)
        self.assertTrue(state['recoverable']);self.assertFalse(state['forgotten_by_age'])
        recalled=b.recall('我们约定周六一起看海',as_of=T0+10000*DAY)
        self.assertIn(nid,[item['id'] for item in recalled['hits']])
        self.assertIsNone(state['recovery_days_left'])
        before=deepcopy(node)
        self.assertEqual(b.forget(now=T0+10000*DAY)['dropped'],0)
        self.assertIn(nid,b.nodes);self.assertEqual(before,b.nodes[nid])

    def test_real_use_strengthens_old_memory_and_is_daily_retry_safe(self):
        b=self.brain();nid=self.add(b,salience=.55);when=T0+365*DAY
        before=adaptive_strength(b,b.nodes[nid],when)
        self.assertEqual(record_memory_use(b,[nid],now=when)['nodes'],1)
        after=adaptive_strength(b,b.nodes[nid],when)
        self.assertGreater(after,before)
        state=deepcopy(b.to_dict())
        self.assertEqual(record_memory_use(b,[nid],now=when)['nodes'],0)
        self.assertEqual(record_memory_use(b,[nid],now=when+60)['nodes'],0)
        self.assertEqual(state,b.to_dict())
        self.assertFalse(b.edges)

    def test_future_practice_never_changes_earlier_strength(self):
        b=self.brain();nid=self.add(b,salience=.1);node=b.nodes[nid]
        before=adaptive_strength(b,node,T0+DAY)
        record_memory_use(b,[nid],now=T0+100*DAY)
        self.assertEqual(before,adaptive_strength(b,node,T0+DAY))
        self.assertGreater(adaptive_strength(b,node,T0+100*DAY),before)

    def test_spacing_frequency_and_compressed_trace_keep_contributing(self):
        b=self.brain();nid=self.add(b);node=b.nodes[nid]
        for day in range(1,40):record_memory_use(b,[nid],now=T0+day*DAY)
        usage=node['meta']['memory_usage']
        self.assertEqual(usage['recall_count'],39)
        self.assertLessEqual(len(usage['traces']),MAX_TRACES)
        self.assertGreater(usage['older']['weight'],0)
        full=adaptive_strength(b,node,T0+45*DAY)
        without=deepcopy(node);without['meta']['memory_usage'].pop('older')
        self.assertGreater(full,adaptive_strength(b,without,T0+45*DAY))
        # Later spaced practice gets a larger bounded trace than massed practice.
        other=self.brain();sparse=self.add(other)
        record_memory_use(other,[sparse],now=T0+7*DAY)
        self.assertGreater(other.nodes[sparse]['meta']['memory_usage']['traces'][0]['weight'],
                           usage['traces'][-1]['weight'])

    def test_older_delivery_never_moves_clocks_backwards(self):
        b=self.brain();nid=self.add(b)
        record_memory_use(b,[nid],now=T0+10*DAY)
        record_memory_use(b,[nid],kind='mention',now=T0+3*DAY)
        self.assertEqual(b.nodes[nid]['reinforced'],T0+10*DAY)
        self.assertEqual(b.nodes[nid]['decay_at'],T0+10*DAY)
        self.assertEqual(record_memory_use(b,[nid],kind='mention',now=T0+3*DAY)['nodes'],0)

    def test_invalid_future_disabled_superseded_and_forgotten_never_revive(self):
        b=self.brain()
        disabled=self.add(b,'停用的旧内容',meta={'memory_disabled':True})
        expired=self.add(b,'已经过期的资料');b.nodes[expired]['valid_to']=T0+DAY
        future=self.add(b,'未来事件资料',event_at=T0+100*DAY)
        forgotten=self.add(b,'明确忘记资料',meta={'forgotten':True})
        valid=self.add(b,'有效但已更正资料');b.nodes[valid]['superseded_by']='correction'
        ids=[disabled,expired,future,forgotten,valid]
        before=deepcopy(b.to_dict())
        self.assertEqual(record_memory_use(b,ids,now=T0+2*DAY)['nodes'],0)
        self.assertEqual(before,b.to_dict())

    def test_explicit_important_and_open_commitments_stay_protected(self):
        b=self.brain();important=self.add(b,meta={'important':True})
        with patch(CLOCK,return_value=T0):promise=b.commit('尚未完成的约定','未来要一起看海')
        for nid in (important,promise):
            state=b._node_state(b.nodes[nid],T0+10000*DAY)
            self.assertTrue(state['protected']);self.assertGreaterEqual(state['effective_salience'],.65)

    def test_reads_and_disabled_usage_do_not_change_memory(self):
        b=self.brain();nid=self.add(b);before=deepcopy(b.to_dict())
        b.export(as_of=T0+DAY);b.recall('周六一起看海',as_of=T0+DAY)
        get_retention_policy(b)
        self.assertEqual(before,b.to_dict())
        save_retention_policy(b,{'usage_reinforcement':False});before=deepcopy(b.to_dict())
        self.assertEqual(record_memory_use(b,[nid],now=T0+DAY)['nodes'],0)
        self.assertEqual(before,b.to_dict())

    def test_opt_out_boundary_ignores_pre_toggle_evidence_after_reenable(self):
        b=self.brain();nid=self.add(b)
        with patch('nkb.companion.retention._now',return_value=T0+10*DAY):
            save_retention_policy(b,{'usage_reinforcement':False})
        with patch('nkb.companion.retention._now',return_value=T0+12*DAY):
            save_retention_policy(b,{'usage_reinforcement':True})
        cutoff=b.meta['memory_usage_cutoff']
        self.assertEqual(record_memory_use(b,[nid],now=T0+DAY)['nodes'],0)
        self.assertNotIn('memory_usage',b.nodes[nid]['meta'])
        self.assertEqual(record_memory_use(b,[nid],now=T0+13*DAY)['nodes'],1)
        # An ordinary write/migration cannot move this opt-out boundary.
        enable_temporal_retention(b)
        self.assertEqual(b.meta['memory_usage_cutoff'],cutoff)
        with self.assertRaises(ValidationError):save_retention_policy(b,{'memory_usage_cutoff':0})

    def test_lexical_mentions_are_scoped_old_evidence_not_injected_material(self):
        b=self.brain();nid=self.add(b,session_id='one',meta={'source':'conversation_turn','assistant_reply':'好'})
        hits=match_mentions(b,'你还记得我们约定周六一起看海吗？','one',now=T0+DAY)
        self.assertEqual([x['id'] for x in hits],[nid])
        b.nodes[nid]['label']='对话 · 我们约定周六一起看海'
        self.assertEqual(match_mentions(b,'我们约定周六一起看海','other',now=T0+DAY),[])
        self.assertEqual([x['id'] for x in match_mentions(b,'我们约定周六一起看海',None,now=T0+DAY)],[nid])
        self.assertEqual(match_mentions(b,'<memory_material>我们约定周六一起看海','one',now=T0+DAY),[])
        self.assertEqual(match_mentions(b,'```\n我们约定周六一起看海\n```','one',now=T0+DAY),[])


if __name__ == '__main__': unittest.main()
