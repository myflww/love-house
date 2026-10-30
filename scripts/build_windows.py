#!/usr/bin/env python3
"""Build Windows x64 native GUI, independent stdio adapters and per-user installer.

Must run on Windows x64 with the pinned desktop build dependencies installed.
Bundles a verified Microsoft Evergreen installer for offline prerequisite repair.
Publication is a separate, explicitly requested step after consumer validation.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def version():
    tree=ast.parse((ROOT/'nkb/_version.py').read_text('utf-8'))
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets))


def run(arguments,**kwargs):
    subprocess.run([str(value) for value in arguments],check=True,**kwargs)


def data_files():
    """Explicit safe assets; never include reports, fixtures, memories or node_modules."""
    files=[(ROOT/'nkb/viz/web','nkb/viz/web'),(ROOT/'nkb/service/harness','nkb/service/harness')]
    # The download endpoint builds a source-only AstrBot ZIP and compares the
    # vendored SDK byte-for-byte; frozen modules alone cannot supply those bytes.
    for name in ('__init__.py','main.py','bridge.py','source_client.py','metadata.yaml',
                 '_conf_schema.json','README.md','LICENSE','package.py'):
        files.append((ROOT/'extensions/astrbot-love-house'/name,'extensions/astrbot-love-house'))
    files.append((ROOT/'nkb/service/source_client.py','nkb/service'))
    for name in ('neural-art.bundle.js','LICENSE.digital-brain','LICENSE.three','LICENSE.orbit','LICENSE.postprocessing'):
        item=ROOT/'nkb/viz/art'/name
        if item.exists():files.append((item,'nkb/viz/art'))
    return files


def freeze_command(name,entry,dist,work,icon,*,console):
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--name',name,
          '--console' if console else '--windowed','--distpath',str(dist),'--workpath',str(work/name),
          '--specpath',str(work/'specs'),'--paths',str(ROOT),'--paths',str(ROOT/'desktop'),
          '--collect-submodules','nkb','--icon',str(icon)]
    # These standalone helpers are loaded from reviewed .py data with importlib.
    # PyInstaller cannot discover their otherwise-unused standard-library imports.
    args.extend(['--hidden-import','plistlib','--hidden-import','zipfile'])
    for source,destination in data_files():args.extend(['--add-data',str(source)+os.pathsep+destination])
    if not console:
        args.extend(['--collect-all','webview','--collect-all','pythonnet','--collect-all','clr_loader',
                     '--hidden-import','webview.platforms.winforms','--hidden-import','clr'])
        args.extend(['--add-data',str(ROOT/'resources/runtime')+os.pathsep+'resources/runtime'])
    args.append(str(entry));return args


def dependency_notices(target):
    """Ship wheel metadata licence files, including the CPython/PyInstaller notices."""
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    info=[]
    for dist in metadata.distributions():
        name=dist.metadata.get('Name','unknown');included=[]
        # Build environment contains only this project's dependencies. Preserve
        # all distributable licence notices; no credentials/config are read.
        for file in dist.files or ():
            text=str(file).replace('\\','/')
            if '.dist-info/' not in text or not any(word in file.name.lower() for word in ('license','licence','copying','notice')):continue
            path=Path(dist.locate_file(file))
            if path.is_file():
                destination=target/name/path.name
                destination.parent.mkdir(parents=True,exist_ok=True)
                if destination.exists() and destination.read_bytes()!=path.read_bytes():
                    destination=destination.with_name(hashlib.sha256(text.encode()).hexdigest()[:8]+'-'+path.name)
                shutil.copy2(path,destination);included.append(str(destination.relative_to(target)))
        info.append({'name':name,'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''), 'files':included})
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,target/'CPython-LICENSE.txt')
    (target/'dependency-licenses.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')


def require_report(command,report):
    report=Path(report);report.unlink(missing_ok=True)
    result=subprocess.run([str(x) for x in command],timeout=150,check=False)
    if not report.is_file():raise RuntimeError('Windows smoke created no report (exit code '+str(result.returncode)+')')
    value=json.loads(report.read_text('utf-8'))
    diagnostic={k:value[k] for k in ('phase','process_complete','failure','cleanup') if k in value}
    if result.returncode or value.get('ok') is not True or value.get('process_complete') is not True:
        raise RuntimeError('Windows smoke failed (exit code '+str(result.returncode)+'): '+json.dumps(diagnostic,ensure_ascii=False))


def verify_webview2_sdk(app):
    """Match redistributed Microsoft SDK DLLs to the licence's exact NuGet build."""
    source=ROOT/'assets/licenses/webview2-sdk-1.0.3856.49'
    provenance=json.loads((source/'provenance.json').read_text('utf-8'))
    for notice in provenance['license_files']:
        if hashlib.sha256((source/notice['file']).read_bytes()).hexdigest()!=notice['sha256']:
            raise RuntimeError('WebView2 SDK licence/notice integrity check failed')
    expected={row['sha256'] for row in provenance['matched_redistributables']}
    required={row['sha256'] for row in provenance['matched_redistributables']
              if 'win-x64/' in row['pywebview_wheel_member'] or '/runtimes/' not in row['pywebview_wheel_member']}
    found=set()
    for path in Path(app).rglob('*.dll'):
        if path.name not in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll'):continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in expected:raise RuntimeError('Bundled WebView2 SDK changed; update its upstream licence provenance before shipping')
        found.add(digest)
    if not required<=found:raise RuntimeError('WebView2 Core/WinForms/x64 loader are missing from the native bundle')
    shutil.copytree(source,Path(app)/'THIRD-PARTY-LICENSES'/source.name,dirs_exist_ok=True)


