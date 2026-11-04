"""Local organization: synthetic sources, no credentials or provider requests."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from nkb import Brain
from nkb.companion.memory import record_turn, build_context
from nkb.companion.ingestion import connected_session_id
from nkb.companion.review import SCHEMA, REFLECTION_SCHEMA, apply_review_plan, get_review_profile, save_review_profile, source_records, revalidate_sources
from nkb.errors import ValidationError
from nkb.organizer.idle_review import IdleReviewer
from nkb.organizer.model import OrganizerConflict
from nkb.organizer.state import fingerprint
from nkb.service.controls import correct, set_enabled, rebuild_source_controls


class IdleReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.brain=Brain.new(); self.brain.meta['library_id']='home'
        rebuild_source_controls(self.brain)
        self.auth={'generation':'g1','connection_ids':['window-a','window-b'],'allow_local':False,
            'connection_scopes':{cid:{'policy':'any','window_id':None,'binding_revision':0} for cid in ('window-a','window-b')}}
        self.lock=threading.RLock(); self.snapshots=0; self.commits=0; self.provider_calls=0
        self.reviewer=self.make_reviewer()

    def source(self,text='今天说的咖啡偏好可能是错的，也应保留当时说法。',connection='window-a',rid=None):
        rid=rid or str(len(self.brain.nodes))
        nid=record_turn(self.brain,text,'助手当时的回答。','session-'+str(connection),rid,connection_id=connection,origin='agent_source_adapter')
        self.brain.nodes[nid]['meta'].update(library_id='home',evidence={'archive_receipt_id':'receipt-'+rid})
        return nid

    def sources(self,count):
        template=deepcopy(self.brain.nodes[self.source(rid='bulk-0')])
        for i in range(1,count):
            node=deepcopy(template);node['id']='bulk-source-'+str(i);node['created']+=i/1000000
            self.brain.nodes[node['id']]=node

    def snapshot(self,library):
        self.assertEqual(library,'home'); self.snapshots+=1
        with self.lock:return {'brain':self.brain.to_dict(),'authorization':deepcopy(self.auth)}

    def apply(self,library,plan,*,commit_guard):
        with self.lock:
            with commit_guard():return apply_review_plan(self.brain,plan,self.auth)

    def finalize(self,library,expected,generation,commit):
        with self.lock:
            revalidate_sources(self.brain,library,self.auth,expected,generation)
            self.commits+=1
            return commit()

    def forbidden(self,*args,**kwargs):
        self.provider_calls+=1
        raise AssertionError('Local organization must never call a provider or request a key')

    def make_reviewer(self,**extra):
        return IdleReviewer(self.tmp.name,snapshot=self.snapshot,apply=self.apply,credential=self.forbidden,
            transport=self.forbidden,finalize=self.finalize,**extra)

    def directory(self,**kwargs):
        return self.reviewer.directory('home',brain=self.brain,authorization=self.auth,**kwargs)

    def legacy(self,source,*,pid='legacy',status='pending',kind='reflection'):
        proposal={'type':kind,'title':'旧版建议','text':'这是旧版派生经验，不是用户事实。','evidence':[{'id':source,'role':'user','quote':self.brain.nodes[source]['text'][:12]}],
            'is_user_fact':False,'is_real_experience':False,'effectiveness':'unverified','automatic_activation':False}
        nid=None
        if status=='accepted':
            nid='review_'+sha256(pid.encode()).hexdigest()[:24]
            self.brain.add(proposal['title'],proposal['text'],id=nid,kind='reflection',meta={'source':'idle_review','library_id':'home',
                'review_schema':REFLECTION_SCHEMA,'review_proposal_id':pid,'review_origin':True,'review_approved':True,'speaker':'assistant',
                'confirmed':False,'important':False,'source_ids':[source],'members':[source],'source_revisions':{source:fingerprint(self.brain.nodes[source])},
                'review_evidence':proposal['evidence'],'authorization_generation':self.auth['generation'],'effectiveness':'unverified','is_user_fact':False,'is_real_experience':False})
        with self.reviewer.db() as db:
            db.execute('INSERT INTO review_proposals VALUES(?,?,?,?,?,?,?,?)',(pid,'home',json.dumps({source:fingerprint(self.brain.nodes[source])}),self.auth['generation'],json.dumps(proposal),'%s'%status,nid,time.time()))
        return pid,nid

    def test_default_disabled_and_manual_directory_never_calls_model_or_changes_memory(self):
        self.source(); original=self.brain.to_dict()
        self.assertFalse(get_review_profile(self.brain)['enabled'])
        preview=self.reviewer.preview('home')
        self.assertTrue(preview['read_only']);self.assertFalse(preview['model_called'])
        self.assertEqual(preview['counts']['pending'],1)
        self.assertEqual(self.reviewer.run_once('home',manual=False)['status'],'paused')
        result=self.reviewer.run_pending('home')
        self.assertEqual(result['status'],'done');self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['graph_changed']);self.assertEqual(result['proposals_created'],0)
        self.assertEqual(self.provider_calls,0);self.assertEqual(self.brain.to_dict(),original)
        state=self.reviewer.status('home')
        self.assertEqual(state['counts']['directory_ready'],1);self.assertEqual(state['summary_status'],'managed_by_organizer')
        self.assertEqual(state['proposals'],[])

    def test_directory_is_metadata_only_original_read_and_same_session_neighbors(self):
        a=self.source(rid='a');b=self.source(rid='b');other=self.source(connection='window-b',rid='c')
        self.reviewer.run_pending('home'); original=self.brain.to_dict()
        rows={r['id']:r for r in self.directory()['entries']}
        self.assertEqual(rows[a]['next_id'],b);self.assertEqual(rows[b]['previous_id'],a)
        self.assertIsNone(rows[other]['previous_id']);self.assertEqual(rows[a]['read_arguments'],{'memory_id':a,'view':'history'})
        self.assertEqual(rows[a]['roles'],['user','assistant']);self.assertNotIn('text',rows[a]);self.assertNotIn('content',rows[a])
        self.assertFalse(self.directory()['complete_library']);self.assertEqual(self.directory()['fallback_tool'],'memory_list')
        self.assertEqual(self.brain.to_dict(),original)
        with self.reviewer.db() as db:dump='\n'.join(db.iterdump())
        self.assertNotIn('助手当时的回答。',dump)

    def test_no_index_or_controls_means_pending_and_honest_fallback(self):
        self.source();self.assertEqual(self.directory()['status'],'pending')
        self.reviewer.run_once('home');self.brain.meta.pop('memory_source_controls')
        packet=self.directory();self.assertEqual(packet['entries'],[])
        self.assertEqual(packet['reason'],'source_controls_not_ready');self.assertEqual(packet['fallback_tool'],'memory_list')

    def test_multiple_authorized_windows_and_library_local_role_boundaries(self):
        a=self.source();b=self.source(connection='window-b');self.source(connection='private');local=self.source(connection=None)
        wrong=self.source();self.brain.nodes[wrong]['meta']['library_id']='other'
        disabled=self.source();self.brain.nodes[disabled]['meta']['memory_disabled']=True
        fake=self.source();self.brain.nodes[fake]['meta']['simulation']=True
        self.assertEqual({r['id'] for r in source_records(self.brain,'home',self.auth)},{a,b})
        self.reviewer.run_once('home');self.assertEqual({r['id'] for r in self.directory()['entries']},{a,b})
        self.auth.update(allow_local=True,generation='g2');self.reviewer.run_once('home')
        self.assertIn(local,{r['id'] for r in self.directory()['entries']})

    def test_bound_window_revision_registered_runtime_and_participant_are_preserved(self):
        nid=self.source();node=self.brain.nodes[nid]
        node['session_id']=connected_session_id('window-a','chosen')
        self.auth['connection_scopes']['window-a']={'policy':'fixed','window_id':'chosen','binding_revision':2}
        node['meta']['evidence'].update(binding_revision=2,source_id='registered',source_runtime_agent_id='fish',participant_scope='external_participant',participant_id='peer-7')
        self.assertEqual(source_records(self.brain,'home',self.auth),[])
        self.auth['source_scopes']={'window-a':{'source_id':'registered','runtime_agent_id':'fish'}}
        self.reviewer.run_once('home');row=self.directory()['entries'][0]
        self.assertEqual(row['participant_id'],'peer-7');self.assertEqual(row['runtime_agent_id'],'fish')
        node['meta']['evidence']['binding_revision']=1
        self.assertEqual(self.directory()['entries'],[])
        node['meta']['evidence']['binding_revision']=2
        self.auth['source_scopes']['window-a']['runtime_agent_id']='other-fish'
        self.assertEqual(self.directory()['entries'],[])

    def test_late_source_and_changed_content_reindex_without_timestamp_watermark(self):
        first=self.source();self.reviewer.run_once('home');late=self.source()
        self.brain.nodes[late]['created']-=3600
        self.assertEqual(self.reviewer.status('home')['counts']['pending'],2) # neighbor changed too
        self.assertEqual(self.reviewer.run_once('home')['status'],'done')
        self.brain.nodes[first]['text']='授权用户编辑后的原话。'
        self.assertNotIn(first,{r['id'] for r in self.directory()['entries']})
        self.assertEqual(self.reviewer.run_once('home')['processed_sources'],1)
        self.assertIn(first,{r['id'] for r in self.directory()['entries']})

    def test_history_corrections_remain_historical_but_user_pause_never_leaks(self):
        old=self.source();correct(self.brain,old,'现在的说法不同。')
        self.assertIn(old,{r['id'] for r in source_records(self.brain,'home',self.auth)})
        self.reviewer.run_once('home');self.assertIn(old,{r['id'] for r in self.directory()['entries']})
        from nkb.companion.catalog import memory_read
        entry=next(r for r in self.directory()['entries'] if r['id']==old)
        self.assertEqual(entry['revision']['state'],'historical')
        self.assertEqual(entry['read_arguments']['view'],'history')
        text=memory_read(self.brain,'home','Synthetic',**entry['read_arguments'])
        self.assertIn('今天说的咖啡偏好',text['text'])
        set_enabled(self.brain,old,False)
        self.assertNotIn(old,{r['id'] for r in self.directory()['entries']})

    def test_derived_pause_checks_live_refs_and_explicit_forget_on_read(self):
        nid=self.source();fact=self.brain.add('摘要','摘要',meta={'source':'organizer','organizer_evidence':[{'id':nid}]})
        self.reviewer.run_once('home');set_enabled(self.brain,fact,False)
        self.assertEqual(self.directory()['entries'],[])
        self.brain.nodes[fact]['meta']['organizer_evidence']=[]
        self.assertEqual(len(self.directory()['entries']),1) # stale map cannot invent a blocker
        self.brain.meta['memory_tombstones']={'node_ids':[nid]}
        self.assertEqual(self.directory()['entries'],[])

    def test_page_is_scoped_and_stale_cursor_fails_closed(self):
        for i in range(5):self.source(rid=str(i))
        self.reviewer.run_once('home');page=self.directory(limit=2)
        ids=[r['id'] for r in page['entries']]
        while page['next_cursor']:
            page=self.directory(limit=2,cursor=page['next_cursor']);ids.extend(r['id'] for r in page['entries'])
        self.assertEqual(len(set(ids)),5)
        cursor=self.directory(limit=1)['next_cursor'];set_enabled(self.brain,ids[-1],False)
        with self.assertRaises(ValidationError):self.directory(limit=1,cursor=cursor)
        with self.assertRaises(ValidationError):self.directory(cursor='broken')
        with self.assertRaises(ValidationError):self.directory(limit=101)

    def test_cohort_enumerated_once_and_page_never_enumerates_graph(self):
        self.sources(1753)
        from nkb.companion.review import source_records as enumerate_sources
        with patch('nkb.organizer.idle_review.source_records',wraps=enumerate_sources) as scan:
            started=time.perf_counter();result=self.reviewer.run_pending('home');elapsed=time.perf_counter()-started
        self.assertEqual(scan.call_count,1);self.assertEqual(result['processed_sources'],1753)
        self.assertEqual(self.commits,7);self.assertLess(elapsed,15)
        original=self.brain.nodes
        class NoScan(dict):
            def values(self):raise AssertionError('directory must not enumerate graph')
            def items(self):raise AssertionError('directory must not enumerate graph')
        self.brain.nodes=NoScan(original)
        try:
            with patch('nkb.organizer.idle_review.source_record',wraps=__import__('nkb.companion.review',fromlist=['source_record']).source_record) as validate:
                page=self.directory(limit=10)
            self.assertEqual(len(page['entries']),10);self.assertLessEqual(validate.call_count,30)
        finally:self.brain.nodes=original

    def test_activity_yields_between_short_commits_and_restart_resumes_exactly(self):
        self.sources(600)
        save_review_profile(self.brain,enabled=True,idle_seconds=30)
        self.reviewer.idle_check=lambda lib,seconds:self.commits<1
        result=self.reviewer.run_once('home',manual=False,idle_for=31)
        self.assertEqual(result['status'],'paused');self.assertEqual(result['processed_sources'],256)
        self.assertEqual(result['remaining'],344)
        restarted=self.make_reviewer();self.assertEqual(restarted.run_pending('home')['processed_sources'],344)
        self.assertEqual(restarted.status('home')['counts']['pending'],0)

    def test_failed_chunk_only_preserves_successfully_committed_progress_and_recovers(self):
        self.sources(300)
        ordinary=self.reviewer.finalize
        def fail_second(*args):
            if self.commits:raise sqlite3.OperationalError('synthetic private raw error')
            return ordinary(*args)
        self.reviewer.finalize=fail_second;result=self.reviewer.run_once('home')
        self.assertEqual(result['status'],'retry');self.assertEqual(result['processed_sources'],256)
        self.assertEqual(self.reviewer.status('home')['counts']['pending'],44)
        self.assertNotIn('private',str(self.reviewer.status('home')['last_error']))
        restarted=self.make_reviewer();self.assertEqual(restarted.run_once('home')['processed_sources'],44)
        self.assertIsNone(restarted.status('home')['last_error'])

    def test_finalizer_revalidates_entire_source_and_neighbors_before_any_commit(self):
        a=self.source();self.source();ordinary=self.reviewer.finalize
        def race(lib,expected,generation,commit):
            self.brain.nodes[a]['text']='提交前内容改变'
            return ordinary(lib,expected,generation,commit)
        self.reviewer.finalize=race;result=self.reviewer.run_once('home')
        self.assertEqual(result['status'],'stale');self.assertFalse(result['progress_advanced'])
        self.assertEqual(self.directory()['indexed_records'],0)
        self.reviewer.finalize=None
        with self.assertRaises(ValidationError):self.reviewer.run_once('home')
        self.assertEqual(self.provider_calls,0)

    def test_revocation_invalidation_cancel_and_stop_fence_late_metadata(self):
        for action in ('revoke','invalidate','cancel','stop'):
            with self.subTest(action=action):
                self.reviewer=self.make_reviewer();self.source(rid=action);ordinary=self.reviewer.finalize
                def race(lib,expected,generation,commit):
                    if action=='revoke':self.auth['generation']+='new'
                    elif action=='invalidate':self.reviewer.invalidate_directory(lib)
                    elif action=='cancel':self.reviewer.cancel(lib)
                    else:self.reviewer.stop()
                    return ordinary(lib,expected,generation,commit)
                self.reviewer.finalize=race;result=self.reviewer.run_once('home')
                self.assertIn(result['status'],('stale','retry'));self.assertFalse(result['progress_advanced'])
                self.assertEqual(self.directory()['entries'],[])

    def test_lease_heartbeat_and_expired_owner_never_writes(self):
        self.source();a=self.reviewer;b=self.make_reviewer();lease=a._claim('home')
        self.assertIsNone(b._claim('home'))
        with a.db() as db:db.execute('UPDATE review_leases SET expires=0')
        replacement=b._claim('home')
        with self.assertRaises(OrganizerConflict):a._check_owned(lease)
        a._release(lease);b._check_owned(replacement);b._release(replacement)
        a.HEARTBEAT_SECONDS=.01;a.LEASE_SECONDS=.08;lease=a._claim('home')
        with a._heartbeat(lease):time.sleep(.12);self.assertIsNone(b._claim('home'))
        a._release(lease)

    def test_existing_archive_is_preserved_and_no_new_accept_is_allowed(self):
        source=self.source();pid,nid=self.legacy(source,status='accepted')
        pending,_=self.legacy(source,pid='pending',kind='strategy_candidate')
        self.reviewer.run_once('home');state=self.reviewer.status('home')
        self.assertEqual(state['counts']['proposals'],2);self.assertTrue(all(p['legacy'] and not p['can_accept'] for p in state['proposals']))
        self.reviewer.cancel('home');self.reviewer.invalidate_directory('home')
        self.assertEqual(self.reviewer.status('home')['counts']['proposals'],2)
        with self.assertRaises(ValidationError):self.reviewer.decide('home',pending,'accept')
        self.assertEqual(self.reviewer.decide('home',pending,'reject')['status'],'rejected')
        self.assertEqual(self.reviewer.decide('home',pid,'rollback')['status'],'rolled_back')
        self.assertTrue(self.brain.nodes[nid]['meta']['memory_disabled'])
        self.assertIn(source,{r['id'] for r in source_records(self.brain,'home',self.auth)})
        self.assertFalse(self.brain.nodes[nid]['meta']['is_user_fact'])

    def test_legacy_archive_has_no_inventory_ceiling_and_stale_page_is_rejected(self):
        source=self.source()
        for i in range(141):self.legacy(source,pid='archive-'+str(i),status='pending' if i<41 else 'rejected')
        page=self.reviewer.status('home');self.assertEqual(page['total'],141)
        cursor=page['next_cursor'];ids=[p['id'] for p in page['proposals']]
        while page['next_cursor']:
            page=self.reviewer.status('home',cursor=page['next_cursor']);ids.extend(p['id'] for p in page['proposals'])
        self.assertEqual(len(set(ids)),141)
        self.reviewer.decide('home',ids[0],'reject')
        with self.assertRaises(ValidationError):self.reviewer.status('home',cursor=cursor)

    def test_legacy_rollback_actual_persist_is_fenced_against_stop_and_expiry(self):
        source=self.source();pid,nid=self.legacy(source,status='accepted')
        self.reviewer.LEASE_SECONDS=.05
        saved=Path(self.tmp.name)/'synthetic-persist.json'
        requested,stopped=threading.Event(),threading.Event();threads=[]
        def persist(library,plan,*,commit_guard):
            with self.lock:
                with commit_guard():
                    result=apply_review_plan(self.brain,plan,self.auth)
                    def stop():
                        requested.set();self.reviewer.stop();stopped.set()
                    thread=threading.Thread(target=stop);threads.append(thread);thread.start()
                    self.assertTrue(requested.wait(1));self.assertFalse(stopped.wait(.08))
                    saved.write_text(json.dumps(self.brain.to_dict()),encoding='utf-8')
            return result
        self.reviewer.apply=persist
        result=self.reviewer.decide('home',pid,'rollback')
        for thread in threads:thread.join(1)
        self.assertTrue(stopped.is_set());self.assertEqual(result['status'],'rolled_back')
        self.assertTrue(json.loads(saved.read_text('utf-8'))['nodes'][nid]['meta']['memory_disabled'])
        self.assertEqual(self.reviewer.status('home')['proposals'][0]['status'],'rolled_back')

    def test_expired_legacy_owner_cannot_enter_actual_graph_persist(self):
        source=self.source();pid,nid=self.legacy(source,status='accepted')
        ordinary=self.reviewer.apply
        def expire(library,plan,*,commit_guard):
            with self.reviewer.db() as db:db.execute('UPDATE review_leases SET expires=0')
            return ordinary(library,plan,commit_guard=commit_guard)
        self.reviewer.apply=expire
        with self.assertRaises(OrganizerConflict):self.reviewer.decide('home',pid,'rollback')
        self.assertFalse(self.brain.nodes[nid]['meta'].get('memory_disabled'))
        self.assertEqual(self.reviewer.status('home')['proposals'][0]['status'],'accepted')

    def test_auto_cadence_preserves_opt_in_and_forget_tombstone_outlives_restart(self):
        source=self.source();save_review_profile(self.brain,enabled=True,idle_seconds=60)
        self.assertEqual(self.reviewer.run_once('home',manual=False,idle_for=59)['status'],'waiting_idle')
        self.assertEqual(self.reviewer.run_once('home',manual=False,idle_for=61)['status'],'done')
        self.reviewer.forget('home',[],[source]);restarted=self.make_reviewer()
        self.assertEqual(restarted.run_once('home')['status'],'waiting');self.assertEqual(restarted.directory('home')['entries'],[])
        with self.assertRaises(ValidationError):save_review_profile(self.brain,api_key='no-secret')


if __name__=='__main__':unittest.main()
