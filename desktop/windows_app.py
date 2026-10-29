"""Native Windows/WebView2 shell. It never opens an external browser as its UI."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
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
SMOKE_PREFIX='love-house-webview2-smoke-'


def smoke_failure(exc):
    """Safe exception diagnostics: code/location, never exception text or keys."""
    frames=traceback.extract_tb(exc.__traceback__)
    result={'type':type(exc).__name__,'errno':getattr(exc,'errno',None),'winerror':getattr(exc,'winerror',None)}
    if getattr(exc,'filename',None):result['file']=Path(exc.filename).name
    if frames:
        last=frames[-1];result['at']={'file':Path(last.filename).name,'function':last.name,'line':last.lineno}
    return result


def smoke_report(path,value):
    if path:
        target=Path(path);target.parent.mkdir(parents=True,exist_ok=True)
        atomic_export(target,json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))


def cleanup_smoke_profile(directory,attempts=8):
    """Remove only our isolated test scratch, with bounded WebView2-lock retry.

    A browser child may release its profile after the GUI loop returns. Only
    Windows sharing/lock violations whose exact failing path is beneath this
    scratch's WebView2 directory may be deferred. A vanished descendant in that
    same profile can be skipped when Chromium concurrently removes a cache tmp.
    ACL/disk/runtime errors fail.
    There is no call against real user data, nor a blanket ignore_errors flag.
    """
    root=Path(directory).resolve();marker=root/'.love-house-smoke-owner.json'
    if not root.name.startswith(SMOKE_PREFIX) or root.parent!=Path(tempfile.gettempdir()).resolve():
        raise ValueError('Refusing cleanup outside isolated native smoke scratch')
    owner=json.loads(marker.read_text('utf-8'))
    if owner!={'schema':'love-house-native-smoke/v1','pid':os.getpid(),'directory':root.name}:
        raise ValueError('Native smoke ownership marker does not match')
    profile=root/'WebView2'
    vanished=0
    def profile_race(function,path,exc):
        nonlocal vanished
        target=Path(path).resolve()
        # Use shutil's complete callback path, not OSError.filename (which can
        # be only a relative cache filename). Never generalise this to ENOENT
        # elsewhere in the test data or to an entry that still exists.
        if isinstance(exc,FileNotFoundError) and target.is_relative_to(profile) and not os.path.lexists(path):
            vanished+=1
            return
        raise exc
    def legacy_profile_race(function,path,exc_info):
        return profile_race(function,path,exc_info[1])
    for attempt in range(1,attempts+1):
        try:
            options={'onexc':profile_race} if sys.version_info>=(3,12) else {'onerror':legacy_profile_race}
            shutil.rmtree(root,**options)
            return {'status':'removed','attempts':attempt,'isolated':True,'vanished_profile_entries':vanished}
        except FileNotFoundError:
            if not root.exists():return {'status':'removed','attempts':attempt,'isolated':True,'vanished_profile_entries':vanished}
            raise
        except OSError as exc:
            filename=getattr(exc,'filename',None)
            known_lock=(getattr(exc,'winerror',None) in (32,33) and filename
                        and Path(filename).resolve().is_relative_to(profile))
            if not known_lock:raise
            if attempt==attempts:
                return {'status':'deferred_profile_lock','attempts':attempt,'isolated':True,
                        'directory':root.name,'winerror':exc.winerror,'file':Path(filename).name,
                        'vanished_profile_entries':vanished,
                        'retained_for':'OS release of the completed test WebView2 profile'}
            time.sleep(.15*attempt)


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
    result.update(phase='complete',process_complete=True,cleanup={'status':'removed','isolated':True})
    smoke_report(report,result)
    return result


def run_window(data_dir,*,smoke=False,report=None,result=None):
    import webview
    runtime=ControllerRuntime(data_dir,testing=smoke).start()
    if result is None:result={}
    result.update(ok=False,version=__version__,renderer='edgechromium',phase='window_start',process_complete=False)
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
                    result.update(ok=True,webview=value,phase='native_checks_passed')
                except Exception as exc:result.update(failure=smoke_failure(exc),phase='native_checks_failed')
                finally:window.destroy()
            window.events.loaded+=verify
        webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(Path(data_dir)/'WebView2'))
        if result.get('error') and not result['ok']:raise RuntimeError('WebView2 unavailable; no legacy renderer fallback')
    finally:
        result['window_phase']=result.get('phase')
        result['phase']='controller_shutdown'
        try:runtime.stop();result['controller_stopped']=True
        except Exception as exc:
            result.update(ok=False,failure=smoke_failure(exc),phase='controller_shutdown_failed');raise
        finally:smoke_report(report,result)
    if smoke and not result['ok']:raise RuntimeError('Windows WebView2 smoke failed; see report')
    return result


def native_smoke(report):
    """Own the native test scratch explicitly; report only after final cleanup."""
    directory=Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX)).resolve()
    (directory/'.love-house-smoke-owner.json').write_text(json.dumps({
        'schema':'love-house-native-smoke/v1','pid':os.getpid(),'directory':directory.name}),encoding='utf-8')
    result={'ok':False,'version':__version__,'phase':'native_start','process_complete':False}
    primary=None
    try:
        run_window(directory,smoke=True,result=result)
    except Exception as exc:
        primary=exc;result['ok']=False;result.setdefault('failure',smoke_failure(exc))
    finally:
        result['phase']='profile_cleanup'
        try:result['cleanup']=cleanup_smoke_profile(directory)
        except Exception as exc:
            result.update(ok=False,cleanup={'status':'failed','failure':smoke_failure(exc)},phase='profile_cleanup_failed')
            if primary is None:primary=exc
        if primary is None and result.get('ok') and result.get('controller_stopped'):
            result.update(phase='complete',process_complete=True)
        smoke_report(report,result)
    if primary is not None:raise primary
    if not result.get('process_complete'):raise RuntimeError('Native test did not complete')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--backend-smoke',action='store_true')
    parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if (args.backend_smoke or args.smoke_test) and not args.report:parser.error('smoke tests require --report')
    if not args.backend_smoke and sys.platform!='win32':parser.error('Windows native shell requires Windows 10/11 x64')
    try:
        if args.backend_smoke:backend_smoke(args.report)
        elif args.smoke_test:native_smoke(args.report)
        else:run_window(args.data_dir or default_data_dir())
        return 0
    except Exception as exc:
        if args.backend_smoke or args.smoke_test:
            try:
                previous=json.loads(args.report.read_text('utf-8')) if args.report.exists() else {}
                previous.update(ok=False,process_complete=False,failure=smoke_failure(exc))
                if previous.get('phase') in (None,'complete'):previous['phase']='process_finalization_failed'
                smoke_report(args.report,previous)
            except Exception:pass  # The nonzero exit remains mandatory even if disk reporting fails.
        if not (args.smoke_test or args.backend_smoke):notify('爱之屋未能打开。若另一窗口已经打开，请切回该窗口。\n本程序需要微软WebView2 Runtime，请从微软官方页面安装后重试：\n'+WEBVIEW2_URL+'\n现有记忆数据已保留。')
        return 1


if __name__=='__main__':raise SystemExit(main())
