"""Recent platform dialogue survives semantic competition and the JSON budget.

Only synthetic in-memory Brains are used; there is no model or credential access.
"""
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.dedup import confirm_duplicate, recording_version
from nkb.companion.memory import build_context, record_turn, remember
from nkb.companion.structured import build_structured_context
from nkb.errors import ValidationError
from nkb.organizer import semantic_recall


QUERY = '我们刚才在 QQ 最后确认的中性暗号是什么'
SOURCE_QQ = 'source_'+'a'*32
SOURCE_WEB = 'source_'+'b'*32


class PlatformRecentRecallTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new(name='合成测试鱼')
        self.brain.meta.update(library_id='fish-a', long_term_archive=True)
        self.stamp = time.time()

    def turn(self, event, user='换暗号', assistant='新的中性暗号是蓝莓抱枕7629。', *,
             platform='qq', ago=20, source=SOURCE_QQ, library='fish-a'):
        at = self.stamp-ago
        nid = record_turn(self.brain, user, assistant, platform+'-session', event, event_at=at)
        self.brain.get(nid)['meta'].update(library_id=library, evidence={
            'platform': platform, 'source_id': source, 'source_event_at': at,
            'participant_scope': 'external_participant', 'participant_id': 'synthetic-qq-peer'})
        return nid

    def build(self, query=QUERY, *, budget=6000, base=None):
        if base is None:
            base = build_context(self.brain, query, max_chars=budget)
        return build_structured_context(self.brain, query, base, max_chars=budget, library_id='fish-a')

    def test_realistic_short_qq_update_beats_old_long_refusals_and_later_webchat_retelling(self):
        old_user = 'QQ 最后确认的中性暗号约定是什么？'*80
        for i in range(3):
            self.turn('old-'+str(i), old_user, '旧约定中拒绝更改，继续用旧值。'*250, ago=100-i)
        latest = self.turn('new-short', ago=90)
        for i in range(8):
            self.turn('retelling-'+str(i), old_user, '网页正在复述以前的旧暗号约定。'*140,
                      platform='webchat', source=SOURCE_WEB, ago=10-i)
        # The regression starts with an actual semantic miss, not a mocked rank.
        semantic = semantic_recall(self.brain, QUERY, k=8)
        self.assertNotIn(latest, [h['id'] for h in semantic['hits']])
        before = deepcopy(self.brain.to_dict())
        base = build_context(self.brain, QUERY, max_chars=6000)
        self.assertIn(latest, base['platform_recent_ids'])
        result = self.build(base=base)
        self.assertEqual(result['memory_context']['records'][0]['id'], latest)
        self.assertIn(latest, result['platform_recent_ids'])
        self.assertEqual(result['memory_ids'].count(latest), 1)
        self.assertLessEqual(len(result['packet']), 6000)
        self.assertEqual(json.loads(result['packet']), result['memory_context'])
        record = next(r for r in result['memory_context']['records'] if r['id'] == latest)
        node = self.brain.get(latest)
        self.assertEqual(record['value'], node['text'])
        self.assertEqual(record['assistant_statement']['value'], node['meta']['assistant_reply'])
        self.assertFalse(record['assistant_statement']['is_user_fact'])
        self.assertEqual(record['epistemic_status'], 'historical_participant_statement')
        self.assertEqual(record['subject'], 'platform_participant')
        self.assertEqual(record['source_time'], node['event_at'])
        self.assertEqual(record['source']['evidence'][0]['platform'], 'qq')
        self.assertEqual(record['source']['evidence'][0]['source_id'], SOURCE_QQ)
        self.assertEqual(before, self.brain.to_dict())

    def test_two_whole_latest_turns_have_budget_priority_and_no_duplicate_semantic_ids(self):
        first = self.turn('first', '我想换一个中性暗号。', '可以，先确认新值。', ago=50)
        second = self.turn('second', ago=40)
        for i in range(4):
            remember(self.brain, ('用户明确记住的其他重要偏好'+str(i)+'。')*35)
        base = build_context(self.brain, QUERY, max_chars=6000)
        self.assertEqual(base['platform_recent_ids'], [second, first])
        result = self.build(base=base)
        self.assertEqual(result['platform_recent_ids'], [second, first])
        self.assertEqual(result['memory_ids'][:2], [second, first])
        self.assertEqual(len(result['memory_ids']), len(set(result['memory_ids'])))
        for record in result['memory_context']['records'][:2]:
            self.assertEqual(record['value'], self.brain.get(record['id'])['text'])
            self.assertEqual(record['assistant_statement']['value'], self.brain.get(record['id'])['meta']['assistant_reply'])

    def test_foreign_disabled_expired_future_and_confirmed_alias_cannot_be_recent(self):
        valid = self.turn('valid', ago=100)
        alias = self.turn('alias', ago=5)
        confirm_duplicate(self.brain, valid, [alias], {n: recording_version(self.brain.get(n)) for n in (valid, alias)})
        foreign = self.turn('foreign', assistant='另一条鱼的唯一暗号。', ago=4, library='fish-b')
        disabled = self.turn('disabled', assistant='已停用的唯一暗号。', ago=3)
        self.brain.get(disabled)['meta']['memory_disabled'] = True
        expired = self.turn('expired', assistant='已失效的唯一暗号。', ago=2)
        self.brain.get(expired)['valid_to'] = self.stamp-1
        future = self.turn('future', assistant='未来的唯一暗号。', ago=-3600)
        result = self.build()
        self.assertEqual(result['platform_recent_ids'], [valid])
        for nid in (alias, foreign, disabled, expired, future):
            self.assertNotIn(nid, result['memory_ids'])
        for text in ('另一条鱼的唯一暗号', '已停用的唯一暗号', '已失效的唯一暗号', '未来的唯一暗号'):
            self.assertNotIn(text, result['packet'])

    def test_unknown_or_inconsistent_event_time_and_unregistered_labels_never_claim_recency(self):
        valid = self.turn('valid', ago=100)
        unknown = self.turn('unknown', assistant='未知发生时间的记录。', ago=5)
        self.brain.get(unknown)['meta']['evidence']['source_time_unknown'] = True
        inconsistent = self.turn('inconsistent', assistant='时间不一致的记录。', ago=4)
        self.brain.get(inconsistent)['meta']['evidence']['source_event_at'] += 1
        unregistered = self.turn('unregistered', assistant='未登记的来源。', ago=3, source='ordinary-label')
        base = build_context(self.brain, QUERY, max_chars=6000)
        self.assertEqual(base['platform_recent_ids'], [valid])
        self.assertNotIn(unknown, base['platform_recent_ids'])
        self.assertNotIn(inconsistent, base['platform_recent_ids'])
        self.assertNotIn(unregistered, base['platform_recent_ids'])

    def test_no_platform_or_explicit_historical_queries_keep_original_semantic_selection(self):
        old = self.turn('old', '以前的约定。', '旧值。', ago=100)
        self.turn('new', ago=10)
        for query in ('QQ 的中性暗号是什么', '我们刚才最后确认的中性暗号是什么',
                      '昨天在 QQ 最后确认的暗号是什么', '以前 QQ 最后确认的约定是什么',
                      'QQ latest agreement from last week'):
            with self.subTest(query=query):
                recalled = {'hits': [{'id': old, 'score': .8}], 'trail': []}
                with patch('nkb.organizer.semantic_recall', return_value=recalled) as recall:
                    base = build_context(self.brain, query, max_chars=6000)
                recall.assert_called_once_with(self.brain, query, k=8)
                self.assertEqual(base['platform_recent_ids'], [])
                self.assertEqual(base['memory_ids'], [old])

    def test_platform_match_is_case_insensitive_but_not_a_partial_platform_name(self):
        latest = self.turn('latest')
        for query in ('qQ 最新确认的暗号是什么', 'latest QQ agreement'):
            self.assertEqual(build_context(self.brain, query)['platform_recent_ids'], [latest])
        self.assertEqual(build_context(self.brain, 'QQMusic 最近确认的暗号')['platform_recent_ids'], [])

    def test_source_reference_labels_are_typed_bounded_and_taken_from_actual_source(self):
        source = self.turn('actual')
        organized = self.brain.add('整理摘录', '换暗号', kind='fact', meta={'source': 'organizer',
            'organizer_evidence': [{'id': source, 'role': 'user', 'platform': 'forged', 'source_id': 'forged'}]})
        base = {'memory_ids': [organized], 'packet': '', 'messages': [], 'truncated': False}
        ref = self.build('暗号', base=base)['memory_context']['records'][0]['source']['evidence'][0]
        self.assertEqual((ref['platform'], ref['source_id']), ('qq', SOURCE_QQ))
        for invalid in ({'platform': 'x'*65}, {'platform': {'bad': 'qq'}}, {'source_id': 'x'*201}, {'source_id': True}):
            with self.subTest(invalid=invalid):
                evidence = self.brain.get(source)['meta']['evidence']
                saved = dict(evidence)
                evidence.update(invalid)
                ref = self.build('暗号', base=base)['memory_context']['records'][0]['source']['evidence'][0]
                self.assertNotIn(next(iter(invalid)), ref)
                self.brain.get(source)['meta']['evidence'] = saved

    def test_stale_or_forged_recent_declaration_is_rechecked_and_oversized_turn_is_omitted_whole(self):
        latest = self.turn('latest')
        base = build_context(self.brain, QUERY, max_chars=6000)
        self.brain.get(latest)['meta']['memory_disabled'] = True
        self.assertEqual(self.build(base=base)['platform_recent_ids'], [])
        self.brain.get(latest)['meta']['memory_disabled'] = False
        for invalid in ('not-a-list', ['x']*3, [None]):
            with self.assertRaises(ValidationError):
                self.build(base={**base, 'platform_recent_ids': invalid})
        huge = self.turn('huge', '全值用户陈述。'*1500, '完整助手陈述。'*1500, ago=1)
        result = self.build()
        self.assertNotIn(huge, result['memory_ids'])
        self.assertNotIn('全值用户陈述', result['packet'])
        self.assertIn(latest, result['memory_ids'])
        self.assertTrue(result['truncated'])


if __name__ == '__main__':
    unittest.main()
