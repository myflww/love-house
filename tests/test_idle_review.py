"""Offline review tests: no user database, provider request or stored credential."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.memory import build_context, record_turn
from nkb.companion.ingestion import connected_session_id
from nkb.companion.review import (SCHEMA, apply_review_plan, get_review_profile,
    save_review_profile, source_records, validate_proposals, revalidate_sources)
from nkb.companion.structured import build_structured_context
from nkb.companion.catalog import memory_catalog, memory_bootstrap
from nkb.errors import ValidationError
from nkb.organizer.config import save_profile
from nkb.organizer.idle_review import IdleReviewer, GUIDANCE
from nkb.organizer.model import OrganizerError, OrganizerConflict
from nkb.service.controls import correct, forget, forget_plan


class IdleReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brain = Brain.new()
        self.brain.meta['library_id'] = 'home'
        save_profile(self.brain, base_url='https://review.example.invalid', model='unit-review')
        self.auth = {'generation': 'g1', 'connection_ids': ['window-a', 'window-b'], 'allow_local': False}
        self.auth['connection_scopes'] = {cid: {'policy': 'any', 'window_id': None, 'binding_revision': 0}
                                          for cid in self.auth['connection_ids']}
        self.lock = threading.RLock()
        self.calls = []
        self.credential_calls = 0
        self.output_type = 'reflection'
        self.after_response = None
        self.error = None
        self.reviewer = self.make_reviewer()

    def source(self, text='咖啡偏好记录：今天讨论了如何核对准确来源。', connection='window-a', rid=None):
        rid = rid or str(len(self.brain.nodes))
        nid = record_turn(self.brain, text, '助手回答只说明当时的想法。', 'session-' + str(connection), rid,
                          connection_id=connection, origin='agent_source_adapter')
        self.brain.nodes[nid]['meta']['library_id'] = 'home'
        self.brain.nodes[nid]['meta']['evidence'] = {'archive_receipt_id': 'receipt-' + rid}
        return nid

    def snapshot(self, library):
        self.assertEqual(library, 'home')
        with self.lock:
            return {'brain': self.brain.to_dict(), 'authorization': deepcopy(self.auth)}

    def apply(self, library, plan, *, commit_guard):
        with self.lock:
            self.assertEqual(library, 'home')
            with commit_guard():
                return apply_review_plan(self.brain, plan, self.auth)

    def finalize(self, library, expected, generation, commit):
        with self.lock:
            revalidate_sources(self.brain, library, self.auth, expected, generation)
            return commit()

    def credential(self, library, profile):
        self.credential_calls += 1
        return {'api_key': 'fake-offline-secret-never-persist', 'base_url': profile['base_url'], 'model': profile['model']}

    def transport(self, request, *, timeout):
        envelope = json.loads(request.data)
        payload = json.loads(envelope['messages'][1]['content'])
        self.calls.append({'envelope': envelope, 'payload': payload})
        if self.error:
            raise self.error
        fragment = payload['sources'][0]
        part = next((part for part in fragment['content'] if len(part['text']) >= 4), None)
        if part is None:
            return {'choices': [{'message': {'content': '{"proposals": []}'}, 'finish_reason': 'stop'}]}
        item = {'type': self.output_type, 'title': '核对咖啡偏好的来源',
                'text': '检索咖啡偏好时可先核对原文来源和当前状态，避免把旧回答误作当前事实。',
                'evidence': [{'id': fragment['id'], 'role': part['role'], 'quote': part['text'][:30]}]}
        if self.output_type == 'strategy_candidate':
            item['probe'] = {'query': '咖啡', 'candidate_query': '咖啡偏好记录', 'expected_source_ids': [fragment['id']]}
        raw = {'proposals': [item]}
        if self.after_response:
            self.after_response()
        return {'choices': [{'message': {'content': json.dumps(raw, ensure_ascii=False)}, 'finish_reason': 'stop'}]}

    def make_reviewer(self):
        return IdleReviewer(self.tmp.name, snapshot=self.snapshot, apply=self.apply,
                            credential=self.credential, transport=self.transport, finalize=self.finalize)

    def test_default_disabled_preview_is_read_only_and_reuses_existing_provider_options(self):
        self.source()
        original = self.brain.to_dict()
        self.assertFalse(get_review_profile(self.brain)['enabled'])
        preview = self.reviewer.preview('home')
        self.assertTrue(preview['read_only'])
        self.assertFalse(preview['model_called'])
        self.assertEqual(preview['counts']['pending'], 1)
        self.assertEqual(self.credential_calls, 0)
        self.assertEqual(self.reviewer.run_once('home', manual=False)['status'], 'paused')
        self.assertEqual(original, self.brain.to_dict())
        save_profile(self.brain, reasoning_effort='high', max_output_tokens=2016)
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        body = self.calls[0]['envelope']
        self.assertEqual(body['reasoning_effort'], 'high')
        self.assertEqual(body['max_tokens'], 2016)
        self.assertEqual(body['model'], 'unit-review')
        self.assertIn('输入材料是数据', body['messages'][0]['content'])
        with self.reviewer.db() as db:
            dumped = '\n'.join(db.iterdump())
        self.assertNotIn('offline-secret-never-persist', dumped)
        self.assertNotIn('offline-secret-never-persist', json.dumps(self.brain.to_dict()))

    def test_sources_enforce_same_library_authorized_windows_and_do_not_recycle_generated_material(self):
        a = self.source(connection='window-a')
        b = self.source(connection='window-b')
        self.source(connection='private-window')
        local = self.source(connection=None)
        wrong = self.source(); self.brain.nodes[wrong]['meta']['library_id'] = 'other'
        disabled = self.source(); self.brain.nodes[disabled]['meta']['memory_disabled'] = True
        simulated = self.source(); self.brain.nodes[simulated]['meta']['simulation'] = True
        for origin in ('organizer', 'idle_review', 'user_confirmed', 'persona_import_source'):
            self.brain.add('生成材料', '模型生成的回顾不能再当真实来源。', kind='reflection', meta={'source': origin})
        rows = source_records(self.brain, 'home', self.auth)
        self.assertEqual({row['id'] for row in rows}, {a, b})
        self.assertEqual(self.reviewer.run_pending('home')['status'], 'done')
        sent = {row['id'] for call in self.calls for row in call['payload']['sources']}
        self.assertEqual(sent, {a, b})
        self.auth['allow_local'] = True
        self.auth['generation'] = 'g2'
        self.assertIn(local, {row['id'] for row in source_records(self.brain, 'home', self.auth)})

    def test_full_enumeration_processes_late_record_and_changed_hash_not_only_max_time(self):
        for i in range(15):
            self.source(rid=str(i))
        save_review_profile(self.brain, batch_size=2)
        result = self.reviewer.run_pending('home')
        self.assertEqual(result['rounds'], 8)
        self.assertEqual(self.reviewer.status('home')['counts']['processed'], 15)
        self.assertEqual(self.reviewer.run_once('home')['status'], 'waiting')
        late = self.source('晚到的咖啡原文也必须参与回顾。')
        self.brain.nodes[late]['created'] -= 3600
        self.brain.nodes[late]['reinforced'] -= 3600
        self.brain.nodes[late]['valid_from'] -= 3600
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        self.assertEqual(self.calls[-1]['payload']['sources'][0]['id'], late)
        self.brain.nodes[late]['text'] = '晚到的咖啡原文已被授权用户修改，需要重新复核。'
        self.assertEqual(self.reviewer.status('home')['counts']['pending'], 1)
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')

    def test_fragments_drain_until_every_character_reviewed_without_daily_ceiling(self):
        nid = self.source('咖啡偏好记录及其来源。' * 70)
        save_profile(self.brain, max_input_chars=101, daily_call_limit=1, daily_char_limit=1)
        result = self.reviewer.run_pending('home')
        self.assertEqual(result['status'], 'done')
        self.assertGreater(result['rounds'], 5)
        ranges = [(call['payload']['sources'][0]['offset'], call['payload']['sources'][0]['end']) for call in self.calls]
        self.assertEqual(ranges[0][0], 0)
        self.assertTrue(all(a[1] == b[0] for a, b in zip(ranges, ranges[1:])))
        total = sum(len(value) for value in (self.brain.nodes[nid]['text'], self.brain.nodes[nid]['meta']['assistant_reply']))
        self.assertEqual(ranges[-1][1], total)

    def test_failure_never_advances_and_provider_limit_retries_smaller_fragments(self):
        self.source('咖啡偏好记录及其来源。' * 30)
        self.error = OrganizerError('fake raw provider error must not persist', 'context_length_exceeded')
        result = self.reviewer.run_once('home')
        self.assertEqual(result['status'], 'retry')
        self.assertFalse(result['progress_advanced'])
        self.assertEqual(self.reviewer.status('home')['counts']['processed'], 0)
        with self.reviewer.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_sources').fetchone()[0], 0)
        size = sum(len(part['text']) for part in self.calls[0]['payload']['sources'][0]['content'])
        self.error = None
        result = self.reviewer.run_pending('home')
        self.assertEqual(result['status'], 'done')
        smaller = sum(len(part['text']) for part in self.calls[1]['payload']['sources'][0]['content'])
        self.assertLess(smaller, size)
        self.assertIsNone(self.reviewer.status('home')['last_error'])

    def test_deleted_corrected_or_revoked_during_model_call_cannot_commit(self):
        for change in ('delete', 'correct', 'revoke'):
            with self.subTest(change=change):
                self.reviewer.invalidate('home')
                nid = self.source(rid=change)
                def mutate():
                    if change == 'delete':
                        forget(self.brain, forget_plan(self.brain, nid))
                        self.reviewer.forget('home', [], [nid])
                    elif change == 'correct':
                        correct(self.brain, nid, '咖啡来源现已更正，旧原文不再参与回顾。')
                    else:
                        self.auth['generation'] += '-revoked'
                        self.auth['connection_ids'] = []
                        self.auth['connection_scopes'] = {}
                self.after_response = mutate
                result = self.reviewer.run_once('home')
                self.assertEqual(result['status'], 'stale')
                self.assertEqual(self.reviewer.status('home')['counts']['proposals'], 0)
                self.after_response = None
                self.auth['connection_ids'] = ['window-a', 'window-b']
                self.auth['connection_scopes'] = {cid: {'policy': 'any', 'window_id': None, 'binding_revision': 0}
                                                  for cid in self.auth['connection_ids']}

    def test_cross_instance_lease_heartbeat_and_expired_owner_never_writes(self):
        self.source()
        a, b = self.reviewer, self.make_reviewer()
        lease = a._claim('home')
        self.assertIsNone(b._claim('home'))
        with a.db() as db:
            db.execute('UPDATE review_leases SET expires=? WHERE library_id=?', (time.time() - 1, 'home'))
        replacement = b._claim('home')
        self.assertNotEqual(replacement['owner'], lease['owner'])
        with self.assertRaises(OrganizerConflict):
            a._check_owned(lease)
        a._release(lease)
        b._check_owned(replacement)
        b._release(replacement)
        a.HEARTBEAT_SECONDS = .015
        a.LEASE_SECONDS = .08
        lease = a._claim('home')
        with a._heartbeat(lease):
            time.sleep(.13)
            self.assertIsNone(b._claim('home'))
        a._release(lease)

    def test_reflection_accepts_only_after_management_action_and_lifecycle_guard_never_resurrects(self):
        source = self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        self.assertEqual([node for node in self.brain.nodes.values() if node['kind'] == 'reflection'], [])
        accepted = self.reviewer.decide('home', item['id'], 'accept')
        nid = accepted['result']['id']
        self.assertFalse(self.brain.nodes[nid]['meta']['confirmed'])
        self.assertEqual(build_context(self.brain, '咖啡偏好')['memory_ids'], [source])
        view = Brain(self.brain.to_dict())
        view.meta['idle_review_current_authorization_generation'] = self.auth['generation']
        packet = build_structured_context(view, '核对咖啡偏好', library_id='home')
        record = next(row for row in packet['memory_context']['records'] if row['id'] == nid)
        self.assertEqual(record['layer'], 'reflection')
        self.assertFalse(record['is_user_fact'])
        self.assertFalse(record['is_real_experience'])
        self.assertEqual(record['effectiveness'], 'unverified')
        self.assertEqual(record['interpretation'], 'unverified_material')
        view.meta['idle_review_current_authorization_generation'] = 'revoked'
        self.assertNotIn(nid, build_context(view, '咖啡偏好')['memory_ids'])
        plan = forget_plan(self.brain, source)
        self.assertIn(nid, plan['node_ids'])
        forget(self.brain, plan)
        self.reviewer.forget('home', [], plan['node_ids'])
        with self.assertRaises(ValidationError):
            self.reviewer.decide('home', item['id'], 'rollback')
        self.assertNotIn(nid, self.brain.nodes)
        self.assertEqual(self.reviewer.status('home')['counts']['proposals'], 0)

    def test_accept_revalidates_under_host_lock_and_rollback_only_disables(self):
        source = self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        ordinary = self.reviewer.apply
        def race(library, plan, *, commit_guard):
            self.brain.nodes[source]['meta']['memory_disabled'] = True
            return ordinary(library, plan, commit_guard=commit_guard)
        self.reviewer.apply = race
        with self.assertRaises(OrganizerConflict):
            self.reviewer.decide('home', item['id'], 'accept')
        self.assertFalse([node for node in self.brain.nodes.values() if node['kind'] == 'reflection'])
        self.brain.nodes[source]['meta'].pop('memory_disabled')
        self.reviewer.apply = ordinary
        nid = self.reviewer.decide('home', item['id'], 'accept')['result']['id']
        before = self.brain.nodes[nid]['text']
        self.assertEqual(self.reviewer.decide('home', item['id'], 'rollback')['status'], 'rolled_back')
        self.assertEqual(self.brain.nodes[nid]['text'], before)
        self.assertTrue(self.brain.nodes[nid]['meta']['memory_disabled'])
        with self.assertRaises(ValidationError):
            self.reviewer.decide('home', item['id'], 'accept')

    def test_strategy_replay_runs_real_retrieval_but_never_claims_independent_improvement_or_activates(self):
        source = self.source()
        self.source('咖啡私人区域，不可从回顾取用。', connection='private-window')
        self.output_type = 'strategy_candidate'
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        proposal = self.reviewer.status('home')['proposals'][0]
        replay = proposal['replay']
        self.assertEqual(replay['effectiveness'], 'unverified')
        self.assertFalse(replay['independent_evaluation'])
        self.assertFalse(replay['strategy_activated'])
        self.assertEqual(replay['boundary']['leaked_ids'], [])
        self.assertIn(source, replay['retrieval']['candidate_ids'])
        self.assertGreater(replay['retrieval']['candidate_found'], 0)
        with self.assertRaises(ValidationError):
            self.reviewer.decide('home', proposal['id'], 'accept')
        self.assertEqual(self.reviewer.decide('home', proposal['id'], 'reject')['status'], 'rejected')

    def test_simulation_is_isolated_and_forged_evidence_or_automatic_flags_are_rejected(self):
        self.source()
        self.output_type = 'simulation'
        self.reviewer.run_once('home')
        proposal = self.reviewer.status('home')['proposals'][0]
        self.assertTrue(proposal['hypothetical'])
        self.assertEqual(proposal['storage'], 'review_only')
        with self.assertRaises(ValidationError):
            self.reviewer.decide('home', proposal['id'], 'accept')
        fragment = self.calls[0]['payload']['sources']
        good = {'type': 'reflection', 'title': '经验', 'text': '这只是经验建议。',
                'evidence': [{'id': fragment[0]['id'], 'role': 'user', 'quote': fragment[0]['content'][0]['text'][:10]}]}
        for mutate in (lambda row: row.update(confirmed=True),
                       lambda row: row['evidence'][0].update(id='foreign'),
                       lambda row: row['evidence'][0].update(role='tool'),
                       lambda row: row['evidence'][0].update(quote='没有出现在原文的伪造引用')):
            bad = deepcopy(good); mutate(bad)
            with self.assertRaises(OrganizerError):
                validate_proposals({'proposals': [bad]}, fragment)

    def test_auto_mode_waits_for_real_idle_and_settings_cannot_contain_secrets(self):
        self.source()
        save_review_profile(self.brain, enabled=True, idle_seconds=60)
        self.assertEqual(self.reviewer.run_once('home', manual=False, idle_for=59)['status'], 'waiting_idle')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.reviewer.run_once('home', manual=False, idle_for=61)['status'], 'done')
        with self.assertRaises(ValidationError):
            save_review_profile(self.brain, api_key='no-secret-config')
        self.assertNotIn('api_key', get_review_profile(self.brain))

    def test_finalizer_protects_last_snapshot_to_journal_commit_and_missing_guard_calls_no_model(self):
        source = self.source()
        ordinary = self.reviewer.finalize
        def race(library, expected, generation, commit):
            self.brain.nodes[source]['text'] = '最终提交前原文已更正，不能保留此前引用副本。'
            return ordinary(library, expected, generation, commit)
        self.reviewer.finalize = race
        self.assertEqual(self.reviewer.run_once('home')['status'], 'stale')
        with self.reviewer.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_proposals').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_sources').fetchone()[0], 0)
        self.calls.clear()
        self.reviewer.finalize = None
        with self.assertRaises(ValidationError):
            self.reviewer.run_once('home')
        self.assertEqual(self.calls, [])

    def test_accept_fences_invalidation_and_expiry_before_host_graph_write(self):
        self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        ordinary = self.reviewer.apply
        def expire(library, plan, *, commit_guard):
            with self.reviewer.db() as db:
                db.execute('UPDATE review_leases SET expires=0 WHERE library_id=?', (library,))
            return ordinary(library, plan, commit_guard=commit_guard)
        self.reviewer.apply = expire
        with self.assertRaises(OrganizerConflict):
            self.reviewer.decide('home', item['id'], 'accept')
        self.assertFalse([node for node in self.brain.nodes.values() if node['kind'] == 'reflection'])
        def invalidate(library, plan, *, commit_guard):
            self.reviewer.invalidate(library)
            return ordinary(library, plan, commit_guard=commit_guard)
        self.reviewer.apply = invalidate
        with self.assertRaises(OrganizerConflict):
            self.reviewer.decide('home', item['id'], 'accept')
        self.assertFalse([node for node in self.brain.nodes.values() if node['kind'] == 'reflection'])

    def test_entire_model_input_is_a_dependency_even_when_only_one_source_is_quoted(self):
        a = self.source('咖啡偏好原文A，提案只引用这一条。')
        b = self.source('茶偏好原文B，模型也实际看过这一条。')
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        self.assertEqual([ref['id'] for ref in item['evidence']], [a])
        self.brain.nodes[b]['text'] = '茶偏好原文B已被用户更正。'
        self.assertEqual(self.reviewer.status('home')['counts']['proposals'], 0)
        with self.assertRaises(OrganizerConflict):
            self.reviewer.decide('home', item['id'], 'accept')
        self.assertFalse([node for node in self.brain.nodes.values() if node['kind'] == 'reflection'])

    def test_same_connection_rebound_window_and_revision_are_not_authorized_by_id_alone(self):
        old = self.source('旧窗口咖啡内容不应该穿过重绑边界。')
        current = self.source('新窗口咖啡内容当前被明确授权。')
        self.brain.nodes[old]['session_id'] = connected_session_id('window-a', 'old-window')
        self.brain.nodes[current]['session_id'] = connected_session_id('window-a', 'current-window')
        scope = {'policy': 'fixed', 'window_id': 'current-window', 'binding_revision': 2}
        self.auth['connection_scopes']['window-a'] = scope
        self.assertEqual({row['id'] for row in source_records(self.brain, 'home', self.auth)}, {current})
        self.brain.nodes[current]['meta']['evidence']['binding_revision'] = 1
        self.assertEqual(source_records(self.brain, 'home', self.auth), [])
        self.brain.nodes[current]['meta']['evidence']['binding_revision'] = 2
        self.assertEqual(len(source_records(self.brain, 'home', self.auth)), 1)
        self.auth['connection_scopes']['window-a']['window_id'] = None
        self.assertEqual(source_records(self.brain, 'home', self.auth), [])
        self.auth['connection_scopes'].pop('window-b')
        with self.assertRaises(ValidationError):
            source_records(self.brain, 'home', self.auth)

    def test_cancel_preserves_proposals_progress_and_rollback_but_fences_inflight(self):
        self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        nid = self.reviewer.decide('home', item['id'], 'accept')['result']['id']
        self.reviewer.cancel('home')
        state = self.reviewer.status('home')
        self.assertEqual(state['counts']['processed'], 1)
        self.assertEqual(state['proposals'][0]['status'], 'accepted')
        self.assertEqual(self.reviewer.decide('home', item['id'], 'rollback')['status'], 'rolled_back')
        self.assertTrue(self.brain.nodes[nid]['meta']['memory_disabled'])
        self.source('空闲回顾新材料，正在处理中。')
        self.after_response = lambda: self.reviewer.cancel('home')
        self.assertEqual(self.reviewer.run_once('home')['status'], 'stale')
        self.assertEqual(self.reviewer.status('home')['counts']['pending'], 1)

    def test_explicit_context_window_is_a_per_call_budget_and_default_does_not_clip(self):
        self.source('咖啡检索来源。' * 1500)
        save_profile(self.brain, context_window=8192, max_output_tokens=512)
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        payload = self.calls[-1]['payload']
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        self.assertLessEqual(len(encoded) + len(GUIDANCE.encode()) + 1024 + 512, 8192)
        self.assertGreater(self.reviewer.status('home')['counts']['pending'], 0)
        self.reviewer.invalidate('home')
        save_profile(self.brain, context_window=0, max_output_tokens=0)
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        payload = self.calls[-1]['payload']
        self.assertEqual(payload['sources'][0]['end'], payload['sources'][0]['total_chars'])
        self.assertNotIn('max_tokens', self.calls[-1]['envelope'])

    def test_slow_persist_commits_once_stop_waits_and_expiry_does_not_reverse_saved_success(self):
        self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        self.reviewer.LEASE_SECONDS = .05
        saved = Path(self.tmp.name) / 'synthetic-persist.json'
        stop_requested, stop_done = threading.Event(), threading.Event()
        stopper = None
        def persist(library, plan, *, commit_guard):
            nonlocal stopper
            with self.lock:
                with commit_guard():
                    result = apply_review_plan(self.brain, plan, self.auth)
                    def stop():
                        stop_requested.set()
                        self.reviewer.stop()
                        stop_done.set()
                    stopper = threading.Thread(target=stop)
                    stopper.start()
                    self.assertTrue(stop_requested.wait(1))
                    self.assertFalse(stop_done.wait(.08))
                    # The lease wall clock now expired, but this fenced host
                    # transaction already entered and owns the SQL write lock.
                    saved.write_text(json.dumps(self.brain.to_dict(), ensure_ascii=False), encoding='utf-8')
            return result
        self.reviewer.apply = persist
        result = self.reviewer.decide('home', item['id'], 'accept')
        stopper.join(1)
        self.assertTrue(stop_done.is_set())
        self.assertEqual(result['status'], 'accepted')
        nid = result['result']['id']
        self.assertIn(nid, json.loads(saved.read_text(encoding='utf-8'))['nodes'])
        self.assertIn(nid, self.brain.nodes)
        self.assertEqual(self.reviewer.status('home')['proposals'][0]['status'], 'accepted')

    def test_success_then_cancel_keeps_accepted_receipt_and_restart_keeps_exact_progress(self):
        self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        ordinary = self.reviewer.apply
        def cancel_after_persist(library, plan, *, commit_guard):
            result = ordinary(library, plan, commit_guard=commit_guard)
            self.reviewer.cancel(library)
            return result
        self.reviewer.apply = cancel_after_persist
        self.assertEqual(self.reviewer.decide('home', item['id'], 'accept')['status'], 'accepted')
        restarted = self.make_reviewer()
        self.assertEqual(restarted.run_once('home')['status'], 'waiting')
        self.assertEqual(restarted.status('home')['proposals'][0]['status'], 'accepted')
        self.assertEqual(restarted.decide('home', item['id'], 'rollback')['status'], 'rolled_back')

    def test_external_participant_identity_stays_attributed_in_review_input(self):
        nid = self.source()
        self.brain.nodes[nid]['meta']['evidence'].update(participant_scope='external_participant', participant_id='qq-peer-7')
        self.assertEqual(self.reviewer.run_once('home')['status'], 'done')
        fragment = self.calls[-1]['payload']['sources'][0]
        self.assertEqual(fragment['participant_scope'], 'external_participant')
        self.assertEqual(fragment['participant_id'], 'qq-peer-7')
        self.assertEqual(fragment['content'][0]['role'], 'user')

    def test_registered_source_identity_must_match_current_runtime_not_only_connection(self):
        nid = self.source()
        evidence = self.brain.nodes[nid]['meta']['evidence']
        evidence.update(source_id='qq-source', source_runtime_agent_id='fish-a')
        self.assertEqual(source_records(self.brain, 'home', self.auth), [])
        self.auth['source_scopes'] = {'window-a': {'source_id': 'qq-source', 'runtime_agent_id': 'fish-b'}}
        self.assertEqual(source_records(self.brain, 'home', self.auth), [])
        self.auth['source_scopes']['window-a']['runtime_agent_id'] = 'fish-a'
        self.assertEqual({row['id'] for row in source_records(self.brain, 'home', self.auth)}, {nid})
        self.auth['source_scopes']['window-a']['source_id'] = 'other-source'
        self.assertEqual(source_records(self.brain, 'home', self.auth), [])

    def test_rollback_review_does_not_hide_its_original_conversation_or_queue_source(self):
        source = self.source()
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        self.reviewer.decide('home', item['id'], 'accept')
        self.reviewer.decide('home', item['id'], 'rollback')
        self.assertIn(source, build_context(self.brain, '咖啡来源')['memory_ids'])
        self.assertEqual({row['id'] for row in source_records(self.brain, 'home', self.auth)}, {source})

    def test_correcting_derived_fact_during_review_invalidates_its_old_raw_evidence(self):
        source = self.source()
        fact = self.brain.add('咖啡旧偏好', '旧的加糖咖啡偏好', kind='preference', meta={'source': 'organizer',
            'organizer_evidence': [{'id': source, 'role': 'user', 'quote': self.brain.nodes[source]['text']}]})
        self.after_response = lambda: correct(self.brain, fact, '现在改为不加糖的咖啡')
        self.assertEqual(self.reviewer.run_once('home')['status'], 'stale')
        self.assertEqual(self.reviewer.status('home')['counts']['proposals'], 0)

    def test_accepted_review_is_hidden_after_its_derived_fact_is_corrected(self):
        source = self.source()
        fact = self.brain.add('咖啡旧偏好', '旧的加糖咖啡偏好', kind='preference', meta={'source': 'organizer',
            'organizer_evidence': [{'id': source, 'role': 'user', 'quote': self.brain.nodes[source]['text']}]})
        self.reviewer.run_once('home')
        item = self.reviewer.status('home')['proposals'][0]
        nid = self.reviewer.decide('home', item['id'], 'accept')['result']['id']
        self.brain.meta['idle_review_current_authorization_generation'] = self.auth['generation']
        self.assertIn(nid, build_context(self.brain, '咖啡来源')['memory_ids'])
        correct(self.brain, fact, '现在改为不加糖的咖啡')
        self.assertNotIn(nid, build_context(self.brain, '咖啡来源')['memory_ids'])

    def test_proposal_inventory_has_no_hard_cap_pages_prioritize_pending_and_invalidate_stale_cursor(self):
        self.source()
        self.reviewer.run_once('home')
        with self.reviewer.db() as db:
            original = dict(db.execute('SELECT * FROM review_proposals').fetchone())
            for index in range(140):
                db.execute('INSERT INTO review_proposals VALUES(?,?,?,?,?,?,?,?)',
                           ('synthetic-' + str(index), 'home', original['source_hashes'], original['generation'],
                            original['proposal_json'], 'pending' if index < 40 else 'rejected', None, time.time() + index))
        first = self.reviewer.status('home')
        self.assertEqual(first['total'], 141)
        self.assertEqual(first['counts']['proposals'], 141)
        self.assertEqual(first['counts']['pending_proposals'], 41)
        self.assertEqual(len(first['proposals']), 25)
        self.assertTrue(all(item['status'] == 'pending' for item in first['proposals']))
        ids = [item['id'] for item in first['proposals']]
        cursor = first['next_cursor']
        while cursor:
            page = self.reviewer.status('home', cursor=cursor)
            ids.extend(item['id'] for item in page['proposals'])
            cursor = page['next_cursor']
        self.assertEqual(len(ids), 141)
        self.assertEqual(len(set(ids)), 141)
        self.reviewer.decide('home', first['proposals'][0]['id'], 'reject')
        with self.assertRaises(ValidationError):
            self.reviewer.status('home', cursor=first['next_cursor'])
        with self.assertRaises(ValidationError):
            self.reviewer.status('home', cursor='invalid')

    def test_many_reflections_share_one_request_local_evidence_scan_without_stale_reuse(self):
        from nkb.companion.memory import _disabled_evidence
        from nkb.organizer.state import fingerprint
        source = self.source()
        self.brain.meta['idle_review_current_authorization_generation'] = self.auth['generation']
        proposal = {'type': 'reflection', 'title': '咖啡来源复核经验', 'text': '咖啡话题应核对原文来源；此经验只是推测。',
                    'evidence': [{'id': source, 'role': 'user', 'quote': self.brain.nodes[source]['text'][:12]}]}
        reflection_ids = set()
        for index in range(40):
            result = apply_review_plan(self.brain, {'schema': SCHEMA, 'library_id': 'home', 'action': 'accept',
                'proposal_id': 'scan-' + str(index), 'proposal': proposal,
                'source_hashes': {source: fingerprint(self.brain.nodes[source])}, 'authorization_generation': self.auth['generation']}, self.auth)
            reflection_ids.add(result['id'])
        def check(operation):
            scans = []
            def scan(brain):
                scans.append(1)
                return _disabled_evidence(brain)
            with patch('nkb.companion.memory._disabled_evidence', side_effect=scan), \
                 patch('nkb.companion.catalog._disabled_evidence', side_effect=scan):
                value = operation()
            self.assertEqual(len(scans), 1)
            return value
        context = check(lambda: build_context(self.brain, '咖啡来源', session_id='session-window-a'))
        self.assertTrue(reflection_ids & set(context['memory_ids']))
        check(lambda: build_structured_context(self.brain, '咖啡来源', session_id='session-window-a', library_id='home'))
        catalog = check(lambda: memory_catalog(self.brain, 'home', 'Synthetic', limit=100))
        self.assertEqual(catalog['total'], 41)
        check(lambda: memory_bootstrap(self.brain, 'home', 'Synthetic'))
        self.brain.nodes[source]['meta']['memory_disabled'] = True
        context = check(lambda: build_context(self.brain, '咖啡来源', session_id='session-window-a'))
        self.assertFalse(reflection_ids & set(context['memory_ids']))
        self.assertEqual(check(lambda: memory_catalog(self.brain, 'home', 'Synthetic'))['total'], 0)


if __name__ == '__main__':
    unittest.main()
