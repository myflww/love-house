"""Actual local TLS/HTTP requests against isolated memory, never a public deployment."""
from __future__ import annotations
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler,HTTPRedirectHandler
import importlib.util

from nkb.service.credentials import KeyStore
from nkb.service.host import MemoryHost,make_controller
from nkb.service.remote_gateway import RemoteGateway,create_server,COOKIE,public_origin


class RemoteGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        openssl=shutil.which('openssl')
        if not openssl:raise unittest.SkipTest('openssl is required to mint isolated TLS test certificates')
        cls.cert_scratch=tempfile.TemporaryDirectory(prefix='love-house-test-tls-')
        root=Path(cls.cert_scratch.name);cls.cert=root/'certificate.pem';cls.key=root/'test-private.pem'
        config=root/'openssl.cnf';config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
        result=subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(config),'-keyout',str(cls.key),'-out',str(cls.cert)],capture_output=True,timeout=20)
        if result.returncode:raise RuntimeError('isolated TLS certificate generation failed')
    @classmethod
    def tearDownClass(cls):cls.cert_scratch.cleanup()
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory(prefix='love-house-remote-test-');self.root=Path(self.scratch.name)
        self.host=MemoryHost(self.root/'data',key_store=KeyStore(allow_keychain=False))
        self.controller=ThreadingHTTPServer(('127.0.0.1',0),make_controller(self.host));self.host.controller_port=self.controller.server_port
        self.controller_thread=threading.Thread(target=self.controller.serve_forever,kwargs={'poll_interval':.01});self.controller_thread.start()
        self.gateway=RemoteGateway(self.host,origin='https://localhost',admin_token='A'*48)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(self.cert,self.key)
        self.server=create_server(self.gateway,tls_context=context)
        self.origin='https://localhost:'+str(self.server.server_port);self.gateway.origin=self.origin;self.gateway.authority='localhost:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01});self.thread.start()
        self.client=build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context(cafile=str(self.cert))))
        self.cookie=None;self.csrf=None
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.controller.shutdown();self.controller.server_close();self.controller_thread.join();self.host.stop();self.scratch.cleanup()
    def req(self,path,body=None,*,token=None,cookie=None,csrf=None,origin=True,headers=None,method=None):
        values={'Content-Type':'application/json'}
        if origin is True:values['Origin']=self.origin
        elif isinstance(origin,str):values['Origin']=origin
        if token:values['Authorization']='Bearer '+token
        if cookie:values['Cookie']=cookie
        if csrf:values['X-LoveHouse-CSRF']=csrf
        if headers:values.update(headers)
        request=Request(self.origin+path,data=None if body is None else json.dumps(body,ensure_ascii=False).encode(),headers=values,method=method)
        try:response=self.client.open(request,timeout=8)
        except HTTPError as error:response=error
        with response:
            data=response.read();content=response.headers.get('Content-Type','')
            value=json.loads(data) if data and 'application/json' in content else data
            return response.status,value,response.headers
    def login(self):
        code,data,headers=self.req('/api/remote/admin/login',{'admin_token':'A'*48})
        self.assertEqual(code,200,data);self.cookie=headers['Set-Cookie'].split(';')[0];self.csrf=data['csrf_token']
        return headers
    def create(self,**data):
        if not self.cookie:self.login()
        code,result,_=self.req('/api/remote/admin/connections',{'name':'手机真实窗口','library_id':'default',**data},cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,result)
        return result,result['connection']['id'],result['remote_config']['headers']['Authorization'][7:]
    def rpc(self,cid,token,method,params=None,*,modern=False,extra=None):
        headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2026-07-28' if modern else '2025-11-25'}
        params=dict(params or {})
        if modern:
            params['_meta']={'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientInfo':{'name':'isolated-test','version':'1'},'io.modelcontextprotocol/clientCapabilities':{}}
            headers['Mcp-Method']=method
            if method=='tools/call':headers['Mcp-Name']=params.get('name','')
        if extra:headers.update(extra)
        return self.req('/mcp/'+cid,{'jsonrpc':'2.0','id':1,'method':method,'params':params},token=token,headers=headers)

    def test_private_admin_cookie_origin_csrf_and_agent_privilege_boundaries(self):
        self.assertEqual(self.req('/api/remote/health')[0],200)
        self.assertEqual(self.req('/api/remote/admin/libraries')[0],401)
        self.assertEqual(self.req('/api/remote/admin/login',{'admin_token':'A'*48},origin='https://wrong.invalid')[0],403)
        headers=self.login();self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('Secure',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        self.assertEqual(self.req('/api/remote/admin/connections',{'name':'bad'},cookie=self.cookie)[0],403)
        self.assertEqual(self.req('/api/remote/admin/connections',{'name':'bad'},cookie=self.cookie,csrf=self.csrf,origin=False)[0],403)
        _,cid,token=self.create()
        self.assertEqual(self.req('/api/remote/admin/libraries',token=token,cookie=self.cookie)[0],403)
        self.assertEqual(self.req('/api/graph',token=token,cookie=self.cookie)[0],403)
        self.assertEqual(self.req('/api/remote/admin/logout',{},cookie=self.cookie,csrf=self.csrf)[0],200)
        self.assertEqual(self.req('/api/remote/admin/session',cookie=self.cookie)[0],401)

    def test_same_origin_referrer_policy_keeps_legacy_browser_origin_without_accepting_null(self):
        code,html,headers=self.req('/mobile')
        self.assertEqual(code,200)
        self.assertEqual(headers['Referrer-Policy'],'same-origin')
        self.assertIn(b'<meta name="referrer" content="same-origin">',html)
        self.assertEqual(self.req('/api/remote/admin/login',{'admin_token':'A'*48},origin='null')[0],403)
        self.login()
        self.assertEqual(self.req('/api/remote/admin/connections',{'name':'must reject','library_id':'default'},
            cookie=self.cookie,csrf=self.csrf,origin='null')[0],403)
        self.assertEqual(self.host.connections.list(),[])

    def test_remote_configuration_has_only_https_urls_and_header_auth_no_local_commands(self):
        config,cid,token=self.create()
        server=next(iter(config['mcp_config']['mcpServers'].values()))
        self.assertEqual(server['url'],self.origin+'/mcp/'+cid)
        self.assertEqual(server['headers']['Authorization'],'Bearer '+token)
        self.assertNotIn('command',server);self.assertNotIn('runtime_dir',json.dumps(config));self.assertNotIn(str(self.root),json.dumps(config))
        self.assertFalse(config['automatic_memory'])
        self.assertEqual(self.req('/mcp/'+cid+'?token='+token,{},token=token)[0],400)
        self.assertEqual(self.req('/api/remote/admin/libraries',cookie=self.cookie)[0],200)
        status,readback,_=self.req('/api/remote/admin/connections/'+cid+'/config',cookie=self.cookie)
        self.assertEqual(status,200);self.assertEqual(readback['mcp_config'],config['mcp_config'])

    def test_remote_rebind_requires_admin_csrf_and_rotates_connection_without_erasing_history(self):
        _,cid,token=self.create()
        hook={'session_id':'remote-fixture-window-a','turn_id':'one','status':'complete',
              'user':'远程合成测试原话','assistant':'远程合成测试回复'}
        route='/api/remote/connections/'+cid+'/events'
        code,saved,_=self.req(route,hook,token=token)
        self.assertEqual(code,200,saved);self.assertTrue(saved['accepted'])
        before=self.host.snapshot('default')
        management='/api/remote/admin/connections/'+cid+'/rebind'
        body={'confirm':True,'expected_bound_session_id':'remote-fixture-window-a'}
        self.assertEqual(self.req(management,body,token=token)[0],403)
        self.assertEqual(self.req(management,body,cookie=self.cookie)[0],403)
        code,result,_=self.req(management,body,cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,result)
        self.assertEqual(result['connection']['binding_revision'],1)
        self.assertIsNone(result['connection']['bound_session_id'])
        self.assertEqual(self.host.snapshot('default'),before)
        self.assertNotIn('private_path',result)
        new_token=result['remote_config']['headers']['Authorization'][7:]
        self.assertNotEqual(new_token,token)
        self.assertEqual(self.req(route,hook,token=token)[0],401)
        hook={**hook,'session_id':'remote-fixture-window-b','turn_id':'two'}
        code,saved,_=self.req(route,hook,token=new_token)
        self.assertEqual(code,200,saved);self.assertTrue(saved['accepted'])
        self.assertEqual(self.host.connections.get(cid)['bound_session_id'],'remote-fixture-window-b')
        self.assertEqual(len(self.host.snapshot('default')['nodes']),2)

    def test_legacy_and_stateless_modern_mcp_and_header_validation(self):
        _,cid,token=self.create()
        status,data,headers=self.rpc(cid,token,'initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
        self.assertEqual(status,200,data);self.assertEqual(data['result']['protocolVersion'],'2025-11-25');self.assertNotIn('Mcp-Session-Id',headers)
        status,data,_=self.rpc(cid,token,'server/discover',modern=True)
        self.assertEqual(status,200,data);self.assertIn('2026-07-28',data['result']['supportedVersions']);self.assertEqual(data['result']['resultType'],'complete')
        for modern in (False,True):
            code,data,_=self.rpc(cid,token,'tools/list',modern=modern)
            self.assertEqual(code,200,data);self.assertIn('memory_bootstrap',[row['name'] for row in data['result']['tools']])
        code,data,_=self.rpc(cid,token,'tools/call',{'name':'memory_status','arguments':{}},modern=True,extra={'Mcp-Name':'memory_bootstrap'})
        self.assertEqual(code,400,data);self.assertEqual(data['error']['code'],-32020)
        code,data,_=self.rpc(cid,token,'tools/list',modern=True,extra={'MCP-Protocol-Version':'1900-01-01'})
        self.assertEqual(code,400);self.assertEqual(data['error']['code'],-32022)
        self.assertEqual(self.rpc(cid,token,'not/a/method',modern=True)[0],404)
        self.assertEqual(self.req('/mcp/'+cid,token=token)[0],405)
        self.assertEqual(self.req('/mcp/'+cid,token=token,origin='https://wrong.invalid')[0],403)

    def test_actual_hook_binds_real_window_not_transport_session_and_saves_original_words(self):
        _,cid,token=self.create()
        call={'name':'memory_record_turn','arguments':{'session_id':'manual-window','request_id':'manual','user':'不得抢占','assistant':'不是自动记录'}}
        _,result,_=self.rpc(cid,token,'tools/call',call,modern=True,extra={'Mcp-Session-Id':'not-the-real-window'})
        self.assertEqual(result['result']['structuredContent']['status'],'awaiting_window_binding')
        self.assertEqual(self.host.connections.get(cid)['session_scope'],'next_session')
        hook={'session_id':'real-host-window','turn_id':'actual-one','status':'complete','user':'真实用户原话','assistant':'真实助手最终回复'}
        code,saved,_=self.req('/api/remote/connections/'+cid+'/events',hook,token=token,headers={'Mcp-Session-Id':'fake-transport-id'})
        self.assertEqual(code,200,saved);self.assertEqual(saved['status'],'saved')
        self.assertEqual(self.host.connections.get(cid)['session_scope'],'next_session')
        self.assertEqual(self.host.connections.get(cid)['bound_session_id'],'real-host-window')
        code,status,_=self.req('/api/remote/connections/'+cid+'/status',token=token)
        self.assertEqual(code,200,status);self.assertFalse(status['automatic_memory'])
        self.assertEqual(status['capture_mode'],'host_hook_received')
        self.assertEqual(status['capture']['hook_event_count'],1)
        other={**hook,'session_id':'another-real-window','turn_id':'outside'}
        code,rejected,_=self.req('/api/remote/connections/'+cid+'/events',other,token=token)
        self.assertEqual(code,200,rejected);self.assertFalse(rejected['accepted']);self.assertEqual(rejected['code'],'scope_conflict')
        self.assertEqual(self.req('/api/remote/connections/'+cid+'/events',hook,token=token)[1]['duplicate'],True)
        _,page,_=self.rpc(cid,token,'tools/call',{'name':'memory_list','arguments':{}},modern=True)
        entry=page['result']['structuredContent']['entries'][0]
        _,read,_=self.rpc(cid,token,'tools/call',{'name':'memory_read','arguments':{'memory_id':entry['id']}})
        self.assertEqual(read['result']['structuredContent']['text'],'真实用户原话')

    def test_fixed_connection_library_isolation_and_manual_does_not_claim_automatic_capture(self):
        _,a,token_a=self.create(session_scope='connection')
        other_lib=self.host.manager.create_library('另一个记忆身份')['id']
        _,b,token_b=self.create(library_id=other_lib)
        self.assertEqual(self.rpc(a,token_b,'tools/list')[0],401)
        self.assertEqual(self.req('/api/remote/connections/'+a+'/status?library_id='+other_lib,token=token_a)[0],403)
        _,invalid,_=self.rpc(a,token_a,'tools/call',{'name':'memory_bootstrap','arguments':{'library_id':other_lib}})
        self.assertTrue(invalid['result']['isError'])
        record={'name':'memory_record_turn','arguments':{'session_id':'real-manual-window','request_id':'manual','user':'实际手动补录','assistant':'这不是自动上报'}}
        _,saved,_=self.rpc(a,token_a,'tools/call',record)
        self.assertEqual(saved['result']['structuredContent']['status'],'saved')
        _,status,_=self.req('/api/remote/connections/'+a+'/status',token=token_a)
        self.assertFalse(status['automatic_memory']);self.assertEqual(status['capture_mode'],'tools_only')
        self.assertEqual(self.host.library(other_lib)['node_count'],0)
        self.assertEqual(self.host.connections.get(b)['session_scope'],'next_session')

    def test_admin_shared_app_proxy_is_fixed_local_and_remains_cookie_protected(self):
        self.login()
        self.assertEqual(self.req('/api/graph')[0],401)
        code,data,_=self.req('/api/graph',cookie=self.cookie);self.assertEqual(code,200,data);self.assertIn('nodes',data)
        self.assertEqual(self.req('/api/adapters/harness/detect',cookie=self.cookie)[0],404)
        code,html,_=self.req('/app/',cookie=self.cookie);self.assertEqual(code,200);self.assertIn(b'/app/remote-bootstrap.js',html)
        self.assertIn(b'data-nkb-component="connection-ux.js"',html)
        self.assertEqual(self.req('/app/')[0],401)
        code,script,_=self.req('/app/remote-bootstrap.js',cookie=self.cookie);self.assertEqual(code,200);self.assertIn(b'X-LoveHouse-CSRF',script)

    def test_shared_08_experiences_rules_and_retention_write_readback_use_same_memory(self):
        self.login()
        for path in ('/api/experiences?limit=30','/api/organizer/rules','/api/retention','/api/organizer'):
            code,data,_=self.req(path,cookie=self.cookie)
            self.assertEqual(code,200,(path,data))
        code,saved,_=self.req('/api/retention/settings',{'forgetting_pace':'gentle','usage_reinforcement':True},cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,saved)
        _,readback,_=self.req('/api/retention',cookie=self.cookie)
        self.assertEqual(readback['settings']['forgetting_pace'],'gentle')
        self.assertTrue(readback['settings']['usage_reinforcement'])
        self.assertEqual(self.host.retention_view('default')['settings'],readback['settings'])

    def test_paused_or_revoked_credentials_and_write_notifications_cannot_submit(self):
        _,cid,token=self.create()
        hook={'session_id':'real','turn_id':'one','user':'实际内容','assistant':'实际回复'}
        body={'jsonrpc':'2.0','method':'tools/call','params':{'name':'memory_remember','arguments':{'text':'不能静默写入','session_id':'real'}}}
        headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
        self.assertEqual(self.req('/mcp/'+cid,body,token=token,headers=headers)[0],400)
        self.assertEqual(self.host.library('default')['node_count'],0)
        route='/api/remote/admin/connections/'+cid
        self.assertEqual(self.req(route+'/enabled',{'enabled':False},cookie=self.cookie,csrf=self.csrf)[0],200)
        self.assertEqual(self.req('/api/remote/connections/'+cid+'/events',hook,token=token)[0],401)
        self.assertEqual(self.req(route+'/enabled',{'enabled':True},cookie=self.cookie,csrf=self.csrf)[0],200)
        self.assertEqual(self.req(route+'/disconnect',{},cookie=self.cookie,csrf=self.csrf)[0],200)
        self.assertEqual(self.rpc(cid,token,'tools/list')[0],401)

    def test_large_legal_dialogue_import_node_query_memory_package_and_share_download(self):
        self.login()
        transcript={'id':'isolated-historical-window','padding':'x'*1100000,
                    'messages':[{'role':'user','content':'历史用户原话'},{'role':'assistant','content':'历史助手原话'}]}
        payload={'name':'historical.json','format':'json','content':json.dumps(transcript,ensure_ascii=False)}
        def post(path,body):return self.req(path,body,cookie=self.cookie,csrf=self.csrf)
        code,preview,_=post('/api/dialogue-import/preview',payload)
        self.assertEqual(code,200,preview);self.assertEqual(preview['added'],1)
        code,saved,_=post('/api/dialogue-import/apply',{**payload,'confirm':True,'expected_fingerprint':preview['fingerprint']})
        self.assertEqual(code,200,saved)
        _,graph,_=self.req('/api/graph',cookie=self.cookie);node_id=graph['nodes'][0]['id']
        code,node,_=self.req('/api/node?id='+node_id,cookie=self.cookie);self.assertEqual(code,200,node)
        self.assertEqual(node['id'],node_id)
        code,packet,_=post('/api/memory/handoff',{'profile':'M'});self.assertEqual(code,200,packet)
        self.assertIn('历史用户原话',packet['text'])
        code,share,_=post('/api/sharing/preview',{});self.assertEqual(code,200,share)
        code,download,_=post('/api/sharing/download',{'format':'json','confirm':True,'expected_revision':share['content_revision']})
        self.assertEqual(code,200,download);self.assertIn('历史用户原话',download['content'])
        self.assertEqual(self.req('/api/search?token=secret',cookie=self.cookie)[0],400)

    def test_registered_sources_and_fixed_plugin_package_download_work_under_admin_auth(self):
        self.login()
        data={'name':'服务器上的SDK来源','adapter':'sdk','runtime_agent_id':'isolated-server-agent','platforms':['*']}
        code,created,_=self.req('/api/agent/sources',data,cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,created);source=created['source'];self.assertEqual(source['library_id'],'default')
        code,sources,_=self.req('/api/agent/sources',cookie=self.cookie)
        self.assertEqual(code,200,sources);self.assertEqual(sources['sources'][0]['id'],source['id'])
        route='/api/agent/sources/'+source['id']
        code,readback,_=self.req(route+'/config',{},cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,readback);self.assertEqual(readback['source']['id'],source['id'])
        code,paused,_=self.req(route+'/enabled',{'enabled':False},cookie=self.cookie,csrf=self.csrf)
        self.assertEqual(code,200,paused);self.assertFalse(paused['source']['enabled'])
        code,archive,headers=self.req('/api/adapters/astrbot/package',cookie=self.cookie)
        self.assertEqual(code,200);self.assertEqual(archive[:2],b'PK')
        self.assertEqual(self.req('/api/adapters/astrbot/package')[0],401)

    def test_mobile_portal_static_files_are_public_but_its_admin_actions_stay_protected(self):
        for path,content_type in (('/mobile','text/html'),('/mobile/remote-mobile.js','javascript'),('/mobile/remote-mobile.css','text/css')):
            code,data,headers=self.req(path)
            self.assertEqual(code,200,(path,data));self.assertIn(content_type,headers['Content-Type'])
        self.assertEqual(self.req('/mobile/../../service/credentials.py')[0],400)
        self.assertEqual(self.req('/mobile/remote-mobile.js?token=secret')[0],400)

    def test_plaintext_requires_explicit_loopback_trusted_proxy_and_secret(self):
        with self.assertRaises(ValueError):create_server(self.gateway)
        gateway=RemoteGateway(self.host,origin='https://my-owned.invalid',admin_token='B'*40,proxy_secret='P'*40)
        with self.assertRaises(ValueError):create_server(gateway,bind='0.0.0.0')
        server=create_server(gateway);thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        from http.client import HTTPConnection
        try:
            for secret,expected in ((None,403),('P'*40,200)):
                connection=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                headers={'Host':'my-owned.invalid','X-Forwarded-Proto':'https'}
                if secret:headers['X-LoveHouse-Proxy-Key']=secret
                connection.request('GET','/api/remote/health',headers=headers);response=connection.getresponse();response.read();self.assertEqual(response.status,expected);connection.close()
        finally:server.shutdown();server.server_close();thread.join()


class RemoteConfigurationValidationTests(unittest.TestCase):
    def test_service_origin_has_no_credentials_or_redirect_target(self):
        for value in ('http://example.com','https://'+'a'+':'+'b'+'@example.com','https://example.com/path','https://example.com?token=secret','https://example.com/#x'):
            with self.subTest(value=value),self.assertRaises(ValueError):public_origin(value)

    def test_launcher_reads_only_explicit_secret_variable_name_without_echoing_value(self):
        path=Path(__file__).resolve().parents[1]/'scripts/run_remote_memory.py'
        spec=importlib.util.spec_from_file_location('remote_launcher',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.named_secret('PRIVATE_ADMIN',{'PRIVATE_ADMIN':'A'*40,'UNRELATED_SECRET':'B'*40}),'A'*40)
        for name,mapping in (('PRIVATE_ADMIN',{'UNRELATED_SECRET':'B'*40}),('INVALID-NAME',{'INVALID-NAME':'C'*40}),('PRIVATE_ADMIN',{'PRIVATE_ADMIN':'short-private-value'})):
            with self.subTest(name=name),self.assertRaises(ValueError) as failure:module.named_secret(name,mapping)
            self.assertNotIn('short-private-value',str(failure.exception));self.assertNotIn('B'*40,str(failure.exception))
