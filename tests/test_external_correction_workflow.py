"""Synthetic registered QQ source: local-user identity confirmation is required."""
import json
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request

from tests import test_fish_life_workflow as workflow_fixture


class ExternalCorrectionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture=workflow_fixture.FishLifeWorkflowTests();self.fixture.setUp()
        self.host=self.fixture.host
        self.old=self.host.transact('default',lambda brain:brain.add('咖啡偏好','我以前喜欢甜咖啡',
            kind='preference',meta={'source':'user_confirmed','confirmed':True,'speaker':'user'}))
        self.source,self.client=self.fixture.source('astrbot','qq')

    def tearDown(self):self.fixture.tearDown()

    def request(self,path,body=None,*,library='default',management=True,token=None):
        headers={'Content-Type':'application/json','X-NKB-Library':library}
        if management:headers['X-LoveHouse-Management']=self.host.management_token
        if token:headers['Authorization']='Bearer '+token
        request=Request(self.fixture.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with self.fixture.http.open(request,timeout=10) as response:return response.status,json.load(response)
        except HTTPError as response:return response.code,json.load(response)

    def captured(self,text):
        ack=self.client.record_dialogue(text,'合成助手原话','qq-private-window','correction-message',platform='qq',
            details={'sender_id':'SYNTHETIC_SENDER','participant_role':'platform_sender'})
        deadline=time.monotonic()+5
        while True:
            self.host.process_pending(library_id='default',receipt_id=ack['receipt_id'])
            nodes=self.host.snapshot('default')['nodes']
            found=next((nid for nid,node in nodes.items() if node.get('meta',{}).get('evidence',{}).get('archive_receipt_id')==ack['receipt_id']),None)
            if found:return found,nodes[found]
            self.assertLess(time.monotonic(),deadline,'Durable QQ receipt must reach the graph')
            time.sleep(.01)

    def test_external_qq_statement_is_review_material_until_user_claims_it(self):
        source_id,node=self.captured('我现在不喝加糖咖啡了')
        self.assertEqual(node['meta']['evidence']['participant_scope'],'external_participant')
        status,timeline=self.request('/api/memory/timeline')
        self.assertEqual(status,200,timeline)
        candidate=next(row for row in timeline['correction_candidates'] if row['source_id']==source_id)
        self.assertEqual(candidate['actor_scope'],'external_participant')
        self.assertTrue(candidate['requires_identity_confirmation'])
        self.assertEqual(candidate['candidates'],[])
        body={'text':'我现在改喝无糖的茶','source_id':source_id}
        self.assertEqual(self.request(f'/api/memories/{self.old}/correct',body)[0],400)
        claimed={**body,'source_confirmed_as_self':True}
        connection=self.host.connections.get(self.source['connection_id'],secret=True)
        self.assertIn(self.request(f'/api/memories/{self.old}/correct',claimed,management=False,token=connection['token'])[0],(401,403))
        self.assertEqual(self.request(f'/api/memories/{self.old}/correct',claimed,library=self.fixture.other)[0],400)
        status,saved=self.request(f'/api/memories/{self.old}/correct',claimed)
        self.assertEqual(status,200,saved)
        self.assertTrue(saved['verification']['previous_excluded'])
        corrected=self.host.snapshot('default')['nodes'][saved['id']]
        self.assertEqual(corrected['meta']['correction_source_ownership'],'explicit_user_confirmation')
        self.assertEqual(corrected['meta']['correction_source_id'],source_id)
        self.assertFalse(self.request('/api/memory/timeline')[1]['correction_candidates'])
        status,verified=self.request(f"/api/memories/{saved['id']}/verify",{'previous_id':self.old,'query':'咖啡偏好'})
        self.assertEqual(status,200,verified)
        self.assertTrue(verified['selection_verified'])
        self.assertFalse(verified['model_adoption_verified'])

    def test_a_quoted_qq_line_is_not_an_owner_correction_hint(self):
        source_id,_=self.captured('对方说：“我现在不喝加糖咖啡了。”')
        status,timeline=self.request('/api/memory/timeline')
        self.assertEqual(status,200,timeline)
        self.assertFalse(timeline['correction_candidates'])
        self.assertEqual(self.request(f'/api/memories/{self.old}/correct',{
            'text':'不能借引用猜主人偏好','source_id':source_id,'source_confirmed_as_self':True})[0],400)


if __name__=='__main__':unittest.main()
