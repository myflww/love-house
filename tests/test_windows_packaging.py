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


if __name__=='__main__':unittest.main()
