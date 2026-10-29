"""Native Windows/WebView2 shell. It never opens an external browser as its UI."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from nkb._version import __version__
from nkb.core.atlas import atlas_brain
from nkb.service.host import MemoryHost,make_controller
from nkb.service.credentials import KeyStore
from nkb.storage.jsonfile import JsonFileStorage

WEBVIEW2_URL='https://developer.microsoft.com/microsoft-edge/webview2/'


def default_data_dir():
    value=os.environ.get('LOCALAPPDATA')
    return Path(value)/'LoveHouse' if value else Path.home()/'AppData/Local/LoveHouse'


class DesktopLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        stream=self.path.open('a+b');stream.seek(0,2)
        if stream.tell()==0:stream.write(b'\0');stream.flush()
        try:
            if sys.platform=='win32':
                import msvcrt
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            stream.close();raise RuntimeError('爱之屋已经打开，请切回原来的窗口。') from None
        self.file=stream
    def release(self):
        if self.file:
            try:
                if sys.platform=='win32':
                    import msvcrt
                    self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            finally:self.file.close();self.file=None


class ControllerRuntime:
    def __init__(self,data_dir,*,testing=False):
        self.root=Path(data_dir).resolve();self.testing=testing;self.host=None;self.server=None;self.thread=None
        self.lock=DesktopLock(self.root/'.desktop-writer.lock');self.ready=self.root/'.runtime/app.json'
    def start(self):
        self.lock.acquire()
        try:
            self.host=MemoryHost(self.root,key_store=KeyStore(allow_source_build=False,allow_keychain=not self.testing))
            example=self.root/'framework-example.brain.json'
            if not self.host.manager.demo_suppressed:
                if not example.exists():atlas_brain(example).save()
                self.host.manager.register_demo(example)
            previous=None
            try:previous=json.loads((self.root/'controller-state.json').read_text('utf-8')).get('controller_port')
            except (OSError,ValueError,AttributeError):pass
            candidates=([previous] if type(previous) is int and 1<=previous<=65535 else [])+([0] if self.testing else [8768,0])
            for port in dict.fromkeys(candidates):
                try:self.server=ThreadingHTTPServer(('127.0.0.1',port),make_controller(self.host));break
                except OSError:
                    if port==0:raise
            self.server.daemon_threads=False;self.host.controller_port=self.server.server_port
            self.url='http://127.0.0.1:'+str(self.server.server_port)+'/'
            self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},daemon=True);self.thread.start()
            state={'pid':os.getpid(),'controller_port':self.server.server_port,'port':self.server.server_port,
                   'personal_port':self.server.server_port,'service_version':'0.4.0','name':'爱之屋记忆服务'}
            JsonFileStorage(self.ready).save(state)
            JsonFileStorage(self.root/'controller-state.json').save({'controller_port':self.server.server_port,'service_version':'0.4.0'})
            return self
        except BaseException:self.stop();raise
    def stop(self):
        if self.server:
            self.server.shutdown();self.server.server_close();self.server=None
        if self.thread:self.thread.join(timeout=5);self.thread=None
        if self.host:self.host.stop();self.host=None
        self.ready.unlink(missing_ok=True);self.lock.release()


def valid_export(filename,content):
    if (not isinstance(filename,str) or not filename or len(filename)>180 or '/' in filename or '\\' in filename
            or re.search(r'[<>:"|?*\x00-\x1f]',filename) or filename in ('.','..')
            or Path(filename).suffix.lower() not in ('.json','.md')
            or filename.rstrip(' .')!=filename
            or filename.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}):
        raise ValueError('分享文件名不正确')
    if not isinstance(content,str):raise ValueError('分享文件内容不正确')
    data=content.encode('utf-8')
    if len(data)>64*1024*1024:raise ValueError('分享文件超过64MiB')
    return data


def atomic_export(path,data):
    target=Path(path);temporary=None
    try:
        descriptor,temporary=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.tmp',dir=target.parent)
        with os.fdopen(descriptor,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,target);temporary=None
    finally:
        if temporary:Path(temporary).unlink(missing_ok=True)


class NativeAPI:
    def __init__(self,url):self._url=url;self._window=None;self._saving=threading.Lock()
    def platform_info(self):return {'platform':'windows','native':True,'renderer':'WebView2','version':__version__,'harness_supported':False}
    def save_memory_file(self,filename,content):
        if not self._saving.acquire(False):return {'saved':False,'cancelled':False,'error':'另一个保存窗口尚未关闭。'}
        try:
            data=valid_export(filename,content)
            if not self._window or self._window.get_current_url()!=self._url:
                raise ValueError('只能从爱之屋本机页面保存分享文件')
            import webview
            selected=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=filename,
                         file_types=('Love House JSON (*.json)','Markdown (*.md)'))
            if not selected:return {'saved':False,'cancelled':True}
            target=selected if isinstance(selected,str) else selected[0]
            if Path(target).suffix.lower()!=Path(filename).suffix.lower():target+=Path(filename).suffix
            atomic_export(target,data)
            return {'saved':True,'cancelled':False}
        except (OSError,ValueError,UnicodeError):return {'saved':False,'cancelled':False,'error':'文件未保存，请检查位置、文件名和磁盘空间。'}
        finally:self._saving.release()


def notify(message):
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,'爱之屋',0x10)
    elif sys.stderr:print(message,file=sys.stderr)


def backend_smoke(report):
    """No GUI/model/real credentials: verify controller, original sharing and restart."""
    import subprocess
    from nkb.service.agent_client import AgentClient
    with tempfile.TemporaryDirectory(prefix='love-house-windows-smoke-') as directory:
        root=Path(directory);runtime=ControllerRuntime(root/'data',testing=True).start()
        try:
            cfg=runtime.host.new_connection({'host':'agent','name':'FAKE Windows Agent','library_id':'default'})
            client=AgentClient(cfg['private_path'])
            assert client.status()['connected']
            assert client.submit_hook({'session_id':'fake-window','turn_id':'one','user':'假数据：我不喜欢被曲解。','assistant':'这是完整的助手原话。','status':'complete'})['saved']
            boot=client.tool('memory_bootstrap',{});assert boot['total_memories']==1
            page=client.tool('memory_list',{});nid=page['entries'][0]['id']
            assert client.tool('memory_read',{'memory_id':nid})['text']=='假数据：我不喜欢被曲解。'
            from nkb.service.sharing import ShareStore
            sharing=ShareStore(runtime.host)
            preview=sharing.preview('default')
            exported=sharing.download('default',format='json',expected_revision=preview['content_revision'])
            bundle=json.loads(exported['content']);assert '假数据' in exported['content']
            restored=sharing.import_file(exported['content'],name='FAKE导入独立库')
            assert restored['library']['id']!='default'
            if getattr(sys,'frozen',False):
                command=next(iter(cfg['mcp_config']['mcpServers'].values()))
                messages='\n'.join(json.dumps(m) for m in [{'jsonrpc':'2.0','id':1,'method':'initialize'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'memory_bootstrap','arguments':{}}}])+'\n'
                response=subprocess.run([command['command'],*command['args']],input=messages,capture_output=True,text=True,encoding='utf-8',timeout=30)
                assert response.returncode==0,response.stderr
                rows=[json.loads(line) for line in response.stdout.splitlines()]
                assert {'memory_bootstrap','memory_list','memory_read'}<={t['name'] for t in rows[1]['result']['tools']}
                assert rows[2]['result']['structuredContent']['identity']['library_id']=='default'
                hook=cfg['hook_config'];fake={'session_id':'fake-window','turn_id':'two','user':'假数据：第二条实际原文','assistant':'第二条实际回复','status':'complete'}
                got=subprocess.run([hook['command'],*hook['args']],input=json.dumps(fake),capture_output=True,text=True,encoding='utf-8',timeout=30)
                assert got.returncode==0 and json.loads(got.stdout)['saved']
            expected=runtime.host.snapshot('default');port=runtime.server.server_port
        finally:runtime.stop()
        assert not runtime.ready.exists()
        runtime=ControllerRuntime(root/'data',testing=True).start()
        try:
            assert runtime.server.server_port==port and runtime.host.snapshot('default')==expected
        finally:runtime.stop()
        result={'ok':True,'version':__version__,'controller':'passed','stdio_and_hook':'passed' if getattr(sys,'frozen',False) else 'source-only',
                'sharing_roundtrip':'passed','restart':'passed','real_model_calls':0,'real_credentials_accessed':False}
        Path(report).write_text(json.dumps(result,indent=2),encoding='utf-8')


def run_window(data_dir,*,smoke=False,report=None):
    import webview
    runtime=ControllerRuntime(data_dir,testing=smoke).start()
    result={'ok':False,'version':__version__,'renderer':'edgechromium'}
    try:
        api=NativeAPI(runtime.url)
        window=webview.create_window('爱之屋',runtime.url,js_api=api,width=1360,height=900,min_size=(900,600),
                                    background_color='#fffaf0',text_select=True,hidden=smoke)
        api._window=window
        def require_edge(renderer):
            result['renderer']=renderer
            if renderer!='edgechromium':
                result['error']='Microsoft WebView2 Runtime is required; legacy MSHTML is not supported.'
                return False
            return True
        window.events.initialized+=require_edge
        webview.settings['ALLOW_DOWNLOADS']=False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=True
        if smoke:
            def verify():
                try:
                    ready=threading.Event();box={}
                    def received(value):box['value']=value;ready.set()
                    window.evaluate_js("(async()=>{const h=await(await fetch('/api/health')).json();const l=await(await fetch('/api/libraries')).json();const gl=document.createElement('canvas').getContext('webgl2');return {health:h,library_count:l.libraries.length,title:document.title,save_bridge:typeof window.pywebview.api.save_memory_file==='function',graph:!!document.querySelector('canvas'),webgl:!!gl};})()",received)
                    assert ready.wait(45),'WebView2 JS response timed out'
                    value=box['value'];assert value['health']['ok'] and value['health']['version']==__version__
                    assert value['save_bridge'] and value['graph'] and value['webgl'],value
                    result.update(ok=True,webview=value)
                except Exception as exc:result.update(error=type(exc).__name__+': '+str(exc)[:500])
                finally:window.destroy()
            window.events.loaded+=verify
        webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(Path(data_dir)/'WebView2'))
        if result.get('error') and not result['ok']:raise RuntimeError('WebView2 unavailable; no legacy renderer fallback')
    finally:
        runtime.stop()
        if report:Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if smoke and not result['ok']:raise RuntimeError('Windows WebView2 smoke failed; see report')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--backend-smoke',action='store_true')
    parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if args.backend_smoke:
        if not args.report:parser.error('--backend-smoke requires --report')
        backend_smoke(args.report);return 0
    if sys.platform!='win32':parser.error('Windows native shell requires Windows 10/11 x64')
    try:
        if args.smoke_test:
            if not args.report:parser.error('--smoke-test requires --report')
            with tempfile.TemporaryDirectory(prefix='love-house-webview2-smoke-') as directory:run_window(directory,smoke=True,report=args.report)
        else:run_window(args.data_dir or default_data_dir())
        return 0
    except Exception:
        if not args.smoke_test:notify('爱之屋未能打开。若另一窗口已经打开，请切回该窗口。\n本程序需要微软WebView2 Runtime，请从微软官方页面安装后重试：\n'+WEBVIEW2_URL+'\n现有记忆数据已保留。')
        return 1


if __name__=='__main__':raise SystemExit(main())
