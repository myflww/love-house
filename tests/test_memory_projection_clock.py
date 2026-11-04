"""Optimized memory reads retain the authoritative graph projection clock."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.memory import build_context, history, record_turn
from nkb.utils import DAY

T0=1700000000.0


class MemoryProjectionClockTests(unittest.TestCase):
    def setUp(self):
        clock_patch=patch('nkb.core.brain._now',return_value=T0)
        self.core=clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.brain=Brain.new()
        self.nid=record_turn(self.brain,'一起准备周六的海边旅行','到时核对天气','window-a','one')

    def test_context_and_history_use_export_clock_even_when_companion_clock_is_far_ahead(self):
        before=deepcopy(self.brain.to_dict())
        with patch('nkb.companion.memory.now',return_value=T0+1000*DAY):
            exported=self.brain.export()
            self.assertTrue(next(n for n in exported['nodes'] if n['id']==self.nid)['recoverable'])
            result=build_context(self.brain,'海边旅行',session_id='window-a')
            self.assertIn(self.nid,result['memory_ids'])
            self.assertEqual(len(result['history']),2)
            self.assertEqual(history(self.brain,'window-a')[0]['content'],'一起准备周六的海边旅行')
        self.assertEqual(before,self.brain.to_dict())

    def test_core_expiry_is_not_bypassed_by_a_younger_companion_clock(self):
        self.core.return_value=T0+201*DAY
        with patch('nkb.companion.memory.now',return_value=T0):
            exported=self.brain.export()
            self.assertFalse(next(n for n in exported['nodes'] if n['id']==self.nid)['recoverable'])
            self.assertEqual(history(self.brain,'window-a'),[])
            self.assertNotIn(self.nid,build_context(self.brain,'海边旅行')['memory_ids'])

    def test_future_text_version_remains_unavailable_at_the_core_reference_time(self):
        self.brain.nodes[self.nid]['updated']=T0+30
        self.brain.nodes[self.nid]['text']='未来编辑的旅行正文不能提前出现'
        self.core.return_value=T0+10
        with patch('nkb.companion.memory.now',return_value=T0+60):
            row=next(n for n in self.brain.export()['nodes'] if n['id']==self.nid)
            self.assertFalse(row['history_available'])
            self.assertEqual(history(self.brain,'window-a'),[])
            result=build_context(self.brain,'海边旅行',session_id='window-a')
            self.assertNotIn(self.nid,result['memory_ids'])
            self.assertNotIn('未来编辑的旅行正文',result['packet'])


if __name__=='__main__':unittest.main()
