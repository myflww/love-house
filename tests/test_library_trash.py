"""Reversible Agent/library removal; only temp directories, never user data."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.libraries import LibraryManager,LibraryError

class LibraryTrashTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.manager=LibraryManager(self.root)
    def demo(self):
        path=self.root/'framework-example.brain.json';brain=Brain.new(path,name='示例原文件')
        brain.add('示例节点','示例内容');brain.save();self.manager.register_demo(path)
        return path

    def test_delete_managed_library_retains_file_and_restores_same_identity_idle(self):
        item=self.manager.create_library('另一个Agent');lid=item['id'];path=self.manager.path_for(lid)
        brain=self.manager.open_library(lid);nid=brain.add('独立原文','不得丢失')
        brain.meta['organizer_profile']={'enabled':True,'provider_id':'separate','model':'old-model'};brain.save()
        self.manager.select(lid);before=path.read_bytes()
        result=self.manager.delete_library(lid)
        self.assertTrue(result['deleted']);self.assertFalse(result['raw_files_removed'])
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.manager.selected_id,'default')
        with self.assertRaises(LibraryError):self.manager.open_library(lid)
        trash=self.manager.list_trash();self.assertEqual(trash[0]['id'],lid);self.assertEqual(trash[0]['node_count'],1)
        reloaded=LibraryManager(self.root);restored=reloaded.restore_library(lid)
        self.assertEqual(restored['library']['id'],lid);self.assertEqual(reloaded.selected_id,lid)
        loaded=reloaded.open_library(lid);self.assertIn(nid,loaded.nodes)
        self.assertFalse(loaded.meta['organizer_profile']['enabled']);self.assertFalse(restored['connections_rebound'])

    def test_default_delete_selects_existing_personal_without_touching_demo(self):
        demo=self.demo();before=demo.read_bytes();other=self.manager.create_library('另一个实际库')
        result=self.manager.delete_library('default')
        self.assertEqual(result['default_id'],other['id']);self.assertEqual(self.manager.default_id,other['id'])
        self.assertEqual(self.manager.selected_id,other['id']);self.assertFalse(result['fallback_created'])
        self.assertTrue(self.manager.get_library('demo')['is_demo']);self.assertEqual(demo.read_bytes(),before)

    def test_last_personal_delete_creates_new_blank_identity_not_demo_or_reused_default(self):
        self.demo();old=self.manager.path_for('default');before=old.read_bytes()
        result=self.manager.delete_library('default');replacement=self.manager.default_id
        self.assertNotIn(replacement,('default','demo'));self.assertTrue(result['fallback_created'])
        self.assertEqual(self.manager.selected_id,replacement);self.assertEqual(self.manager.open_library(replacement).nodes,{})
        self.assertEqual(old.read_bytes(),before)
        with self.assertRaises(LibraryError):self.manager.create_library('不能复用旧身份',library_id='default')
        reloaded=LibraryManager(self.root);self.assertEqual(reloaded.default_id,replacement)
        self.assertEqual({r['id'] for r in reloaded.list_trash()},{'default'})

    def test_legacy_default_file_is_never_moved_or_overwritten_by_trash(self):
        directory=self.root/'legacy';directory.mkdir();path=directory/'personal.brain.json'
        brain=Brain.new(path,name='旧版个人库');nid=brain.add('旧记录','原样保留');brain.save()
        before=path.read_bytes();manager=LibraryManager(directory)
        manager.delete_library('default');self.assertEqual(path.read_bytes(),before)
        manager=LibraryManager(directory);self.assertNotEqual(manager.default_id,'default')
        restored=manager.restore_library('default');self.assertEqual(restored['library']['id'],'default')
        self.assertEqual(manager.path_for('default'),path.resolve());self.assertIn(nid,manager.open_library('default').nodes)
        self.assertEqual(path.read_bytes(),before)

    def test_deleted_demo_stays_suppressed_on_registration_and_restart_until_restore(self):
        path=self.demo();before=path.read_bytes();self.manager.select('demo')
        removed=self.manager.delete_library('demo')
        self.assertEqual(removed['selected_id'],'default');self.assertTrue(self.manager.demo_suppressed)
        manager=LibraryManager(self.root);registration=manager.register_demo(path)
        self.assertTrue(registration['registration_suppressed']);self.assertNotIn('demo',{r['id'] for r in manager.list_libraries()})
        self.assertEqual(path.read_bytes(),before)
        restored=manager.restore_library('demo');self.assertTrue(restored['library']['read_only'])
        self.assertFalse(manager.demo_suppressed);self.assertEqual(path.read_bytes(),before)

    def test_no_auto_demo_registration_with_a_new_path_can_override_the_trashed_source(self):
        old=self.demo();self.manager.delete_library('demo')
        alternate=self.root/'new-example.brain.json';Brain.new(alternate,name='新版本示例').save()
        result=self.manager.register_demo(alternate)
        self.assertTrue(result['registration_suppressed'])
        self.manager.restore_library('demo');self.assertEqual(self.manager.path_for('demo'),old.resolve())

    def test_nonselected_delete_keeps_current_view_and_repeat_delete_is_idempotent(self):
        a=self.manager.create_library('A');b=self.manager.create_library('B');self.manager.select(a['id'])
        self.manager.delete_library(b['id']);before=self.manager.registry_path.read_bytes()
        repeat=self.manager.delete_library(b['id'])
        self.assertTrue(repeat['duplicate']);self.assertEqual(self.manager.registry_path.read_bytes(),before)
        self.assertEqual(self.manager.selected_id,a['id'])

    def test_missing_trash_file_cannot_be_silently_replaced_on_restore(self):
        item=self.manager.create_library('文件缺失');path=self.manager.path_for(item['id'])
        self.manager.delete_library(item['id']);path.unlink()
        self.assertFalse(self.manager.list_trash()[0]['restorable'])
        with self.assertRaises(LibraryError):self.manager.restore_library(item['id'])
        self.assertFalse(path.exists());self.assertEqual(len(self.manager.list_trash()),1)

    def test_registry_commit_failure_keeps_old_library_active_and_cleans_only_empty_fallback(self):
        old=self.manager.path_for('default');before=old.read_bytes()
        with patch.object(self.manager._storage,'save',side_effect=OSError('simulated registry write failure')):
            with self.assertRaises(OSError):self.manager.delete_library('default')
        self.assertEqual(self.manager.default_id,'default');self.assertEqual(old.read_bytes(),before)
        self.assertEqual(list(self.manager.directory.glob('*.brain.json')),[old])
        self.assertEqual(self.manager.list_trash(),[])

    def test_trash_does_not_leak_storage_paths_and_rejects_unsafe_ids(self):
        row=self.manager.create_library('safe');self.manager.delete_library(row['id'])
        self.assertFalse(any('path' in key or 'storage' in key for key in self.manager.list_trash()[0]))
        for value in ('../outside','/tmp/a','','UpperCase'):
            with self.subTest(value=value),self.assertRaises(LibraryError):self.manager.delete_library(value)
            with self.subTest(value=value),self.assertRaises(LibraryError):self.manager.restore_library(value)

if __name__=='__main__':unittest.main()
