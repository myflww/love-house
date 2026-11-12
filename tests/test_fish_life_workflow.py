"""A synthetic fish's QQ reason and browser experience become one evidence-bound memory.

Real local HTTP/SDK/Controller are used; the organizer transport is an explicit
fake. This is not an actual QQ account, browser driver, or AstrBot acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.request import Request, ProxyHandler, build_opener

from nkb import Brain
from nkb.organizer.config import get_profile,save_profile
from nkb.organizer.model import call_model
from nkb.organizer.state import build_input,validate_plan,apply_plan
from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost,make_controller
from nkb.service.source_client import SourceClient,SourceClientError


class FishLifeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='love-house-fish-life-workflow-')
        self.root=Path(self.temp.name)
        self.host=MemoryHost(self.root,key_store=KeyStore(allow_keychain=False),
                             organizer_transport=Mock(side_effect=AssertionError('No default model calls')))
        self.host.organizer.stop()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);self.thread.start()
        self.http=build_opener(ProxyHandler({}));self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.other=self.host.manager.create_library('另一只鱼')['id']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.host.stop();self.temp.cleanup()

    def source(self,adapter,platform,library='default',runtime='fish-one'):
        request=Request(self.base+'/api/agent/sources',data=json.dumps({'name':'合成生活来源 '+platform,
            'adapter':adapter,'runtime_agent_id':runtime,'platforms':[platform]}).encode(),
            headers={'Content-Type':'application/json','X-NKB-Library':library})
        with self.http.open(request,timeout=10) as response:value=json.load(response)
        return value['source'],SourceClient(value['private_path'],timeout=2)

    def node_for(self,receipt,library='default'):
        nodes=self.host.snapshot(library)['nodes']
        return next(nid for nid,node in nodes.items() if node.get('meta',{}).get('evidence',{}).get('archive_receipt_id')==receipt)

    def test_one_cross_platform_life_event_is_readable_and_recalled_without_technical_logs_or_other_fish(self):
        qq_source,qq=self.source('astrbot','qq')
        web_source,web=self.source('sdk','browser')
        _,other=self.source('sdk','browser',self.other,'fish-two')
        reason_text='因为朋友周六准备去海边，所以请查一下天气。'
        what_text='在网页上查到了海边周六的天气。'
        result_text='天气资料显示周六白天没有降雨。'
        reason_ack=qq.record_dialogue(reason_text,'好呀，我会去核对天气。','qq-friend','request-weather',platform='qq',
                                     occurred_at=1700000000,details={'sender_id':'SYNTHETIC_FRIEND','participant_role':'platform_sender'})
        what_ack=web.record_observation(what_text,'browser-task','look-up-weather',platform='browser',occurred_at=1700000030,
                                        source_url='https://example.test/weather',outcome='observed')
        result_ack=web.record_observation(result_text,'browser-task','weather-result',platform='browser',occurred_at=1700000060,
                                          source_url='https://example.test/weather',outcome='success')
        other.record_observation('另一只鱼的独有经历 OTHER_FISH_SECRET','other-task','other-result',platform='browser')
        for ack in (reason_ack,what_ack,result_ack):self.assertTrue(ack['archive_committed'])
        raw_ids=[self.node_for(ack['receipt_id']) for ack in (reason_ack,what_ack,result_ack)]
        before=deepcopy(self.host.snapshot('default')['nodes'])
        self.assertEqual(len(before),3)
        self.assertEqual(len(self.host.connections.archives('default')),3)
        self.assertEqual({before[nid]['meta']['evidence']['platform'] for nid in raw_ids},{'qq','browser'})
        self.assertEqual({before[nid]['meta']['evidence']['source_runtime_agent_id'] for nid in raw_ids},{'fish-one'})

        # Enable only a synthetic per-library profile; the live organizer is
        # stopped and the only model call below uses a local fake transport.
        self.host.transact('default',lambda b:save_profile(b,enabled=True,provider_id='FAKE',base_url='https://offline.invalid/v1',model='FAKE'))
        brain=Brain(self.host.snapshot('default'));profile=get_profile(brain)
        payload,guards=build_input(brain,'default',[{'raw_id':nid,'progress':'{}'} for nid in raw_ids],profile)
        reason={'id':raw_ids[0],'role':'user','quote':reason_text}
        what={'id':raw_ids[1],'role':'tool','quote':what_text}
        outcome={'id':raw_ids[2],'role':'tool','quote':result_text}
        fake_output={'version':1,'operations':[{'action':'remember','layer':'experience','key':'experience.weather.for.friend',
            'text':'为朋友的海边行程核对天气','certainty':'clear','domain':'real','evidence':[reason,what,outcome],
            'episode':{'what':what,'reason':reason,'outcome':outcome}}]}
        requests=[]
        def fake_model(request,*,timeout):
            body=json.loads(request.data);requests.append(body)
            self.assertIn('episode',body['messages'][0]['content'])
            self.assertNotIn('OTHER_FISH_SECRET',body['messages'][1]['content'])
            return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(fake_output,ensure_ascii=False)}}]}
        output=call_model(profile,'FAKE-WORKFLOW-NOT-A-REAL-KEY',payload,send=fake_model)
        plan=validate_plan(output,payload,guards,'synthetic-life-job',profile)
        applied=self.host.transact('default',lambda b:apply_plan(b,plan,'default'))
        self.assertEqual(len(requests),1)
        self.assertEqual(len(applied['created']),1,applied)
        self.assertEqual(applied['candidates'],[])
        after=self.host.snapshot('default')['nodes']
        self.assertEqual({nid:after[nid] for nid in raw_ids},before)
        self.assertEqual(len(self.host.connections.archives('default')),3)

        # The human experience view shows one occurrence assembled from three
        # sources, while all original observations remain available as evidence.
        view=self.host.experiences_view('default')
        self.assertEqual(view['total'],1)
        entry=view['entries'][0];episode=entry['episode']
        self.assertEqual(episode['event_at'],1700000030)
        self.assertEqual(episode['outcome_at'],1700000060)
        self.assertEqual(episode['reason']['basis'],'platform_participant_statement')
        self.assertEqual(episode['reason']['participant_id'],'SYNTHETIC_FRIEND')
        self.assertFalse(episode['reason_verified'])
        self.assertEqual(episode['status'],'success')
        self.assertEqual(episode['status_scope'],'quoted_result_report')
        for text in (what_text,reason_text,result_text):self.assertIn(text,entry['display'])
        self.assertNotIn('browser_call',entry['display']);self.assertNotIn('arguments',entry['display'])
        self.assertIn('对方原话',entry['display'])

        # The fish can take its organized memory back through another source,
        # not merely view it in the desktop. Switching GUI identities does not
        # change the QQ source's fixed binding.
        self.host.manager.select(self.other)
        recalled=qq.read_context('为朋友查询海边天气的经历','new-qq-conversation',max_chars=24000)
        material=json.dumps(recalled,ensure_ascii=False)
        self.assertEqual(recalled['library_id'],'default')
        self.assertIn('love-house-experience/v1',material)
        for text in (what_text,reason_text,result_text):self.assertIn(text,material)
        self.assertNotIn('OTHER_FISH_SECRET',material)
        self.assertEqual(len(self.host.snapshot(self.other)['nodes']),1)
        self.assertFalse(qq_source['full_activity_coverage_verified'])
        self.assertFalse(web_source['full_activity_coverage_verified'])
        with self.assertRaises(SourceClientError):web.record_observation('未适配平台不得假装覆盖','x','game',platform='game')
        self.host.organizer.transport.assert_not_called()


if __name__=='__main__':unittest.main()
