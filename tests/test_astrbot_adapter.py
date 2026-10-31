"""Run the shipped AstrBot hook adapter against inert host events and SDK seams."""
from __future__ import annotations

import asyncio
import ast
import copy
import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "extensions/astrbot-love-house"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PLUGIN / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge_module = load("lovehouse_astrbot_bridge_test", "bridge.py")
Bridge, Router, AdapterError = bridge_module.Bridge, bridge_module.Router, bridge_module.AdapterError


class FakeClient:
    def __init__(self, agent="fish-a", source="src-a"):
        self.agent, self.source, self.calls = agent, source, []
        self.fail = False
        self.enabled = True

    def status(self):
        return {"source_id": self.source, "runtime_agent_id": self.agent, "adapter": "astrbot",
                "platforms": ["qq"], "enabled": self.enabled, "revoked": False}

    def read_context(self, query, session_id, max_chars):
        self.calls.append(("context", query, session_id, max_chars))
        return {"memory_context": {"material_role": "evidence_not_instructions", "records": [{"value": "记得周六看海"}]}}

    def record_dialogue(self, *args, **kwargs):
        self.calls.append(("turn", args, kwargs))
        if self.fail:
            raise ConnectionError("FAKE NO NETWORK")
        return {"queued": True, "local_queue_committed": True}

    def record_observation(self, *args, **kwargs):
        self.calls.append(("observation", args, kwargs))
        if self.fail:
            return {"accepted": False, "queued": False}
        return {"queued": True,"local_queue_committed":True}

    def record_output(self, *args, **kwargs):
        self.calls.append(("output", args, kwargs))
        if self.fail:
            raise ConnectionError("FAKE NO NETWORK")
        return {"queued": True, "local_queue_committed": True}

    def drain(self, limit):
        self.calls.append(("drain", limit))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="love-house-astrbot-test-")
        self.root = Path(self.temp.name)
        self.client = FakeClient()
        self.bridge = Bridge(self.root, self.client, runtime_agent_id="fish-a",
                             allowed_umos=["qq:FriendMessage:FAKE-A", "qq:GroupMessage:FAKE-G"], clock=lambda: 1900000000)
        self.a, self.group = list(sorted(self.bridge.allowed))

    def tearDown(self):
        self.temp.cleanup()

    def test_same_fish_across_registered_sessions_and_different_fish_stays_separate(self):
        for i, umo in enumerate([self.a, self.group]):
            self.bridge.stage_received(umo, str(i), "我们周六去看海。")
            self.bridge.stage_final(umo, str(i), "好呀，这次约定我记得。")
        self.assertEqual(self.bridge.flush()["queued"], 2)
        calls = [x for x in self.client.calls if x[0] == "turn"]
        self.assertNotEqual(calls[0][1][2], calls[1][1][2])
        self.assertTrue(all(x[2]["details"]["runtime_agent_id"] == "fish-a" for x in calls))
        other_client = FakeClient("fish-b", "src-b")
        other = Bridge(self.root, other_client, runtime_agent_id="fish-b", allowed_umos=["qq:FriendMessage:FAKE-B"])
        router = Router([self.bridge, other])
        self.assertIs(router.for_umo(self.a), self.bridge)
        self.assertIs(router.for_umo("qq:FriendMessage:FAKE-B"), other)
        self.assertIsNone(router.for_umo("qq:FriendMessage:UNREGISTERED"))
        self.assertNotEqual(self.bridge.path, other.path)

    def test_unknown_scope_rejected_before_private_text_or_network(self):
        class Poison:
            def __str__(self):
                raise AssertionError("unregistered body must not be inspected")
        with self.assertRaises(AdapterError):
            self.bridge.stage_received("qq:UNREGISTERED", "1", Poison())
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.bridge.status()["awaiting_final"], 0)

    def test_duplicate_callbacks_restart_and_changed_same_message_fail_closed(self):
        first = self.bridge.stage_received(self.a, "one", "原始消息。"); self.bridge.stage_received(self.a, "one", "原始消息。")
        with self.assertRaises(AdapterError):self.bridge.stage_received(self.a, "one", "不同消息。")
        self.bridge.stage_final(self.a, "one", "完整回复。")
        self.bridge.stage_final(self.a, "one", "完整回复。")
        self.bridge.flush()
        reopened = Bridge(self.root, self.client, runtime_agent_id="fish-a", allowed_umos=list(self.bridge.allowed), clock=lambda:1900000000)
        self.assertTrue(reopened.stage_final(self.a, "one", "完整回复。")["duplicate"])
        with self.assertRaises(AdapterError):reopened.stage_final(self.a, "one", "另一份最终回复。")
        self.assertEqual(sum(x[0] == "turn" for x in self.client.calls), 1)
        with closing(sqlite3.connect(self.bridge.path)) as db, db:
            row = db.execute("SELECT user,assistant,text,details FROM records WHERE id=?", (first,)).fetchone()
        self.assertEqual(row, (None, None, None, "{}"))

    def test_partial_tool_step_errors_are_not_a_complete_dialogue(self):
        self.bridge.stage_received(self.a, "one", "原始消息。")
        for extra in ({"is_chunk": True}, {"has_tool_calls": True}, {"role": "err"}):
            self.assertFalse(self.bridge.stage_final(self.a, "one", "中间片段", **extra)["staged"])
        self.assertEqual(self.bridge.status()["awaiting_final"], 1)
        self.assertEqual(self.bridge.flush()["queued"], 0)
        self.assertEqual(self.bridge.stage_final(self.a, "never-received", "这是独立输出，没有虚构用户原话")["kind"], "output")

    def test_standalone_output_retries_and_restart_never_create_a_fake_turn(self):
        result = self.bridge.stage_final(self.a, "solo", "我整理好了看海计划。",
            execution_origin="scheduled", actual_platform="cron")
        self.assertEqual(result["kind"], "output")
        self.assertTrue(self.bridge.stage_final(self.a, "solo", "我整理好了看海计划。")["duplicate"])
        self.client.fail = True
        self.assertEqual(self.bridge.flush()["waiting"], 1)
        reopened = Bridge(self.root, self.client, runtime_agent_id="fish-a", allowed_umos=list(self.bridge.allowed))
        self.client.fail = False
        self.assertEqual(reopened.flush()["queued"], 1)
        self.assertTrue(reopened.stage_final(self.a, "solo", "我整理好了看海计划。")["duplicate"])
        self.assertEqual(reopened.flush()["queued"], 0)
        outputs = [c for c in self.client.calls if c[0] == "output"]
        self.assertEqual(outputs[-1][1][0], "我整理好了看海计划。")
        self.assertEqual(outputs[-1][2]["details"]["execution_origin"], "scheduled")
        self.assertEqual(outputs[-1][2]["details"]["actual_platform"], "cron")
        self.assertNotIn("participant_role", outputs[-1][2]["details"])
        self.assertFalse(any(c[0] == "turn" for c in self.client.calls))
        with self.assertRaises(AdapterError): reopened.stage_final(self.a, "solo", "另一份输出")
        with closing(sqlite3.connect(reopened.path)) as db:
            self.assertEqual(db.execute("SELECT user,assistant,text FROM records WHERE id=?",(result["event_id"],)).fetchone(),(None,None,None))

    def test_existing_input_remains_one_turn_and_non_final_output_is_rejected(self):
        self.bridge.stage_received(self.a, "has-user", "我们去看海。")
        self.bridge.stage_final(self.a, "has-user", "好的。")
        self.bridge.stage_final(self.a, "has-user", "好的。")
        for extra in ({"is_chunk":True},{"has_tool_calls":True},{"role":"err"},{"aborted":True}):
            self.assertFalse(self.bridge.stage_final(self.a, "no-user", "这不是最终成功输出", **extra)["staged"])
        self.assertEqual(self.bridge.flush()["queued"],1)
        self.assertEqual(sum(c[0]=="turn" for c in self.client.calls),1)
        self.assertFalse(any(c[0]=="output" for c in self.client.calls))

    def test_durable_failure_survives_restart_and_success_clears_only_body_copy(self):
        self.bridge.stage_received(self.a, "one", "原始消息。")
        self.bridge.stage_final(self.a, "one", "完整回复。")
        self.client.fail = True
        self.assertEqual(self.bridge.flush()["waiting"], 1)
        reopened = Bridge(self.root, self.client, runtime_agent_id="fish-a", allowed_umos=list(self.bridge.allowed))
        self.assertEqual(reopened.status()["pending"], 1)
        self.client.fail = False
        self.assertEqual(reopened.flush()["queued"], 1)
        self.assertEqual(reopened.status()["pending"], 0)

    def test_send_callback_is_only_host_stage_not_delivery_or_read_proof(self):
        first=self.bridge.note_host_send_stage(self.a,"one")
        self.bridge.note_host_send_stage(self.a,"one")
        self.assertTrue(first["private_only"])
        self.assertEqual(self.bridge.status()["private_host_send_stages"],1)
        self.assertEqual(self.bridge.status()["pending"],0)
        self.assertEqual(self.bridge.flush()["queued"],0)
        self.assertFalse(any(c[0] in ("observation","turn","output") for c in self.client.calls))
        with closing(sqlite3.connect(self.bridge.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT observed_at FROM host_send_stages WHERE id=?",(first["event_id"],)).fetchone()[0],1900000000)

    def test_legacy_send_stage_caller_only_notes_metadata_and_never_reads_prose(self):
        class Poison:
            def __str__(self):raise AssertionError("A send-stage note has no prose")
        self.bridge.stage_observation(self.a,"command",Poison(),stage="after_message_sent")
        self.assertEqual(self.bridge.status()["private_host_send_stages"],1)
        self.assertEqual(self.bridge.status()["pending"],0)
        self.assertEqual(self.client.calls,[])
        with self.assertRaises(AdapterError):self.bridge.note_host_send_stage("qq:UNREGISTERED","command")

    def test_send_metadata_never_changes_sdk_event_details_or_existing_history(self):
        self.bridge.stage_received(self.a,"one","原始消息。")
        self.bridge.stage_final(self.a,"one","完整回复。")
        self.client.fail=True
        self.assertEqual(self.bridge.flush()["waiting"],1)
        first=next(c for c in self.client.calls if c[0]=="turn")
        with closing(sqlite3.connect(self.bridge.path)) as db:
            before=db.execute("SELECT * FROM records").fetchall()
        self.bridge.note_host_send_stage(self.a,"one")
        self.bridge.note_host_send_stage(self.a,"program-command")
        with closing(sqlite3.connect(self.bridge.path)) as db:
            self.assertEqual(db.execute("SELECT * FROM records").fetchall(),before)
        reopened=Bridge(self.root,self.client,runtime_agent_id="fish-a",allowed_umos=list(self.bridge.allowed))
        self.client.fail=False
        self.assertEqual(reopened.flush()["queued"],1)
        last=[c for c in self.client.calls if c[0]=="turn"][-1]
        self.assertEqual(first[1:],last[1:])
        self.assertEqual(reopened.status()["private_host_send_stages"],2)
        self.assertFalse(any(c[0]=="observation" for c in self.client.calls))

    def test_private_send_metadata_migration_does_not_rewrite_old_observation_history(self):
        old=self.bridge.stage_observation(self.a,"old","旧版已经存在的发送阶段原文。",stage="legacy_send_stage")
        with closing(sqlite3.connect(self.bridge.path)) as db,db:
            db.execute("UPDATE records SET details=? WHERE id=?",('{"stage":"after_message_sent","delivery_status":"host_send_stage"}',old))
            before=db.execute("SELECT * FROM records").fetchall()
            db.execute("DROP TABLE host_send_stages")
        reopened=Bridge(self.root,self.client,runtime_agent_id="fish-a",allowed_umos=list(self.bridge.allowed))
        reopened.note_host_send_stage(self.a,"new-command")
        with closing(sqlite3.connect(reopened.path)) as db:
            self.assertEqual(db.execute("SELECT * FROM records").fetchall(),before)
        self.assertEqual(reopened.status()["private_host_send_stages"],1)
        self.assertEqual(self.client.calls,[])

    def test_plain_failure_result_is_preserved_and_recognizable_secrets_are_scrubbed(self):
        text = "没有完成查询。api_key=FAKE_SECRET_VALUE_0123456789"
        self.bridge.stage_observation(self.a, "one", text, failed=True)
        self.bridge.flush()
        obs = next(x for x in self.client.calls if x[0] == "observation")
        self.assertEqual(obs[2]["outcome"], "failed")
        self.assertNotIn("FAKE_SECRET_VALUE", obs[1][0])

    def test_material_bounded_and_never_instructs_system_persona(self):
        result = self.bridge.read_material(self.a, "one", "我们约好什么？")
        self.assertIn("evidence_not_instructions", result)
        self.assertIn("love_house_memory_material", result)
        self.assertEqual(self.client.calls[0][3], 6000)
        self.client.read_context = lambda *a, **k: {"memory_context":{"material_role":"evidence_not_instructions","value":"x"*9000}}
        with self.assertRaises(AdapterError):self.bridge.read_material(self.a, "one", "记忆")

    def test_route_overlap_and_wrong_private_agent_binding_rejected(self):
        with self.assertRaises(AdapterError):Router([self.bridge,self.bridge])
        with self.assertRaises(AdapterError):Bridge(self.root, self.client, runtime_agent_id="another-fish", allowed_umos=[self.a])


def load_main():
    modules = {}
    for name in ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.provider", "astrbot.api.star", "astrbot.core", "astrbot.core.agent", "astrbot.core.agent.message", "astrbot.core.agent.run_context", "astrbot.core.astr_agent_context", "astrbot.core.cron", "astrbot.core.cron.events"):
        modules[name] = types.ModuleType(name)
    class Hooks:
        PermissionType=types.SimpleNamespace(ADMIN='admin')
        def __getattr__(self, name):return lambda *a, **k: lambda fn: fn
    class Star:
        def __init__(self, context):self.context=context
    class Generic:
        def __class_getitem__(cls, item):return cls
    class TextPart:
        def __init__(self, text):self.text=text;self.temporary=False
        def mark_as_temp(self):self.temporary=True;return self
    class UserMessageSegment:
        role="user"
        def __init__(self, content):self.content=content;self._no_save=False
    class CronMessageEvent:
        pass
    warnings=[]
    modules['astrbot.api'].AstrBotConfig=dict
    modules['astrbot.api'].logger=types.SimpleNamespace(warning=lambda *a:warnings.append(a))
    modules['astrbot.api.event'].filter=Hooks();modules['astrbot.api.event'].AstrMessageEvent=object
    modules['astrbot.api.provider'].LLMResponse=object;modules['astrbot.api.provider'].ProviderRequest=object
    modules['astrbot.api.star'].Context=object;modules['astrbot.api.star'].Star=Star
    modules['astrbot.api.star'].register=lambda *a:lambda cls:cls
    modules['astrbot.core.agent.message'].TextPart=TextPart
    modules['astrbot.core.agent.message'].UserMessageSegment=UserMessageSegment
    modules['astrbot.core.agent.run_context'].ContextWrapper=Generic
    modules['astrbot.core.astr_agent_context'].AstrAgentContext=object
    modules['astrbot.core.cron.events'].CronMessageEvent=CronMessageEvent
    package=types.ModuleType('lovehouse_astrbot_plugin_test');package.__path__=[str(PLUGIN)];modules[package.__name__]=package
    with patch.dict(sys.modules,modules):
        main=load(package.__name__+'.main','main.py')
    return main,warnings


class FakeEvent:
    def __init__(self, umo, mid='FAKE-message'):
        self.unified_msg_origin=umo
        self.message_str='我想找一份新的看海路线。'
        self.message_obj=types.SimpleNamespace(message_id=mid,timestamp=1800000000)
        self.extras={}
    def get_extra(self,k):return self.extras.get(k)
    def set_extra(self,k,v):self.extras[k]=v
    def get_sender_id(self):return 'FAKE-participant'
    def get_platform_name(self):return 'aiocqhttp'
    def get_platform_id(self):return self.unified_msg_origin.split(':',1)[0]


class HookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-astrbot-hook-test-');self.root=Path(self.temp.name)
        self.main,self.warnings=load_main()
        self.client=FakeClient();self.bridge=Bridge(self.root,self.client,runtime_agent_id='fish-a',allowed_umos=['qq:FriendMessage:FAKE-A'],clock=lambda:1900000000)
        self.plugin=self.main.LoveHousePlugin.__new__(self.main.LoveHousePlugin)
        self.plugin.config={'enabled':True,'record_observations':True};self.plugin.router=Router([self.bridge]);self.plugin._last_warning=None;self.plugin._worker=None
        self.event=FakeEvent('qq:FriendMessage:FAKE-A')

    async def asyncTearDown(self):self.temp.cleanup()

    async def test_request_real_hook_stages_original_once_and_adds_temporary_material(self):
        req=types.SimpleNamespace(system_prompt='保留的原人格',prompt='原始请求',extra_user_content_parts=[])
        await self.plugin.recall_before_request(self.event,req)
        await self.plugin.recall_before_request(self.event,req)
        self.assertEqual(req.system_prompt,'保留的原人格');self.assertEqual(req.prompt,'原始请求')
        self.assertEqual(len(req.extra_user_content_parts),1);self.assertTrue(req.extra_user_content_parts[0].temporary)
        self.assertEqual(sum(x[0]=='context' for x in self.client.calls),1)
        self.assertEqual(self.bridge.status()['awaiting_final'],1)
        next_step=types.SimpleNamespace(system_prompt='保留的原人格',extra_user_content_parts=[])
        await self.plugin.recall_before_request(self.event,next_step)
        self.assertEqual(len(next_step.extra_user_content_parts),1)
        self.assertEqual(sum(x[0]=='context' for x in self.client.calls),1)

    async def test_unregistered_and_paused_routes_never_read_message_body(self):
        class Unbound:
            unified_msg_origin='qq:NOT-REGISTERED'
            @property
            def message_str(self):raise AssertionError('No unrelated messages')
        await self.plugin.recall_before_request(Unbound(),object())
        self.client.enabled=False
        await self.plugin.recall_before_request(self.event,object())
        self.assertEqual(self.client.calls,[]);self.assertEqual(self.bridge.status()['awaiting_final'],0)
        self.client.enabled=True;self.client.agent='another-fish'
        await self.plugin.recall_before_request(self.event,object())
        self.assertEqual(self.bridge.status()['awaiting_final'],0)

    async def test_final_and_tool_result_hooks_preserve_observed_material_without_parameters(self):
        req=types.SimpleNamespace(system_prompt='',extra_user_content_parts=[])
        await self.plugin.recall_before_request(self.event,req)
        resp=types.SimpleNamespace(completion_text='我找到路线了。',is_chunk=False,tools_call_name=[],role='assistant')
        await self.plugin.final_generation(self.event,None,resp)
        dangerous_args={'api_key':'FAKE_DONT_STORE_PROVIDER_KEY_012345'}
        tool_result=types.SimpleNamespace(content=[types.SimpleNamespace(type='text',text='页面提供了两条路线。')],isError=False)
        await self.plugin.observation(self.event,object(),dangerous_args,tool_result)
        await self.plugin.send_stage(self.event)
        self.bridge.flush()
        turns=[x for x in self.client.calls if x[0]=='turn'];obs=[x for x in self.client.calls if x[0]=='observation']
        self.assertEqual(len(turns),1);self.assertEqual(turns[0][2]['delivery_status'],'generated')
        self.assertEqual(len(obs),1);self.assertTrue(all(x[2]['outcome']=='observed' for x in obs))
        self.assertEqual(self.bridge.status()['private_host_send_stages'],1)
        self.assertNotIn('FAKE_DONT_STORE_PROVIDER_KEY',json.dumps(self.client.calls))

    async def test_program_command_send_stage_creates_no_memories_and_checks_scope_first(self):
        self.event.message_str='/lovehouse_status'
        await self.plugin.send_stage(self.event)
        await self.plugin.send_stage(self.event)
        self.assertEqual(self.bridge.status()['private_host_send_stages'],1)
        self.assertEqual(self.bridge.status()['awaiting_final'],0)
        self.assertEqual(self.bridge.status()['pending'],0)
        self.assertEqual(self.client.calls,[])
        unbound=FakeEvent('qq:FriendMessage:UNREGISTERED')
        await self.plugin.send_stage(unbound)
        self.client.enabled=False
        await self.plugin.send_stage(FakeEvent(self.event.unified_msg_origin,'paused-command'))
        self.assertEqual(self.bridge.status()['private_host_send_stages'],1)
        self.assertEqual(self.bridge.flush()['queued'],0)
        self.assertFalse(any(c[0] in ('turn','output','observation') for c in self.client.calls))

    async def test_qq_label_cannot_capture_chatui_or_mismatched_platform_instance(self):
        for platform_name,platform_id in [('webchat','qq'),('aiocqhttp','foreign-instance')]:
            event=FakeEvent(self.event.unified_msg_origin)
            event.get_platform_name=lambda:platform_name
            event.get_platform_id=lambda:platform_id
            req=types.SimpleNamespace(system_prompt='原人格',extra_user_content_parts=[])
            await self.plugin.recall_before_request(event,req)
            self.assertEqual(self.bridge.status()['awaiting_final'],0)
            self.assertEqual(self.client.calls,[])
            self.assertEqual(req.system_prompt,'原人格')

    async def test_first_failure_warning_is_visible_even_on_a_freshly_booted_runner(self):
        with patch('time.monotonic',side_effect=[1.0,2.0,62.0]):
            self.plugin._warn('first')
            self.plugin._warn('throttled')
            self.plugin._warn('after_interval')
        self.assertEqual(len(self.warnings),2)

    async def test_recall_failure_never_rewrites_persona_and_original_waits_for_final(self):
        self.client.read_context=lambda *a,**k:(_ for _ in ()).throw(ConnectionError('FAKE PRIVATE ERROR'))
        req=types.SimpleNamespace(system_prompt='原人格',extra_user_content_parts=[])
        await self.plugin.recall_before_request(self.event,req)
        self.assertEqual(req.system_prompt,'原人格');self.assertEqual(req.extra_user_content_parts,[])
        self.assertEqual(self.bridge.status()['awaiting_final'],1)
        self.assertTrue(self.warnings);self.assertNotIn('FAKE PRIVATE ERROR',str(self.warnings))

    def scheduled(self, *, umo=None, message_id="scheduled-once"):
        cls=type("ScheduledEvent",(FakeEvent,self.main.CronMessageEvent),{})
        event=cls(umo or self.event.unified_msg_origin, message_id)
        event.message_str="现在主动检查看海计划，但这不是主人发言。"
        event.get_platform_name=lambda:"cron"
        return event

    async def test_scheduled_default_off_and_fake_cron_name_cannot_expand_scope(self):
        event=self.scheduled()
        context=types.SimpleNamespace(messages=[])
        resp=types.SimpleNamespace(completion_text="主动检查完成。",is_chunk=False,tools_call_name=[],role="assistant")
        await self.plugin.recall_before_agent(event,context)
        await self.plugin.final_generation(event,context,resp)
        self.assertEqual(context.messages,[])
        self.assertEqual(self.bridge.status()["pending"],0)
        self.assertEqual(self.client.calls,[])
        self.plugin.config["record_scheduled_outputs"]=True
        fake=FakeEvent(self.event.unified_msg_origin)
        fake.get_platform_name=lambda:"cron"
        for event in [fake,self.scheduled(umo="qq:FriendMessage:UNREGISTERED"),self.scheduled()]:
            if isinstance(event,self.main.CronMessageEvent) and event.unified_msg_origin==self.event.unified_msg_origin:
                event.get_platform_id=lambda:"wrong-instance"
            await self.plugin.recall_before_agent(event,context)
            await self.plugin.final_generation(event,context,resp)
        self.assertEqual(self.client.calls,[])
        self.assertEqual(context.messages,[])

    async def test_registered_scheduled_run_recalls_then_stages_only_assistant_output_and_visible_result(self):
        self.plugin.config["record_scheduled_outputs"]=True
        event=self.scheduled()
        context=types.SimpleNamespace(messages=[])
        await self.plugin.recall_before_agent(event,context)
        await self.plugin.recall_before_agent(event,context)
        self.assertEqual(len(context.messages),1)
        self.assertEqual(context.messages[0].role,"user")
        self.assertTrue(context.messages[0]._no_save)
        self.assertTrue(context.messages[0].content[0].temporary)
        self.assertEqual(sum(c[0]=="context" for c in self.client.calls),1)
        self.assertEqual(self.bridge.status()["awaiting_final"],0)
        # Even an alternate host calling both hooks may not turn scheduler text
        # into a user statement. Its existing request marker prevents duplication.
        req=types.SimpleNamespace(extra_user_content_parts=[])
        await self.plugin.recall_before_request(event,req)
        self.assertEqual(self.bridge.status()["awaiting_final"],0)
        resp=types.SimpleNamespace(completion_text="我检查了计划，目前不需要修改。",is_chunk=False,tools_call_name=[],role="assistant")
        await self.plugin.final_generation(event,context,resp)
        await self.plugin.final_generation(event,context,resp)
        result=types.SimpleNamespace(content=[types.SimpleNamespace(type="text",text="查询失败，网站暂不可用。")],isError=True)
        await self.plugin.observation(event,object(),{"api_key":"FAKE_DO_NOT_PERSIST_0123456789"},result)
        self.assertEqual(self.bridge.flush()["queued"],2)
        output=next(c for c in self.client.calls if c[0]=="output")
        self.assertEqual(output[1][0],resp.completion_text)
        self.assertEqual(output[2]["details"]["actual_platform"],"cron")
        self.assertEqual(output[2]["details"]["execution_origin"],"scheduled")
        self.assertEqual(output[2]["platform"],"qq")
        observation=next(c for c in self.client.calls if c[0]=="observation")
        self.assertEqual(observation[2]["outcome"],"failed")
        self.assertEqual(observation[2]["details"]["actual_platform"],"cron")
        self.assertFalse(any(c[0]=="turn" for c in self.client.calls))
        self.assertNotIn("DO_NOT_PERSIST",json.dumps(self.client.calls))
        with closing(sqlite3.connect(self.bridge.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM records WHERE user IS NOT NULL").fetchone()[0],0)

    async def test_normal_request_then_agent_begin_does_not_duplicate_material_or_turn(self):
        req=types.SimpleNamespace(extra_user_content_parts=[],system_prompt="原人格")
        await self.plugin.recall_before_request(self.event,req)
        context=types.SimpleNamespace(messages=[])
        await self.plugin.recall_before_agent(self.event,context)
        self.assertEqual(context.messages,[])
        self.assertEqual(sum(c[0]=="context" for c in self.client.calls),1)
        resp=types.SimpleNamespace(completion_text="正常最终回复。",is_chunk=False,tools_call_name=[],role="assistant")
        await self.plugin.final_generation(self.event,context,resp)
        self.bridge.flush()
        self.assertEqual(sum(c[0]=="turn" for c in self.client.calls),1)
        self.assertFalse(any(c[0]=="output" for c in self.client.calls))

    async def test_non_cron_framework_bypassing_request_hook_gets_memory_and_independent_output(self):
        context=types.SimpleNamespace(messages=[])
        await self.plugin.recall_before_agent(self.event,context)
        self.assertEqual(len(context.messages),1)
        self.assertEqual(self.bridge.status()["awaiting_final"],0)
        resp=types.SimpleNamespace(completion_text="这是绕过请求钩子的可见最终输出。",is_chunk=False,tools_call_name=[],role="assistant")
        await self.plugin.final_generation(self.event,context,resp)
        self.bridge.flush()
        self.assertEqual(sum(c[0]=="output" for c in self.client.calls),1)
        self.assertFalse(any(c[0]=="turn" for c in self.client.calls))

    async def test_agent_begin_recall_failure_keeps_chat_and_final_output_queued(self):
        self.client.read_context=lambda *a,**k:(_ for _ in ()).throw(ConnectionError("FAKE PRIVATE FAILURE"))
        context=types.SimpleNamespace(messages=[])
        await self.plugin.recall_before_agent(self.event,context)
        self.assertEqual(context.messages,[])
        resp=types.SimpleNamespace(completion_text="模型依然正常输出。",is_chunk=False,tools_call_name=[],role="assistant")
        await self.plugin.final_generation(self.event,context,resp)
        self.client.fail=True
        self.assertEqual(self.bridge.flush()["waiting"],1)
        self.assertEqual(self.bridge.status()["pending"],1)
        self.assertNotIn("FAKE PRIVATE FAILURE",str(self.warnings))

    async def test_official_abort_pair_error_chunk_and_tool_step_are_not_outputs(self):
        part=self.main.TextPart
        stopped=types.SimpleNamespace(messages=[types.SimpleNamespace(role="user",content=[part(text="Stop output.")]),
            types.SimpleNamespace(role="assistant",content=[part(text="Output stopped.")])])
        for completion,extra,context in [
            ("Output stopped.",{},stopped),
            ("FAKE PRIVATE EXCEPTION API KEY",{"role":"err"},types.SimpleNamespace(messages=[])),
            ("片段",{"is_chunk":True},types.SimpleNamespace(messages=[])),
            ("中间步骤",{"tools_call_name":["ignored-tool-name"]},types.SimpleNamespace(messages=[])),
            ("停止",{"aborted":True},types.SimpleNamespace(messages=[])),
        ]:
            values={"completion_text":completion,"is_chunk":False,"tools_call_name":[],"role":"assistant",**extra}
            await self.plugin.final_generation(self.event,context,types.SimpleNamespace(**values))
        self.assertEqual(self.bridge.status()["pending"],2)
        self.assertEqual(self.client.calls,[])
        self.assertEqual(self.bridge.flush()["queued"],2)
        self.assertFalse(any(c[0] in ("turn","output") for c in self.client.calls))
        observations=[c for c in self.client.calls if c[0]=="observation"]
        self.assertEqual({c[2]["details"]["execution_status"] for c in observations},{"failed","cancelled"})
        self.assertEqual({c[2]["outcome"] for c in observations},{"observed","failed"})
        self.assertNotIn("FAKE PRIVATE EXCEPTION",json.dumps(self.client.calls))


class PackagingTests(unittest.TestCase):
    def test_plugin_contains_private_config_routing_and_no_provider_key_configuration(self):
        schema=json.loads((PLUGIN/'_conf_schema.json').read_text())
        self.assertFalse(schema['enabled']['default'])
        self.assertFalse(schema['record_scheduled_outputs']['default'])
        self.assertEqual(schema['bindings']['default'],[])
        self.assertNotIn('api_key',schema)
        self.assertTrue((PLUGIN/'metadata.yaml').is_file())

    def test_vendored_client_matches_shared_source_client(self):
        self.assertEqual((PLUGIN/'source_client.py').read_bytes(),(ROOT/'nkb/service/source_client.py').read_bytes())

    def test_source_package_excludes_private_configuration_databases_and_queues(self):
        import subprocess
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'adapter.zip'
            result=subprocess.run([sys.executable,str(PLUGIN/'package.py'),'--check','--output',str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            with zipfile.ZipFile(output) as z:
                paths=z.namelist()
                self.assertTrue(all(x.startswith('astrbot_plugin_love_house/') for x in paths))
                self.assertFalse(any(x.endswith(('.sqlite3','.pyc')) or 'outbox' in x or 'source-config' in x for x in paths))
                self.assertIn('astrbot_plugin_love_house/main.py',paths)


class PackageBytesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-plugin-package-test-')
        self.base=Path(self.temp.name)
        self.plugin=self.base/'extensions/astrbot-love-house'
        self.plugin.mkdir(parents=True)
        self.module=load('love_house_plugin_package_bytes_test','package.py')
        for name in self.module.FILES:shutil.copy2(PLUGIN/name,self.plugin/name)
        sdk=self.base/'nkb/service/source_client.py';sdk.parent.mkdir(parents=True)
        shutil.copy2(ROOT/'nkb/service/source_client.py',sdk)
        self.patch=patch.object(self.module,'PLUGIN_DIR',self.plugin);self.patch.start()

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_fixed_allowlist_timestamps_modes_and_private_material_excluded(self):
        (self.plugin/'source-config.json').write_text('PRIVATE_SOURCE_CONFIGURATION')
        (self.plugin/'capture.sqlite3').write_bytes(b'PRIVATE_CHAT_DATABASE')
        (self.plugin/'outbox').mkdir();(self.plugin/'outbox'/'event.json').write_text('PRIVATE_PENDING_MESSAGE')
        first=self.module.package_bytes()
        for name in self.module.FILES:
            os.utime(self.plugin/name,(1750000000,1750000000))
            (self.plugin/name).chmod(0o600)
        second=self.module.package_bytes()
        self.assertEqual(first,second)
        import zipfile
        with zipfile.ZipFile(BytesIO(first)) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.namelist(),['astrbot_plugin_love_house/'+name for name in self.module.FILES])
            for info in z.infolist():
                self.assertEqual(info.date_time,(1980,1,1,0,0,0))
                self.assertEqual(info.create_system,3)
                self.assertEqual(stat.S_IMODE(info.external_attr>>16),0o644)
            body=b''.join(z.read(name) for name in z.namelist())
            self.assertNotIn(b'PRIVATE_CHAT_DATABASE',body)
            self.assertNotIn(b'PRIVATE_PENDING_MESSAGE',body)
            self.assertNotIn(b'PRIVATE_SOURCE_CONFIGURATION',body)

    def test_strict_sdk_matches_shared_bytes_and_is_optional_only_explicitly(self):
        sdk=self.base/'nkb/service/source_client.py'
        sdk.write_text('SDK_CHANGED')
        with self.assertRaisesRegex(ValueError,'differs'):self.module.package_bytes()
        self.assertIsInstance(self.module.package_bytes(strict_sdk=False),bytes)
        sdk.unlink()
        with self.assertRaises(ValueError):self.module.package_bytes()
        with self.assertRaises(ValueError):self.module.package_bytes(strict_sdk='false')

    def test_missing_directory_and_symlink_inputs_are_rejected(self):
        file=self.plugin/'README.md';file.unlink()
        with self.assertRaises(ValueError):self.module.package_bytes()
        file.mkdir()
        with self.assertRaises(ValueError):self.module.package_bytes()
        file.rmdir()
        try:file.symlink_to(PLUGIN/'README.md')
        except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):self.module.package_bytes()

    def test_total_source_budget_fails_before_producing_an_archive(self):
        (self.plugin/'README.md').write_bytes(b'x'*self.module.MAX_SOURCE_BYTES)
        with self.assertRaisesRegex(ValueError,'4 MiB'):self.module.package_bytes()

    def test_cli_file_and_in_memory_http_payload_have_identical_bytes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'adapter.zip'
            result=subprocess.run([sys.executable,str(PLUGIN/'package.py'),'--check','--output',str(file)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            actual=load('love_house_actual_plugin_package_http_test','package.py').package_bytes()
            self.assertEqual(file.read_bytes(),actual)


class ProtocolIntegrationTests(unittest.TestCase):
    def test_actual_bridge_and_vendored_sdk_roundtrip_to_disposable_memory_host(self):
        from nkb.service.credentials import KeyStore
        from nkb.service.host import MemoryHost,make_controller
        sdk=load('astrbot_vendored_sdk_protocol_test','source_client.py')
        with tempfile.TemporaryDirectory(prefix='love-house-astrbot-protocol-') as folder:
            root=Path(folder);host=MemoryHost(root,key_store=KeyStore(allow_keychain=False))
            server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(host));host.controller_port=server.server_port
            thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
            try:
                created=host.register_agent_source('default',{'name':'合成QQ来源','adapter':'astrbot','runtime_agent_id':'fish-a','platforms':['qq']})
                client=sdk.SourceClient(created['private_path'],timeout=2)
                bridge=Bridge(root/'adapter-state',client,runtime_agent_id='fish-a',allowed_umos=['qq:FriendMessage:FAKE-A','qq:GroupMessage:FAKE-G'])
                bridge.stage_received('qq:FriendMessage:FAKE-A','m1','我们周六一起去看海。',occurred_at=time.time()-5,sender_id='FAKE-participant')
                bridge.stage_final('qq:FriendMessage:FAKE-A','m1','我会保留这次约定。')
                bridge.note_host_send_stage('qq:FriendMessage:FAKE-A','m1')
                self.assertEqual(bridge.flush()['queued'],1)
                self.assertEqual(len(host.snapshot('default')['nodes']),1)
                self.assertEqual(len(host.connections.archives('default')),1)
                material=bridge.read_material('qq:GroupMessage:FAKE-G','m2','周六看海')
                self.assertIn('周六',material)
                other=host.manager.create_library('另一条鱼')['id']
                self.assertEqual(host.snapshot(other)['nodes'],{})
                bridge.stage_final('qq:FriendMessage:FAKE-A','m1','我会保留这次约定。')
                bridge.flush()
                self.assertEqual(len(host.connections.archives('default')),1)
                self.assertEqual(bridge.status()['pending'],0)
                # A scheduled/independent final output can outlive memory-service
                # downtime in the actual SDK queue without inventing a user turn.
                transport=client.transport
                def offline(*args,**kwargs):raise ConnectionError('FAKE OFFLINE')
                client.transport=offline
                output=bridge.stage_final('qq:FriendMessage:FAKE-A','scheduled-m3','我主动规划了去看海的路线。',
                    execution_origin='scheduled',actual_platform='cron',occurred_at=time.time())
                self.assertEqual(output['kind'],'output')
                bridge.note_host_send_stage('qq:FriendMessage:FAKE-A','scheduled-m3')
                self.assertEqual(bridge.flush()['queued'],1)
                bridge.note_host_send_stage('qq:FriendMessage:FAKE-A','scheduled-m3')
                self.assertEqual(client.status()['pending'],1)
                self.assertEqual(len(host.connections.archives('default')),1)
                client.transport=transport
                client.drain()
                self.assertEqual(client.status()['pending'],0)
                archives=host.connections.archives('default')
                self.assertEqual(len(archives),2)
                raw=json.loads(archives[-1]['payload'])
                normalized=(raw.get('record') or {}).get('normalized') or raw.get('normalized') or raw
                self.assertEqual(normalized['type'],'output')
                self.assertEqual(normalized['role'],'assistant')
                self.assertNotIn('user',normalized)
                nodes=host.snapshot('default')['nodes']
                outputs=[n for n in nodes.values() if n['meta'].get('source')=='agent_output']
                self.assertEqual(len(outputs),1)
                self.assertEqual(outputs[0]['meta']['speaker'],'assistant')
                self.assertEqual(len([n for n in nodes.values() if n['meta'].get('source')=='conversation_turn']),1)
                self.assertIn('主动规划',bridge.read_material('qq:GroupMessage:FAKE-G','m4','主动规划看海路线'))
                bridge.stage_final('qq:FriendMessage:FAKE-A','scheduled-m3','我主动规划了去看海的路线。')
                self.assertEqual(bridge.flush()['queued'],0)
                self.assertEqual(len(host.connections.archives('default')),2)
            finally:
                server.shutdown();server.server_close();thread.join();host.stop()


class PinnedOfficialMessageFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_tool_loop_provider_payload_keeps_temporary_material_but_history_does_not(self):
        source=os.environ.get('ASTRBOT_OFFLINE_SOURCE')
        if not source:
            self.skipTest('Set ASTRBOT_OFFLINE_SOURCE to a pinned v4.29.3 checkout for offline upstream API verification')
        upstream=Path(source).resolve()
        # Explicit upstream code only: never import astrbot.__init__, create a
        # provider instance, inspect runtime configuration, or open HTTP sockets.
        import tomllib
        self.assertEqual(tomllib.loads((upstream/'pyproject.toml').read_text())['project']['version'],'4.29.3')
        modules={name:types.ModuleType(name) for name in ('astrbot','astrbot.core','astrbot.core.agent','astrbot.core.provider')}
        modules['astrbot'].logger=types.SimpleNamespace(debug=lambda *a,**k:None)
        with patch.dict(sys.modules,modules):
            def upstream_module(name,relative):
                spec=importlib.util.spec_from_file_location(name,upstream/relative)
                module=importlib.util.module_from_spec(spec)
                sys.modules[name]=module
                spec.loader.exec_module(module)
                return module
            message=upstream_module('astrbot.core.agent.message','astrbot/core/agent/message.py')
            context=upstream_module('astrbot.core.agent.run_context','astrbot/core/agent/run_context.py')
            modalities=upstream_module('astrbot.core.provider.modalities','astrbot/core/provider/modalities.py')

            def method(relative,cls,name,namespace):
                tree=ast.parse((upstream/relative).read_text())
                owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
                definition=copy.deepcopy(next(n for n in owner.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name))
                definition.decorator_list=[]
                fragment=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),definition],type_ignores=[])
                ast.fix_missing_locations(fragment)
                exec(compile(fragment,str(upstream/relative),'exec'),namespace)
                return namespace[name]

            namespace={'copy':copy,'json':json,'Message':message.Message,'is_checkpoint_message':message.is_checkpoint_message,
                'sanitize_contexts_by_modalities':modalities.sanitize_contexts_by_modalities,
                'log_context_sanitize_stats':modalities.log_context_sanitize_stats,
                'dump_messages_with_checkpoints':message.dump_messages_with_checkpoints}
            class OfflineCompletion:
                pass
            async def offline_retry(provider,call,**kwargs):return await call()
            namespace.update(ChatCompletion=OfflineCompletion,retry_provider_request=offline_retry,
                build_conversation_headers=lambda value:{},logger=modules['astrbot'].logger)
            provider_path='astrbot/core/provider/sources/openai_source.py'
            class OfflineProvider:
                provider_config={}
                default_params={'messages','model'}
                def __init__(self):
                    self.client=types.SimpleNamespace(base_url=types.SimpleNamespace(host='api.deepseek.com'),
                        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=self.capture_completion)))
                def get_model(self):return 'deepseek-chat'
                async def capture_completion(self,**payload):
                    self.http_payload=copy.deepcopy(payload)
                    return OfflineCompletion()
                async def _parse_openai_completion(self,completion,tools):
                    return types.SimpleNamespace(role='assistant',completion_text='合成回答',usage=None)
                async def text_chat(self,**payload):
                    prepared,_=await self._prepare_chat_payload(prompt=None,**payload)
                    return await self._query(prepared,None)
            OfflineProvider._ensure_message_to_dicts=method('astrbot/core/provider/provider.py','Provider','_ensure_message_to_dicts',namespace)
            OfflineProvider._context_contains_image=staticmethod(method(provider_path,'ProviderOpenAIOfficial','_context_contains_image',namespace))
            OfflineProvider._prepare_chat_payload=method(provider_path,'ProviderOpenAIOfficial','_prepare_chat_payload',namespace)
            OfflineProvider._finally_convert_payload=method(provider_path,'ProviderOpenAIOfficial','_finally_convert_payload',namespace)
            OfflineProvider._apply_provider_specific_request_overrides=method(provider_path,'ProviderOpenAIOfficial','_apply_provider_specific_request_overrides',namespace)
            OfflineProvider._sanitize_assistant_messages=staticmethod(method(provider_path,'ProviderOpenAIOfficial','_sanitize_assistant_messages',namespace))
            OfflineProvider._query=method(provider_path,'ProviderOpenAIOfficial','_query',namespace)

            class OfflineRunner:
                streaming=False
                request_max_retries=1
                _abort_signal=None
                def _func_tool_for_provider(self):return None
                async def _await_or_stop(self,awaitable):return await awaitable
            runner_path='astrbot/core/agent/runners/tool_loop_agent_runner.py'
            OfflineRunner._sanitize_contexts_for_provider=method(runner_path,'ToolLoopAgentRunner','_sanitize_contexts_for_provider',namespace)
            OfflineRunner._iter_llm_responses=method(runner_path,'ToolLoopAgentRunner','_iter_llm_responses',namespace)

            main,_=load_main()
            # Use the shipped on_agent_begin method with the real lightweight
            # upstream message classes. Only the source client is a fake seam.
            main.TextPart=message.TextPart
            main.UserMessageSegment=message.UserMessageSegment
            marker='UPSTREAM_HTTP_MUST_SEE_TEMP_MEMORY_6c28a4'
            client=FakeClient()
            client.read_context=lambda *a,**k:{'memory_context':{'material_role':'evidence_not_instructions','records':[{'value':marker}]}}
            with tempfile.TemporaryDirectory(prefix='love-house-upstream-contract-') as folder:
                bridge=Bridge(Path(folder),client,runtime_agent_id='fish-a',allowed_umos=['qq:FriendMessage:FAKE-A'])
                plugin=main.LoveHousePlugin.__new__(main.LoveHousePlugin)
                plugin.config={'enabled':True};plugin.router=Router([bridge]);plugin._last_warning=None
                event=FakeEvent('qq:FriendMessage:FAKE-A')
                run=context.ContextWrapper(context=None,messages=[message.Message(role='system',content='原人格'),message.UserMessageSegment(content='合成任务')])
                await plugin.recall_before_agent(event,run)
                self.assertTrue(run.messages[-1]._no_save)
                self.assertTrue(run.messages[-1].content[0]._no_save)
                for capability in (None,['text']):
                    runner=OfflineRunner();runner.run_context=run;runner.provider=OfflineProvider()
                    runner.provider.provider_config={'modalities':capability}
                    runner.req=types.SimpleNamespace(session_id='synthetic',conversation=None,extra_user_content_parts=[],model='deepseek-chat')
                    with patch('socket.create_connection',side_effect=AssertionError('No real HTTP allowed')):
                        replies=[reply async for reply in runner._iter_llm_responses()]
                    self.assertEqual(len(replies),1)
                    payload=runner.provider.http_payload
                    self.assertIn(marker,json.dumps(payload['messages']))
                    self.assertNotIn('_no_save',json.dumps(payload))
                    self.assertEqual(payload['messages'][0],{'role':'system','content':'原人格'})

                saved=[]
                class Conversations:
                    async def update_conversation(self,*args,**kwargs):saved.append(kwargs['history'])
                stage=types.SimpleNamespace(conv_manager=Conversations())
                save=method('astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py','InternalAgentSubStage','_save_to_history',namespace)
                request=types.SimpleNamespace(conversation=types.SimpleNamespace(cid='synthetic',token_usage=None),tool_calls_result=None)
                run.messages.append(message.AssistantMessageSegment(content='合成回答'))
                await save(stage,event,request,types.SimpleNamespace(role='assistant',completion_text='合成回答',usage=None),run.messages,None)
                self.assertEqual(len(saved),1)
                self.assertNotIn(marker,json.dumps(saved))
                self.assertEqual([entry['role'] for entry in saved[0]],['user','assistant'])


if __name__=='__main__':unittest.main()