def build(*,installer=True,iscc=None):
    if sys.platform!='win32' or platform.machine().lower() not in ('amd64','x86_64'):
        raise SystemExit('Build on Windows x64; cross-compiling on macOS is not supported.')
    from PIL import Image
    from fetch_windows_runtime import ensure_runtime
    # Fail before freezing if the pinned Microsoft installer cannot be verified.
    ensure_runtime(ROOT)
    output=ROOT/'dist/windows';output.mkdir(parents=True,exist_ok=True)
    work=ROOT/'build/windows';work.mkdir(parents=True,exist_ok=True)
    icon=work/'LoveHouse.ico'
    Image.open(ROOT/'assets/branding/love-house-icon.png').convert('RGBA').save(icon,format='ICO',sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    for name,entry,console in [('LoveHouseBridge','agent_memory_bridge.py',True),('LoveHouseHook','agent_memory_hook.py',True),('LoveHouse','windows_app.py',False)]:
        run(freeze_command(name,ROOT/'desktop'/entry,output,work,icon,console=console),cwd=ROOT)
    app=output/'LoveHouse'
    for name,destination in [('LoveHouseBridge','bridge'),('LoveHouseHook','hook')]:
        source=output/name;target=app/destination
        if target.exists():shutil.rmtree(target)
        shutil.move(str(source),str(target))
    shutil.copy2(icon,app/'LoveHouse.ico')
    for name in ('LICENSE','NOTICE','THIRD_PARTY_NOTICES.md'):
        if (ROOT/name).exists():shutil.copy2(ROOT/name,app/name)
    dependency_notices(app/'THIRD-PARTY-LICENSES')
    verify_webview2_sdk(app)
    for license in (ROOT/'nkb/viz/art').glob('LICENSE*'):shutil.copy2(license,app/'THIRD-PARTY-LICENSES'/license.name)
    shutil.copy2(ROOT/'assets/fonts/ark-pixel-OFL.txt',app/'THIRD-PARTY-LICENSES/ark-pixel-OFL.txt')
    (app/'WINDOWS-README.txt').write_text(
        'Love House / 爱之屋 '+version()+'\n\nWindows 10 (2004+) / Windows 11 x64.\n'
        'This is a native WebView2 desktop app. Python and Node are bundled/not required.\n'
        'Microsoft WebView2 Runtime is required. Setup checks its actual loader\n'
        'and offers to install the included, verified Microsoft Evergreen runtime\n'
        'when it is absent. An offline x64 installer is included in the bundle.\n'
        'The Microsoft component is governed by Microsoft licence terms:\n'
        'https://developer.microsoft.com/microsoft-edge/webview2/\n'
        'Portable users: explicitly run LoveHouse.exe --repair-runtime to repair\n'
        'it. No administrator access, Python or Node installation is required.\n'
        'The repair checks Microsoft Authenticode and the pinned SHA256, then\n'
        'checks runtime availability again after installation.\n\n'
        'If the window does not open, run LoveHouse.exe --diagnose (or the same\n'
        'command in the installed folder). It writes a runtime-only report to\n'
        '%LOCALAPPDATA%\\LoveHouse\\logs and opens the folder; the startup log\n'
        '(startup.log) never contains memories, keys or conversation text.\n\n'
        'Memories: %LOCALAPPDATA%\\LoveHouse. Uninstall keeps memories.\n'
        'Connect using Other Agent / Copy memory connection configuration (MCP).\n'
        'Windows DeepSeek Harness automatic configuration has not been verified/supported.\n'
        'Publicly downloadable; original project code is licensed for noncommercial use.\n'
        'Third-party components retain their own licences in THIRD-PARTY-LICENSES.\n',encoding='utf-8')
    reports=ROOT/'build/windows/reports';reports.mkdir(parents=True,exist_ok=True)
    # The windowed executable's exit code alone is insufficient; both commands
    # must create explicit success reports after executing the packaged runtime.
    require_report([app/'LoveHouse.exe','--backend-smoke','--report',reports/'backend.json'],reports/'backend.json')
    require_report([app/'LoveHouse.exe','--smoke-test','--report',reports/'native.json'],reports/'native.json')
    release=ROOT/'dist/release';release.mkdir(parents=True,exist_ok=True)
    archive=release/('LoveHouse-'+version()+'-Windows-x64')
    shutil.make_archive(str(archive),'zip',output,'LoveHouse')
    if installer:
        candidates=[iscc,shutil.which('ISCC')]
        for base in (os.environ.get('ProgramFiles(x86)'),os.environ.get('ProgramFiles'),os.environ.get('LOCALAPPDATA','')+'/Programs'):
            if base:candidates.append(Path(base)/'Inno Setup 6/ISCC.exe')
        compiler=next((Path(value) for value in candidates if value and Path(value).is_file()),None)
        if compiler is None:raise RuntimeError('Install official Inno Setup 6, or pass --iscc with its ISCC.exe path')
        run([compiler,'/DAppVersion='+version(),'/DBundleDir='+str(app),'/DOutputDirPath='+str(release),ROOT/'desktop/windows-installer.iss'])
    checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in release.glob('*Windows-x64*') if p.is_file()}
    (release/'Windows-SHA256SUMS.txt').write_text(''.join(value+'  '+name+'\n' for name,value in checksums.items()),encoding='utf-8')
    print(json.dumps({'version':version(),'bundle':str(app),'assets':checksums,'native_smoke':True,'backend_smoke':True,'installed':False},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--no-installer',action='store_true')
    parser.add_argument('--iscc',type=Path,help='Path to an official Inno Setup 6 compiler.')
    args=parser.parse_args();build(installer=not args.no_installer,iscc=args.iscc)
