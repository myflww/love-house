"""Recorded mistakes and corrections remain reachable within live permissions."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.catalog import memory_bootstrap, memory_catalog, memory_read
from nkb.companion.memory import build_context, record_turn, remember
from nkb.companion.structured import build_structured_context
from nkb.companion.versions import read_memory_versions
from nkb.errors import ValidationError
from nkb.service.controls import (correct, forget, forget_plan, history_restore_preview,
                                 rebuild_source_controls, restore_history, set_enabled)


class HistoryRetrievalTests(unittest.TestCase):
    def brain(self, library='home'):
        brain=Brain.new();brain.meta.update(library_id=library,long_term_archive=True)
        return brain

    def revision(self, brain):
        raw=record_turn(brain,'我以为朋友没有回信是因为生气了。','我当时也猜他在生气。','window-a','misunderstanding')
        old=brain.add('朋友未回信的理解','我以为朋友没有回信是因为生气了。',kind='fact',
            meta={'source':'organizer','library_id':'home','members':[raw],
                  'organizer_evidence':[{'id':raw,'role':'user'}]})
        new=correct(brain,old,'朋友后来解释没有回信只是工作很忙，并没有生气。')['id']
        return raw,old,new

    def records(self, brain, query='朋友回信', **kwargs):
        return build_structured_context(brain,query,library_id='home',max_chars=32000,**kwargs)['memory_context']['records']

    def test_default_current_and_comparison_preserve_both_utterances_and_sources(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        before=deepcopy(brain.to_dict())
        current=self.records(brain)
        self.assertIn(new,{r['id'] for r in current})
        self.assertFalse({raw,old}&{r['id'] for r in current})
        result=build_structured_context(brain,'朋友回信前后理解有什么变化',library_id='home',max_chars=32000)
        packet=result['memory_context'];records={r['id']:r for r in packet['records']}
        self.assertEqual(result['view'],'comparison')
        self.assertTrue({raw,old,new}<=records.keys())
        self.assertEqual(records[old]['revision']['superseded_by'],new)
        self.assertEqual(records[old]['revision']['state'],'historical')
        self.assertFalse(records[old]['validity']['active'])
        self.assertEqual(records[old]['interpretation'],'historical_evidence')
        self.assertEqual(records[raw]['assistant_statement']['value'],'我当时也猜他在生气。')
        self.assertEqual(records[old]['source']['evidence'][0]['id'],raw)
        self.assertEqual(records[old]['source']['evidence'][0]['role'],'user')
        for row in records.values():
            self.assertIsInstance(row['recorded_at'],(int,float))
            self.assertFalse(row['revision']['world_truth_assessed'])
        self.assertTrue(any(r['type']=='later_correction' for r in packet['relations']))
        self.assertEqual(brain.to_dict(),before)

    def test_explicit_view_overrides_language_and_two_authorized_windows_share_one_library(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        for session in ('window-a','window-b'):
            result=build_context(brain,'朋友以前为什么没有回信',session_id=session,library_id='home',view='current')
            self.assertNotIn(old,result['memory_ids']);self.assertNotIn(raw,result['memory_ids'])
            history=build_context(brain,'朋友回信',session_id=session,library_id='home',view='history',max_chars=32000)
            self.assertTrue({raw,old,new}<=set(history['memory_ids']))
        independent=self.brain('independent')
        remember(independent,'另一个独立窗口中的朋友说法')
        self.assertNotIn('工作很忙',json.dumps(build_context(independent,'朋友',library_id='independent'),ensure_ascii=False))
        with self.assertRaises(ValidationError):memory_read(brain,'independent','Wrong',memory_id=old,view='history')

    def test_metadata_only_correction_keeps_exact_literal_guards_but_not_edited_sources(self):
        from nkb.organizer.state import fingerprint
        for edited in (False,True):
            with self.subTest(edited=edited):
                brain=self.brain();raw=record_turn(brain,'我猜朋友生气了。','我也不确定。','window-a','literal')
                old=brain.add('朋友的原话记录','我猜朋友生气了。',kind='episode',meta={
                    'source':'organizer','attributed_material':True,'statement_attribution':'user',
                    'statement_source_revisions':{raw:fingerprint(brain.nodes[raw])},
                    'organizer_evidence':[{'id':raw,'role':'user'}],'members':[raw]})
                if edited:brain.nodes[raw]['text']='原文已被修改成另一件事。'
                new=correct(brain,old,'后来朋友说他只是很忙。')['id']
                ids={r['id'] for r in self.records(brain,query='朋友',view='history')}
                self.assertIn(new,ids)
                self.assertEqual(old in ids,not edited)

    def test_supplied_base_context_cannot_bypass_paused_source_exclusion(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        set_enabled(brain,old,False)
        packet=build_structured_context(brain,'朋友',{'memory_ids':[raw,old,new]},library_id='home',view='history')
        self.assertEqual(packet['memory_context']['records'],[])

    def test_explicit_pause_is_never_bypassed_by_history_or_versions(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        set_enabled(brain,old,False)
        self.assertEqual(brain.nodes[old]['meta']['memory_disabled_origin'],'explicit_user_action')
        self.assertIn(raw,brain.meta['memory_source_controls']['blocked_by'])
        for mode in ('current','history','comparison'):
            self.assertFalse(self.records(brain,view=mode))
            self.assertFalse(memory_catalog(brain,'home','Home',view=mode)['entries'])
            self.assertEqual(memory_bootstrap(brain,'home','Home',view=mode)['total_memories'],0)
            for nid in (raw,old,new):
                with self.assertRaises(ValidationError):memory_read(brain,'home','Home',memory_id=nid,view=mode)
        versions=read_memory_versions(brain,'home',new)
        self.assertTrue(all(not r['available'] and 'text' not in r and 'label' not in r for r in versions['entries']))
        self.assertEqual(history_restore_preview(brain,old)['node_ids'],[])

    def test_forgetting_and_deleted_sources_do_not_resurrect_in_history(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        brain.remove(raw)
        self.assertNotIn(old,{r['id'] for r in self.records(brain,view='history')})
        with self.assertRaises(ValidationError):memory_read(brain,'home','Home',memory_id=old,view='history')
        forget(brain,forget_plan(brain,old))
        reopened=Brain(brain.to_dict())
        self.assertFalse(self.records(reopened,view='comparison'))
        self.assertNotIn(old,reopened.nodes);self.assertNotIn(new,reopened.nodes)

    def test_cross_library_source_and_replacement_never_return_bodies(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        brain.nodes[raw]['meta']['library_id']='foreign'
        self.assertNotIn(old,{r['id'] for r in self.records(brain,view='history')})
        brain.nodes[new]['meta']['library_id']='foreign'
        versions=read_memory_versions(brain,'home',old)
        self.assertNotIn(new,{r['id'] for r in versions['entries']})
        self.assertNotIn('工作很忙',json.dumps(versions,ensure_ascii=False))

    def legacy(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        for node in brain.nodes.values():node['meta'].pop('memory_revision',None)
        brain.nodes[old]['meta']['memory_disabled']=True
        return brain,raw,old,new

    def test_legacy_requires_reviewed_scope_and_restores_only_historical_access(self):
        brain,raw,old,new=self.legacy()
        self.assertNotIn(old,{r['id'] for r in self.records(brain,view='history')})
        preview=history_restore_preview(brain,new)
        self.assertEqual(preview['node_ids'],[old]);self.assertEqual(preview['source_ids'],[raw])
        self.assertTrue(read_memory_versions(brain,'home',new)['legacy_history_requires_confirmation'])
        with self.assertRaises(ValidationError):restore_history(brain,new,expected_revision=preview['expected_revision'])
        restored=restore_history(brain,new,confirm=True,expected_revision=preview['expected_revision'])
        self.assertEqual(set(restored['historical_ids']),{old,raw})
        self.assertFalse(restored['current_memory_restored'])
        self.assertEqual(brain.nodes[old]['meta']['memory_disabled_origin'],'legacy_history_restore')
        self.assertTrue({raw,old,new}<={r['id'] for r in self.records(brain,view='comparison')})
        self.assertFalse({raw,old}&{r['id'] for r in self.records(brain)})

    def test_legacy_restore_never_overrides_explicit_pause_and_rejects_changed_scope(self):
        brain,raw,old,new=self.legacy()
        preview=history_restore_preview(brain,old)
        brain.nodes[raw]['text']='原文已被后来编辑'
        with self.assertRaises(ValidationError):restore_history(brain,old,confirm=True,expected_revision=preview['expected_revision'])
        brain.nodes[old]['meta']['memory_disabled_origin']='explicit_user_action'
        preview=history_restore_preview(brain,old)
        self.assertEqual(preview['node_count'],0)
        restore_history(brain,old,confirm=True,expected_revision=preview['expected_revision'])
        self.assertTrue(brain.nodes[old]['meta']['memory_disabled'])
        self.assertNotIn(old,{r['id'] for r in self.records(brain,view='history')})

    def test_catalog_cursors_and_read_chunks_cannot_cross_view_or_edits(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        page=memory_catalog(brain,'home','Home',view='history',limit=1)
        with self.assertRaises(ValidationError):memory_catalog(brain,'home','Home',cursor=page['next_cursor'],view='current')
        chunk=memory_read(brain,'home','Home',memory_id=old,view='history',max_chars=5)
        self.assertEqual(chunk['text'],brain.nodes[old]['text'][:5])
        with self.assertRaises(ValidationError):memory_read(brain,'home','Home',memory_id=old,view='current',revision=chunk['revision'])
        brain.nodes[raw]['meta']['memory_disabled']=True
        with self.assertRaises(ValidationError):memory_read(brain,'home','Home',memory_id=old,view='history',revision=chunk['revision'])

    def test_single_target_read_projects_once_and_validates_live_pause(self):
        brain=self.brain();nid=remember(brain,'我关于咖啡的完整原话')
        for i in range(20):remember(brain,f'其他材料{i}')
        from nkb.companion import catalog
        with patch.object(catalog,'_record',wraps=catalog._record) as project:
            first=memory_read(brain,'home','Home',memory_id=nid,max_chars=2)
            self.assertEqual(project.call_count,1)
            memory_read(brain,'home','Home',memory_id=nid,offset=2,max_chars=2,revision=first['revision'])
            self.assertEqual(project.call_count,2)
        brain.nodes[nid]['meta']['memory_disabled']=True
        with self.assertRaises(ValidationError):memory_read(brain,'home','Home',memory_id=nid,revision=first['revision'])

    def test_versions_page_chain_and_source_controls_rebuild_use_live_metadata(self):
        brain=self.brain();raw,old,new=self.revision(brain)
        page=read_memory_versions(brain,'home',new,limit=1);entries=list(page['entries'])
        while page['next_cursor']:
            page=read_memory_versions(brain,'home',new,limit=1,cursor=page['next_cursor']);entries.extend(page['entries'])
        self.assertEqual({r['id'] for r in entries},{raw,old,new})
        self.assertEqual(page['current_id'],new)
        self.assertTrue(all(r['available'] for r in entries))
        brain.nodes[old]['meta']['memory_disabled']=True
        summary=rebuild_source_controls(brain)
        self.assertEqual(summary['blocked_sources'],1)
        self.assertEqual(brain.meta['memory_source_controls']['blocked_by'][raw],[old])
        brain.nodes[old]['meta']['organizer_evidence']=[]
        rebuild_source_controls(brain)
        self.assertEqual(brain.meta['memory_source_controls']['blocked_by'],{})


if __name__=='__main__':unittest.main()
