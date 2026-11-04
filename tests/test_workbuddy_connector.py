"""Synthetic WorkBuddy configuration and real MCP startup regression checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nkb.service.agent_client import (
    AgentClient, AgentConnectionError, configure_workbuddy, make_agent_config,
    validate_config, validate_hook_matcher, connection_config_diagnostic,
)

ROOT=Path(__file__).resolve().parents[1]


class WorkBuddyConnectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'用户 数据'/'LoveHouse'
        self.home=Path(self.temp.name)/'用户主目录'
        self.secret={'id':'conn_workbuddy_fixture','library_id':'default','token':'FAKE-SYNTHETIC-PRIVATE-TOKEN',
                     'enabled':True,'revoked':False,'session_scope':'next_session','binding_revision':0}
        self.target=self.home/'.workbuddy/mcp.json'

    def install(self,**kwargs):
        return configure_workbuddy(self.root,self.secret,home=self.home,**kwargs)

    def write_existing(self,value):
        self.target.parent.mkdir(parents=True,exist_ok=True)
        self.target.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        return self.target.read_bytes()

    def test_preview_uses_actual_private_path_without_writing_and_separates_proofs(self):
        plan=self.install()
        self.assertFalse(self.home.exists())
        self.assertFalse(self.root.exists())
        self.assertEqual(plan['private_path'],str((self.root/'agent-connections/conn_workbuddy_fixture.json').resolve()))
        command=next(iter(plan['mcp_config']['mcpServers'].values()))
        self.assertEqual(command['args'][-1],plan['private_path'])
        self.assertFalse(plan['hook_supported'])
        self.assertIsNone(plan['tools_loaded'])
        self.assertTrue(plan['requires_trust'])
        self.assertIn('信任',''.join(plan['next_steps']))
        self.assertIn('重启',''.join(plan['next_steps']))
        self.assertNotIn(self.secret['token'],json.dumps(plan))

    def test_merge_backs_up_exact_bytes_preserves_other_servers_and_never_installs_hooks(self):
        old={'mcpServers':{'another-server':{'command':'safe-program','env':{'PRIVATE_EXISTING':'MUST-STAY-LOCAL'}}},
             'preferences':{'keep':'原值'}}
        raw=self.write_existing(old)
        settings=self.target.parent/'settings.json'
        settings.write_bytes(b'{"existing":true}')
        plan=self.install(apply=True)
        self.assertTrue(plan['applied'])
        self.assertTrue(plan['readback_verified'])
        actual=json.loads(self.target.read_text('utf-8'))
        self.assertEqual(actual['mcpServers']['another-server'],old['mcpServers']['another-server'])
        self.assertEqual(actual['preferences'],old['preferences'])
        self.assertEqual(Path(plan['backup_path']).read_bytes(),raw)
        self.assertEqual(settings.read_bytes(),b'{"existing":true}')
        self.assertFalse((self.home/'.codebuddy').exists())
        self.assertNotIn('MUST-STAY-LOCAL',json.dumps(plan))
        self.assertNotIn(self.secret['token'],self.target.read_text('utf-8'))
        self.assertEqual(json.loads(Path(plan['private_path']).read_text('utf-8'))['token'],self.secret['token'])
        self.assertTrue(self.install()['readback_verified'])

    def test_passive_connection_plan_does_not_read_existing_host_json(self):
        raw=self.write_existing({'mcpServers':{'another-server':{'command':'safe-program',
            'env':{'PRIVATE_EXISTING':'MUST-STAY-LOCAL'}}}})
        with patch('nkb.service.agent_client._read_json',side_effect=AssertionError('passive host read')) as read:
            plan=self.install(inspect_existing=False)
        read.assert_not_called()
        self.assertTrue(plan['config_exists'])
        self.assertFalse(plan['readback_checked'])
        self.assertFalse(plan['readback_verified'])
        self.assertEqual(self.target.read_bytes(),raw)
        self.assertNotIn('MUST-STAY-LOCAL',json.dumps(plan))
        with self.assertRaises(AgentConnectionError):self.install(inspect_existing='yes')

    def test_reinstall_updates_only_own_entry_and_verifies_real_saved_json(self):
        first=self.install(apply=True)
        old=json.loads(self.target.read_text('utf-8'))
        name=next(iter(old['mcpServers']))
        old['mcpServers'][name]['command']='old-runtime-path'
        self.write_existing(old)
        second=self.install(apply=True)
        self.assertTrue(second['readback_verified'])
        self.assertEqual(json.loads(self.target.read_text('utf-8'))['mcpServers'],first['mcp_config']['mcpServers'])

    def test_same_name_other_identity_is_not_overwritten(self):
        plan=self.install()
        name=next(iter(plan['mcp_config']['mcpServers']))
        raw=self.write_existing({'mcpServers':{name:{'command':'another-app','args':['another-private.json']}}})
        with self.assertRaises(AgentConnectionError) as caught:self.install(apply=True)
        self.assertEqual(caught.exception.code,'mcp_name_conflict')
        self.assertEqual(self.target.read_bytes(),raw)
        self.assertFalse(self.root.exists())

    def test_other_global_memory_connector_blocks_preview_and_apply_without_reading_its_private_file(self):
        plan=self.install()
        own_name=next(iter(plan['mcp_config']['mcpServers']))
        other_name='love-house-memory-OTHERLIB'
        foreign_private=self.home/'private-other-memory.json'
        raw=self.write_existing({'mcpServers':{
            other_name:{'command':'other-runtime','args':['--connection-config',str(foreign_private)],
                        'env':{'PRIVATE_TOKEN':'FOREIGN-SECRET-MUST-NOT-LEAVE-CONFIG'}},
            'unrelated-server':{'command':'keep-this-program'}}})
        original_reader=__import__('nkb.service.agent_client',fromlist=['_read_json'])._read_json
        def only_host_profile(path,limit):
            self.assertEqual(Path(path).resolve(),self.target.resolve(),'Must not follow a different memory connector private file')
            return original_reader(path,limit)
        with patch('nkb.service.agent_client._read_json',side_effect=only_host_profile):
            blocked=self.install()
            self.assertFalse(blocked['supported']);self.assertFalse(blocked['can_apply'])
            self.assertFalse(blocked['readback_verified'])
            self.assertEqual(blocked['code'],'cross_memory_connector_conflict')
            self.assertEqual(blocked['other_memory_connector_count'],1)
            self.assertIn('复用已有连接',''.join(blocked['next_steps']))
            self.assertNotIn('FOREIGN-SECRET',json.dumps(blocked))
            self.assertNotIn(str(foreign_private),json.dumps(blocked))
            self.assertNotIn(other_name,json.dumps(blocked))
            with self.assertRaises(AgentConnectionError) as caught:self.install(apply=True)
        self.assertEqual(caught.exception.code,'cross_memory_connector_conflict')
        self.assertEqual(self.target.read_bytes(),raw)
        self.assertEqual({p.name for p in self.target.parent.iterdir()},{'mcp.json'})
        self.assertFalse(self.root.exists())
        self.assertNotIn(own_name,json.loads(self.target.read_text())['mcpServers'])

    def test_current_entry_match_does_not_hide_another_memory_connector_or_trust_disabled_flags(self):
        own=self.install()['mcp_config']['mcpServers']
        raw=self.write_existing({'mcpServers':{**own,
            'love-house-memory-another':{'disabled':True,'enabled':False,'command':'other-runtime'}}})
        plan=self.install()
        self.assertFalse(plan['supported']);self.assertFalse(plan['can_apply'])
        self.assertFalse(plan['readback_verified'])
        with self.assertRaises(AgentConnectionError) as caught:self.install(apply=True)
        self.assertEqual(caught.exception.code,'cross_memory_connector_conflict')
        self.assertEqual(self.target.read_bytes(),raw)
        self.assertFalse(self.root.exists())

    def test_passive_plan_does_not_inspect_another_memory_connector(self):
        raw=self.write_existing({'mcpServers':{'love-house-memory-other':{'command':'other-runtime'}}})
        with patch('nkb.service.agent_client._read_json',side_effect=AssertionError('passive host profile read')):
            plan=self.install(inspect_existing=False)
        self.assertTrue(plan['supported'])
        self.assertIsNone(plan['can_apply'])
        self.assertFalse(plan['readback_checked'])
        self.assertNotIn('other_memory_connector_count',plan)
        self.assertEqual(self.target.read_bytes(),raw)
        self.assertFalse(self.root.exists())

    def test_invalid_or_duplicate_json_does_not_destroy_user_configuration(self):
        self.target.parent.mkdir(parents=True)
        for raw in (b'not-json',b'{"mcpServers":{},"mcpServers":{}}',b'{"mcpServers":[]}'):
            self.target.write_bytes(raw)
            with self.assertRaises(AgentConnectionError):self.install(apply=True)
            self.assertEqual(self.target.read_bytes(),raw)
        self.assertEqual(list(self.target.parent.glob('*.bak')),[])

    def test_disabled_connection_cannot_install(self):
        self.secret['enabled']=False
        with self.assertRaises(AgentConnectionError) as caught:self.install(apply=True)
        self.assertEqual(caught.exception.code,'paused')
        self.assertFalse(self.home.exists())

    def test_generated_match_all_is_a_valid_regular_expression(self):
        bundle=make_agent_config(self.root,self.secret)
        self.assertEqual(bundle['hook_config']['matcher'],'.*')
        for invalid in ('*','[','('):
            with self.assertRaises(AgentConnectionError) as caught:validate_hook_matcher(invalid)
            self.assertEqual(caught.exception.code,'invalid_matcher')

    def test_missing_bridge_and_hook_config_produce_structured_actionable_diagnostics(self):
        missing=self.root/'agent-connections/conn_missing.json'
        env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'}
        for executable in ('agent_memory_bridge.py','agent_memory_hook.py'):
            result=subprocess.run([sys.executable,str(ROOT/'desktop'/executable),'--connection-config',str(missing)],
                                  input='{}',capture_output=True,text=True,encoding='utf-8',env=env,timeout=15)
            self.assertEqual(result.returncode,2)
            diagnostic=json.loads(result.stderr)
            self.assertEqual(diagnostic['code'],'connection_config_not_found')
            self.assertEqual(diagnostic['config_path'],str(missing))
            self.assertIn('expected_directory',diagnostic)
            self.assertEqual(diagnostic['next_action'],'copy_connection_config_path')
            self.assertNotIn(self.secret['token'],result.stderr+result.stdout)
            if executable=='agent_memory_bridge.py':self.assertEqual(result.stdout,'')

    def test_invalid_private_json_contents_never_reach_stderr(self):
        path=self.root/'bad.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"token":"NEVER-PRINT-THIS"',encoding='utf-8')
        result=subprocess.run([sys.executable,str(ROOT/'desktop/agent_memory_bridge.py'),'--connection-config',str(path)],
                              input='',capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,2)
        self.assertEqual(json.loads(result.stderr)['code'],'invalid_file')
        self.assertNotIn('NEVER-PRINT-THIS',result.stderr)

    def test_legacy_scope_migrates_without_treating_fixed_enum_as_a_session_id(self):
        bundle=make_agent_config(self.root,self.secret,persist=True)
        config=json.loads(Path(bundle['private_path']).read_text('utf-8'))
        for legacy,policy,bound in [('connection','any',None),('next_session','next_session',None),('old-window','fixed','old-window')]:
            value={**config,'session_scope':legacy,'bound_session_id':None}
            value.pop('session_scope_policy')
            normalized=validate_config(value)
            self.assertEqual(normalized['session_scope_policy'],policy)
            self.assertEqual(normalized['bound_session_id'],bound)
        with self.assertRaises(AgentConnectionError):validate_config({**config,'session_scope_policy':'fixed','bound_session_id':None})

    def test_explicit_policy_is_not_interpreted_as_a_legacy_window_id(self):
        config=json.loads(Path(make_agent_config(self.root,self.secret,persist=True)['private_path']).read_text('utf-8'))
        with self.assertRaises(AgentConnectionError) as caught:
            validate_config({**config,'session_scope_policy':'not-a-policy'})
        self.assertEqual(caught.exception.code,'invalid_config')
        with self.assertRaises(AgentConnectionError):
            make_agent_config(self.root,{**self.secret,'session_scope_policy':'not-a-policy'},persist=True)

    def test_config_helper_normalizes_legacy_secrets_before_adding_policy(self):
        for legacy,policy,bound in [('connection','any',None),('next_session','next_session',None),
                                   ('configured-window','fixed','configured-window')]:
            with self.subTest(legacy=legacy):
                bundle=make_agent_config(self.root/legacy,{**self.secret,'session_scope':legacy},persist=True)
                stored=json.loads(Path(bundle['private_path']).read_text('utf-8'))
                self.assertEqual(stored['session_scope_policy'],policy)
                self.assertEqual(stored['session_scope'],policy)
                self.assertEqual(stored['bound_session_id'],bound)
                self.assertEqual(bundle['connection_config_public']['bound_session_id'],bound)

    def test_macos_missing_config_points_to_existing_application_data_namespace(self):
        with patch('nkb.service.agent_client.sys.platform','darwin'),patch('nkb.service.agent_client.Path.home',return_value=self.home):
            diagnostic=connection_config_diagnostic(self.root/'missing.json')
        self.assertEqual(diagnostic['expected_directory'],str(self.home/'Library/Application Support/NeuralKnowledge/agent-connections'))
        self.assertEqual(diagnostic['config_path'],str(self.root/'missing.json'))
        self.assertEqual(diagnostic['next_action'],'copy_connection_config_path')

    def test_rebind_revision_resets_claim_and_does_not_drain_old_pending_under_new_credential(self):
        bundle=make_agent_config(self.root,self.secret,persist=True)
        client=AgentClient(bundle['private_path'])
        hook={'session_id':'old-window','turn_id':'old-turn','user':'SYNTHETIC OLD USER','assistant':'SYNTHETIC OLD REPLY'}
        with patch.object(client,'discover',side_effect=AgentConnectionError('offline','offline')):
            self.assertTrue(client.submit_hook(hook)['queued'])
        old_config=client.config()
        old_pending=list(Path(old_config['outbox_dir']).glob('*.json'))
        self.assertEqual(len(old_pending),1)
        revised={**self.secret,'binding_revision':1,'token':'NEW-SYNTHETIC-TOKEN'}
        updated=make_agent_config(self.root,revised,persist=True)
        self.assertFalse(client.config()['enabled'])
        self.assertTrue(client.config()['revoked'])
        self.assertEqual(client.config()['token'],'')
        self.assertNotEqual(updated['private_path'],bundle['private_path'])
        client=AgentClient(updated['private_path'])
        current=client.config()
        self.assertIsNone(current['bound_session_id'])
        self.assertEqual(client.pending_count(),0)
        self.assertEqual(Path(current['outbox_dir']).name,'binding-1')
        self.assertTrue(old_pending[0].exists())
        self.assertEqual(client.submit_tool_record('memory_record_turn',{
            'session_id':'new-window','request_id':'manual','user':'a','assistant':'b'})['next_action'],
            'wait_for_source_adapter_binding')
        with self.assertRaises(AgentConnectionError):make_agent_config(self.root,self.secret,persist=True)
        self.assertEqual(client.config()['token'],'NEW-SYNTHETIC-TOKEN')

    def test_rebinding_replaces_owned_workbuddy_entry_with_new_private_path(self):
        first=self.install(apply=True)
        old_path=first['private_path']
        self.secret={**self.secret,'binding_revision':1,'token':'NEW-REVISION-TOKEN'}
        revised=self.install(apply=True)
        self.assertTrue(revised['readback_verified'])
        self.assertNotEqual(old_path,revised['private_path'])
        self.assertEqual(next(iter(json.loads(self.target.read_text('utf-8'))['mcpServers'].values()))['args'][-1],revised['private_path'])
        old_client=AgentClient(old_path)
        with self.assertRaises(AgentConnectionError) as caught:
            old_client.submit_hook({'session_id':'old-window','turn_id':'old','user':'old','assistant':'old'})
        self.assertEqual(caught.exception.code,'paused')


if __name__=='__main__':unittest.main()
