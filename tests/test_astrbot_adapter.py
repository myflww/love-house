"""Run the shipped AstrBot hook adapter against inert host events and SDK seams."""
from __future__ import annotations

import asyncio
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
        self.assertFalse(self.bridge.stage_final(self.a, "never-received", "不能编造用户原话")["staged"])

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
        self.bridge.stage_observation(self.a, "one", "宿主完成发送阶段；无收件人送达证明。", stage="after_message_sent")
        self.bridge.stage_observation(self.a, "one", "宿主完成发送阶段；无收件人送达证明。", stage="after_message_sent")
        self.bridge.flush()
        obs = [x for x in self.client.calls if x[0] == "observation"]
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0][2]["outcome"], "observed")
        self.assertFalse(obs[0][2]["details"]["recipient_read"])

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
    for name in ("astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.provider", "astrbot.api.star", "astrbot.core", "astrbot.core.agent", "astrbot.core.agent.message", "astrbot.core.agent.run_context", "astrbot.core.astr_agent_context"):
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
    warnings=[]
    modules['astrbot.api'].AstrBotConfig=dict
    modules['astrbot.api'].logger=types.SimpleNamespace(warning=lambda *a:warnings.append(a))
    modules['astrbot.api.event'].filter=Hooks();modules['astrbot.api.event'].AstrMessageEvent=object
    modules['astrbot.api.provider'].LLMResponse=object;modules['astrbot.api.provider'].ProviderRequest=object
    modules['astrbot.api.star'].Context=object;modules['astrbot.api.star'].Star=Star
    modules['astrbot.api.star'].register=lambda *a:lambda cls:cls
    modules['astrbot.core.agent.message'].TextPart=TextPart
    modules['astrbot.core.agent.run_context'].ContextWrapper=Generic
    modules['astrbot.core.astr_agent_context'].AstrAgentContext=object
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
        self.assertEqual(len(obs),2);self.assertTrue(all(x[2]['outcome']=='observed' for x in obs))
        self.assertNotIn('FAKE_DONT_STORE_PROVIDER_KEY',json.dumps(self.client.calls))

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


class PackagingTests(unittest.TestCase):
    def test_plugin_contains_private_config_routing_and_no_provider_key_configuration(self):
        schema=json.loads((PLUGIN/'_conf_schema.json').read_text())
        self.assertFalse(schema['enabled']['default'])
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
            finally:
                server.shutdown();server.server_close();thread.join();host.stop()


if __name__=='__main__':unittest.main()
