"""Actual Controller transitions cannot revive pending strong-use feedback."""
from copy import deepcopy
import unittest

from tests import test_memory_experience_service as experience_service


class FeedbackLifecycleEdgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=experience_service.MemoryExperienceServiceTests()
        self.fixture.setUp()

    def tearDown(self):self.fixture.tearDown()

    def feedback(self,ticket):
        f=self.fixture
        return f.request('/api/memory/feedback',{'connection_id':f.cid,'delivery_id':ticket['id'],
            'session_id':'window-a','ids':[f.note],'kind':'confirmed'})

    def test_queued_confirmation_is_discarded_when_user_opts_out_and_cannot_return_after_reenable(self):
        f=self.fixture;ticket=f.delivered()
        before=deepcopy(f.host.snapshot('default')['nodes'][f.note])
        self.assertEqual(self.feedback(ticket)[0],200)
        self.assertIn('confirmed',{row['kind'] for row in f.host.usage.pending('default')})
        self.assertEqual(f.request('/api/retention/settings',{'usage_reinforcement':False})[0],200)
        self.assertEqual(f.request('/api/retention/settings',{'usage_reinforcement':True})[0],200)
        f.host.transact('default',lambda brain:brain.add('无关的新记录','退出和重新启用后的一次普通保存'))
        restored=f.host.snapshot('default')['nodes'][f.note]
        self.assertEqual(restored,before)
        self.assertEqual(f.host.usage.pending('default'),[])

    def test_forgetting_after_confirmation_revokes_ticket_and_preserves_other_library_feedback(self):
        f=self.fixture;ticket=f.delivered()
        self.assertEqual(self.feedback(ticket)[0],200)
        other=f.host.transact(f.other,lambda brain:brain.add('独立库的事实','另一份存档的独立原文',id=f.note))
        f.host.usage.enqueue(f.other,[other],'confirmed')
        other_pending=f.host.usage.pending(f.other)
        f.host.forget_memory('default',f.note)
        f.host.transact('default',lambda brain:brain.add('删除后的保存','不能重建已明确忘记的记录'))
        self.assertNotIn(f.note,f.host.snapshot('default')['nodes'])
        self.assertEqual(f.host.usage.pending('default'),[])
        self.assertEqual(f.host.usage.pending(f.other),other_pending)
        self.assertEqual(self.feedback(ticket)[0],400)
        self.assertIsNone(f.host.usage.latest_delivery('default',f.cid))


if __name__=='__main__':unittest.main()
