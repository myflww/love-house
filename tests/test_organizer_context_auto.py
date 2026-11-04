"""Full selected context and explicit/recovered slices, with no remote provider."""
from copy import deepcopy
import json
import tempfile
import unittest

from nkb import Brain
from nkb.companion import record_turn
from nkb.organizer import Organizer, OrganizerError, apply_plan, get_profile, save_profile
from nkb.organizer.rules import SYSTEM_GUIDANCE


class OrganizerAutoContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brain = Brain.new()
        save_profile(self.brain, enabled=True, base_url='https://offline.invalid', model='FAKE',
                     auto_trigger_count=1)
        self.calls = []
        self.credential_calls = []
        self.worker = self.make_worker()

    def make_worker(self):
        def credential(*_):
            self.credential_calls.append(True)
            return 'FAKE-offline-key'

        def send(request, *, timeout):
            self.calls.append(json.loads(json.loads(request.data)['messages'][1]['content']))
            return {'choices':[{'message':{'content':'{"version":1,"operations":[]}'},'finish_reason':'stop'}]}

        worker = Organizer(self.tmp.name,snapshot=lambda _:deepcopy(self.brain.to_dict()),
            apply=lambda lid, plan:apply_plan(self.brain,plan,lid),credential=credential,transport=send)
        self.addCleanup(worker.stop)
        return worker

    def add(self, user, assistant, index):
        rid = record_turn(self.brain,user,assistant,'synthetic-window',str(index))
        self.worker.enqueue('a',[rid])
        return rid

    def due(self, job_id):
        with self.worker.db() as db:db.execute('UPDATE jobs SET next_run=0 WHERE id=?',(job_id,))

    def test_default_full_context_above_48000_and_preview_is_read_only(self):
        originals = []
        for index in range(3):
            user = str(index) + '真实用户原文。' * 4000
            assistant = str(index) + '真实助手原文。' * 4000
            rid = self.add(user,assistant,index)
            originals.append((rid,user,assistant))
        self.assertEqual(get_profile(self.brain)['max_input_chars'],0)
        before = deepcopy(self.brain.to_dict())
        preview = self.worker.preview('a')
        self.assertGreater(preview['input_chars'],48000)
        self.assertEqual(preview['raw_count'],3)
        self.assertFalse(preview['will_call_model'])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.credential_calls,[])
        self.assertEqual(self.brain.to_dict(),before)
        self.assertEqual(self.worker.run_once('a')['status'],'done')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.worker.status('a')['counts'],{'done':3})
        records = {row['id']:row for row in self.calls[0]['raw']}
        for rid,user,assistant in originals:
            self.assertEqual(records[rid]['roles'],{'user':user,'assistant':assistant})

    def test_explicit_character_slice_finishes_both_roles_without_losing_tail(self):
        save_profile(self.brain,max_input_chars=3000,batch_size=1)
        user = '完整用户原文。' * 1000
        assistant = '完整助手原文。' * 1000
        self.add(user,assistant,0)
        for _ in range(40):
            self.assertEqual(self.worker.run_once('a')['status'],'done')
            if self.worker.status('a')['counts'].get('done'):break
        self.assertEqual(self.worker.status('a')['counts'],{'done':1})
        self.assertGreater(len(self.calls),1)
        self.assertTrue(all(len(json.dumps(payload,ensure_ascii=False))<=3000 for payload in self.calls))
        records = [raw for payload in self.calls for raw in payload['raw']]
        self.assertEqual(''.join(row['roles'].get('user','') for row in records),user)
        self.assertEqual(''.join(row['roles'].get('assistant','') for row in records),assistant)

    def test_auto_context_rejection_uses_actual_material_and_survives_timeout_restart(self):
        user = '要保留的用户原文。' * 4000
        assistant = '要保留的助手原文。' * 4000
        self.add(user,assistant,0)
        sizes = []
        completed = []

        def send(request, *, timeout):
            payload = json.loads(json.loads(request.data)['messages'][1]['content'])
            sizes.append(len(json.dumps(payload,ensure_ascii=False)))
            if len(sizes)==1:raise OrganizerError('synthetic context rejection','context_length_exceeded')
            if len(sizes)==2:raise TimeoutError('synthetic timeout')
            completed.extend(payload['raw'])
            return {'choices':[{'message':{'content':'{"version":1,"operations":[]}'},'finish_reason':'stop'}]}

        self.worker.transport = send
        result = self.worker.run_once('a')
        self.assertEqual(result['code'],'context_length_exceeded')
        self.assertGreater(sizes[0],48000)
        self.due(result['job_id'])
        result = self.worker.run_once('a')
        self.assertEqual(result['code'],'timeout')
        self.assertLess(sizes[1],sizes[0])
        self.assertGreater(sizes[1],9000)
        self.due(result['job_id'])
        self.worker.stop()
        self.worker = self.make_worker()
        self.worker.transport = send
        self.assertEqual(self.worker.run_once('a')['status'],'done')
        self.assertEqual(sizes[2],sizes[1])
        for _ in range(10):
            if self.worker.status('a')['counts'].get('done'):break
            self.assertEqual(self.worker.run_once('a')['status'],'done')
        self.assertEqual(self.worker.status('a')['counts'],{'done':1})
        self.assertEqual(''.join(row['roles'].get('user','') for row in completed),user)
        self.assertEqual(''.join(row['roles'].get('assistant','') for row in completed),assistant)

    def test_persona_preview_can_select_full_assistant_material_in_auto_mode(self):
        for index in range(2):
            self.add('合成用户问题'+str(index),'合成助手人格材料。'*3000,index)
        before = deepcopy(self.brain.to_dict())
        preview = self.worker.persona_selection('a')
        self.assertEqual(preview['selected_records'],2)
        self.assertTrue(preview['budget_available'])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.credential_calls,[])
        self.assertEqual(self.brain.to_dict(),before)

    def test_explicit_token_window_uses_serialized_utf8_bound_and_keeps_all_slices(self):
        save_profile(self.brain,context_window=65536,max_output_tokens=8192)
        user = '中文和emoji也按实际编码预算🐳。' * 1500
        assistant = '完整助手尾文。' * 1500
        self.add(user,assistant,0)
        preview = self.worker.preview('a')
        self.assertFalse(preview['will_call_model'])
        self.assertEqual(self.credential_calls,[])
        for _ in range(30):
            self.assertEqual(self.worker.run_once('a')['status'],'done')
            if self.worker.status('a')['counts'].get('done'):break
        self.assertEqual(self.worker.status('a')['counts'],{'done':1})
        self.assertGreater(len(self.calls),1)
        for payload in self.calls:
            used = len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
            self.assertLessEqual(used+len(SYSTEM_GUIDANCE.encode('utf-8'))+1024+8192,65536)
        records = [raw for payload in self.calls for raw in payload['raw']]
        self.assertEqual(''.join(row['roles'].get('user','') for row in records),user)
        self.assertEqual(''.join(row['roles'].get('assistant','') for row in records),assistant)


if __name__=='__main__':unittest.main()
