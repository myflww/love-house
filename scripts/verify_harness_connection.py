#!/usr/bin/env python3
"""Run isolated, real Harness CLI turns through a local synthetic model and memory service.

Uses only the explicit installed app/CLI, temporary DSH_HOME and synthetic text.
Never loads a real Harness profile, provider key or personal memory directory.
The JSON report distinguishes an actual host turn from an emitted SDK fixture.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.request import ProxyHandler, Request, build_opener

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nkb.service.host import MemoryHost, make_controller
from nkb.service.httpd import LoopbackHTTPServer as ThreadingHTTPServer
from nkb.service.credentials import KeyStore
from nkb._version import __version__


def host_command(app=None,*,node=None,cli=None):
    if cli:
        entry=Path(cli).expanduser().resolve()
        runtime=Path(node).expanduser().resolve() if node else Path(shutil.which('node') or '')
        if not entry.is_file() or not runtime.is_file():raise ValueError('Provide the existing official CLI entry and Node executable')
        package=entry.parent.parent
        metadata=json.loads((package/'package.json').read_text('utf-8'))
        if metadata.get('name')!='@deepseek-ai/dsh':raise ValueError('CLI entry must belong to the official @deepseek-ai/dsh package')
        return [str(runtime),str(entry)],Path(app).expanduser().resolve() if app else package
    if not app:raise ValueError('Provide --harness-app or --cli with --node')
    app=Path(app).expanduser().resolve()
    if app.is_file():app=app.parent
    if (app/'Contents').is_dir():
        executable=app/'Contents/MacOS/DeepSeek Harness'
        entry=app/'Contents/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js'
    else:
        executable=app/'DeepSeek Harness.exe'
        entry=app/'resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js'
    if not executable.is_file():raise ValueError('The specified official Harness executable does not exist')
    return [str(executable),str(entry)],app


def verify(args):
    command,app=host_command(args.harness_app,node=args.node,cli=args.cli)
    report_dir=args.report_dir.expanduser().resolve();report_dir.mkdir(parents=True,exist_ok=True)
    suite={'schema':'love-house-real-harness-qa/v1','product_version':__version__,
           'system':platform.system(),'architecture':platform.machine(),'python':platform.python_version(),
           'real_host_cli':True,'synthetic_model_only':True,'real_credentials_accessed':False,
           'cases':[],'ok':False,'complete':False}
    helper_path=ROOT/'extensions/deepseek-harness/configure.py'
    spec=importlib.util.spec_from_file_location('isolated_harness_configure',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    opener=build_opener(ProxyHandler({}));model_calls=[]
    answer='Synthetic Harness reply: the green lantern is safely remembered.'
    class SyntheticModel(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"data":[{"id":"deepseek-flash","object":"model"}]}')
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            model_calls.append({'path':self.path,'stream':bool(body.get('stream')),
                                'roles':[m.get('role') for m in body.get('messages',[])]})
            message={'id':'synthetic-local-message','type':'message','role':'assistant','model':'deepseek-flash',
                     'content':[{'type':'text','text':answer}],'stop_reason':'end_turn','stop_sequence':None,
                     'usage':{'input_tokens':10,'output_tokens':15}}
            self.send_response(200)
            if not body.get('stream'):
                self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(message).encode());return
            self.send_header('Content-Type','text/event-stream');self.end_headers()
            events=[('message_start',{'type':'message_start','message':{**message,'content':[],'stop_reason':None,'usage':{'input_tokens':10,'output_tokens':0}}}),
                    ('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}}),
                    ('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':answer}}),
                    ('content_block_stop',{'type':'content_block_stop','index':0}),
                    ('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':15}}),
                    ('message_stop',{'type':'message_stop'})]
            for event,data in events:
                self.wfile.write(('event: '+event+'\ndata: '+json.dumps(data)+'\n\n').encode());self.wfile.flush()
    model=ThreadingHTTPServer(('127.0.0.1',0),SyntheticModel)
    model_thread=threading.Thread(target=model.serve_forever,kwargs={'poll_interval':.05},daemon=True);model_thread.start()
    def request(port,path,data):
        req=Request('http://127.0.0.1:'+str(port)+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
        with opener.open(req,timeout=30) as response:return json.load(response)
    def run_cli(options,environment,work,name):
        with (report_dir/(name+'.stdout.txt')).open('w',encoding='utf-8') as stdout,(report_dir/(name+'.stderr.txt')).open('w',encoding='utf-8') as stderr:
            return subprocess.run([*command,*options],cwd=work,env=environment,stdout=stdout,stderr=stderr,
                                  timeout=args.timeout,check=False).returncode
    try:
        with tempfile.TemporaryDirectory(prefix='love-house-real-harness-qa-') as directory:
            temporary=Path(directory)
            detected=helper.detect(str(app),str(temporary/'not-created-profile'))
            suite['detected']=detected
            if not detected.get('supported'):raise AssertionError('Installed host contract is not supported')
            version=detected['version'];suite['host_version']=version
            for mode in ('harness','agent'):
                case={'connection_host':mode,'host_version':version,'ok':False};suite['cases'].append(case)
                work=temporary/mode;work.mkdir();dsh_home=work/'dsh';profile=dsh_home/'profiles/headless'
                environment=dict(os.environ)
                for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','DEEPSEEK_API_KEY','DEEPSEEK_AUTH_TOKEN',
                            'OPENAI_BASE_URL','ANTHROPIC_BASE_URL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY'):
                    environment.pop(key,None)
                environment.update(DSH_HOME=str(dsh_home),DSH_TELEMETRY_DISABLED='1',
                    DEEPSEEK_API_KEY='FAKE-offline-synthetic-model',DEEPSEEK_BASE_URL='http://127.0.0.1:'+str(model.server_port)+'/anthropic',
                    ELECTRON_RUN_AS_NODE='1',NO_PROXY='127.0.0.1,localhost',PYTHONDONTWRITEBYTECODE='1')
                case['profile_init_exit']=run_cli(['--profile','headless','--dump-config'],environment,work,mode+'-profile')
                if case['profile_init_exit']!=0:raise AssertionError('Official CLI did not create its isolated profile')
                host=MemoryHost(work/'memory',key_store=KeyStore(allow_source_build=False,allow_keychain=False),
                    adapter_options={'profile_dir':str(profile),'app_path':str(app)})
                host.updates.settings({'auto_check':False})
                server=ThreadingHTTPServer(('127.0.0.1',0),make_controller(host));host.controller_port=server.server_port
                thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.05},daemon=True);thread.start()
                runtime=host.root/'.runtime';runtime.mkdir(exist_ok=True)
                (runtime/'fixture.json').write_text(json.dumps({'pid':os.getpid(),'controller_port':server.server_port,'service_version':'0.4.0'}))
                try:
                    created=host.new_connection({'host':mode,'name':'Synthetic real-host QA','library_id':'default','session_scope':'next_session'})
                    cid=created['connection']['id'];case['connection_id']=cid
                    applied=request(server.server_port,'/api/connections/'+cid+'/configure',{'apply':True,'app_path':str(app)})
                    case['plugin_applied']=applied.get('applied') is True
                    if not case['plugin_applied']:raise AssertionError('Product did not install its actual host plugin')
                    user='Synthetic '+platform.system()+' Harness '+version+' asks to remember the green lantern.'
                    before_calls=len(model_calls)
                    case['official_turn_exit']=run_cli(['--profile','headless','--json',user],environment,work,mode+'-turn')
                    deadline=time.monotonic()+20
                    while True:
                        state=host.connections.get(cid);snapshot=host.snapshot('default')
                        if state['archive_status']=='automatic_connected' or time.monotonic()>=deadline:break
                        time.sleep(.1)
                    text=json.dumps(snapshot,ensure_ascii=False)
                    case.update(archive_status=state['archive_status'],original_user_saved=user in text,
                                original_assistant_saved=answer in text,nodes=len(snapshot['nodes']),
                                bound_session=state['session_scope'],model_requests=len(model_calls)-before_calls)
                    foreign='Foreign session must not enter the memory: '+user
                    case['foreign_turn_exit']=run_cli(['--profile','headless','--json',foreign],environment,work,mode+'-foreign')
                    after=host.snapshot('default');foreign_text=json.dumps(after,ensure_ascii=False)
                    case['foreign_window_excluded']=len(after['nodes'])==case['nodes'] and foreign not in foreign_text
                    case['ok']=bool(case['official_turn_exit']==0 and case['foreign_turn_exit']==0
                                    and case['archive_status']=='automatic_connected' and case['original_user_saved']
                                    and case['original_assistant_saved'] and case['model_requests']>0 and case['foreign_window_excluded'])
                    if not case['ok']:raise AssertionError('Actual host turn or fixed-window capture verification failed')
                finally:
                    server.shutdown();server.server_close();thread.join(timeout=5);host.stop()
            suite['ok']=len(suite['cases'])==2 and all(case['ok'] for case in suite['cases'])
    except Exception as error:
        suite['error']={'type':type(error).__name__,'message':str(error)}
        (report_dir/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        model.shutdown();model.server_close();model_thread.join(timeout=5)
        suite.update(complete=True,model_requests=model_calls)
        (report_dir/'result.json').write_text(json.dumps(suite,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return suite


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness-app',type=Path)
    parser.add_argument('--node',type=Path)
    parser.add_argument('--cli',type=Path)
    parser.add_argument('--report-dir',required=True,type=Path)
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args(argv)
    if args.timeout<1:parser.error('--timeout must be positive')
    try:result=verify(args)
    except (OSError,ValueError) as error:parser.error(str(error))
    print(json.dumps({'ok':result['ok'],'complete':result['complete'],'host_version':result.get('host_version'),
                      'cases':[{'host':case['connection_host'],'ok':case['ok']} for case in result['cases']]},ensure_ascii=False))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
