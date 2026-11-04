"""Real HTTP integration; synthetic windows, forbidden provider, no paid requests."""
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
        self.calls=[]
        def forbidden(*args,**kwargs):
            self.calls.append(1)
            raise AssertionError('Local directory must not call model or credential services')
        self.host.reviews.engine.credential=forbidden
        self.host.reviews.engine.transport=forbidden

    def complete(self):
        result=self.host.reviews.engine.run_pending(self.library,manual=True)
        self.assertEqual(result['status'],'done',result)
        self.assertEqual(result['model_calls'],0)
        return self.host.reviews.engine.directory(self.library)

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
        self.assertEqual({row['id'] for row in self.host.reviews.engine.directory(self.library)['entries']}, {first,second});self.assertEqual(self.calls,[])
        before = self.host.reviews.snapshot(self.library)['authorization']['generation']
        status, value = self.request(f'/api/connections/{self.cid}/rebind',
            {'expected_bound_session_id': 'window-a', 'confirm': True})
        self.assertEqual(status, 200, value)
        after = self.host.reviews.snapshot(self.library)['authorization']['generation']
        self.assertNotEqual(before, after)
        preview = self.request('/api/idle-review/preview', {})[1]
        self.assertEqual([r['id'] for r in preview['sources']], [second])
        self.assertEqual(preview['proposals'], [])

    def test_new_accept_is_retired_and_legacy_withdrawal_persists_without_recreating_sources(self):
        from hashlib import sha256
        from nkb.companion.review import REFLECTION_SCHEMA
        from nkb.organizer.state import fingerprint
        nid=self.source();self.mock();self.complete()
        pid='old-accepted';reflection='review_'+sha256(pid.encode()).hexdigest()[:24]
        auth=self.host.reviews.snapshot(self.library)['authorization'];source=self.host.snapshot(self.library)['nodes'][nid]
        proposal={'type':'reflection','title':'旧版派生材料','text':'旧版未经验证的交流经验。','evidence':[{'id':nid,'role':'user','quote':source['text'][:12]}],
            'is_user_fact':False,'is_real_experience':False,'effectiveness':'unverified','automatic_activation':False}
        def seed(brain):
            brain.add(proposal['title'],proposal['text'],id=reflection,kind='reflection',meta={'source':'idle_review','library_id':self.library,
                'review_schema':REFLECTION_SCHEMA,'review_proposal_id':pid,'review_origin':True,'review_approved':True,'speaker':'assistant',
                'confirmed':False,'source_ids':[nid],'members':[nid],'source_revisions':{nid:fingerprint(source)},
                'authorization_generation':auth['generation'],'effectiveness':'unverified','is_user_fact':False,'is_real_experience':False})
        self.host.transact(self.library,seed)
        with self.host.reviews.engine.db() as db:
            db.execute('INSERT INTO review_proposals VALUES(?,?,?,?,?,?,?,?)',(pid,self.library,json.dumps({nid:fingerprint(source)}),auth['generation'],json.dumps(proposal),'accepted',reflection,time.time()))
        self.assertEqual(self.request(f'/api/idle-review/proposals/{pid}/accept',{})[0],400)
        self.assertEqual(self.request(f'/api/idle-review/proposals/{pid}/rollback',{},library=self.other)[0],400)
        status,receipt=self.request(f'/api/idle-review/proposals/{pid}/rollback',{})
        self.assertEqual(status,200,receipt);self.assertEqual(receipt['status'],'rolled_back')
        saved=self.host.snapshot(self.library)
        self.assertTrue(saved['nodes'][reflection]['meta']['memory_disabled']);self.assertIn(nid,saved['nodes'])
        self.assertNotIn('idle_review_current_authorization_generation',json.dumps(saved))
        self.assertEqual(self.calls,[])
        self.host.forget_memory(self.library,nid)
        self.assertEqual(self.host.reviews.engine.directory(self.library)['entries'],[])

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
        self.assertEqual(self.calls, [])

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
