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


class WindowsPackagingTests(unittest.TestCase):
    def test_gui_and_console_are_distinct_bundles_with_only_safe_assets(self):
        command=builder.freeze_command('LoveHouse',ROOT/'desktop/windows_app.py',Path('out'),Path('build'),Path('icon.ico'),console=False)
        self.assertIn('--windowed',command);self.assertNotIn('--console',command)
        self.assertIn('webview.platforms.winforms',command)
        bridge=builder.freeze_command('LoveHouseBridge',ROOT/'desktop/agent_memory_bridge.py',Path('out'),Path('build'),Path('icon.ico'),console=True)
        self.assertIn('--console',bridge);self.assertNotIn('--windowed',bridge)
        for source,destination in builder.data_files():
            self.assertTrue(source.exists(),source)
            self.assertNotIn('data/',str(source.relative_to(ROOT)))
            self.assertNotIn('reports',str(source.relative_to(ROOT)))
            self.assertNotIn('node_modules',str(source.relative_to(ROOT)))

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
            window.create_file_dialog.return_value=(str(target),)
            api=windows.NativeAPI('http://127.0.0.1:8768/');api._window=window
            fake=SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1))
            with patch.dict(sys.modules,{'webview':fake}):
                self.assertTrue(api.save_memory_file('分享.json','完整用户原话：不喜欢咖啡。\n实际助手回复。')['saved'])
                self.assertFalse(api.save_memory_file('../escape.json','x')['saved'])
                self.assertFalse(api.save_memory_file('C:\\escape.json','x')['saved'])
            self.assertEqual(target.read_text('utf-8'),'完整用户原话：不喜欢咖啡。\n实际助手回复。')
            self.assertEqual(window.create_file_dialog.call_count,1)
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_cancel_and_foreign_origin_do_not_write_or_open_save_dialog(self):
        api=windows.NativeAPI('http://127.0.0.1:8768/');api._window=MagicMock()
        api._window.get_current_url.return_value='https://example.com/'
        self.assertFalse(api.save_memory_file('copy.json','x')['saved'])
        api._window.create_file_dialog.assert_not_called()
        api._window.get_current_url.return_value='http://127.0.0.1:8768/'
        api._window.create_file_dialog.return_value=None
        with patch.dict(sys.modules,{'webview':SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1))}):
            result=api.save_memory_file('copy.json','x')
        self.assertFalse(result['saved']);self.assertTrue(result['cancelled'])

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


if __name__=='__main__':unittest.main()
