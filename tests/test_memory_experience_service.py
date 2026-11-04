"""Real HTTP checks for scope transparency, corrections and verified feedback."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from nkb.service.agent_client import event_from_hook
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost, make_controller
from nkb.service.httpd import LoopbackHTTPServer


class MemoryExperienceServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = MemoryHost(Path(self.temp.name), key_store=KeyStore(allow_keychain=False),
            organizer_transport=lambda *_a, **_k: self.fail('No paid model calls in experience checks'))
        self.host.updates.settings({'auto_check': False})
        self.server = LoopbackHTTPServer(('127.0.0.1', 0), make_controller(self.host))
        self.host.controller_port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.library = 'default'
        self.other = self.host.manager.create_library('另一独立存档')['id']
        self.note = self.host.transact(self.library, lambda b: b.add('散步安排',
            '明天一起在公园散步，之后讨论读书计划。', kind='fact', tags=['公园', '散步'],
            meta={'source': 'user_confirmed', 'confirmed': True, 'speaker': 'user'}))
        self.cid, self.token = self.connection(self.library, 'window-a')
        self.other_cid, self.other_token = self.connection(self.other, 'window-b')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.host.stop()
        self.temp.cleanup()

    def connection(self, library, window):
        result = self.host.new_connection({'name': window, 'host': 'agent',
            'library_id': library, 'session_scope': window})
        cid = result['connection']['id']
        return cid, self.host.connections.get(cid, secret=True)['token']

    def request(self, path, body=None, *, library=None, management=True, token=None):
        headers = {'Content-Type': 'application/json', 'X-NKB-Library': library or self.library}
        if management:
            headers['X-LoveHouse-Management'] = self.host.management_token
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(f'http://127.0.0.1:{self.server.server_port}' + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            return response.code, json.load(response)

    def delivered(self):
        status, value = self.request(f'/api/connections/{self.cid}/context',
            {'session_id': 'window-a', 'query': '公园散步'}, management=False, token=self.token)
        self.assertEqual(status, 200, value)
        ticket = value['memory_delivery']
        self.assertIn(self.note, ticket['node_ids'])
        return ticket

    def feedback(self, ticket, **updates):
        return {'delivery_id': ticket['id'], 'session_id': 'window-a', 'ids': [self.note],
                'kind': 'confirmed', **updates}

    def test_management_projection_is_scoped_and_not_a_model_adoption_receipt(self):
        self.assertEqual(self.request('/api/memory/experience', management=False)[0], 401)
        self.assertEqual(self.request('/api/memory/experience', management=False, token=self.token)[0], 403)
        status, value = self.request('/api/memory/experience')
        self.assertEqual(status, 200, value)
        self.assertEqual([c['id'] for c in value['connections']], [self.cid])
        row = value['connections'][0]
        self.assertEqual(row['scope']['window_id'], 'window-a')
        self.assertFalse(row['model_adoption_verified'])
        self.assertEqual(next(s for s in row['stages'] if s['id'] == 'provided')['state'], 'waiting')
        encoded = json.dumps(value)
        self.assertNotIn(self.token, encoded)
        self.assertNotIn(self.other_cid, encoded)

    def test_legacy_library_correction_receipt_uses_manager_owned_identity(self):
        status,value=self.request(f'/api/memories/{self.note}/correct',{'text':'现在改为周日早晨在公园散步。'})
        self.assertEqual(status,200,value)
        self.assertTrue(value['saved'])
        self.assertEqual(value['change_scope']['library_id'],self.library)
        self.assertEqual(self.host.snapshot(self.library)['nodes'][value['id']]['meta']['library_id'],self.library)

    def test_delivery_explanation_shows_real_provided_ids_only_in_owner_library(self):
        ticket = self.delivered()
        value = self.request('/api/memory/experience')[1]['connections'][0]
        self.assertEqual(value['recent_delivery']['id'], ticket['id'])
        self.assertEqual([n['id'] for n in value['recent_delivery']['items']], [self.note])
        other = self.request('/api/memory/experience', library=self.other)[1]
        self.assertNotIn(self.note, json.dumps(other))
        self.assertFalse(value['model_adoption_verified'])

    def test_client_cannot_claim_user_confirmation_or_management_authority(self):
        ticket = self.delivered()
        path = f'/api/connections/{self.cid}/memory-feedback'
        self.assertEqual(self.request(path, self.feedback(ticket), management=False, token=self.token)[0], 400)
        self.assertEqual(self.request(path, self.feedback(ticket, management=True), management=False, token=self.token)[0], 400)
        self.assertEqual(self.request(path, self.feedback(ticket, kind='cited'), management=False, token=self.token)[0], 400)

    def test_explicit_user_feedback_requires_matching_library_window_and_live_memory(self):
        ticket = self.delivered()
        body = {'connection_id': self.cid, **self.feedback(ticket)}
        self.assertEqual(self.request('/api/memory/feedback', body, library=self.other)[0], 400)
        self.assertEqual(self.request('/api/memory/feedback', {**body, 'session_id': 'window-b'})[0], 400)
        status, result = self.request('/api/memory/feedback', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['recorded_ids'], [self.note])
        self.assertFalse(result['model_adoption_verified'])
        self.assertEqual(self.request('/api/memory/feedback', body)[1]['duplicate_ids'], [self.note])
        self.request(f'/api/memories/{self.note}/enabled', {'enabled': False})
        self.assertEqual(self.request('/api/memory/feedback', body)[0], 400)

    def test_closed_commitment_is_history_and_cannot_be_updated_with_memory_bearer(self):
        # Older/manual commitment records can omit status; they remain open.
        nid = self.host.transact(self.library, lambda b: b.add('面试约定', '周末一起复习面试',
            kind='commitment', meta={'source': 'user_confirmed', 'speaker': 'user', 'confirmed': True}))
        before = self.host.context(self.cid, self.token, {'session_id': 'window-a', 'query': '未完成的面试约定'})
        self.assertIn(nid, before['memory_ids'])
        path = f'/api/commitments/{nid}/status'
        self.assertEqual(self.request(path, {'status': 'done'}, management=False, token=self.token)[0], 403)
        status, value = self.request(path, {'status': 'done', 'note': '已一起完成'})
        self.assertEqual(status, 200, value)
        self.assertFalse(value['follow_up'])
        self.assertEqual(self.request('/api/memory/timeline?view=open')[1]['entries'], [])
        closed = self.request('/api/memory/timeline?view=closed')[1]['entries']
        self.assertEqual([item['id'] for item in closed], [nid])
        self.assertFalse(closed[0]['follow_up'])

    def test_rebound_or_paused_connection_cannot_reuse_old_delivery_feedback(self):
        ticket = self.delivered()
        self.host.connections.toggle(self.cid, False)
        body = {'connection_id': self.cid, **self.feedback(ticket)}
        self.assertEqual(self.request('/api/memory/feedback', body)[0], 400)
        self.host.connections.toggle(self.cid, True)
        self.host.connections.rebind(self.cid, {'confirm': True, 'expected_bound_session_id': 'window-a'})
        self.assertEqual(self.request('/api/memory/feedback', body)[0], 400)
        self.assertIsNone(self.host.connections.get(self.cid)['bound_session_id'])
        self.host.connections.authorize_session(self.cid, 'window-a')
        self.assertEqual(self.request('/api/memory/feedback', body)[0], 400)
        recent = self.request('/api/memory/experience')[1]['connections'][0]['recent_delivery']
        self.assertIsNone(recent)

    def test_opt_out_rejects_stronger_feedback_without_recreating_pending_use(self):
        ticket = self.delivered()
        self.host.retention_settings(self.library, {'usage_reinforcement': False})
        status, value = self.request('/api/memory/feedback', {'connection_id': self.cid, **self.feedback(ticket)})
        self.assertEqual(status, 400, value)
        self.assertEqual(self.host.usage.pending(self.library), [])

    def test_auxiliary_delivery_failure_does_not_hide_connection_scope_or_archive_status(self):
        def unavailable(*_a, **_kw):
            raise RuntimeError('Synthetic auxiliary journal failure')
        self.host.usage.latest_delivery = unavailable
        status, value = self.request('/api/memory/experience')
        self.assertEqual(status, 200, value)
        connection = value['connections'][0]
        self.assertEqual(connection['scope']['window_id'], 'window-a')
        self.assertFalse(connection['delivery_record_available'])
        self.assertEqual(len(connection['stages']), 5)

    def test_stale_provided_record_cannot_strengthen_material_with_changed_library_attribution(self):
        ticket = self.delivered()
        self.host.transact(self.library, lambda b: b.nodes[self.note]['meta'].update(library_id=self.other))
        status, value = self.request('/api/memory/feedback', {'connection_id': self.cid, **self.feedback(ticket)})
        self.assertEqual(status, 400, value)
        provided = self.request('/api/memory/experience')[1]['connections'][0]['recent_delivery']
        self.assertEqual(provided['items'], [])
        self.assertEqual(provided['unavailable_count'], 1)

    def test_correction_is_independently_verified_after_committed_save(self):
        status, correction = self.request(f'/api/memories/{self.note}/correct',
            {'text': '现在改为在湖边散步，原公园计划已调整。', 'label': '散步安排'})
        self.assertEqual(status, 200, correction)
        status, verified = self.request(f"/api/memories/{correction['id']}/verify",
            {'previous_id': self.note, 'query': '散步安排'})
        self.assertEqual(status, 200, verified)
        self.assertTrue(verified['selection_verified'])
        self.assertTrue(verified['previous_excluded'])
        self.assertFalse(verified['model_adoption_verified'])
        self.assertEqual(self.request(f"/api/memories/{correction['id']}/verify",
            {'previous_id': self.note}, library=self.other)[0], 400)

    def test_citation_feedback_requires_real_same_window_archived_reply(self):
        ticket = self.delivered()
        event = event_from_hook({'session_id': 'window-a', 'turn_id': 'citation-turn', 'status': 'complete',
            'user': '你还记得散步安排吗？', 'assistant': '记得，你说过明天一起在公园散步。'})
        self.host.accept(self.cid, self.token, event)
        deadline = time.monotonic() + 5
        response_node = None
        while time.monotonic() < deadline:
            self.host.process_pending(library_id=self.library)
            with self.host.connections.db() as db:
                row = db.execute("SELECT node_ids FROM receipts WHERE connection_id=? AND status='saved'", (self.cid,)).fetchone()
            if row:
                response_node = json.loads(row['node_ids'])[0]
                break
            time.sleep(.01)
        self.assertIsNotNone(response_node)
        body = self.feedback(ticket, kind='cited', response_node_id=response_node,
            references=[{'id': self.note, 'quote': '明天一起在公园散步'}])
        status, value = self.request(f'/api/connections/{self.cid}/memory-feedback', body,
            management=False, token=self.token)
        self.assertEqual(status, 200, value)
        self.assertEqual(value['evidence'], 'archived_reply_reference')
        forged = {**body, 'response_node_id': self.note}
        self.assertEqual(self.request(f'/api/connections/{self.cid}/memory-feedback', forged,
            management=False, token=self.token)[0], 400)
