import json
from copy import deepcopy
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.handoff import PROFILES, readable_time, window_handoff
from nkb.companion.memory import record_turn
from nkb.companion.persona import import_persona
from nkb.errors import ValidationError


class WindowHandoffTests(unittest.TestCase):
    def test_scoped_read_only_and_human_dates(self):
        b = Brain.new(name="鲸鱼娘")
        b.meta['library_id'] = 'a'
        record_turn(b, '喜欢温水', '我也喜欢', 'old', 'one')
        import_persona(b, '温柔的小鲸鱼', {'origin':'user_import'})
        before = deepcopy(b.to_dict())
        packet = window_handoff(b, 'a', '鲸鱼娘', profile='M')
        self.assertEqual(before, b.to_dict())
        self.assertIn('温柔的小鲸鱼', packet['text'])
        self.assertIn('喜欢温水', packet['text'])
        self.assertIn('T', packet['packet']['records'][0]['source_time'])
        self.assertFalse(packet['automatic_recording'])
        self.assertFalse(packet['packet']['records'][0]['assistant_statement']['is_user_fact'])
        with self.assertRaises(ValidationError): window_handoff(b, 'b', '别的库')

    def test_sizes_are_bounded_whole_records_and_no_false_complete(self):
        b = Brain.new()
        for i in range(80):
            b.add(f'事实{i}', '不能' + '截断原句' * 40, meta={'source':'user_confirmed','confirmed':True})
        counts = []
        for profile, limit in PROFILES.items():
            p = window_handoff(b, 'a', '档案', profile=profile)
            self.assertLessEqual(len(p['text']), limit)
            self.assertEqual(p['chars'], len(p['text']))
            parsed = json.loads(p['text'].split('```json\n')[1].split('\n```')[0])
            self.assertEqual(parsed, p['packet'])
            self.assertEqual(p['included_memories'] + p['omitted_memories'], 80)
            self.assertFalse(p['all_memory_loaded'])
            self.assertTrue(all(r['text'] == '不能' + '截断原句' * 40 for r in parsed['records']))
            counts.append(p['included_memories'])
        self.assertLessEqual(counts[0], counts[1]); self.assertLessEqual(counts[1], counts[2])

    def test_disabled_and_forgotten_evidence_not_in_packet(self):
        b = Brain.new()
        b.add('停用', 'NO_DISABLED', meta={'memory_disabled':True})
        b.add('遗忘', 'NO_FORGOTTEN', meta={'forgotten':True})
        b.add('好', 'KEEP')
        p = window_handoff(b, 'a', '家')
        self.assertNotIn('NO_', p['text']); self.assertIn('KEEP', p['text'])

    def test_credentials_scrubbed_invalid_profile_and_demo_rejected(self):
        b = Brain.new()
        b.add('资料', 'api_key=FAKEEXAMPLESECRET0123456789 /Users/example/private.txt')
        p = window_handoff(b, 'a', '家')
        self.assertNotIn('FAKEEXAMPLESECRET', p['text'])
        self.assertNotIn('/Users/example', p['text'])
        self.assertGreater(p['redactions']['credential_texts'], 0)
        with self.assertRaises(ValidationError):window_handoff(b, 'a', '家', profile='XL')
        b.meta['demo'] = True
        with self.assertRaises(ValidationError):window_handoff(b, 'a', '家')

    def test_missing_source_time_remains_unknown_and_roleplay_is_preserved(self):
        b = Brain.new()
        b.add('故事里的约定', '在月亮上见面', kind='episode', meta={'source_time_unknown':True,'domain':'roleplay'})
        item = window_handoff(b, 'a', '家')['packet']['records'][0]
        self.assertEqual(item['source_time'], '时间未提供')
        self.assertEqual(item['domain'], 'roleplay')

    def test_time_never_presents_missing_as_now(self):
        self.assertEqual(readable_time(None, 1000), '时间未提供')
        self.assertIn('约 8 个月前', readable_time(0, 8*30*86400))
        self.assertIn('未来时间', readable_time(10000, 1000))

    def test_freeform_atom_subject_and_qualifiers_are_also_scrubbed(self):
        import time
        b = Brain.new()
        secret = 'api_key=FAKE_HANDOFF_SCOPE_SECRET_0123456789'
        source = b.add('来源', secret, meta={'source':'conversation_turn','assistant_reply':'原文'})
        b.add('提取资料', secret, meta={'source':'organizer', 'memory_atom':{
            'schema':'love-house-memory-atom/v1','layer':'fact','subject':secret,
            'predicate':'said','value':secret,'qualifiers':{'scope':secret,'polarity':'unknown'},
            'domain':'real','certainty':'clear','recorded_at':time.time()+1,
            'evidence':[{'id':source,'role':'user'}]}})
        p = window_handoff(b, 'a', '家')
        self.assertEqual(p['included_memories'], 2)
        self.assertNotIn('FAKE_HANDOFF_SCOPE_SECRET', p['text'])


if __name__ == '__main__': unittest.main()
