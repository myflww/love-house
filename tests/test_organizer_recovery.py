"""Durable automatic recovery with disposable libraries and an offline model."""
from copy import deepcopy
import json
import tempfile
import time
import unittest

from nkb import Brain
from nkb.companion import record_turn
from nkb.organizer import Organizer, apply_plan, save_profile


class OrganizerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brains = {lid: Brain.new() for lid in ('a', 'b')}
        for brain in self.brains.values():
            save_profile(brain, enabled=True, base_url='https://offline.invalid',
                         model='offline-test', batch_size=1, auto_trigger_count=1, max_attempts=1,max_input_chars=18000)
        self.fail_model = False
        self.fail_apply = False
        self.calls = []
        self.worker = self.make_worker()

    def make_worker(self):
        def send(request, *, timeout):
            payload = json.loads(json.loads(request.data)['messages'][1]['content'])
            self.calls.append(payload)
            if self.fail_model:
                raise TimeoutError('offline only')
            return {'choices': [{'message': {'content': '{"version":1,"operations":[]}'},
                                 'finish_reason': 'stop'}]}

        def apply(lid, plan):
            if self.fail_apply:
                raise OSError('offline disk failure')
            return apply_plan(self.brains[lid], plan, lid)

        worker = Organizer(self.tmp.name, snapshot=lambda lid: deepcopy(self.brains[lid].to_dict()),
                           apply=apply, credential=lambda lid, profile: 'offline-key', transport=send)
        self.addCleanup(worker.stop)
        return worker

    def enqueue(self, lid='a'):
        brain = self.brains[lid]
        rid = record_turn(brain, '合成原文', '合成回复', 'test-session', str(len(brain.nodes)))
        self.worker.enqueue(lid, [rid])
        return rid

    def make_due(self, job_id):
        with self.worker.db() as db:
            db.execute('UPDATE jobs SET next_run=0 WHERE id=?', (job_id,))

    def test_failures_exceed_old_attempt_limit_and_finish_without_manual_retry(self):
        rid = self.enqueue()
        self.fail_model = True
        expected_delays = [5, 10, 20, 40, 80, 160, 300, 300]
        job_id = None
        for attempt, delay in enumerate(expected_delays, 1):
            before = time.time()
            result = self.worker.run_once(flush=False)
            self.assertEqual(result['status'], 'retry')
            if job_id is None:
                job_id = result['job_id']
            self.assertEqual(result['job_id'], job_id)
            job = self.worker.status('a')['jobs'][0]
            self.assertEqual(job['attempts'], attempt)
            self.assertGreaterEqual(job['next_run'], before + delay)
            self.assertLessEqual(job['next_run'], time.time() + delay)
            # Calling the worker again before its deadline must not call the API.
            calls = len(self.calls)
            self.worker.run_once(flush=False)
            self.assertEqual(len(self.calls), calls)
            self.make_due(job_id)
        self.fail_model = False
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual(self.worker.status('a')['counts'], {'done': 1})
        self.assertIn(rid, self.brains['a'].nodes)
        self.assertEqual(self.worker.enqueue('a', [rid])['queued'], 0)
        self.assertEqual(len(self.calls), len(expected_delays) + 1)

    def test_repeated_apply_failure_reuses_cached_plan_and_finishes_after_restart(self):
        self.enqueue()
        self.fail_apply = True
        for _ in range(5):
            result = self.worker.run_once(flush=False)
            self.assertEqual(result['status'], 'retry')
            self.make_due(result['job_id'])
        self.assertEqual(len(self.calls), 1)
        self.worker.stop()
        self.fail_apply = False
        restored = self.make_worker()
        self.assertEqual(restored.run_once(flush=False)['status'], 'done')
        self.assertEqual(len(self.calls), 1)

    def test_legacy_failed_jobs_resume_on_start_without_resetting_attempts(self):
        self.enqueue()
        self.fail_model = True
        result = self.worker.run_once(flush=False)
        with self.worker.db() as db:
            db.execute("UPDATE jobs SET status='failed',attempts=8,next_run=0 WHERE id=?", (result['job_id'],))
            db.execute("UPDATE items SET status='failed' WHERE job_id=?", (result['job_id'],))
        self.worker.stop()
        self.fail_model = False
        restored = self.make_worker()
        self.assertEqual(restored.status('a')['counts'], {'retry': 1})
        result = restored.run_once(flush=False)
        self.assertEqual(result['status'], 'done')
        self.assertEqual(restored.status('a')['jobs'][0]['attempts'], 9)

    def test_deleted_rejected_cancelled_and_completed_jobs_are_never_recovered(self):
        for state, code in [('failed', 'source_deleted'), ('failed', 'privacy_deleted'),
                            ('rejected', 'timeout'), ('cancelled', 'timeout'), ('done', None)]:
            with self.subTest(state=state, code=code):
                lid = state + '-' + str(code)
                self.brains[lid] = Brain.new()
                save_profile(self.brains[lid], enabled=True, base_url='https://offline.invalid',
                             model='offline-test', auto_trigger_count=1, batch_size=1)
                self.enqueue(lid)
                self.fail_model = True
                result = self.worker.run_once(lid, flush=False)
                with self.worker.db() as db:
                    db.execute('UPDATE jobs SET status=?,error_code=?,next_run=0 WHERE id=?',
                               (state, code, result['job_id']))
                    db.execute('UPDATE items SET status=? WHERE job_id=?', (state, result['job_id']))
                self.fail_model = False
                before = len(self.calls)
                restored = self.make_worker()
                self.assertEqual(restored.status(lid)['jobs'][0]['status'], state)
                restored.run_once(lid, flush=False)
                self.assertEqual(len(self.calls), before)

    def test_deleted_source_after_failure_is_not_sent_or_revived(self):
        rid = self.enqueue()
        self.fail_model = True
        failed = self.worker.run_once(flush=False)
        self.brains['a'].remove(rid)
        self.make_due(failed['job_id'])
        self.fail_model = False
        self.assertEqual(self.worker.run_once(flush=False)['code'], 'source_deleted')
        calls = len(self.calls)
        restored = self.make_worker()
        self.assertEqual(restored.run_once(flush=False)['status'], 'idle')
        self.assertEqual(len(self.calls), calls)
        self.assertNotIn(rid, self.brains['a'].nodes)

    def test_pending_retry_does_not_block_another_library_and_obeys_pause(self):
        self.enqueue('a')
        self.fail_model = True
        failed = self.worker.run_once('a', flush=False)
        self.enqueue('b')
        self.fail_model = False
        self.assertEqual(self.worker.run_once(flush=False)['library_id'], 'b')
        save_profile(self.brains['a'], enabled=False)
        self.make_due(failed['job_id'])
        calls = len(self.calls)
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'paused')
        self.assertEqual(len(self.calls), calls)
        save_profile(self.brains['a'], enabled=True)
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')

    def test_backoff_is_bounded_even_for_long_lived_failure_count(self):
        self.assertEqual(Organizer._retry_delay(1000000), 300)

    def test_deleted_member_does_not_strand_surviving_batch_below_threshold(self):
        save_profile(self.brains['a'], batch_size=2, auto_trigger_count=2)
        removed = self.enqueue()
        kept = self.enqueue()
        self.fail_apply = True
        failed = self.worker.run_once(flush=False)
        self.assertEqual(failed['status'], 'retry')
        self.assertEqual(len(self.calls), 1)
        self.brains['a'].remove(removed)
        self.fail_apply = False
        self.make_due(failed['job_id'])
        self.assertEqual(self.worker.run_once(flush=False)['code'], 'source_deleted')
        self.assertEqual(len(self.calls), 1)
        with self.worker.db() as db:
            deleted_job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (failed['job_id'],)).fetchone())
        self.assertEqual(json.loads(deleted_job['raw_ids']), [removed])
        self.assertIsNone(deleted_job['plan_json'])
        self.assertEqual(self.worker.status('a')['counts'], {'failed': 1, 'pending': 1})
        # The survivor was already part of this cycle, even if the configured
        # trigger has since increased. It needs no new conversation to finish.
        save_profile(self.brains['a'], auto_trigger_count=20)
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual(self.worker.status('a')['counts'], {'done': 1, 'failed': 1})
        self.assertEqual([r['id'] for r in self.calls[-1]['raw']], [kept])

    def test_missing_archive_only_stops_its_own_source_in_a_mixed_batch(self):
        save_profile(self.brains['a'], batch_size=2, auto_trigger_count=2)
        for index, receipt in enumerate(('missing-receipt', 'kept-receipt')):
            rid = record_turn(self.brains['a'], '合成原文' + str(index), '回复', 'session', str(index))
            self.brains['a'].nodes[rid]['meta']['evidence'] = {'archive_receipt_id': receipt}
            self.worker.enqueue('a', [receipt])
        self.worker.read_archive = lambda lid, rid: None if rid == 'missing-receipt' else {
            'library_id': lid, 'id': rid, 'normalized': {'type': 'turn', 'user': '合成原文1', 'assistant': '回复'}}
        self.assertEqual(self.worker.run_once(flush=False)['code'], 'source_deleted')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual([r['receipt_id'] for r in self.calls[-1]['raw']], ['kept-receipt'])

    def test_legacy_persona_failure_requires_explicit_retry_even_with_memory_items(self):
        self.enqueue()
        self.fail_model = True
        failed = self.worker.run_once(flush=False)
        with self.worker.db() as db:
            db.execute("UPDATE jobs SET purpose='persona',status='failed',next_run=0 WHERE id=?", (failed['job_id'],))
            db.execute("UPDATE items SET status='failed' WHERE job_id=?", (failed['job_id'],))
        self.worker.stop()
        self.fail_model = False
        restored = self.make_worker()
        self.assertEqual(restored.run_once(flush=False)['status'], 'idle')
        self.assertEqual(restored.status('a')['jobs'][0]['status'], 'failed')
        self.assertEqual(len(self.calls), 1)

    def test_truncated_response_retries_smaller_slice_then_finishes_all_raw_text(self):
        text = '需要保留的合成原话。' * 2500
        assistant = '助手结尾也要完整保留。'
        rid = record_turn(self.brains['a'], text, assistant, 'long-session', 'long-record')
        self.worker.enqueue('a', [rid])
        requests = []
        successful = []

        def send(request, *, timeout):
            body = json.loads(request.data)
            payload = json.loads(body['messages'][1]['content'])
            requests.append((body, payload))
            if len(requests) == 1:
                return {'choices': [{'message': {'content': '{'}, 'finish_reason': 'length'}]}
            successful.extend(payload['raw'])
            return {'choices': [{'message': {'content': '{"version":1,"operations":[]}'}, 'finish_reason': 'stop'}]}

        self.worker.transport = send
        failed = self.worker.run_once(flush=False)
        self.assertEqual(failed['code'], 'truncated_output')
        self.make_due(failed['job_id'])
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertLess(len(json.dumps(requests[1][1])), len(json.dumps(requests[0][1])))
        self.assertLessEqual(len(json.dumps(requests[1][1], ensure_ascii=False)), 9000)
        self.assertIn('operations最多1项', requests[1][0]['messages'][0]['content'])
        for _ in range(30):
            if self.worker.status('a')['counts'].get('done'):
                break
            self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual(self.worker.status('a')['counts'], {'done': 1})
        self.assertEqual(''.join(row['roles'].get('user', '') for row in successful), text)
        self.assertEqual(''.join(row['roles'].get('assistant', '') for row in successful), assistant)
        self.assertEqual(self.brains['a'].nodes[rid]['text'], text)

    def test_truncated_multi_source_retry_splits_safely_and_keeps_tail_eligible(self):
        save_profile(self.brains['a'], batch_size=4, auto_trigger_count=4)
        ids = [self.enqueue() for _ in range(4)]
        requests = []

        def send(request, *, timeout):
            payload = json.loads(json.loads(request.data)['messages'][1]['content'])
            requests.append(payload)
            return {'choices': [{'message': {'content': '{"version":1,"operations":[]}'},
                                 'finish_reason': 'length' if len(requests) == 1 else 'stop'}]}

        self.worker.transport = send
        failed = self.worker.run_once(flush=False)
        self.assertEqual(failed['code'], 'truncated_output')
        self.make_due(failed['job_id'])
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual(len(requests[1]['raw']), 1)
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertEqual(self.worker.status('a')['counts'], {'done': 4})
        self.assertEqual([row['id'] for payload in requests[1:] for row in payload['raw']], ids)

    def test_compact_retry_keeps_operation_and_evidence_validation(self):
        self.enqueue()
        attempts = []

        def send(request, *, timeout):
            payload = json.loads(json.loads(request.data)['messages'][1]['content'])
            attempts.append(payload)
            raw = payload['raw'][0]
            op = {'action':'remember','layer':'fact','key':'test.key','text':'合成事实',
                  'certainty':'clear','domain':'real',
                  'evidence':[{'id':raw['id'],'role':'user','quote':raw['roles']['user']}]}
            return {'choices': [{'message': {'content': json.dumps({'version':1, 'operations':[op, op]})},
                                 'finish_reason': 'length' if len(attempts) == 1 else 'stop'}]}

        self.worker.transport = send
        failed = self.worker.run_once(flush=False)
        self.make_due(failed['job_id'])
        rejected = self.worker.run_once(flush=False)
        self.assertEqual(rejected['code'], 'invalid_output')
        self.assertEqual(self.worker.status('a')['counts'], {'retry': 1})
        self.assertFalse(any(node['meta'].get('source') == 'organizer' for node in self.brains['a'].nodes.values()))

    def test_compact_limit_survives_timeout_restart_and_further_truncation(self):
        text = '合成原文需要完整保留。' * 2000
        rid = record_turn(self.brains['a'], text, '助手尾文', 'session', 'compact-restart')
        self.worker.enqueue('a', [rid])
        sizes = []

        def send(request, *, timeout):
            body = json.loads(request.data)
            payload = json.loads(body['messages'][1]['content'])
            sizes.append(len(json.dumps(payload, ensure_ascii=False)))
            if len(sizes) == 2:
                raise TimeoutError('synthetic timeout after compact retry')
            return {'choices': [{'message': {'content': '{"version":1,"operations":[]}'},
                                 'finish_reason': 'length' if len(sizes) in (1, 3) else 'stop'}]}

        self.worker.transport = send
        for code in ('truncated_output', 'timeout'):
            result = self.worker.run_once(flush=False)
            self.assertEqual(result['code'], code)
            self.make_due(result['job_id'])
        self.worker.stop()
        self.worker = self.make_worker()
        self.worker.transport = send
        result = self.worker.run_once(flush=False)
        self.assertEqual(result['code'], 'truncated_output')
        self.assertEqual(sizes[2], sizes[1])
        self.assertLess(sizes[1], sizes[0])
        self.make_due(result['job_id'])
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'done')
        self.assertLess(sizes[3], sizes[2])
        with self.worker.db() as db:
            guards = json.loads(db.execute('SELECT plan_json FROM jobs WHERE id=?', (result['job_id'],)).fetchone()[0])
        self.assertEqual(guards['retry_limits'], {'max_input_chars': 4500, 'max_ops': 1})

    def test_startup_automatically_splits_historical_deleted_batch_using_current_archive_proof(self):
        save_profile(self.brains['a'], batch_size=4, auto_trigger_count=4)
        receipts = ['kept-receipt', 'missing-receipt', 'foreign-receipt', 'tombstoned-receipt']
        for index, receipt in enumerate(receipts):
            rid = record_turn(self.brains['a'], '原文' + str(index), '回复', 'session', str(index))
            self.brains['a'].nodes[rid]['meta']['evidence'] = {'archive_receipt_id': receipt}
            self.worker.enqueue('a', [receipt])
        job = self.worker._claim('a', self.brains['a'].meta['organizer_profile'], True)
        with self.worker.db() as db:
            db.execute("UPDATE jobs SET status='failed',error_code='source_deleted',attempts=7 WHERE id=?", (job['id'],))
            db.execute("UPDATE items SET status='failed' WHERE job_id=?", (job['id'],))
            db.execute("INSERT INTO tombstones VALUES('a','raw','tombstoned-receipt',?)", (time.time(),))
        self.worker.stop()
        restored = self.make_worker()
        reads = []

        def archive(lid, rid):
            reads.append(rid)
            if rid == 'missing-receipt':
                return None
            return {'id': rid, 'library_id': 'b' if rid == 'foreign-receipt' else lid,
                    'normalized': {'type':'turn','user':'原文0','assistant':'回复'}}

        restored.read_archive = archive
        result = restored.run_once(flush=False)
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual(restored.status('a')['counts'], {'done':1,'failed':3})
        self.assertEqual([row['receipt_id'] for row in self.calls[-1]['raw']], ['kept-receipt'])
        self.assertNotIn('tombstoned-receipt', reads)
        with restored.db() as db:
            failed = dict(db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
        self.assertEqual(set(json.loads(failed['raw_ids'])), set(receipts[1:]))
        self.assertEqual(failed['attempts'], 7)
        before = list(reads)
        self.assertEqual(restored.run_once(flush=False)['status'], 'idle')
        self.assertEqual(reads, before)

    def test_automatic_false_deletion_proof_cannot_requeue_after_forget(self):
        receipt = 'receipt-forgotten-during-repair'
        rid = record_turn(self.brains['a'], '要遗忘的原文', '回复', 'session', 'forget-proof')
        self.brains['a'].nodes[rid]['meta']['evidence'] = {'archive_receipt_id': receipt}
        self.worker.enqueue('a', [receipt])
        job = self.worker._claim('a', self.brains['a'].meta['organizer_profile'], True)
        with self.worker.db() as db:
            db.execute("UPDATE jobs SET status='failed',error_code='source_deleted' WHERE id=?", (job['id'],))
            db.execute("UPDATE items SET status='failed' WHERE job_id=?", (job['id'],))

        def archive(lid, source):
            self.worker.forget(lid, [source], [rid])
            self.brains[lid].remove(rid)
            return {'id':source,'library_id':lid,'normalized':{'type':'turn','user':'要遗忘的原文','assistant':'回复'}}

        self.worker.read_archive = archive
        self.assertEqual(self.worker.run_once(flush=False)['status'], 'idle')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.worker.status('a')['counts'], {})
        self.assertEqual(self.worker.status('a')['jobs'][0]['status'], 'cancelled')

    def legacy_cached_plan(self):
        save_profile(self.brains['a'],max_input_chars=0)
        self.enqueue()
        self.fail_apply=True
        failed=self.worker.run_once(flush=False)
        self.assertEqual(failed['status'],'retry')
        with self.worker.db() as db:
            plan=json.loads(db.execute('SELECT plan_json FROM jobs WHERE id=?',(failed['job_id'],)).fetchone()[0])
            plan['profile'].update(daily_call_limit=100,daily_char_limit=200000,max_input_chars=18000)
            for key in ('context_window','max_output_tokens','reasoning_effort'):plan['profile'].pop(key,None)
            db.execute('UPDATE jobs SET plan_json=?,next_run=0 WHERE id=?',(json.dumps(plan),failed['job_id']))
        self.worker.stop();self.fail_apply=False
        return failed['job_id']

    def test_legacy_cached_profile_normalizes_retired_defaults_without_another_paid_call(self):
        self.legacy_cached_plan()
        restored=self.make_worker()
        self.assertEqual(restored.run_once(flush=False)['status'],'done')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(restored.status('a')['counts'],{'done':1})

    def test_legacy_cached_profile_still_rejects_a_real_provider_configuration_change(self):
        job=self.legacy_cached_plan()
        save_profile(self.brains['a'],model='a-different-user-selected-model')
        restored=self.make_worker()
        result=restored.run_once(flush=False)
        self.assertEqual(result['code'],'stale_input')
        self.assertEqual(len(self.calls),1)
        with restored.db() as db:
            self.assertIsNone(db.execute('SELECT plan_json FROM jobs WHERE id=?',(job,)).fetchone()[0])


if __name__ == '__main__':
    unittest.main()
