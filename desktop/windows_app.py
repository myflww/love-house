"""Native Windows/WebView2 shell. It never opens an external browser as its UI."""
from __future__ import annotations
import argparse
import errno
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from nkb._version import __version__
from nkb.core.atlas import atlas_brain
from nkb.service.host import MemoryHost,make_controller
from nkb.service.credentials import KeyStore
from nkb.storage.jsonfile import JsonFileStorage
from windows_diagnostics import (WEBVIEW2_URL,AlreadyRunning,StartupLog,WebView2Unavailable,
                                 DotNetUnavailable,NativeStartupTimeout,
                                 diagnostic_report,failure_record,runtime_folder,startup_facts,
                                 startup_log_path,system_facts,webview2_status)
from windows_prerequisites import runtime_status,dotnet_status,repair_runtime,bundled_installer_status

SMOKE_PREFIX='love-house-webview2-smoke-'
ALREADY_RUNNING_MESSAGE=('爱之屋已经在运行。\n\n请切回已经打开的窗口。如果看不到窗口，'
                         '请在任务管理器里结束 LoveHouse.exe 后再打开。\n\n启动日志：\n{log}')
WEBVIEW2_MESSAGE=('爱之屋需要微软 WebView2 运行时才能显示界面，这台电脑上还没有找到。\n\n'
                  '安装 Microsoft Edge WebView2 Runtime 后重新打开爱之屋即可，记忆数据不受影响。\n\n'
                  '是否现在打开微软官方下载页？\n'+WEBVIEW2_URL)
FAILURE_MESSAGE=('爱之屋未能打开。\n\n错误类型：{kind}\n启动日志：\n{log}\n\n'
                 '现有记忆数据已保留。是否打开日志所在文件夹？')
smoke_failure=failure_record


def sanitize_native_environment():
    """Keep launcher/other Python apps from selecting a foreign CLR or browser.

    Never log values: they can contain paths, credentials or debug endpoints.
    Only this child process is changed; the user's system environment is intact.
    """
    removed=[]
    for name in list(os.environ):
        upper=name.upper()
        if upper in ('PYTHONHOME','PYTHONPATH','PYWEBVIEW_GUI') or upper.startswith(('PYTHONNET_','WEBVIEW2_')):
            removed.append(name);os.environ.pop(name,None)
    return sorted(removed)


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
            beneath_profile=bool(filename and Path(filename).resolve().is_relative_to(profile))
            known_lock=getattr(exc,'winerror',None) in (32,33) and beneath_profile
            # Chromium may create a cache file between rmtree's scan and
            # rmdir. Retry this race only inside the owned WebView2 scratch.
            profile_write_race=getattr(exc,'winerror',None)==145 and beneath_profile
            if not (known_lock or profile_write_race):raise
            if attempt==attempts:
                if not known_lock:raise
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
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES,errno.EAGAIN) or getattr(exc,'winerror',None) in (32,33,36):
                raise AlreadyRunning('爱之屋已经打开，请切回原来的窗口。') from None
            raise
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
            if self.testing:self.host.updates.settings({'auto_check':False})
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
            state={'pid':os.getpid(),'controller_instance_id':self.host.instance_id,'controller_port':self.server.server_port,'port':self.server.server_port,
                   'personal_port':self.server.server_port,'service_version':'0.4.0','name':'爱之屋记忆服务'}
            JsonFileStorage(self.ready).save(state)
            JsonFileStorage(self.root/'controller-state.json').save({'controller_port':self.server.server_port,'service_version':'0.4.0'})
            return self
        except BaseException:self.stop();raise
    def stop(self):
        # A failed second instance owns nothing. In particular, its finally
        # block must never remove the first writer's ready file.
        if self.lock.file is None:return
        try:
            if self.server:
                # BaseServer.shutdown waits forever if serve_forever never ran.
                if self.thread and self.thread.is_alive():self.server.shutdown()
                self.server.server_close();self.server=None
            if self.thread:
                if self.thread.ident is not None:self.thread.join(timeout=5)
                self.thread=None
            if self.host:self.host.stop();self.host=None
        finally:
            try:self.ready.unlink(missing_ok=True)
            finally:self.lock.release()


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
    def platform_info(self):return {'platform':'windows','native':True,'renderer':'WebView2','version':__version__,'harness_supported':True}
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


