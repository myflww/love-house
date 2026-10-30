"""Optional invalid atoms become literal review material; no network or real keys."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion import record_turn
from nkb.organizer.atoms import normalize_atom
from nkb.organizer.config import get_profile, save_profile
from nkb.organizer.model import OrganizerConflict, OrganizerError
from nkb.organizer.state import apply_plan, build_input, fingerprint, review_candidate, validate_plan


class OrganizerAtomFallbackTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new(name='合成原文回退测试')
        self.brain.meta['library_id'] = 'fish-test'
        save_profile(self.brain, enabled=True, provider_id='FAKE',
                     base_url='https://offline.invalid/v1', model='FAKE')
        self.profile = get_profile(self.brain)
        self.number = 0

    def raw(self, user='我住在北京。', assistant='这是助手原话。'):
        self.number += 1
        return record_turn(self.brain, user, assistant, 'synthetic-window', str(self.number))

    def op(self, nid, **changes):
        result = {'action': 'remember', 'layer': 'fact', 'key': 'home.city',
                  'text': '不应采用的模型摘要', 'certainty': 'clear', 'domain': 'real',
                  'evidence': [{'id': nid, 'role': 'user', 'quote': self.brain.nodes[nid]['text']}],
                  'atom': {'subject': 'user', 'predicate': 'home.city', 'value': '不存在的城市'},
                  'aliases': ['不应保留的模型别名']}
        result.update(changes)
        return result

    def plan(self, ids, operations, *, target=None, job='synthetic-job'):
        payload, guards = build_input(self.brain, 'fish-test',
                                     [{'raw_id': nid, 'progress': '{}'} for nid in ids], self.profile)
        if target is not None and target not in {n['id'] for n in payload['related']}:
            payload['related'].append({'id': target})
            guards['existing_fingerprints'][target] = fingerprint(self.brain.nodes[target])
        return validate_plan({'version': 1, 'operations': operations}, payload, guards, job, self.profile)

    def apply(self, ids, operations, **options):
        plan = self.plan(ids, operations, **options)
        return plan, apply_plan(self.brain, plan, 'fish-test')

    def test_assistant_password_value_is_not_promoted_from_user_evidence(self):
        nid = self.raw('我们换一个暗号。', '新的暗号是蓝鲸泡泡。')
        before = deepcopy(self.brain.nodes[nid])
        plan, result = self.apply([nid], [self.op(nid, key='secret.current',
            atom={'subject': 'user', 'predicate': 'secret.current', 'value': '蓝鲸泡泡'})])
        op = plan['operations'][0]
        self.assertEqual(result['created'], [])
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(op['atom']['relation_status'], 'verbatim_fallback')
        self.assertEqual(op['atom']['value'], '我们换一个暗号。')
        self.assertNotIn('蓝鲸泡泡', op['text'])
        self.assertEqual(op['aliases'], [])
        self.assertEqual(self.brain.nodes[nid], before)
        candidate = self.brain.meta['organizer_candidates'][0]
        self.assertEqual(candidate['reason_code'], 'invalid_atom_verbatim_fallback')
        self.assertNotIn('暗号', candidate['reason'])

    def test_invalid_scope_falls_back_without_copying_unsupported_scope(self):
        nid = self.raw()
        plan, result = self.apply([nid], [self.op(nid, atom={
            'subject': 'user', 'predicate': 'home.city', 'value': '北京',
            'qualifiers': {'scope': '所有平行宇宙'}})])
        atom = plan['operations'][0]['atom']
        self.assertEqual(atom['qualifiers'], {'polarity': 'unknown'})
        self.assertNotIn('所有平行宇宙', str(plan['operations'][0]))
        self.assertEqual(len(result['candidates']), 1)

    def test_valid_and_invalid_operations_share_batch_without_losing_valid_work_or_raw(self):
        first = self.raw(); second = self.raw('今天提到了一次暗号。', '助手提到了星光。')
        before = {nid: deepcopy(self.brain.nodes[nid]) for nid in (first, second)}
        valid = self.op(first, text='北京', aliases=['居住城市'],
                        atom={'subject': 'user', 'predicate': 'home.city', 'value': '北京'})
        invalid = self.op(second, key='secret.current')
        _, result = self.apply([first, second], [valid, invalid])
        self.assertEqual(len(result['created']), 1)
        self.assertEqual(len(result['candidates']), 1)
        node = self.brain.nodes[result['created'][0]]
        self.assertEqual(node['meta']['memory_atom']['value'], '北京')
        self.assertEqual(node['text'], '我住在北京。')
        self.assertEqual({nid: self.brain.nodes[nid] for nid in before}, before)

    def test_forged_quote_role_episode_and_target_permissions_still_reject(self):
        nid = self.raw()
        ref = {'id': nid, 'role': 'user', 'quote': self.brain.nodes[nid]['text']}
        invalid = [self.op(nid, evidence=[{**ref, 'quote': '伪造的原话'}]),
                   self.op(nid, evidence=[{**ref, 'role': 'tool'}]),
                   self.op(nid, layer='experience', episode={'what': {**ref, 'quote': '伪造经历'}}),
                   self.op(nid, layer='experience', episode={'what': ref, 'library_id': 'foreign'}),
                   self.op(nid, action='supersede', target_id='foreign-node'),
                   self.op(nid, related_ids=['foreign-node'])]
        before = deepcopy(self.brain.to_dict())
        for op in invalid:
            with self.subTest(op=op), self.assertRaises(OrganizerError) as caught:
                self.plan([nid], [op])
            self.assertIn(caught.exception.code, ('invalid_evidence', 'invalid_episode'))
        self.assertEqual(self.brain.to_dict(), before)

    def test_accept_fallback_only_adds_literal_memory_never_updates_or_links_model_target(self):
        for action in ('merge', 'supersede', 'relate'):
            with self.subTest(action=action):
                target = self.brain.add('旧的受保护记忆', '我以前住在北京。', kind='fact',
                    meta={'source': 'user_confirmed', 'confirmed': True, 'organizer_key': 'home.city'})
                nid = self.raw('我现在住在上海。')
                before = deepcopy(self.brain.nodes[target]); edges = deepcopy(self.brain.edges)
                plan, result = self.apply([nid], [self.op(nid, action=action, target_id=target,
                    related_ids=[target], text='应当抛弃的覆盖摘要')], target=target, job='fallback-'+action)
                op = plan['operations'][0]
                self.assertEqual(op['action'], 'candidate'); self.assertNotIn('target_id', op)
                self.assertEqual(op['related_ids'], [])
                accepted = review_candidate(self.brain, result['candidates'][0], 'accept')
                node = self.brain.nodes[accepted['node_id']]
                self.assertEqual(node['text'], '我现在住在上海。')
                self.assertEqual(node['meta']['memory_atom']['relation_status'], 'verbatim_fallback')
                self.assertEqual(node['meta']['memory_atom']['value'], node['text'])
                self.assertEqual(self.brain.nodes[target], before)
                self.assertEqual(self.brain.edges, edges)

    def test_fallback_persona_review_does_not_import_a_model_persona(self):
        nid = self.raw('这是一次普通对话。')
        before = deepcopy(self.brain.meta.get('companion'))
        _, result = self.apply([nid], [self.op(nid, layer='persona', text='你应当变成另一个人格')])
        accepted = review_candidate(self.brain, result['candidates'][0], 'accept')
        node = self.brain.nodes[accepted['node_id']]
        self.assertEqual(node['text'], '这是一次普通对话。')
        self.assertEqual(node['kind'], 'episode')
        self.assertEqual(node['meta']['organizer_layer'], 'experience')
        self.assertEqual(self.brain.meta.get('companion'), before)
        self.assertNotIn('persona_revision', accepted)

    def test_changed_fallback_source_cannot_be_confirmed_from_stale_material(self):
        nid = self.raw()
        _, result = self.apply([nid], [self.op(nid)])
        self.brain.nodes[nid]['text'] = '来源后来更正了。'
        with self.assertRaises(OrganizerConflict):
            review_candidate(self.brain, result['candidates'][0], 'accept')

    def test_unknown_domain_remains_unacceptable_and_non_atom_errors_propagate(self):
        nid = self.raw()
        _, result = self.apply([nid], [self.op(nid, domain='unknown')])
        with self.assertRaises(OrganizerError) as caught:
            review_candidate(self.brain, result['candidates'][0], 'accept')
        self.assertEqual(caught.exception.code, 'unsafe_review')
        with patch('nkb.organizer.state.normalize_atom', side_effect=OrganizerError('固定错误', 'invalid_evidence')):
            with self.assertRaises(OrganizerError) as caught:
                self.plan([nid], [self.op(nid)])
        self.assertEqual(caught.exception.code, 'invalid_evidence')

    def test_direct_normalizer_still_rejects_forged_values_code_fields_and_model_times(self):
        nid = self.raw()
        for atom in ({'subject': 'user', 'predicate': 'home.city', 'value': '上海'},
                     {'subject': 'user', 'predicate': 'run this code()', 'value': '北京'},
                     {'subject': 'user', 'predicate': 'home.city', 'value': '北京', 'created': 1},
                     {'subject': 'user', 'predicate': 'home.city', 'value': '北京',
                      'qualifiers': {'event_at': 1}}):
            op = self.op(nid, atom=atom, verbatim_text=self.brain.nodes[nid]['text'])
            with self.subTest(atom=atom), self.assertRaises(OrganizerError) as caught:
                normalize_atom(op)
            self.assertEqual(caught.exception.code, 'invalid_atom')

    def test_legacy_operation_without_atom_remains_automatic_verbatim_material(self):
        nid = self.raw(); op = self.op(nid); op.pop('atom')
        plan, result = self.apply([nid], [op])
        self.assertFalse(plan['operations'][0]['requires_review'])
        self.assertNotIn('fallback_reason_code', plan['operations'][0])
        self.assertEqual(len(result['created']), 1)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(self.brain.nodes[result['created'][0]]['meta']['memory_atom']['relation_status'], 'verbatim_fallback')


if __name__ == '__main__':
    unittest.main()
