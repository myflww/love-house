"""Natural query and cached-read acceptance using synthetic in-memory graphs."""
from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.errors import ValidationError
from nkb.organizer.state import prepare_recall, semantic_recall
from nkb.retrieval.query import plan_query
from nkb.retrieval.scoring import OverlapScorer


class QueryRecallTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new()
        self.brain.meta.update(library_id='synthetic-one', long_term_archive=True)
        self.ref = datetime(2026, 11, 4, 12).timestamp()

    def add(self, text, *, when=None, **fields):
        with patch('nkb.core.brain._now', return_value=self.ref - 1):
            return self.brain.add(text, text, event_at=when, **fields)

    def recall(self, query, **kwargs):
        return semantic_recall(self.brain, query, as_of=self.ref, **kwargs)

    def test_explicit_and_relative_dates_select_real_source_time_not_import_date(self):
        yesterday = datetime(2026, 11, 3, 14).timestamp()
        previous = datetime(2026, 11, 2, 14).timestamp()
        wanted = self.add('咖啡研讨会有蓝莓茶', when=yesterday)
        older = self.add('咖啡研讨会有橘子茶', when=previous)
        unknown = self.add('咖啡研讨会日期不知道', when=yesterday, meta={'source_time_unknown': True})
        implicit = self.add('咖啡研讨会只有录入时间')
        for query in ('2026年11月3日咖啡研讨会', '2026-11-03咖啡研讨会', '昨天咖啡研讨会'):
            result = self.recall(query)
            self.assertEqual([row['id'] for row in result['hits']], [wanted])
            self.assertFalse({older, unknown, implicit} & {row['id'] for row in result['hits']})
            self.assertIn('event_time_range', result['query_understanding'])

    def test_calendar_boundary_and_last_week_are_deterministic_local_days(self):
        for text in ('昨天', '2026-11-03'):
            plan = plan_query(text + '约定', self.ref)
            self.assertEqual(datetime.fromtimestamp(plan.start), datetime(2026, 11, 3))
            self.assertEqual(datetime.fromtimestamp(plan.end), datetime(2026, 11, 4))
        plan = plan_query('上周画作讨论', self.ref)
        self.assertEqual(datetime.fromtimestamp(plan.start), datetime(2026, 10, 26))
        self.assertEqual(datetime.fromtimestamp(plan.end), datetime(2026, 11, 2))

    def test_organized_memory_uses_evidence_event_time_instead_of_organization_time(self):
        yesterday = datetime(2026, 11, 3, 14).timestamp()
        wanted = self.add('咖啡研讨会真实摘要', kind='fact', meta={'source':'organizer',
            'source_time_unknown':False, 'memory_atom':{'event_at':yesterday}})
        result = self.recall('昨天咖啡研讨会')
        self.assertIn(wanted, [row['id'] for row in result['hits']])

    def test_invalid_date_and_unresolved_pronoun_do_not_guess_a_memory(self):
        self.add('那个事情的上次约定已经记录', kind='fact')
        for query, reason in (('2026-02-30约定', 'invalid_calendar_date'), ('还记得上次那个事情吗', 'missing_topic')):
            result = self.recall(query)
            self.assertEqual(result['hits'], [])
            self.assertTrue(result['query_understanding']['needs_clarification'] or reason == 'invalid_calendar_date')
            self.assertEqual(result['query_understanding']['reason'], reason)
        self.assertEqual(self.recall('上回那个怎么样了')['hits'], [])
        self.assertTrue(self.recall('上回那个怎么样了')['query_understanding']['needs_clarification'])

    def test_recent_and_historical_bias_never_recover_expired_or_disabled_facts(self):
        old = self.add('蓝莓咖啡喜好', when=self.ref - 40 * 86400, kind='fact')
        latest = self.add('蓝莓咖啡喜好', when=self.ref - 100, kind='fact')
        self.assertEqual(self.recall('最近蓝莓咖啡喜好')['hits'][0]['id'], latest)
        self.assertEqual(self.recall('以前蓝莓咖啡喜好')['hits'][0]['id'], old)
        self.brain.nodes[old]['meta']['memory_disabled'] = True
        self.assertNotIn(old, [row['id'] for row in self.recall('以前蓝莓咖啡喜好', include_expired=True)['hits']])
        self.brain.nodes[latest]['valid_to'] = self.ref - 10
        self.assertEqual(self.recall('现在蓝莓咖啡喜好')['hits'], [])

    def test_unfinished_intent_selects_only_explicit_open_commitments(self):
        open_id = self.add('承诺完成航海画作', kind='commitment', meta={'status': 'open'})
        self.add('承诺完成航海画作', kind='commitment', meta={'status': 'done'})
        self.add('航海画作未完成的猜测', kind='fact')
        result = self.recall('上次还没完成的约定')
        self.assertEqual([row['id'] for row in result['hits']], [open_id])
        self.assertTrue(result['query_understanding']['unfinished_only'])

    def test_best_alias_evidence_wins_even_when_inserted_after_four_weak_matches(self):
        for i in range(4):
            self.add('不相关资料'+str(i), kind='fact', meta={'source':'organizer', 'organizer_aliases':['安家地标']})
        wanted = self.add('居住在合成小镇', kind='fact', meta={'source':'organizer', 'organizer_aliases':['安家地点']})
        result = self.recall('请说说安家地点')
        self.assertEqual(result['semantic_expansions'][0]['memory_id'], wanted)
        self.assertIn(wanted, [row['id'] for row in result['hits']])

    def test_auditable_synonym_group_uses_only_existing_alias_evidence(self):
        home = self.add('用户确认住在合成蓝莓镇', kind='fact',
                        meta={'source': 'organizer', 'organizer_aliases': ['居住地点']})
        result = self.recall('我家在哪儿')
        self.assertIn(home, [row['id'] for row in result['hits']])
        self.assertEqual(result['semantic_expansions'][0]['terms'], ['居住地点'])
        self.assertFalse(result['query_understanding']['inferred_facts'])
        self.brain.remove(home)
        self.assertEqual(self.recall('我家在哪儿')['hits'], [])

    def test_shared_preparation_reuses_only_unchanged_encoding_and_rechecks_live_scope(self):
        wanted = self.add('合成松果偏好', kind='fact')
        self.add('合成其他偏好', kind='fact')
        prepared = prepare_recall(self.brain)
        before = deepcopy(self.brain.to_dict())
        with patch.object(self.brain, '_vec_for', wraps=self.brain._vec_for) as encode:
            self.recall('松果偏好', prepared=prepared)
            self.assertEqual(encode.call_count, 0)
            self.recall('松果偏好', prepared=prepared)
            self.assertEqual(encode.call_count, 0)
            self.brain.nodes[wanted]['text'] = '合成新松果偏好'
            self.recall('新松果', prepared=prepared)
            self.assertEqual(encode.call_count, 1)
        self.brain.nodes[wanted]['text'] = before['nodes'][wanted]['text']
        self.assertEqual(before, self.brain.to_dict())
        self.brain.nodes[wanted]['meta']['library_id'] = 'synthetic-two'
        self.assertNotIn(wanted, [row['id'] for row in self.recall('松果', prepared=prepared)['hits']])
        self.brain.nodes[wanted]['meta'].pop('library_id')
        self.brain.nodes[wanted]['meta']['memory_disabled'] = True
        self.assertNotIn(wanted, [row['id'] for row in self.recall('松果', prepared=prepared, include_expired=True)['hits']])
        self.brain.remove(wanted)
        self.assertNotIn(wanted, self.brain._semantic_vectors['entries'])
        self.assertNotIn(wanted, [row['id'] for row in self.recall('松果', prepared=prepared)['hits']])

    def test_tombstone_and_wrong_brain_cannot_be_bypassed_with_prepared_object(self):
        wanted = self.add('合成私密松果', kind='fact')
        prepared = prepare_recall(self.brain)
        self.recall('松果', prepared=prepared)
        self.brain.meta['memory_tombstones'] = {'node_ids': [wanted]}
        self.assertEqual(self.recall('松果', prepared=prepared)['hits'], [])
        with self.assertRaises(ValidationError):
            semantic_recall(Brain.new(), '松果', prepared=prepared)
        with self.assertRaises(ValidationError):
            self.recall('松果', candidate_ids='bad-shape')

    def test_encoder_change_invalidates_reused_preparation(self):
        wanted = self.add('Synthetic Blueberry', kind='fact')
        prepared = prepare_recall(self.brain)
        self.recall('Synthetic', prepared=prepared)
        calls = []
        def changed_encoder(text):
            calls.append(text)
            return set(text.casefold().split())
        self.brain.encoder = changed_encoder
        result = self.recall('blueberry', prepared=prepared)
        self.assertIn(wanted, [row['id'] for row in result['hits']])
        self.assertTrue(any('Synthetic Blueberry' in text for text in calls))

    def test_comparing_past_and_present_does_not_apply_oldest_only_bias(self):
        self.assertEqual(plan_query('以前和现在的蓝莓口味', self.ref).intent, 'comparison')

    def test_same_question_finds_explicit_correction_without_sending_old_claim(self):
        from nkb.service.controls import correct
        from nkb.companion.memory import build_context
        old = self.add('咖啡偏好', kind='fact', when=self.ref - 30)
        # Management writes use the real clock; query after the new revision.
        result = correct(self.brain, old, '现在改喝茶')
        replacement = result['id']
        context = build_context(self.brain, '咖啡偏好', library_id='synthetic-one')
        self.assertIn(replacement, context['memory_ids'])
        self.assertNotIn(old, context['memory_ids'])
        related = next(row for row in context['hits'] if row['id'] == replacement)
        self.assertEqual(related['text'], '现在改喝茶')
        prepared = prepare_recall(self.brain)
        semantic_recall(self.brain, '咖啡偏好', prepared=prepared)
        self.brain.nodes[old]['meta']['forgotten'] = True
        self.assertNotIn(replacement, [row['id'] for row in semantic_recall(self.brain, '咖啡偏好', prepared=prepared)['hits']])

    def test_forged_or_foreign_correction_relation_cannot_supply_query_anchor(self):
        old = self.add('合成秘密咖啡偏好', kind='fact')
        replacement = self.add('改喝茶', kind='fact', meta={'source':'user_confirmed', 'confirmed':True,
                                                        'speaker':'user', 'corrects':old})
        self.assertEqual(self.recall('咖啡偏好')['hits'][0]['id'], old)
        self.brain.nodes[old]['superseded_by'] = replacement
        self.brain.nodes[old]['meta']['library_id'] = 'synthetic-two'
        self.assertEqual(self.recall('咖啡偏好')['hits'], [])

    def test_candidate_lane_preserves_full_graph_lifecycle_checks_and_custom_scorer_contract(self):
        source = self.add('旧事实', kind='fact')
        reflection = self.add('合成反思松果', kind='reflection', meta={'members':[source]})
        self.brain.nodes[source]['valid_to'] = self.ref - 10
        self.brain.nodes[source]['superseded_by'] = 'synthetic-replacement'
        self.assertEqual(self.brain.recall('松果', candidate_ids={reflection}, as_of=self.ref)['hits'], [])
        seen = []
        class Custom(OverlapScorer):
            def __call__(inner, nodes, *args):
                seen.append(set(nodes))
                return super().__call__(nodes, *args)
        self.brain.scorer = Custom()
        self.brain.recall('松果', candidate_ids={reflection}, as_of=self.ref)
        self.assertEqual(seen[-1], set(self.brain.nodes))


if __name__ == '__main__':
    unittest.main()