def notify(message,title='爱之屋',flags=0x10):
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,title,flags)
    elif sys.stderr:print(message,file=sys.stderr)


def ask_yes_no(message,title='爱之屋'):
    """只有用户明确点"是"才继续；非 Windows 环境一律不猜。"""
    if sys.platform=='win32':
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None,message,title,0x04|0x40)==6
    if sys.stderr:print(message,file=sys.stderr)
    return False


def open_target(target):
    """打开官方下载页或日志目录；失败只记录，不改变退出码。"""
    try:
        if sys.platform=='win32':os.startfile(str(target));return True
        if sys.platform=='darwin':
            import subprocess
            subprocess.run(['open',str(target)],check=False);return True
        return False
    except OSError:return False


def write_diagnostics(data_dir,log):
    """把只含运行时事实的诊断文本写到数据目录，供用户直接转发。"""
    facts=startup_facts(data_dir)
    facts['log']=str(log.path)
    report=diagnostic_report(facts,log.tail())
    name=time.strftime('diagnostics-%Y%m%d-%H%M%S')+'.txt'
    for folder in (Path(data_dir)/'logs',Path(tempfile.gettempdir())/'LoveHouse'):
        try:
            folder.mkdir(parents=True,exist_ok=True)
            target=folder/name;target.write_text(report,encoding='utf-8');return target
        except OSError:continue
    raise OSError('diagnostics could not be written')


def backend_smoke(report):
    """No GUI/model/real credentials: verify controller, original sharing and restart."""
    import subprocess
    from nkb.service.agent_client import AgentClient
    with tempfile.TemporaryDirectory(prefix='love-house-windows-smoke-') as directory:
        root=Path(directory);runtime=ControllerRuntime(root/'data',testing=True).start()
        try:
            cfg=runtime.host.new_connection({'host':'agent','name':'FAKE Windows Agent','library_id':'default'})
            from nkb.service.host import local_json
            latest={'retention':local_json(runtime.server.server_port,'/api/retention'),
                    'rules':local_json(runtime.server.server_port,'/api/organizer/rules'),
                    'sources':local_json(runtime.server.server_port,'/api/agent/sources'),
                    'experiences':local_json(runtime.server.server_port,'/api/experiences'),
                    'updates':local_json(runtime.server.server_port,'/api/updates'),
                    'handoff':local_json(runtime.server.server_port,'/api/memory/handoff',{'profile':'S'})}
            assert latest['retention']['mode']=='adaptive'
            assert runtime.host.snapshot('default')['config']['max_nodes'] is None
            assert latest['rules']['read_only'] and latest['rules']['guidance']
            assert latest['sources']['agent_id']=='default' and latest['experiences']['read_only']
            assert latest['updates']['current_version']==__version__ and not latest['updates']['settings']['auto_check']
            assert latest['handoff']['read_only']
            plugin=runtime.host.astrbot_package()
            assert plugin.startswith(b'PK'), 'Reviewed AstrBot source package missing'
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
                'sharing_roundtrip':'passed','restart':'passed','latest_feature_apis':'passed','astrbot_source_package':'passed','real_model_calls':0,'real_credentials_accessed':False}
    result.update(phase='complete',process_complete=True,cleanup={'status':'removed','isolated':True})
    smoke_report(report,result)
    return result


