"""Real HTTP integration; synthetic windows, mock provider, no paid requests."""
import json
import time
import unittest

from nkb.organizer.config import save_profile
from nkb.service.agent_client import event_from_hook
from tests import test_memory_experience_service as fixture


class IdleReviewServiceTests(unittest.TestCase):
    setUp = fixture.MemoryExperienceServiceTests.setUp
    tearDown = fixture.MemoryExperienceServiceTests.tearDown
    connection = fixture.MemoryExperienceServiceTests.connection
    request = fixture.MemoryExperienceServiceTests.request

    def source(self, cid=None, token=None, window='window-a', text='测试来源：讨论核对咖啡偏好的原话。'):
        cid, token = cid or self.cid, token or self.token
        event = event_from_hook({'session_id': window, 'turn_id': str(time.time_ns()), 'status': 'complete',
            'user': text, 'assistant': '测试回答：使用前核对来源，不把推测当事实。'})
        library = self.host.connections.get(cid)['library_id']
        status, value = self.request(f'/api/connections/{cid}/events', event, management=False, token=token,library=library)
        self.assertEqual(status, 200, value)
        self.host.process_pending()
        with self.host.connections.db() as db:
            row = db.execute('SELECT node_ids FROM receipts WHERE id=?', (value['receipt_id'],)).fetchone()
        return json.loads(row['node_ids'])[0]

    def mock(self):
        self.calls = []
        self.host.transact(self.library, lambda b: save_profile(b,
            base_url='https://review.example.invalid', model='synthetic-review'))
        self.host.reviews.engine.credential = lambda lib, profile: {
            'api_key': 'synthetic-not-a-real-key', 'model': profile['model'], 'base_url': profile['base_url']}
        def transport(request, *, timeout):
            body = json.loads(request.data)
            payload = json.loads(body['messages'][1]['content'])
            self.calls.append(payload)
            source = payload['sources'][0]
            part = source['content'][0]
            item = {'type': 'reflection', 'title': '核对来源的交流经验',
                'text': '讨论咖啡时可先核对原话。这是交流方法的推测，不是用户事实。',
                'evidence': [{'id': source['id'], 'role': part['role'], 'quote': part['text'][:20]}]}
            return {'choices': [{'message': {'content': json.dumps({'proposals': [item]})}, 'finish_reason': 'stop'}]}
        self.host.reviews.engine.transport = transport

    def complete(self):
        result = self.host.reviews.engine.run_pending(self.library, manual=True)
        self.assertEqual(result['status'], 'done', result)
        return self.request('/api/idle-review')[1]['proposals'][0]['id']

    def test_management_preview_is_read_only_and_scope_stays_explicit(self):
        self.source()
        other_node = self.source(self.other_cid, self.other_token, 'window-b', '独立库的保密来源，不得出现在另一库。')
        self.mock()
        self.assertEqual(self.request('/api/idle-review', management=False)[0], 401)
        self.assertEqual(self.request('/api/idle-review', management=False, token=self.token)[0], 403)
        status, preview = self.request('/api/idle-review/preview', {})
        self.assertEqual(status, 200, preview)
        self.assertFalse(preview['profile']['enabled'])
        self.assertFalse(preview['model_called'])
        self.assertEqual(preview['counts']['eligible'], 1)
        self.assertNotIn(other_node, json.dumps(preview))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.host.reviews.engine.run_once(self.library, manual=False)['status'], 'paused')

    def test_two_selected_windows_share_one_library_without_rebinding_or_cross_library_import(self):
        second_cid, second_token = self.connection(self.library, 'window-c')
        first = self.source()
        second = self.source(second_cid, second_token, 'window-c', '第二个获准窗口也应能回顾自己的原话。')
        self.mock()
        self.complete()
        self.assertEqual({row['id'] for payload in self.calls for row in payload['sources']}, {first, second})
        before = self.host.reviews.snapshot(self.library)['authorization']['generation']
        status, value = self.request(f'/api/connections/{self.cid}/rebind',
            {'expected_bound_session_id': 'window-a', 'confirm': True})
        self.assertEqual(status, 200, value)
        after = self.host.reviews.snapshot(self.library)['authorization']['generation']
        self.assertNotEqual(before, after)
        preview = self.request('/api/idle-review/preview', {})[1]
        self.assertEqual([r['id'] for r in preview['sources']], [second])
        self.assertEqual(preview['proposals'], [])

    def test_explicit_accept_is_non_fact_rollback_and_runtime_authority_never_persists(self):
        nid = self.source()
        self.mock()
        pid = self.complete()
        self.assertEqual(self.request(f'/api/idle-review/proposals/{pid}/accept', {}, library=self.other)[0], 400)
        status, receipt = self.request(f'/api/idle-review/proposals/{pid}/accept', {})
        self.assertEqual(status, 200, receipt)
        reflection = receipt['result']['id']
        meta = self.host.snapshot(self.library)['nodes'][reflection]['meta']
        self.assertFalse(meta['is_user_fact'])
        self.assertFalse(meta['confirmed'])
        packet = self.host.structured_context(self.library, {'query': '咖啡核对来源', 'max_chars': 20000})
        self.assertNotIn('idle_review_current_authorization_generation', json.dumps(self.host.snapshot(self.library)))
        self.assertNotIn('idle_review_current_authorization_generation', self.host.manager.path_for(self.library).read_text(encoding='utf-8'))
        self.assertNotIn(reflection, [r['id'] for r in self.request('/api/idle-review/preview', {})[1]['sources']])
        self.assertTrue(packet['read_only'])
        self.assertEqual(self.request('/api/idle-review/settings', {'enabled': False})[0], 200)
        self.assertEqual(self.request(f'/api/idle-review/proposals/{pid}/rollback', {})[0], 200)
        self.assertTrue(self.host.snapshot(self.library)['nodes'][reflection]['meta']['memory_disabled'])
        self.host.forget_memory(self.library, nid)
        self.assertEqual(self.request('/api/idle-review')[1]['proposals'], [])
        self.assertEqual(self.request(f'/api/idle-review/proposals/{pid}/accept', {})[0], 400)

    def test_http_manual_run_drains_background_queue_and_settings_reject_injected_authority(self):
        self.source()
        self.mock()
        self.assertEqual(self.request('/api/idle-review/settings', {'allow_local': False})[0], 400)
        status, result = self.request('/api/idle-review/run', {})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['library_id'], self.library)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = self.request('/api/idle-review')[1]
            if value['counts']['processed'] == 1 and not value['running']:
                break
            time.sleep(.01)
        self.assertEqual(value['counts']['pending'], 0, value)
        self.assertEqual(len(self.calls), 1)

    def test_backup_and_trash_restore_require_new_background_review_consent(self):
        from nkb.companion.review import save_review_profile
        from nkb.libraries import LibraryManager
        from nkb.core.brain import Brain
        self.host.transact(self.library, lambda b: save_review_profile(b,enabled=True))
        backup=self.host.backups.create(self.library)
        restored=self.host.backups.restore(backup['id'],self.library)['library']['id']
        self.assertFalse(self.host.snapshot(restored)['meta']['idle_review_profile']['enabled'])
        # Exercise the manager directly: legacy trash need not have passed the
        # current desktop's delete_library pause callback.
        manager=LibraryManager(self.host.root/'legacy-trash-fixture')
        lib=manager.create_library('旧回收站')['id']
        brain=manager.open_library(lib)
        save_review_profile(brain,enabled=True)
        brain.meta['idle_review_current_authorization_generation']='saved-authority-is-not-current'
        brain.persist()
        manager.delete_library(lib)
        manager.restore_library(lib)
        raw=Brain.open(manager.path_for(lib)).to_dict()
        self.assertFalse(raw['meta']['idle_review_profile']['enabled'])
        self.assertNotIn('idle_review_current_authorization_generation',raw['meta'])


if __name__ == '__main__':
    unittest.main()
