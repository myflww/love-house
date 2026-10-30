from __future__ import annotations
import copy
import json
import os
import threading
import unittest
from unittest.mock import patch
import test_http as fixtures
from nkb import Brain
from nkb.adapters.http import make_handler

class CompanionHTTPTests(unittest.TestCase):
    setUp=fixtures.HTTPTests.setUp
    tearDown=fixtures.HTTPTests.tearDown
    request=fixtures.HTTPTests.request

    def test_profile_confirmed_memory_context_and_reopen(self):
        self.assertEqual(self.request('POST','/api/ai/profile',{'name':'测试角色','user_name':'测试用户','persona':'简短回答'})[0],200)
        status,memory,_=self.request('POST','/api/ai/remember',{'text':'测试用户不喝咖啡','kind':'preference','important':True})
        self.assertEqual(status,200,memory)
        before=self.path.read_bytes(); snapshot=copy.deepcopy(self.brain.to_dict())
        status,context,_=self.request('POST','/api/ai/context',{'query':'我喜欢什么饮料','session_id':'s1'})
        self.assertEqual(status,200,context)
        self.assertIn(memory['id'],context['memory_ids'])
        self.assertIn('不喝咖啡',context['packet'])
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.brain.to_dict(),snapshot)
        self.assertEqual(Brain.open(self.path).meta['companion_profile']['name'],'测试角色')

    def test_missing_key_is_error_without_saving_fake_turn(self):
        before=self.path.read_bytes()
        with patch.dict(os.environ,{},clear=True):
            status,result,_=self.request('POST','/api/ai/chat',{'message':'你好','session_id':'s','request_id':'r'})
        self.assertEqual(status,400,result);self.assertEqual(result['code'],'missing_key')
        self.assertEqual(self.path.read_bytes(),before)

    def test_chat_is_injected_recorded_and_idempotent_without_saving_key(self):
        with patch('nkb.adapters.http.DeepSeekClient.reply',return_value='测试助手回复') as client:
            payload={'message':'这是一条用户原文','session_id':'s','request_id':'r','api_key':'FAKE_KEY_FOR_TEST'}
            status,result,_=self.request('POST','/api/ai/chat',payload)
            self.assertEqual(status,200,result);self.assertTrue(result['saved'])
            args=client.call_args.kwargs;self.assertEqual(args['messages'][-1]['content'],payload['message'])
            self.assertEqual(self.request('POST','/api/ai/chat',payload)[1]['reply'],'测试助手回复')
            client.assert_called_once()
        raw=self.path.read_text();self.assertNotIn(payload['api_key'],raw)
        n=self.brain.nodes[result['id']];self.assertEqual(n['text'],payload['message'])
        self.assertEqual(n['meta']['assistant_reply'],'测试助手回复')
        self.assertEqual(n['meta']['roles']['text'],'user')
        self.assertFalse(n['important'])

    def test_chat_save_failure_can_retry_without_rebilling(self):
        payload={'message':'用户原文','session_id':'retry','request_id':'r'}
        with patch('nkb.adapters.http.DeepSeekClient.reply',return_value='已收到的回复') as client:
            before=copy.deepcopy(self.brain.to_dict())
            with patch.object(self.brain,'persist',side_effect=OSError('disk')):
                status,result,_=self.request('POST','/api/ai/chat',payload)
            self.assertEqual(status,200);self.assertFalse(result['saved']);self.assertEqual(result['reply'],'已收到的回复')
            self.assertEqual(self.brain.to_dict(),before)
            retry=self.request('POST','/api/ai/chat',payload)[1]
            self.assertTrue(retry['saved']);client.assert_called_once()

    def test_network_does_not_hold_graph_operation_lock(self):
        started=threading.Event();release=threading.Event();result=[]
        def slow(**kwargs):started.set();release.wait(3);return '模拟网络回复'
        with patch('nkb.adapters.http.DeepSeekClient.reply',side_effect=slow):
            thread=threading.Thread(target=lambda:result.append(self.request('POST','/api/ai/chat',{'message':'你好','session_id':'s','request_id':'slow'})))
            thread.start();self.assertTrue(started.wait(2))
            try:self.assertEqual(self.request('GET','/api/graph')[0],200)
            finally:release.set();thread.join(5)
        self.assertEqual(result[0][0],200)

    def test_save_retry_cannot_relabel_the_provider_model(self):
        payload={'message':'原文','session_id':'model-retry','request_id':'one','model':'model-a'}
        with patch('nkb.adapters.http.DeepSeekClient.reply',return_value='模型A的回复') as client:
            with patch.object(self.brain,'persist',side_effect=OSError('disk')):
                self.assertFalse(self.request('POST','/api/ai/chat',payload)[1]['saved'])
            self.assertEqual(self.request('POST','/api/ai/chat',{**payload,'model':'model-b'})[0],400)
            result=self.request('POST','/api/ai/chat',payload)[1]
            self.assertTrue(result['saved']);client.assert_called_once()
            self.assertEqual(self.brain.nodes[result['id']]['meta']['model'],'model-a')

    def test_harness_remember_is_not_user_confirmed_and_event_is_sourced(self):
        status,r,_=self.request('POST','/api/ai/remember',{'text':'Harness提供的记录','origin':'harness','session_id':'s'})
        self.assertEqual(status,200,r);n=self.brain.nodes[r['id']]
        self.assertEqual(n['meta']['source'],'harness_recorded');self.assertFalse(n['meta']['confirmed'])
        self.assertNotIn('用户确认',n['tags'])
        payload={'text':'观察到了网页标题','session_id':'s','request_id':'event-1','source_url':'https://example.com/page?token=private#fragment','outcome':'observed'}
        status,event,_=self.request('POST','/api/ai/event',payload)
        self.assertEqual(status,200,event);self.assertEqual(event['source_url'],'https://example.com/page')
        self.assertEqual(self.request('POST','/api/ai/event',payload)[1]['id'],event['id'])
        self.assertNotIn('token=private',self.path.read_text())
        self.assertEqual(self.brain.nodes[event['id']]['meta']['source'],'tool_observation')

    def test_record_does_not_upgrade_assistant_claims_to_facts(self):
        payload={'user':'今天做了测试','assistant':'我猜你很喜欢辣椒','session_id':'record','request_id':'one'}
        status,r,_=self.request('POST','/api/ai/record',payload)
        self.assertEqual(status,200,r);self.assertEqual(self.brain.nodes[r['id']]['text'],payload['user'])
        self.assertEqual(self.request('POST','/api/ai/record',payload)[1]['id'],r['id'])
        self.assertFalse(any(n['kind']=='preference' and '辣椒' in n['text'] for n in self.brain.nodes.values()))

if __name__=='__main__':unittest.main()