def run_window(data_dir,*,smoke=False,report=None,result=None,log=None,visible=False):
    # Arbitrate the writer before testing the renderer. A second instance must
    # consistently report already_running even when its environment is broken.
    runtime=ControllerRuntime(data_dir,testing=smoke).start()
    if result is None:result={}
    result.update(ok=False,version=__version__,renderer='edgechromium',phase='window_start',process_complete=False)
    finished=threading.Event()
    try:
        dotnet=dotnet_status()
        if log:log.write('prerequisites',phase='dotnet_check',dotnet=dotnet)
        if dotnet.get('ok') is False:raise DotNetUnavailable()
        facts=runtime_status()
        if log:log.write('webview2',phase='runtime_check',**facts)
        if not facts['available']:
            if facts.get('code') in ('loader_missing','loader_load_failed'):
                raise ImportError('Packaged WebView2Loader is unavailable')
            raise WebView2Unavailable(facts)
        result['runtime']=facts
        result['system_runtime_preinstalled']=True
        result['phase']='clr_initialization'
        import webview
        if log:log.write('window',phase='window_start',smoke=smoke)
        api=NativeAPI(runtime.url)
        window=webview.create_window('爱之屋',runtime.url,js_api=api,width=1360,height=900,min_size=(900,600),
                                    background_color='#fffaf0',text_select=True,hidden=smoke and not visible)
        api._window=window
        def loaded():
            finished.set()
            if not smoke:result.update(ok=True,phase='window_ready')
            if log:log.write('window',phase='window_ready',renderer=result.get('renderer'))
        window.events.loaded+=loaded
        window.events.closed+=lambda:finished.set()
        def require_edge(renderer):
            result['renderer']=renderer
            if renderer!='edgechromium':
                result['error']='Microsoft WebView2 Runtime is required; legacy MSHTML is not supported.'
                return False
            return True
        window.events.initialized+=require_edge
        webview.settings['ALLOW_DOWNLOADS']=False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=True
        def watchdog():
            # pywebview logs (rather than raises) some async initialization
            # errors. Bound that wait, close the blank window, and let main
            # produce a safe diagnostic instead of hanging indefinitely.
            if not finished.wait(60):
                result.update(ok=False,startup_timeout=True,phase='webview2_initialization_timeout')
                if log:log.write('failure',phase='webview2_initialization_timeout')
                window.destroy()
        if smoke:
            def verify():
                try:
                    ready=threading.Event();box={}
                    def received(value):box['value']=value;ready.set()
                    window.evaluate_js("(async()=>{const h=await(await fetch('/api/health')).json();const l=await(await fetch('/api/libraries')).json();const gl=document.createElement('canvas').getContext('webgl2');return {health:h,library_count:l.libraries.length,title:document.title,save_bridge:typeof window.pywebview.api.save_memory_file==='function',graph:!!document.querySelector('canvas'),webgl:!!gl,latest_controls:['memoryRetentionDialog','organizerRulesBtn','dialogueImportDialog','windowHandoffBtn','checkForUpdates','agentSourcesDialog','experienceTimelineDialog'].every(id=>!!document.getElementById(id))};})()",received)
                    assert ready.wait(45),'WebView2 JS response timed out'
                    value=box['value'];assert value['health']['ok'] and value['health']['version']==__version__
                    assert value['save_bridge'] and value['graph'] and value['webgl'] and value['latest_controls'],value
                    result.update(ok=True,webview=value,phase='native_checks_passed')
                except Exception as exc:result.update(failure=smoke_failure(exc),phase='native_checks_failed')
                finally:window.destroy()
            window.events.loaded+=verify
        guard=threading.Thread(target=watchdog,daemon=True);guard.start()
        result['phase']='webview2_initialization'
        webview.start(gui='edgechromium',debug=False,private_mode=False,storage_path=str(Path(data_dir)/'WebView2'))
        finished.set();guard.join(timeout=1)
        if result.get('startup_timeout'):raise NativeStartupTimeout()
        if log:log.write('window',phase='window_closed',renderer=result.get('renderer'))
        if result.get('error') and not result['ok']:
            raise WebView2Unavailable({'available':False,'renderer':result.get('renderer'),'checked':webview2_status()})
    finally:
        finished.set()
        result['window_phase']=result.get('phase')
        result['phase']='controller_shutdown'
        try:runtime.stop();result['controller_stopped']=True
        except Exception as exc:
            result.update(ok=False,failure=smoke_failure(exc),phase='controller_shutdown_failed');raise
        finally:smoke_report(report,result)
    if smoke and not result['ok']:raise RuntimeError('Windows WebView2 smoke failed; see report')
    return result


