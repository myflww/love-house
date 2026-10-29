"""Single-library complete sharing, privacy, fresh identity import and AI sidecars."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nkb import Brain, Config
from nkb.errors import ValidationError
from nkb.companion.memory import record_turn, save_profile
from nkb.service.controls import set_enabled, forget, forget_plan
from nkb.service.host import MemoryHost
from nkb.service.credentials import KeyStore
from nkb.service.sharing import (ShareStore, prepare_share, share_preview, to_markdown,
                                 build_summary_input, validate_summary_response)


class SharingPureTests(unittest.TestCase):
    def setUp(self):
        self.brain = Brain.new(name='一只鱼', config=Config(half_life={'episode': 120}, recovery_days=365))
        self.turn = record_turn(self.brain, '我喜欢无糖茶。', '我记住啦。', '窗口1', '轮1')
        self.fact = self.brain.add('饮品偏好', '用户偏爱无糖茶', kind='preference', meta={
            'source': 'organizer', 'organizer_evidence': [{'id': self.turn, 'role': 'user', 'quote': '我喜欢无糖茶。'}]})
        self.brain.link(self.turn, self.fact, .5)
        save_profile(self.brain, name='小鱼', persona='语气温柔。', user_name='朋友')
        self.archives = [{'id': 'receipt_one', 'library_id': 'only', 'connection_id': 'conn_PRIVATE',
                          'session_id': '窗口1', 'kind': 'turn', 'status': 'saved', 'received': 1234., 'applied': 1235.,
                          'node_ids': json.dumps([self.turn]),
                          'payload': json.dumps({'session_id': '窗口1', 'event_id': '轮1', 'normalized': {
                              'type': 'turn', 'user': '我喜欢无糖茶。', 'assistant': '我记住啦。', 'status': 'complete'}}, ensure_ascii=False)}]

    def package(self):
        return prepare_share(deepcopy(self.brain.to_dict()), deepcopy(self.archives), library_id='only', name='一只鱼', created=123456.)

    def test_complete_export_preserves_original_roles_relationships_and_persona_without_mutation(self):
        original = deepcopy(self.brain.to_dict()); raw = deepcopy(self.archives)
        package = self.package()
        self.assertEqual(package['counts']['node_count'], 2)
        self.assertEqual(package['counts']['edge_count'], 1)
        self.assertEqual(package['counts']['archive_count'], 1)
        self.assertEqual(package['memory']['nodes'][self.turn]['text'], '我喜欢无糖茶。')
        self.assertEqual(package['memory']['nodes'][self.turn]['meta']['assistant_reply'], '我记住啦。')
        self.assertEqual(package['memory']['meta']['companion_profile']['persona'], '语气温柔。')
        self.assertEqual(package['memory']['config']['half_life']['episode'], 120)
        self.assertEqual(package['memory']['config']['recovery_days'], 365)
        self.assertEqual(self.brain.to_dict(), original)
        self.assertEqual(self.archives, raw)
        self.assertTrue(share_preview(package)['exact_copy'])
        self.assertNotIn('only', json.dumps(package))
        self.assertNotIn('conn_PRIVATE', json.dumps(package))

    def test_one_foreign_archive_is_rejected_not_silently_mixed(self):
        self.archives.append({**self.archives[0], 'id': 'other', 'library_id': 'someone_else'})
        with self.assertRaises(ValidationError): self.package()

    def test_credentials_runtime_and_local_paths_removed_but_ordinary_token_word_kept(self):
        node = self.brain.nodes[self.fact]
        node['meta'].update(api_key='FAKE-key-from-struct', token='FAKE-token-from-struct', headers={'Authorization': 'FAKE_AUTH'},
                            credential_ref='FAKE_REF', path='/Users/other/secret.txt', unknown_note='普通 token 分词讨论',
                            origin='harness_hook', connection_id='conn_private_live', source_url='https://example.test/note?key=abc#private')
        node['text'] += '\nAPI key: sk-' + 'X'*24 + '\n文件 /Users/other/private.txt\nBearer ' + 'Y'*25
        self.brain.meta['organizer_profile'] = {'api_key': 'NEVER_INCLUDE', 'base_url': 'https://provider.invalid'}
        self.brain.meta['organizer_log'] = ['HIDDEN_LOG']
        record = json.loads(self.archives[0]['payload']); record['env'] = {'API_KEY': 'HIDDEN_ENV'}
        self.archives[0]['payload'] = json.dumps(record)
        package = self.package(); encoded = json.dumps(package, ensure_ascii=False)
        for secret in ('FAKE-key-from-struct', 'FAKE-token-from-struct', 'FAKE_AUTH', 'FAKE_REF', 'NEVER_INCLUDE', 'HIDDEN_LOG', 'HIDDEN_ENV',
                       'conn_private_live', '/Users/', 'X'*24, 'Y'*25, '?key=abc'):
            self.assertNotIn(secret, encoded)
        self.assertIn('普通 token 分词讨论', encoded)
        self.assertIn('shared_source_', encoded)
        self.assertFalse(share_preview(package)['exact_copy'])
        self.assertGreater(package['privacy']['redactions']['credential_fields'], 0)

    def test_inactive_and_superseded_retained_as_inactive(self):
        set_enabled(self.brain, self.fact, False)
        self.brain.nodes[self.turn]['valid_to'] = 1234.
        self.brain.nodes[self.turn]['superseded_by'] = self.fact
        package = self.package()
        self.assertEqual(package['counts']['node_count'], 2)
        self.assertEqual(package['counts']['disabled_count'], 1)
        self.assertEqual(package['counts']['superseded_count'], 1)
        self.assertTrue(package['memory']['nodes'][self.fact]['meta']['memory_disabled'])

    def test_forgotten_records_and_dependent_copies_never_export(self):
        self.brain.meta['memory_tombstones'] = {'node_ids': [self.turn], 'raw_ids': ['receipt_one'],
                                                'text_hashes': []}
        package = self.package()
        self.assertEqual(package['memory']['nodes'], {})
        self.assertEqual(package['archives'], [])
        self.assertNotIn('我喜欢无糖茶。', json.dumps(package, ensure_ascii=False))

    def test_forgotten_exact_text_hash_redacts_other_copies(self):
        from hashlib import sha256
        self.brain.meta['memory_tombstones'] = {'text_hashes': [sha256('用户偏爱无糖茶'.encode()).hexdigest()]}
        package = self.package()
        self.assertEqual(package['memory']['nodes'][self.fact]['text'], '[用户已忘记]')
        self.assertEqual(package['privacy']['redactions']['forgotten_texts'], 1)

    def test_partial_unindexed_archive_preserved_without_promoting_to_completed_node(self):
        partial = {**self.archives[0], 'id': 'partial', 'node_ids': '[]', 'status': 'archived',
                   'payload': json.dumps({'normalized': {'type': 'turn', 'status': 'partial', 'user': '没说完', 'assistant': ''}})}
        self.archives.append(partial)
        package = self.package()
        self.assertEqual(package['counts']['node_count'], 2)
        self.assertEqual(package['archives'][-1]['record']['normalized']['status'], 'partial')

    def test_markdown_contains_every_node_and_original_event(self):
        package = self.package(); md = to_markdown(package)
        for text in ('我喜欢无糖茶。', '我记住啦。', '用户偏爱无糖茶', '语气温柔。', 'receipt_one', self.turn, self.fact, '完整节点资料与来源'):
            self.assertIn(text, md)
        self.assertIn('JSON 文件', md)
        self.assertFalse(share_preview(package)['markdown_importable'])

    def test_preview_revision_stable_when_only_export_clock_changes(self):
        a = self.package()
        b = prepare_share(deepcopy(self.brain.to_dict()), deepcopy(self.archives), library_id='only', name='一只鱼', created=999.)
        self.assertEqual(a['content_revision'], b['content_revision'])
        self.brain.nodes[self.turn]['text'] += '新的文字'
        self.assertNotEqual(a['content_revision'], self.package()['content_revision'])

    def test_ai_input_is_bounded_whole_records_and_summary_only_sidecar(self):
        for i in range(30): self.brain.add(f'记录{i}', '很长的独立原文。'*80, kind='episode')
        package = self.package(); before = deepcopy(package)
        request = build_summary_input(package, max_chars=2000)
        self.assertLess(request['coverage']['included_nodes'], request['coverage']['total_nodes'])
        self.assertGreater(request['coverage']['omitted_nodes'], 0)
        material = json.loads(request['messages'][1]['content'])
        self.assertTrue(all(r['text'] in {n['text'] for n in package['memory']['nodes'].values()} for r in material['records']))
        result = validate_summary_response('{"summary":"这是一份关于无糖茶的阅读索引。"}', request['coverage'])
        self.assertTrue(result['not_full_memory'])
        self.assertEqual(result['coverage'], request['coverage'])
        self.assertEqual(before, package)
        for invalid in ('没按JSON回复', {'summary': ''}, {'summary': '摘要', 'all_memories_loaded': True}):
            with self.assertRaises(ValidationError): validate_summary_response(invalid, request['coverage'])


class ShareStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.host = MemoryHost(Path(self.temp.name), key_store=KeyStore(allow_keychain=False))
        self.store = ShareStore(self.host)
        self.config = self.host.new_connection({'name': '已有鱼', 'host': 'agent', 'library_id': 'default'})
        self.cid = self.config['connection']['id']; token = self.host.connections.get(self.cid, secret=True)['token']
        self.receipt = self.host.accept(self.cid, token, {'session_id': '原窗口', 'event_id': '原轮次',
                            'normalized': {'type': 'turn', 'turn_id': '原轮次', 'status': 'complete', 'user': '属于这个存档的原话。', 'assistant': '这是助手当时的回复。'}})
        self.host.transact('default', lambda b: save_profile(b, persona='温柔的小鱼'))
        self.other = self.host.manager.create_library('另外的鱼')['id']
        self.host.transact(self.other, lambda b: b.add('别的库', '绝不能进入这个分享文件'))

    def tearDown(self):
        self.host.stop(); self.temp.cleanup()

    def test_preview_and_download_are_single_library_read_only_no_model_key(self):
        before = self.host.snapshot('default'); selected = self.host.manager.selected_id
        preview = self.store.preview('default'); download = self.store.download('default', expected_revision=preview['content_revision'])
        self.assertEqual(preview['archive_count'], 1)
        self.assertEqual(download['mime'], 'application/json; charset=utf-8')
        self.assertNotIn('绝不能进入这个分享文件', download['content'])
        self.assertFalse(preview['model_called'])
        self.assertEqual(before, self.host.snapshot('default'))
        self.assertEqual(selected, self.host.manager.selected_id)
        self.assertEqual(self.host.organizer_view('default')['status']['completed'], 0)

    def test_import_creates_fresh_identity_and_does_not_rebind_or_enable_models(self):
        content = self.store.download('default')['content']; before = self.host.snapshot('default'); connection = self.host.connections.get(self.cid, secret=True)
        count = len(self.host.manager.list_libraries())
        preview = self.store.import_preview(content)
        self.assertTrue(preview['will_create_new_library']); self.assertEqual(count, len(self.host.manager.list_libraries()))
        result = self.store.import_file(content); lid = result['library']['id']
        self.assertNotEqual(lid, 'default'); self.assertNotEqual(lid, self.other)
        self.assertFalse(result['connections_rebound']); self.assertFalse(result['organizer_enabled'])
        self.assertEqual(connection, self.host.connections.get(self.cid, secret=True))
        self.assertEqual(before, self.host.snapshot('default'))
        imported = self.host.snapshot(lid)
        self.assertEqual({n['text'] for n in imported['nodes'].values()}, {'属于这个存档的原话。'})
        self.assertEqual(imported['meta']['companion_profile']['persona'], '温柔的小鱼')
        self.assertFalse(imported['meta']['organizer_profile']['enabled'])
        self.assertEqual(self.host.connections.list(lid), [])
        archives = self.host.connections.archives(lid)
        self.assertEqual(len(archives), 1)
        self.assertNotEqual(archives[0]['id'], self.receipt['receipt_id'])
        evidence = next(iter(imported['nodes'].values()))['meta']['evidence']
        self.assertEqual(evidence['archive_receipt_id'], archives[0]['id'])
        self.assertEqual(self.host.manager.selected_id, lid)

    def test_stale_preview_does_not_download_changed_data(self):
        preview = self.store.preview('default')
        self.host.transact('default', lambda b: b.add('新内容', '新的一句话'))
        with self.assertRaises(ValidationError): self.store.download('default', expected_revision=preview['content_revision'])

    def test_bad_import_does_not_create_a_library_or_change_any_existing_one(self):
        content = self.store.download('default')['content']; count = len(self.host.manager.list_libraries())
        for field, bad in [('format', 'other'), ('scope', 'all_libraries'), ('name', '')]:
            value = json.loads(content); value[field] = bad
            with self.assertRaises(ValidationError): self.store.import_file(json.dumps(value))
        value = json.loads(content); value['memory']['nodes'][next(iter(value['memory']['nodes']))]['salience'] = 'wrong'
        with self.assertRaises(ValidationError): self.store.import_file(json.dumps(value))
        value = json.loads(content); value['archives'][0]['received'] = {'not': 'a time'}
        with self.assertRaises(ValidationError): self.store.import_file(json.dumps(value))
        self.assertEqual(count, len(self.host.manager.list_libraries()))
        self.assertEqual(len(self.host.connections.list()), 1)

    def test_import_strips_injected_provider_and_credentials_and_keeps_inactive_state(self):
        value = json.loads(self.store.download('default')['content'])
        node = next(iter(value['memory']['nodes'].values())); node['meta'].update(memory_disabled=True, api_key='INJECTED_KEY')
        value['memory']['meta']['organizer_profile'] = {'enabled': True, 'provider_id': 'connection:BAD', 'model': 'PAY'}
        value['memory']['meta']['runtime'] = {'path': '/Users/other/secret'}
        imported = self.store.import_file(json.dumps(value)); lid = imported['library']['id']; brain = self.host.snapshot(lid)
        self.assertTrue(next(iter(brain['nodes'].values()))['meta']['memory_disabled'])
        self.assertNotIn('INJECTED_KEY', json.dumps(brain))
        self.assertNotIn('PAY', json.dumps(brain))
        self.assertNotIn('runtime', brain['meta'])

    def test_forgotten_material_is_not_reintroduced_in_share_or_import(self):
        nid = next(iter(self.host.snapshot('default')['nodes']))
        self.host.forget_memory('default', nid)
        package = self.store.download('default')
        self.assertNotIn('属于这个存档的原话。', package['content'])
        lid = self.store.import_file(package['content'])['library']['id']
        self.assertEqual(self.host.snapshot(lid)['nodes'], {})
        self.assertEqual(self.host.connections.archives(lid), [])

    def test_ai_summary_sidecar_keeps_complete_memory_and_preview_counts(self):
        package = self.store.prepare('default'); summary_input = build_summary_input(package)
        summary = validate_summary_response({'summary': '用户和小鱼的交流记录。'}, summary_input['coverage'])
        content = json.loads(self.store.download('default', reading_summary=summary)['content'])
        self.assertEqual(content['reading_summary']['text'], summary['text'])
        self.assertTrue(content['reading_summary']['not_full_memory'])
        self.assertEqual(content['memory'], package['memory'])
        self.assertEqual(content['archives'], package['archives'])


if __name__ == '__main__': unittest.main()
