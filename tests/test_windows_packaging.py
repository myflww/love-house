"""Portable Windows build contracts. Native WebView2/exe tests run in release CI."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


windows=load('love_house_windows_shell','desktop/windows_app.py')
builder=load('love_house_windows_builder','scripts/build_windows.py')
runtime_fetcher=load('love_house_runtime_fetcher','scripts/fetch_windows_runtime.py')


class WindowsPackagingTests(unittest.TestCase):
    def test_gui_and_console_are_distinct_bundles_with_only_safe_assets(self):
        command=builder.freeze_command('LoveHouse',ROOT/'desktop/windows_app.py',Path('out'),Path('build'),Path('icon.ico'),console=False)
        self.assertIn('--windowed',command);self.assertNotIn('--console',command)
        self.assertIn('webview.platforms.winforms',command)
        self.assertIn('plistlib',command);self.assertIn('zipfile',command)
        bridge=builder.freeze_command('LoveHouseBridge',ROOT/'desktop/agent_memory_bridge.py',Path('out'),Path('build'),Path('icon.ico'),console=True)
        self.assertIn('--console',bridge);self.assertNotIn('--windowed',bridge)
        for source,destination in builder.data_files():
            self.assertTrue(source.exists(),source)
            self.assertNotIn('data/',str(source.relative_to(ROOT)))
            self.assertNotIn('reports',str(source.relative_to(ROOT)))
            self.assertNotIn('node_modules',str(source.relative_to(ROOT)))

    def test_latest_source_downloads_are_explicit_and_include_the_sdk_integrity_input(self):
        files=builder.data_files()
        plugin={(source.name,destination) for source,destination in files if 'astrbot-love-house' in source.parts}
        allowed={'__init__.py','main.py','bridge.py','source_client.py','metadata.yaml',
                 '_conf_schema.json','README.md','LICENSE','package.py'}
        self.assertEqual(plugin,{(name,'extensions/astrbot-love-house') for name in allowed})
        self.assertIn((ROOT/'nkb/service/source_client.py','nkb/service'),files)

    def test_native_testing_disables_background_update_network_and_publishes_instance_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=windows.ControllerRuntime(Path(directory)/'data',testing=True).start()
            try:
                self.assertFalse(runtime.host.updates.status()['settings']['auto_check'])
                ready=json.loads(runtime.ready.read_text('utf-8'))
                self.assertEqual(ready['controller_instance_id'],runtime.host.instance_id)
                self.assertEqual(runtime.host.retention_view('default')['mode'],'adaptive')
                self.assertIsNone(runtime.host.snapshot('default')['config']['max_nodes'])
            finally:runtime.stop()

    def test_smoke_accepts_background_delivery_only_after_exact_bound_roles_exist(self):
        host=MagicMock()
        correct={'text':'actual user','meta':{'source':'conversation_turn','assistant_reply':'actual assistant'}}
        host.snapshot.side_effect=[{'nodes':{}},{'nodes':{'saved':correct}}]
        with patch.object(windows.time,'sleep'):
            windows.require_smoke_turn_saved(host,'fixed-library','actual user','actual assistant')
        self.assertEqual(host.snapshot.call_args_list,[unittest.mock.call('fixed-library'),unittest.mock.call('fixed-library')])
        for node in ({**correct,'text':'different user'},
                     {'text':'actual user','meta':{'source':'conversation_turn','assistant_reply':'wrong assistant'}},
                     {'text':'actual user','meta':{'source':'harness_recorded','assistant_reply':'actual assistant'}}):
            host.snapshot.side_effect=None;host.snapshot.return_value={'nodes':{'unproven':node}}
            with patch.object(windows.time,'monotonic',side_effect=[0,11]),self.assertRaises(AssertionError):
                windows.require_smoke_turn_saved(host,'fixed-library','actual user','actual assistant')

    def test_frozen_windows_config_uses_console_exes_and_no_pythonhome_or_token(self):
        from nkb.service.agent_client import make_agent_config
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/'LoveHouse.exe'
            with patch('nkb.service.agent_client.sys.platform','win32'),patch('nkb.service.agent_client.sys.frozen',True,create=True),patch('nkb.service.agent_client.sys.executable',str(executable)):
                result=make_agent_config(Path(directory)/'FAKE-data',{'id':'conn_fake','library_id':'default','token':'FAKE-LOCAL-CONNECTION-TOKEN','enabled':True,'revoked':False},persist=True)
            command=next(iter(result['mcp_config']['mcpServers'].values()))
            self.assertEqual(Path(command['command']),Path(directory).resolve()/'bridge/LoveHouseBridge.exe')
            self.assertEqual(command['args'],['--connection-config',result['private_path']])
            self.assertEqual(Path(result['hook_config']['command']),Path(directory).resolve()/'hook/LoveHouseHook.exe')
            public=json.dumps([result['mcp_config'],result['hook_config']])
            self.assertNotIn('FAKE-LOCAL-CONNECTION-TOKEN',public)
            self.assertNotIn('PYTHONHOME',public);self.assertNotIn('-u',command['args'])

    def test_data_location_is_per_user_and_distinct_from_install_directory(self):
        with patch.dict(os.environ,{'LOCALAPPDATA':str(ROOT/'FAKE-localappdata')}):
            self.assertEqual(windows.default_data_dir(),ROOT/'FAKE-localappdata/LoveHouse')
        installer=(ROOT/'desktop/windows-installer.iss').read_text('utf-8')
        self.assertIn('PrivilegesRequired=lowest',installer)
        self.assertIn('DefaultDirName={localappdata}\\Programs\\LoveHouse',installer)
        self.assertNotIn('[UninstallDelete]',installer)
        self.assertNotIn('Webview2Setup.exe',installer)

    def test_native_save_preserves_unicode_content_and_never_accepts_direct_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'分享.json';window=MagicMock();window.get_current_url.return_value='http://127.0.0.1:8768/'
            api=windows.NativeAPI('http://127.0.0.1:8768/');api._window=window
            with patch.object(windows,'export_save_dialog',return_value=str(target)) as dialog:
                self.assertTrue(api.save_memory_file('分享.json','完整用户原话：不喜欢咖啡。\n实际助手回复。')['saved'])
                self.assertFalse(api.save_memory_file('../escape.json','x')['saved'])
                self.assertFalse(api.save_memory_file('C:\\escape.json','x')['saved'])
            dialog.assert_called_once_with(window,'分享.json')
            self.assertEqual(target.read_text('utf-8'),'完整用户原话：不喜欢咖啡。\n实际助手回复。')
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_cancel_and_foreign_origin_do_not_write_or_open_save_dialog(self):
        api=windows.NativeAPI('http://127.0.0.1:8768/');api._window=MagicMock()
        api._window.get_current_url.return_value='https://example.com/'
        with patch.object(windows,'export_save_dialog',return_value=None) as dialog:
            self.assertFalse(api.save_memory_file('copy.json','x')['saved'])
            dialog.assert_not_called()
            api._window.get_current_url.return_value='http://127.0.0.1:8768/'
            result=api.save_memory_file('copy.json','x')
        self.assertFalse(result['saved']);self.assertTrue(result['cancelled'])

    def test_save_dialog_and_disk_failures_are_errors_and_navigation_during_save_cannot_write(self):
        api=windows.NativeAPI('http://127.0.0.1:8768/');api._window=MagicMock()
        api._window.get_current_url.return_value=api._url
        with patch.object(windows,'export_save_dialog',side_effect=RuntimeError('PRIVATE PATH')):
            result=api.save_memory_file('copy.json','x')
        self.assertFalse(result['saved']);self.assertFalse(result['cancelled']);self.assertNotIn('PRIVATE PATH',result['error'])
        with patch.object(windows,'export_save_dialog',return_value='copy.json'),patch.object(windows,'atomic_export',side_effect=PermissionError('PRIVATE PATH')):
            result=api.save_memory_file('copy.json','x')
        self.assertFalse(result['saved']);self.assertFalse(result['cancelled'])
        api._window.get_current_url.side_effect=[api._url,'https://example.com/']
        with patch.object(windows,'export_save_dialog',return_value='copy.json'),patch.object(windows,'atomic_export') as write:
            self.assertFalse(api.save_memory_file('copy.json','x')['saved']);write.assert_not_called()

    def test_astrbot_native_export_accepts_no_remote_bytes_or_path_and_uses_host_package(self):
        host=MagicMock();host.astrbot_package.return_value=b'REVIEWED SYNTHETIC PLUGIN ZIP'
        api=windows.NativeAPI('http://127.0.0.1:8768/',host);api._window=MagicMock()
        api._window.get_current_url.return_value=api._url
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'插件.zip'
            with patch.object(windows,'export_save_dialog',return_value=str(target)) as dialog:
                self.assertTrue(api.export_astrbot_adapter()['saved'])
            self.assertEqual(target.read_bytes(),host.astrbot_package.return_value)
            dialog.assert_called_once_with(api._window,'LoveHouse-AstrBot-0.2.0-experimental.zip')
        with self.assertRaises(TypeError):api.export_astrbot_adapter('untrusted-path.zip')
        api._window.get_current_url.return_value='https://example.com/'
        host.astrbot_package.reset_mock();self.assertFalse(api.export_astrbot_adapter()['saved']);host.astrbot_package.assert_not_called()

    def test_reserved_windows_export_names_and_non_utf8_are_rejected(self):
        for filename in ['CON.json','lpt1.md','NUL.json','wrong.exe','end.md ','a|b.json','/tmp/x.json','..\\x.json']:
            with self.subTest(filename=filename),self.assertRaises(ValueError):windows.valid_export(filename,'content')
        with self.assertRaises(UnicodeError):windows.valid_export('safe.json','\ud800')

    def test_windows_liveness_uses_read_only_process_query_without_os_kill(self):
        from nkb.service.agent_client import AgentClient
        from ctypes import wintypes
        kernel=MagicMock();kernel.OpenProcess.return_value=1234
        def alive(handle,pointer):ctypes.cast(pointer,ctypes.POINTER(wintypes.DWORD)).contents.value=259;return True
        kernel.GetExitCodeProcess.side_effect=alive
        with patch('nkb.service.agent_client.sys.platform','win32'),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch('nkb.service.agent_client.os.kill') as kill:
            self.assertTrue(AgentClient._alive(123))
            self.assertFalse(AgentClient._alive(-1));kill.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(1234)
        kernel.OpenProcess.assert_called_once_with(0x1000,False,123)

    def test_controller_lock_preserves_running_ready_file_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=windows.ControllerRuntime(directory,testing=True).start()
            try:
                self.assertEqual(runtime.host.snapshot('default')['nodes'],{})
                self.assertEqual(len(runtime.host.manager.list_libraries()),2)
                ready=runtime.ready.read_bytes();other=windows.ControllerRuntime(directory,testing=True)
                with self.assertRaises(RuntimeError):other.start()
                self.assertEqual(runtime.ready.read_bytes(),ready)
                port=runtime.server.server_port
            finally:runtime.stop()
            self.assertFalse(runtime.ready.exists())
            restarted=windows.ControllerRuntime(directory,testing=True).start()
            try:self.assertEqual(restarted.server.server_port,port)
            finally:restarted.stop()

    def test_source_backend_smoke_runs_sharing_roundtrip_without_real_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'report.json';windows.backend_smoke(report)
            value=json.loads(report.read_text('utf-8'))
            self.assertTrue(value['ok']);self.assertEqual(value['sharing_roundtrip'],'passed')
            self.assertFalse(value['real_credentials_accessed']);self.assertEqual(value['real_model_calls'],0)

    def test_release_requires_native_and_installed_smoke_before_upload(self):
        workflow=(ROOT/'.github/workflows/release.yml').read_text('utf-8')
        self.assertIn('runs-on: windows-latest',workflow)
        self.assertIn('installed-native.json',workflow)
        self.assertIn('--diagnose',workflow)
        self.assertIn('installed-diagnostics.txt',workflow)
        self.assertIn('needs: windows',workflow)
        self.assertNotIn('continue-on-error: true',workflow)
        self.assertIn('native.json',(ROOT/'scripts/build_windows.py').read_text('utf-8'))
        self.assertIn("webview.start(gui='edgechromium'",(ROOT/'desktop/windows_app.py').read_text('utf-8'))
        with patch.object(builder.sys,'platform','darwin'),self.assertRaises(SystemExit):builder.build()

    def test_microsoft_sdk_notices_are_exact_and_unmatched_dlls_stop_release(self):
        import hashlib
        source=ROOT/'assets/licenses/webview2-sdk-1.0.3856.49'
        provenance=json.loads((source/'provenance.json').read_text('utf-8'))
        for notice in provenance['license_files']:
            self.assertEqual(hashlib.sha256((source/notice['file']).read_bytes()).hexdigest(),notice['sha256'])
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'Microsoft.Web.WebView2.Core.dll').write_bytes(b'FAKE-unverified-dll')
            with self.assertRaisesRegex(RuntimeError,'changed'):builder.verify_webview2_sdk(directory)

    def smoke_directory(self):
        directory=Path(tempfile.mkdtemp(prefix=windows.SMOKE_PREFIX)).resolve()
        (directory/'.love-house-smoke-owner.json').write_text(json.dumps({
            'schema':'love-house-native-smoke/v1','pid':os.getpid(),'directory':directory.name}))
        (directory/'WebView2').mkdir()
        return directory

    def test_only_owned_webview2_sharing_violation_can_defer_cleanup(self):
        import shutil
        directory=self.smoke_directory()
        exc=PermissionError(13,'FAKE sharing violation',str(directory/'WebView2/locked.pma'));exc.winerror=32
        try:
            with patch.object(windows.shutil,'rmtree',side_effect=exc) as remove,patch.object(windows.time,'sleep'):
                result=windows.cleanup_smoke_profile(directory,attempts=3)
            self.assertEqual(result['status'],'deferred_profile_lock');self.assertEqual(result['winerror'],32)
            self.assertEqual(remove.call_count,3);self.assertTrue(result['isolated'])
        finally:shutil.rmtree(directory)

    def test_permission_errors_and_nonprofile_paths_are_not_downgraded_to_success(self):
        import shutil
        for filename,code in [('outside-profile.txt',32),('WebView2/denied.txt',5)]:
            directory=self.smoke_directory();exc=PermissionError(13,'FAKE error',str(directory/filename));exc.winerror=code
            try:
                with patch.object(windows.shutil,'rmtree',side_effect=exc),self.assertRaises(PermissionError):
                    windows.cleanup_smoke_profile(directory,attempts=1)
            finally:shutil.rmtree(directory)
        with tempfile.TemporaryDirectory(prefix='unrelated-') as other:
            with self.assertRaises(ValueError):windows.cleanup_smoke_profile(other)
            self.assertTrue(Path(other).is_dir())

    def test_webview2_concurrently_deleted_cache_tmp_is_ignored_only_after_it_vanishes(self):
        import shutil
        directory=self.smoke_directory();original=shutil.rmtree
        missing=directory/'WebView2'/'Sdch Dictionaries-fake-fixture.tmp'
        def concurrent_remove(path,**kwargs):
            exc=FileNotFoundError(2,'Already removed by WebView2',missing.name)
            if 'onexc' in kwargs:kwargs['onexc'](os.unlink,str(missing),exc)
            else:kwargs['onerror'](os.unlink,str(missing),(type(exc),exc,None))
            return original(path)
        try:
            with patch.object(windows.shutil,'rmtree',side_effect=concurrent_remove):
                result=windows.cleanup_smoke_profile(directory)
            self.assertEqual(result['status'],'removed')
            self.assertEqual(result['vanished_profile_entries'],1)
            self.assertFalse(directory.exists())
        finally:
            if directory.exists():original(directory)

    def test_cleanup_callback_does_not_hide_missing_nonprofile_or_existing_profile_entries(self):
        import shutil
        original=shutil.rmtree
        for relative,exists in [('controller-state.json',False),('WebView2/still-present.tmp',True)]:
            directory=self.smoke_directory();entry=directory/relative
            if exists:entry.write_text('FAKE cache still present')
            def failed_remove(path,**kwargs):
                exc=FileNotFoundError(2,'FAKE ENOENT',entry.name)
                if 'onexc' in kwargs:kwargs['onexc'](os.unlink,str(entry),exc)
                else:kwargs['onerror'](os.unlink,str(entry),(type(exc),exc,None))
            try:
                with patch.object(windows.shutil,'rmtree',side_effect=failed_remove),self.assertRaises(FileNotFoundError):
                    windows.cleanup_smoke_profile(directory)
                self.assertTrue(directory.exists())
                if exists:self.assertTrue(entry.exists())
            finally:original(directory)

    def test_python311_cleanup_uses_same_narrow_filter_through_onerror_adapter(self):
        import shutil
        directory=self.smoke_directory();original=shutil.rmtree
        missing=directory/'WebView2/vanished.tmp'
        def concurrent_remove(path,**kwargs):
            self.assertIn('onerror',kwargs);self.assertNotIn('onexc',kwargs)
            exc=FileNotFoundError(2,'FAKE vanished cache',missing.name)
            kwargs['onerror'](os.unlink,str(missing),(type(exc),exc,None))
            return original(path)
        try:
            with patch.object(windows.sys,'version_info',(3,11)),patch.object(windows.shutil,'rmtree',side_effect=concurrent_remove):
                result=windows.cleanup_smoke_profile(directory)
            self.assertEqual(result['status'],'removed');self.assertEqual(result['vanished_profile_entries'],1)
        finally:
            if directory.exists():original(directory)

    def test_native_success_is_finalized_after_shutdown_and_explicit_cleanup(self):
        def verified(directory,**kwargs):kwargs['result'].update(ok=True,controller_stopped=True,renderer='edgechromium')
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'native.json'
            with patch.object(windows,'run_window',side_effect=verified):value=windows.native_smoke(report)
            self.assertTrue(value['ok']);self.assertTrue(value['process_complete'])
            self.assertEqual(value['phase'],'complete');self.assertEqual(value['cleanup']['status'],'removed')
            self.assertEqual(json.loads(report.read_text('utf-8')),value)

    def test_native_failure_writes_safe_error_metadata_and_is_not_masked_by_cleanup(self):
        def broken(directory,**kwargs):raise PermissionError(13,'FAKE message contains FAKE-PRIVATE-KEY',str(Path(directory)/'unknown'))
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'native.json'
            with patch.object(windows,'run_window',side_effect=broken),self.assertRaises(PermissionError):windows.native_smoke(report)
            value=json.loads(report.read_text('utf-8'));self.assertFalse(value['ok']);self.assertFalse(value['process_complete'])
            self.assertEqual(value['failure']['type'],'PermissionError')
            self.assertNotIn('FAKE-PRIVATE-KEY',report.read_text('utf-8'))
            self.assertEqual(value['cleanup']['status'],'removed')

    def test_nonzero_exit_is_rejected_even_with_success_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'native.json'
            def process(*args,**kwargs):
                report.write_text(json.dumps({'ok':True,'process_complete':True,'phase':'complete'}))
                return SimpleNamespace(returncode=1)
            with patch.object(builder.subprocess,'run',side_effect=process),self.assertRaisesRegex(RuntimeError,'exit code 1'):
                builder.require_report(['FAKE-LoveHouse.exe'],report)

    def test_zero_exit_still_requires_process_finalization_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            report=Path(directory)/'native.json'
            def process(*args,**kwargs):
                report.write_text(json.dumps({'ok':True,'process_complete':False,'phase':'profile_cleanup'}))
                return SimpleNamespace(returncode=0)
            with patch.object(builder.subprocess,'run',side_effect=process),self.assertRaises(RuntimeError):
                builder.require_report(['FAKE-LoveHouse.exe'],report)


    def test_webview2_detection_reads_every_documented_channel(self):
        diagnostics=load('love_house_windows_diagnostics','desktop/windows_diagnostics.py')
        channel='{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
        user_path='Software\\Microsoft\\EdgeUpdate\\Clients\\'+channel
        machine_path='Software\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\'+channel
        class Key:
            def __init__(self,values):self.values=values
            def __enter__(self):return self
            def __exit__(self,*arguments):return False
        class Registry:
            HKEY_CURRENT_USER='HKCU';HKEY_LOCAL_MACHINE='HKLM'
            def __init__(self,values):self.values=values
            def OpenKey(self,hive,key):
                if (hive,key) in self.values:return Key(self.values[(hive,key)])
                raise OSError(2,'FAKE missing key')
            def QueryValueEx(self,key,name):
                if name in key.values:return key.values[name],1
                raise OSError(2,'FAKE missing value')
        registry=Registry({('HKCU',user_path):{'pv':'120.0.2210.144'},
                           ('HKLM',machine_path):{'pv':'7.0.0.0'}})
        self.assertEqual(diagnostics.registry_channels(registry),
                         [{'channel':'runtime','hive':'HKCU','version':'120.0.2210.144'}])
        self.assertEqual(diagnostics.registry_channels(Registry({})),[])

    def test_webview2_status_accepts_standard_files_and_never_guesses(self):
        diagnostics=load('love_house_windows_diagnostics','desktop/windows_diagnostics.py')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);executable=root/'Microsoft/EdgeWebView/Application/120.0.2210.144/msedgewebview2.exe'
            executable.parent.mkdir(parents=True);executable.write_bytes(b'FAKE loader')
            found=diagnostics.webview2_status({'LOCALAPPDATA':str(root)},registry=lambda:[])
            self.assertTrue(found['available']);self.assertEqual(found['version'],'120.0.2210.144')
            self.assertEqual(found['file_hits'],1)
            missing=diagnostics.webview2_status({'LOCALAPPDATA':str(root/'empty')},registry=lambda:[])
            self.assertFalse(missing['available']);self.assertIsNone(missing['version'])

    def test_bundled_fixed_runtime_is_offered_to_pywebview(self):
        diagnostics=load('love_house_windows_diagnostics','desktop/windows_diagnostics.py')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);exe=root/'LoveHouse.exe';exe.write_bytes(b'FAKE')
            folder=root/'WebView2Runtime';folder.mkdir();(folder/'msedgewebview2.exe').write_bytes(b'FAKE')
            with patch.object(diagnostics.sys,'executable',str(exe)):
                self.assertEqual(diagnostics.runtime_folder(),folder.resolve())
                status=diagnostics.webview2_status({'LOCALAPPDATA':str(root/'empty')},registry=lambda:[])
                self.assertTrue(status['available']);self.assertTrue(status['custom_folder'])

    def test_startup_log_records_failure_type_without_exception_text(self):
        diagnostics=load('love_house_windows_diagnostics','desktop/windows_diagnostics.py')
        with tempfile.TemporaryDirectory() as directory:
            log=diagnostics.StartupLog(Path(directory)/'logs/startup.log',max_bytes=500)
            for _ in range(30):log.write('failure',type='PermissionError',note='x'*80)
            self.assertTrue((Path(directory)/'logs/startup.1.log').is_file())
            text=(Path(directory)/'logs/startup.log').read_text('utf-8')
            self.assertLess(len(text),1400);self.assertIn('"event": "failure"',text)
            try:raise PermissionError(13,'FAKE-PRIVATE-KEY',str(Path(directory)/'secret.txt'))
            except PermissionError as exc:record=diagnostics.failure_record(exc)
            self.assertEqual(record['type'],'PermissionError');self.assertNotIn('FAKE-PRIVATE-KEY',json.dumps(record))
            self.assertEqual(diagnostics.classify(WindowsErrorStub()),'unexpected')

    def test_main_offers_official_page_when_webview2_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            asked=[];opened=[]
            controller=MagicMock();controller.start.return_value=controller
            with patch.object(windows.sys,'platform','win32'),\
                 patch.object(windows,'ControllerRuntime',return_value=controller),\
                 patch.object(windows,'dotnet_status',return_value={'ok':True,'available':True}),\
                 patch.object(windows,'runtime_status',return_value={'available':False,'code':'runtime_missing'}),\
                 patch.object(windows,'bundled_installer_status',return_value={'available':False,'verified':False}),\
                 patch.object(windows,'ask_yes_no',side_effect=lambda message:asked.append(message) or True),\
                 patch.object(windows,'open_target',side_effect=opened.append),\
                 patch.object(sys,'argv',['LoveHouse.exe','--data-dir',directory]):
                self.assertEqual(windows.main(),1)
            log=(Path(directory)/'logs/startup.log').read_text('utf-8')
            self.assertIn('webview2_unavailable',log)
            self.assertIn('WebView2',asked[0])
            self.assertEqual(opened,[windows.WEBVIEW2_URL])
            self.assertNotIn('已经在运行',asked[0])
            controller.start.assert_called_once();controller.stop.assert_called_once()

    def test_main_reports_running_instance_separately_from_missing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            messages=[]
            with patch.object(windows.sys,'platform','win32'),\
                 patch.object(windows,'run_window',side_effect=windows.AlreadyRunning('FAKE lock busy')),\
                 patch.object(windows,'notify',side_effect=lambda message,**keywords:messages.append(message)),\
                 patch.object(sys,'argv',['LoveHouse.exe','--data-dir',directory]):
                self.assertEqual(windows.main(),1)
            self.assertIn('已经在运行',messages[0]);self.assertNotIn('WebView2',messages[0])
            self.assertIn('already_running',(Path(directory)/'logs/startup.log').read_text('utf-8'))

    def test_main_logs_only_failure_type_and_opens_log_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            opened=[]
            def explode(*arguments,**keywords):raise ValueError('FAKE-PRIVATE-KEY')
            with patch.object(windows.sys,'platform','win32'),\
                 patch.object(windows,'run_window',side_effect=explode),\
                 patch.object(windows,'ask_yes_no',return_value=True),\
                 patch.object(windows,'open_target',side_effect=opened.append),\
                 patch.object(sys,'argv',['LoveHouse.exe','--data-dir',directory]):
                self.assertEqual(windows.main(),1)
            log=(Path(directory)/'logs/startup.log').read_text('utf-8')
            self.assertIn('"type": "ValueError"',log);self.assertNotIn('FAKE-PRIVATE-KEY',log)
            self.assertEqual(opened,[(Path(directory)/'logs')])

    def test_diagnose_writes_runtime_facts_and_opens_their_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            opened=[]
            with patch.object(windows,'open_target',side_effect=opened.append),\
                 patch.object(sys,'argv',['LoveHouse.exe','--diagnose','--data-dir',directory]):
                self.assertEqual(windows.main(),0)
            reports=list((Path(directory)/'logs').glob('diagnostics-*.txt'))
            self.assertEqual(len(reports),1)
            text=reports[0].read_text('utf-8')
            self.assertIn('WebView2',text);self.assertIn('本文件不含记忆',text)
            self.assertNotIn(str(Path.home()),text)
            self.assertEqual(opened,[reports[0].parent])

    def test_installer_repairs_only_after_explicit_confirmation_and_checks_again(self):
        installer=(ROOT/'desktop/windows-installer.iss').read_text('utf-8')
        self.assertIn('RuntimeCommand',installer);self.assertIn('CurStepChanged',installer)
        self.assertNotIn('RegKeyExists',installer)
        self.assertIn('MB_YESNO',installer)
        self.assertEqual(installer.count("RuntimeCommand('--runtime-status')"),2)
        self.assertIn("RuntimeCommand('--repair-runtime')",installer)
        self.assertIn('RaiseException',installer)

    def test_gui_bundles_offline_runtime_without_tripling_console_adapter_size(self):
        common=['Fake',ROOT/'desktop/windows_app.py',Path('out'),Path('build'),Path('icon.ico')]
        gui=builder.freeze_command(*common,console=False)
        console=builder.freeze_command(*common,console=True)
        runtime_asset=str(ROOT/'resources/runtime')+os.pathsep+'resources/runtime'
        self.assertIn(runtime_asset,gui);self.assertNotIn(runtime_asset,console)

    def test_runtime_fetch_refuses_wrong_hash_before_signature_or_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'download.exe';candidate.write_bytes(b'FAKE incorrect installer')
            verify=MagicMock(return_value={'verified':True})
            with patch.object(runtime_fetcher.sys,'platform','win32'),\
                 patch.dict(sys.modules,{'windows_prerequisites':SimpleNamespace(bundled_installer_status=verify)}),\
                 self.assertRaisesRegex(RuntimeError,'SHA256'):
                runtime_fetcher.ensure_runtime(root,installer_path=candidate)
            verify.assert_not_called()
            self.assertFalse((root/'resources/runtime'/runtime_fetcher.FILENAME).exists())

    def test_runtime_fetch_refuses_invalid_signature_after_matching_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);candidate=root/'download.exe';candidate.write_bytes(b'FAKE installer')
            verify=MagicMock(return_value={'verified':False,'code':'signature_invalid'})
            with patch.object(runtime_fetcher.sys,'platform','win32'),\
                 patch.object(runtime_fetcher,'sha256',return_value=runtime_fetcher.SHA256),\
                 patch.dict(sys.modules,{'windows_prerequisites':SimpleNamespace(bundled_installer_status=verify)}),\
                 self.assertRaisesRegex(RuntimeError,'signature_invalid'):
                runtime_fetcher.ensure_runtime(root,installer_path=candidate)
            verify.assert_called_once()
            self.assertFalse((root/'resources/runtime'/runtime_fetcher.FILENAME).exists())

    def test_cached_runtime_is_reverified_and_rejected_without_redownload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cached=root/'resources/runtime'/runtime_fetcher.FILENAME
            cached.parent.mkdir(parents=True);cached.write_bytes(b'FAKE tampered cache')
            verify=MagicMock(return_value={'verified':False,'code':'hash_mismatch'})
            with patch.object(runtime_fetcher.sys,'platform','win32'),\
                 patch.dict(sys.modules,{'windows_prerequisites':SimpleNamespace(bundled_installer_status=verify)}),\
                 patch.object(runtime_fetcher.urllib.request,'urlopen') as download,\
                 self.assertRaisesRegex(RuntimeError,'hash_mismatch'):
                runtime_fetcher.ensure_runtime(root)
            download.assert_not_called()
            self.assertEqual(cached.read_bytes(),b'FAKE tampered cache')

    def test_release_preserves_historical_assets_and_requires_consumer_evidence(self):
        workflow=(ROOT/'.github/workflows/release.yml').read_text('utf-8')
        self.assertNotIn('--clobber',workflow)
        self.assertIn('inputs.consumer_validation_evidence',workflow)
        self.assertIn('system_runtime_preinstalled',workflow)
        self.assertIn('--consumer-smoke',workflow)

    def test_native_shell_separates_startup_log_from_memory_data(self):
        with tempfile.TemporaryDirectory() as directory:
            log=windows.StartupLog(windows.startup_log_path(directory))
            log.write('start',version='FAKE')
            self.assertTrue(Path(directory,'logs/startup.log').is_file())
            self.assertFalse(Path(directory,'brain.json').exists())


class WindowsErrorStub(Exception):
    """Stand-in for a non-diagnostic exception in classification tests."""


if __name__=='__main__':unittest.main()