def native_smoke(report,log=None,*,visible=False):
    """Own the native test scratch explicitly; report only after final cleanup."""
    directory=Path(tempfile.mkdtemp(prefix=SMOKE_PREFIX+'中文 路径-')).resolve()
    (directory/'.love-house-smoke-owner.json').write_text(json.dumps({
        'schema':'love-house-native-smoke/v1','pid':os.getpid(),'directory':directory.name}),encoding='utf-8')
    result={'ok':False,'version':__version__,'phase':'native_start','process_complete':False}
    if log:log.write('smoke',phase='native_start',isolated=True)
    scratch_log=StartupLog(Path(directory)/'startup.log')
    primary=None
    try:
        run_window(directory,smoke=True,result=result,log=scratch_log,visible=visible)
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
    parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--consumer-smoke',action='store_true')
    parser.add_argument('--runtime-status',action='store_true');parser.add_argument('--repair-runtime',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    smoke=args.backend_smoke or args.smoke_test or args.consumer_smoke
    if smoke and not args.report:parser.error('smoke tests require --report')
    if sum(bool(x) for x in (args.backend_smoke,args.smoke_test,args.consumer_smoke,args.diagnose,args.runtime_status,args.repair_runtime))>1:
        parser.error('select only one diagnostic or test action')
    native=not (smoke or args.diagnose or args.runtime_status or args.repair_runtime)
    if native and sys.platform!='win32':parser.error('Windows native shell requires Windows 10/11 x64')
    removed=sanitize_native_environment()
    data_dir=args.data_dir or default_data_dir()
    log=StartupLog(startup_log_path(data_dir))
    log.write('start',version=__version__,native=native,**system_facts())
    if removed:log.write('environment_sanitized',variables=removed)
    try:
        if args.backend_smoke:backend_smoke(args.report)
        elif args.smoke_test or args.consumer_smoke:native_smoke(args.report,log=log,visible=args.consumer_smoke)
        elif args.runtime_status or args.repair_runtime:
            if args.repair_runtime:value=repair_runtime(force=True)
            else:
                facts=runtime_status();net=dotnet_status()
                value={'ok':facts['available'] and net.get('ok') is not False,'runtime':facts,'dotnet':net}
            value.update(process_complete=True,version=__version__)
            smoke_report(args.report,value)
            if sys.stdout:print(json.dumps(value,ensure_ascii=False))
            return 0 if value.get('ok') else 1
        elif args.diagnose:
            target=write_diagnostics(data_dir,log);log.write('diagnostics',file=target.name)
            open_target(target.parent);return 0
        else:
            run_window(data_dir,log=log)
        return 0
    except AlreadyRunning:
        log.write('already_running')
        if native:notify(ALREADY_RUNNING_MESSAGE.format(log=log.path),flags=0x40)
        smoke_report(args.report,{'ok':False,'code':'already_running','process_complete':False})
        return 1
    except WebView2Unavailable as exc:
        log.write('webview2_unavailable',renderer=exc.facts.get('renderer'),checked=exc.facts.get('checked'))
        if native:
            installer=bundled_installer_status()
            if installer.get('verified'):
                consent=('爱之屋需要微软 WebView2 运行时。安装包已附带经过微软数字签名验证的离线组件。\n\n'
                         '是否现在安装或修复？现有记忆数据不受影响。\n微软组件说明：\n'+WEBVIEW2_URL)
                if ask_yes_no(consent):
                    fixed=repair_runtime()
                    log.write('runtime_repair',**fixed)
                    if fixed.get('ok'):
                        try:run_window(data_dir,log=log);return 0
                        except Exception as retry:
                            record=failure_record(retry);log.write('failure',**record)
                    notify('运行时修复或启动未完成，请查看启动日志：\n'+str(log.path))
            elif ask_yes_no(WEBVIEW2_MESSAGE):open_target(WEBVIEW2_URL)
        smoke_report(args.report,{'ok':False,'code':'webview2_unavailable','process_complete':False})
        return 1
    except Exception as exc:
        record=failure_record(exc);log.write('failure',**record)
        if smoke or args.runtime_status or args.repair_runtime:
            try:
                previous=json.loads(args.report.read_text('utf-8')) if args.report.exists() else {}
                previous.update(ok=False,process_complete=False,failure=record)
                if previous.get('phase') in (None,'complete'):previous['phase']='process_finalization_failed'
                smoke_report(args.report,previous)
            except Exception:pass  # The nonzero exit remains mandatory even if disk reporting fails.
        else:
            if ask_yes_no(FAILURE_MESSAGE.format(kind=record.get('kind',record['type']),log=log.path)):open_target(log.path.parent)
        return 1


if __name__=='__main__':raise SystemExit(main())
