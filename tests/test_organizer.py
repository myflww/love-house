"""Organizer acceptance uses fake transport and disposable queues only; no real provider/API key."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest

from nkb import Brain
from nkb.errors import ValidationError
from nkb.organizer.config import endpoint
from nkb.companion import record_turn, save_profile as save_persona
from nkb.organizer import (Organizer, OrganizerError, OrganizerConflict, apply_plan, get_profile,
                           rollback, save_profile, semantic_recall, review_candidate, forget_plan_data)

KEY = "FAKE-organizer-key-never-real"


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.brains = {"a":Brain.new(), "b":Brain.new()}
        self.calls = []
        self.apply_calls = []
        self.reply = self.default_reply
        self.apply_failure = False
        self.credential_calls = []
        self.organizer = self.make()
        self.addCleanup(self.organizer.stop)
        for brain in self.brains.values():
            save_profile(brain, enabled=True, base_url="https://provider.invalid/v1", model="offline-test", provider_id="fake")

    def make(self, archive=None):
        def snapshot(lid): return deepcopy(self.brains[lid].to_dict())
        def apply(lid, plan):
            self.apply_calls.append(deepcopy(plan))
            if self.apply_failure: raise OSError("save failed "+KEY)
            return apply_plan(self.brains[lid],plan,lid)
        def credential(lid, profile):
            self.credential_calls.append(lid)
            return KEY
        def send(request, timeout):
            payload = json.loads(json.loads(request.data)["messages"][1]["content"])
            self.calls.append(payload)
            output = self.reply(payload)
            return {"choices":[{"message":{"content":json.dumps(output,ensure_ascii=False)},"finish_reason":"stop"}]}
        return Organizer(self.tmp.name,snapshot=snapshot,apply=apply,credential=credential,transport=send,read_archive=archive)

    def raw(self, user="我住在北京", assistant="这是助手原话", lid="a", receipt=None):
        brain = self.brains[lid]
        nid = record_turn(brain,user,assistant,"session",str(len(brain.nodes)))
        if receipt: brain.nodes[nid]["meta"]["evidence"] = {"archive_receipt_id":receipt}
        return nid

    def op(self, payload, **fields):
        raw = payload["raw"][0]
        role = "user" if "user" in raw["roles"] else next(iter(raw["roles"]))
        return {"action":"remember","layer":"fact","key":"home.city","text":"模型语义概括，不直接冒充用户原话",
                "evidence":[{"id":raw["id"],"role":role,"quote":raw["roles"][role][:100]}],
                "aliases":["安家地点"],"certainty":"clear","domain":"real",**fields}

    def default_reply(self, payload): return {"version":1,"operations":[self.op(payload)]}
    def generated(self,lid="a"): return [n for n in self.brains[lid].nodes.values() if n["meta"].get("source")=="organizer"]
    def run_raw(self, user="我住在北京", **kwargs):
        nid = self.raw(user,**kwargs)
        self.organizer.enqueue(kwargs.get("lid","a"),[nid])
        return nid,self.organizer.run_once(kwargs.get("lid","a"))

    def test_clear_fact_is_automatic_verbatim_sourced_and_idempotent_without_changing_raw(self):
        nid = self.raw()
        original = deepcopy(self.brains["a"].nodes[nid])
        self.organizer.enqueue("a",[nid]); result=self.organizer.run_once("a")
        self.assertEqual(result["status"],"done")
        node=self.generated()[0]
        self.assertEqual(node["text"],"我住在北京")
        self.assertEqual(node["meta"]["organizer_evidence"][0]["id"],nid)
        self.assertEqual(self.brains["a"].nodes[nid],original)
        self.assertEqual(self.organizer.enqueue("a",[nid])["queued"],0)
        duplicate=apply_plan(self.brains["a"],self.apply_calls[-1],"a")
        self.assertTrue(duplicate["duplicate"]);self.assertEqual(len(self.generated()),1)
        self.assertEqual(self.organizer.status('a')['jobs'][0]['raw_ids'],[nid])

    def test_quote_cannot_cherry_pick_away_a_user_negation(self):
        self.reply=lambda p:{'version':1,'operations':[self.op(p,layer='preference',
                      evidence=[{'id':p['raw'][0]['id'],'role':'user','quote':'喜欢咖啡'}])]}
        self.run_raw('我不喜欢咖啡。')
        self.assertEqual(self.generated()[0]['text'],'我不喜欢咖啡。')

    def test_duplicate_merge_and_new_fact_supersession_preserve_old_history(self):
        self.run_raw(); old=self.generated()[0]["id"]
        self.reply=lambda p:{"version":1,"operations":[self.op(p,action="merge",target_id=old)]}
        _,merged=self.run_raw()
        self.assertEqual(merged["status"],"done");self.assertEqual(len(self.generated()),1)
        self.assertEqual(len(self.brains["a"].nodes[old]["meta"]["organizer_evidence"]),2)
        self.reply=lambda p:{"version":1,"operations":[self.op(p,action="supersede",target_id=old)]}
        _,updated=self.run_raw("现在我住在上海")
        self.assertEqual(updated["status"],"done")
        self.assertIsNotNone(self.brains["a"].nodes[old]["valid_to"])
        self.assertEqual(self.brains["a"].nodes[old]["text"],"我住在北京")

    def test_important_manual_fact_and_persona_are_not_automatically_overwritten(self):
        brain=self.brains["a"]
        old=brain.add("我住在北京","我住在北京",kind="fact",meta={"source":"user_confirmed","important":True})
        save_persona(brain,persona="明确重要人格")
        self.reply=lambda p:{"version":1,"operations":[self.op(p,action="supersede",target_id=old)]}
        _,result=self.run_raw("现在我住在上海")
        self.assertEqual(result["status"],"done");self.assertEqual(self.generated(),[])
        self.assertIsNone(brain.nodes[old]["valid_to"])
        self.assertEqual(brain.meta["companion_profile"]["persona"],"明确重要人格")
        self.assertEqual(len(brain.meta["organizer_candidates"]),1)

    def test_assistant_self_claim_roleplay_and_uncertainty_are_review_candidates(self):
        self.reply=lambda p:{"version":1,"operations":[self.op(p,evidence=[{"id":p['raw'][0]['id'],"role":"assistant","quote":"你有一个女儿"}])]}
        nid=self.raw("只是一个普通问题","你有一个女儿")
        self.organizer.enqueue("a",[nid]);self.assertEqual(self.organizer.run_once("a")["status"],"done")
        self.assertEqual(self.generated(),[])
        self.reply=self.default_reply
        self.run_raw("角色扮演：我住在火星")
        self.assertEqual(self.generated(),[])
        candidate=self.brains['a'].meta['organizer_candidates'][-1]
        with self.assertRaises(OrganizerError):review_candidate(self.brains['a'],candidate['id'],'accept')

    def test_failed_tool_result_is_an_observed_episode_never_a_confirmed_user_fact(self):
        nid=self.brains['a'].add('网页工具失败','HTTP 404，任务未完成',kind='episode',
                                meta={'source':'tool_observation','outcome':'failed','origin':'browser'})
        self.organizer.enqueue('a',[nid])
        self.assertEqual(self.organizer.run_once('a')['status'],'done')
        node=self.generated()[0]
        self.assertEqual(node['kind'],'episode')
        self.assertIn('failed',node['text']);self.assertIn('不是用户确认事实',node['text'])
        self.assertFalse(node['meta']['confirmed'])
        self.assertEqual(node['meta']['evidence_scope'],'tool_observation')

    def test_forged_cross_library_evidence_and_delete_actions_are_rejected(self):
        foreign=self.raw("我在另一个库",lid="b")
        cases=[lambda p:self.op(p,evidence=[{"id":foreign,"role":"user","quote":"我在另一个库"}]),
               lambda p:self.op(p,action="delete"),
               lambda p:{**self.op(p),"code":"dangerous()"}]
        for index,fn in enumerate(cases):
            self.reply=lambda p,fn=fn:{"version":1,"operations":[fn(p)]}
            nid=self.raw("本库原文"+str(index));self.organizer.enqueue("a",[nid])
            result=self.organizer.run_once("a")
            self.assertIn(result["status"],("retry","failed"))
        self.assertEqual(self.generated(),[])
        self.assertEqual(self.brains['b'].nodes[foreign]['text'],"我在另一个库")

    def test_source_changes_while_model_is_running_reject_stale_apply(self):
        nid=self.raw();self.organizer.enqueue('a',[nid])
        def changed(payload):
            self.brains['a'].nodes[nid]['meta']['memory_disabled']=True
            return self.default_reply(payload)
        self.reply=changed
        result=self.organizer.run_once('a')
        self.assertEqual(result['code'],'stale_input');self.assertEqual(self.generated(),[])

    def test_disabled_library_does_not_starve_an_enabled_other_library(self):
        save_profile(self.brains['a'],enabled=False)
        a=self.raw(lid='a');b=self.raw("我住在另一个库",lid='b')
        self.organizer.enqueue('a',[a]);self.organizer.enqueue('b',[b])
        result=self.organizer.run_once()
        self.assertEqual(result['library_id'],'b');self.assertEqual(len(self.generated('b')),1)
        self.assertEqual(self.generated('a'),[])

    def test_budget_limited_library_does_not_starve_an_enabled_other_library(self):
        save_profile(self.brains['a'],daily_call_limit=1)
        self.run_raw()
        a=self.raw('另一个未整理事实',lid='a');b=self.raw('另一个库的事实',lid='b')
        self.organizer.enqueue('a',[a]);self.organizer.enqueue('b',[b])
        result=self.organizer.run_once()
        self.assertEqual(result['status'],'done');self.assertEqual(result['library_id'],'b')
        self.assertEqual(len(self.generated('b')),1)
        self.assertEqual(self.organizer.status('a')['counts'].get('pending'),1)
        self.assertEqual(self.organizer.run_once()['status'],'budget_limited')

    def test_automatic_library_selection_is_round_robin_even_with_a_backlog(self):
        for lid in ('a','b'):
            save_profile(self.brains[lid],cadence='session')
            self.organizer.enqueue(lid,[self.raw('第一条事实',lid=lid),self.raw('第二条事实',lid=lid)])
        libraries=[self.organizer.run_once()['library_id'] for _ in range(4)]
        self.assertEqual(libraries,['a','b','a','b'])

    def test_disabled_preview_is_readonly_has_no_credential_or_transport_call(self):
        save_profile(self.brains['a'],enabled=False)
        nid=self.raw();self.organizer.enqueue('a',[nid])
        before=deepcopy(self.brains['a'].to_dict())
        result=self.organizer.preview('a')
        self.assertEqual(result['raw_count'],1);self.assertFalse(result['will_call_model'])
        self.assertEqual(self.organizer.run_once('a')['status'],'paused')
        self.assertEqual(self.calls,[]);self.assertEqual(self.credential_calls,[])
        self.assertEqual(before,self.brains['a'].to_dict())

    def test_batch_waits_at_most_thirty_seconds_or_manual_flush(self):
        nid=self.raw();self.organizer.enqueue('a',[nid])
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'waiting')
        with self.organizer.db() as db:db.execute('UPDATE items SET created=created-31')
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.run_raw("另一个明确事实")
        self.assertEqual(len(self.calls),2)

    def test_session_cadence_and_daily_budget_limit_actual_batches(self):
        save_profile(self.brains['a'],cadence='session',daily_call_limit=1)
        a=self.raw();b=self.raw("我喜欢喝茶")
        self.organizer.enqueue('a',[a,b])
        self.assertEqual(self.organizer.run_once('a',flush=False)['status'],'done')
        self.assertEqual(self.organizer.run_once('a')['status'],'budget_limited')
        self.assertEqual(len(self.calls),1)

    def test_daily_material_character_limit_keeps_unfinished_tail_in_queue(self):
        save_profile(self.brains['a'],cadence='session',daily_char_limit=3000)
        nid=self.raw('用户明确原文内容'*300)
        self.reply=lambda p:{'version':1,'operations':[]}
        self.organizer.enqueue('a',[nid])
        self.assertEqual(self.organizer.run_once('a')['status'],'done')
        self.assertEqual(self.organizer.run_once('a')['status'],'budget_limited')
        self.assertLessEqual(self.organizer.status('a')['usage_24h']['chars'],3000)
        self.assertEqual(self.organizer.status('a')['counts'].get('pending'),1)

    def test_failed_apply_keeps_validated_plan_and_retries_without_second_model_call(self):
        nid=self.raw();self.organizer.enqueue('a',[nid]);self.apply_failure=True
        failed=self.organizer.run_once('a')
        self.assertEqual(failed['status'],'retry')
        self.assertEqual(self.organizer.status('a')['counts']['retry'],1)
        self.assertNotIn(KEY,json.dumps(self.organizer.status('a')))
        self.apply_failure=False;self.organizer.retry(failed['job_id'])
        self.assertEqual(self.organizer.run_once('a')['status'],'done')
        self.assertEqual(len(self.calls),1)

    def test_pending_queue_and_expired_running_lease_recover_in_a_new_worker(self):
        nid=self.raw();self.organizer.enqueue('a',[nid])
        self.apply_failure=True
        failed=self.organizer.run_once('a')
        with self.organizer.db() as db:
            db.execute("UPDATE jobs SET status='running',lease_until=0 WHERE id=?",(failed['job_id'],))
            db.execute("UPDATE items SET status='running' WHERE job_id=?",(failed['job_id'],))
        self.apply_failure=False
        restored=self.make();self.addCleanup(restored.stop)
        self.assertEqual(restored.run_once()['status'],'done')
        self.assertEqual(restored.status('a')['counts'].get('done'),1)
        self.assertEqual(len(self.calls),1)

    def test_wrong_key_merge_or_user_edited_fact_is_reviewed_not_automatically_changed(self):
        self.run_raw();old=self.generated()[0]['id']
        self.reply=lambda p:{'version':1,'operations':[self.op(p,action='merge',target_id=old,key='unrelated.preference')]}
        self.run_raw('我住在北京')
        self.assertEqual(len(self.brains['a'].meta['organizer_candidates']),1)
        self.brains['a'].update(old,text='用户已经明确编辑的正文')
        self.reply=lambda p:{'version':1,'operations':[self.op(p,action='supersede',target_id=old)]}
        # Include enough literal overlap to make this related old record visible to the model.
        self.run_raw('用户已经明确编辑的正文，现在有新说明')
        self.assertIsNone(self.brains['a'].nodes[old]['valid_to'])
        self.assertEqual(self.brains['a'].nodes[old]['text'],'用户已经明确编辑的正文')

    def test_semantic_alias_recall_and_rollback_have_verifiable_sources_and_preserve_raw(self):
        nid,result=self.run_raw();brain=self.brains['a'];generated=self.generated()[0]['id']
        before=deepcopy(brain.to_dict())
        recalled=semantic_recall(brain,'安家地点')
        self.assertIn(generated,[h['id'] for h in recalled['hits']]);self.assertTrue(recalled['semantic_expansions'])
        self.assertEqual(before,brain.to_dict())
        rollback(brain,result['job_id'])
        self.assertNotIn(generated,brain.nodes);self.assertIn(nid,brain.nodes)
        with self.assertRaises(OrganizerConflict):apply_plan(brain,self.apply_calls[-1],'a')

    def test_read_full_nested_archive_and_do_not_mark_truncated_excerpt_as_full(self):
        nid=self.raw("节点摘录；完整原文保存在档案",receipt='receipt-x')
        self.brains['a'].nodes[nid]['meta']['evidence']['content_truncated']=True
        self.organizer.enqueue('a',['receipt-x'])
        failed=self.organizer.run_once('a')
        self.assertEqual(failed['code'],'missing_archive');self.assertEqual(self.calls,[])
        archive={'record':{'record':{'normalized':{'type':'turn','user':'完整原文：我住在北京','assistant':'完整回复'}}}}
        restored=self.make(archive=lambda lid,rid:archive)
        self.addCleanup(restored.stop);restored.retry(failed['job_id'])
        self.assertEqual(restored.run_once('a')['status'],'done')
        self.assertEqual(self.generated()[0]['text'],'完整原文：我住在北京')

    def test_long_raw_is_processed_in_budgeted_slices_instead_of_silently_losing_tail(self):
        save_profile(self.brains['a'],max_input_chars=3000,cadence='session')
        nid=self.raw('明确原文。'*1000,assistant='助手结尾')
        self.reply=lambda p:{'version':1,'operations':[]}
        self.organizer.enqueue('a',[nid])
        for _ in range(20):
            result=self.organizer.run_once('a')
            if self.organizer.status('a')['counts'].get('done'):break
        self.assertEqual(self.organizer.status('a')['counts'].get('done'),1)
        self.assertGreater(len(self.calls),1)
        self.assertTrue(any('助手结尾' in r['roles'].get('assistant','') for p in self.calls for r in p['raw']))
        self.assertTrue(all(len(json.dumps(p,ensure_ascii=False))<=3000 for p in self.calls))

    def test_forget_tombstones_unqueued_ids_and_scrubs_queue_text_and_blocks_inflight_apply(self):
        secret='必须被清除的本地敏感原文'
        nid=self.raw(secret,receipt='receipt-delete');self.organizer.enqueue('a',['receipt-delete'])
        def deleted(payload):
            self.organizer.forget('a',['receipt-delete'],[nid])
            self.brains['a'].nodes[nid]['meta']['memory_disabled']=True
            return self.default_reply(payload)
        self.reply=deleted
        result=self.organizer.run_once('a')
        self.assertEqual(result['status'],'cancelled');self.assertEqual(self.generated(),[])
        self.assertEqual(self.organizer.enqueue('a',['receipt-delete'])['queued'],0)
        self.organizer.forget('a',['never-queued'])
        self.assertEqual(self.organizer.enqueue('a',['never-queued'])['queued'],0)
        with self.organizer.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM jobs')]
            self.assertEqual(db.execute('PRAGMA secure_delete').fetchone()[0],1)
        self.assertNotIn(secret,json.dumps(rows,ensure_ascii=False))
        for path in Path(self.tmp.name).glob('organizer.sqlite3*'):
            self.assertNotIn(secret.encode(),path.read_bytes())

    def test_forget_during_apply_cannot_resave_a_job_result_after_deletion_returns(self):
        secret='apply之后删除的敏感原文'
        nid=self.raw(secret,receipt='receipt-after-apply')
        self.organizer.enqueue('a',['receipt-after-apply'])
        original=self.organizer.apply
        def apply_then_forget(lid,plan):
            result=original(lid,plan)
            self.organizer.forget(lid,['receipt-after-apply'],[nid])
            forget_plan_data(self.brains[lid],['receipt-after-apply'],[nid])
            for n in list(self.generated(lid)):self.brains[lid].remove(n['id'])
            self.brains[lid].remove(nid)
            return result
        self.organizer.apply=apply_then_forget
        self.assertEqual(self.organizer.run_once('a')['status'],'cancelled')
        with self.organizer.db() as db:
            row=dict(db.execute('SELECT * FROM jobs').fetchone())
        self.assertIsNone(row['result_json']);self.assertIsNone(row['plan_json']);self.assertIsNone(row['input_json'])
        self.assertEqual(self.brains['a'].meta['organizer_log'],[])

    def test_stop_during_model_call_does_not_apply_after_the_response_arrives(self):
        nid=self.raw();self.organizer.enqueue('a',[nid])
        def stopped(payload):
            self.organizer.stop()
            return self.default_reply(payload)
        self.reply=stopped
        self.assertEqual(self.organizer.run_once('a')['status'],'cancelled')
        self.assertEqual(self.apply_calls,[]);self.assertEqual(self.generated(),[])

    def test_forget_during_credential_lookup_cannot_rewrite_input_or_send_the_deleted_raw(self):
        nid=self.raw('在凭证lookup期间被遗忘',receipt='receipt-before-send')
        self.organizer.enqueue('a',['receipt-before-send'])
        def credential(lid,profile):
            self.organizer.forget(lid,['receipt-before-send'],[nid])
            return KEY
        self.organizer.credential=credential
        self.assertEqual(self.organizer.run_once('a')['status'],'cancelled')
        self.assertEqual(self.calls,[])
        with self.organizer.db() as db:
            row=dict(db.execute('SELECT * FROM jobs').fetchone())
        self.assertIsNone(row['input_json']);self.assertIsNone(row['plan_json']);self.assertIsNone(row['result_json'])

    def test_archive_from_another_library_is_not_sent_even_if_node_ids_match(self):
        self.raw(receipt='receipt-owned')
        worker=self.make(archive=lambda lid,rid:{'library_id':'b','id':rid,'normalized':{'type':'turn','user':'外国库秘密','assistant':'x'}})
        self.addCleanup(worker.stop);worker.enqueue('a',['receipt-owned'])
        self.assertEqual(worker.run_once('a')['code'],'source_deleted')
        self.assertEqual(self.calls,[])

    def test_cached_plan_does_not_replay_after_source_archive_was_deleted(self):
        nid=self.raw(receipt='receipt-cache')
        archive={'normalized':{'type':'turn','user':'我住在北京','assistant':'原始助手'}}
        available={'value':archive}
        worker=self.make(archive=lambda lid,rid:available['value']);self.addCleanup(worker.stop)
        worker.enqueue('a',['receipt-cache']);self.apply_failure=True
        result=worker.run_once('a');self.assertEqual(result['status'],'retry')
        self.apply_failure=False;available['value']=None;worker.retry(result['job_id'])
        result=worker.run_once('a')
        self.assertEqual(result['code'],'source_deleted');self.assertEqual(self.generated(),[])
        self.assertEqual(worker.status('a')['counts']['failed'],1)

    def test_safe_configuration_is_library_local_and_rejects_inline_keys(self):
        before=get_profile(self.brains['b'])
        save_profile(self.brains['a'],daily_char_limit=3000,cadence='session')
        self.assertEqual(get_profile(self.brains['b']),before)
        with self.assertRaises(ValidationError):save_profile(self.brains['a'],api_key=KEY)
        with self.assertRaises(ValidationError):save_profile(self.brains['a'],base_url='http://external.invalid')

    def test_invalid_api_address_is_validation_error_not_parser_or_header_error(self):
        for address in ('https://[bad-ipv6','https://provider.invalid:0','https://provider.invalid:99999',
                        'https://provider.invalid/v1\r\nHeader:x','https://provider.invalid/with space',
                        'https://provider.invalid\\evil/path','https://@provider.invalid','https://provider.invalid/\x7f'):
            with self.subTest(address=repr(address)),self.assertRaises(ValidationError):endpoint(address)
        self.assertEqual(endpoint('http://127.0.0.1:8080/v1'),'http://127.0.0.1:8080/v1/chat/completions')


if __name__=='__main__':unittest.main()
