"""Exercise an actual Windows installer upgrade using disposable synthetic data.

No existing application, user data directory or provider credential is used.
Only a newly generated library/provider scope is written to Windows Credential
Manager and that exact synthetic scope is deleted before reporting completion.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid

OLD_VERSION = '0.9.1rc1'
NEW_VERSION = '0.10.1rc1'
OLD_SETUP_SHA256 = '56634d8e63e806c5d988302ed01678d2881a40e4c12f836a08ae1b361bccdad6'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_PREFIX='love-house-upgrade-中文 空格-'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class App:
    def __init__(self, executable, data):
        self.executable, self.data = Path(executable), Path(data)
        self.process = None
        self.base = None
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))

    def start(self, version):
        self.data.mkdir(parents=True, exist_ok=True)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        environment = dict(os.environ)
        environment['LOCALAPPDATA'] = str(self.data.parent / 'isolated-local-appdata')
        environment['TEMP'] = environment['TMP'] = str(self.data.parent / 'isolated-temp')
        Path(environment['TEMP']).mkdir(exist_ok=True)
        log_cursor=startup_log_cursor(self.data)
        self.process = subprocess.Popen([str(self.executable), '--data-dir', str(self.data)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
        end = time.monotonic() + 65
        while time.monotonic() < end:
            require(self.process.poll() is None, 'Disposable app exited before its Controller was ready')
            try:
                ready = json.loads((self.data / '.runtime/app.json').read_text('utf-8'))
                if ready['pid'] != self.process.pid:
                    time.sleep(.1)
                    continue
                self.base = 'http://127.0.0.1:' + str(ready['controller_port'])
                health = self.request('/api/health')
                if health['ok'] is True and health['version'] == version and window_ready(self.data,log_cursor,version):
                    response = self.client.open(self.base + '/', timeout=15)
                    require(response.status == 200, 'Disposable UI session was not issued')
                    response.read()
                    response.close()
                    return self
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.1)
        raise AssertionError('Disposable app native-window startup timed out')

    def request(self, path, payload=None, *, library=None, bearer=None, anonymous=False, status=200):
        headers = {'Origin': self.base, 'Content-Type': 'application/json'}
        if library:
            headers['X-NKB-Library'] = library
        if bearer:
            headers['Authorization'] = 'Bearer ' + bearer
        encoded = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = Request(self.base + path, data=encoded, headers=headers)
        client = build_opener() if anonymous else self.client
        try:
            with client.open(request, timeout=20) as response:
                code, raw = response.status, response.read(4 * 1024 * 1024)
        except HTTPError as exc:
            code, raw = exc.code, exc.read(4 * 1024 * 1024)
        require(code == status, 'Disposable Controller expected HTTP '+str(status)+' but received '+str(code)+' for '+path)
        return json.loads(raw)

    def close(self, *, strict=True):
        if not self.process:
            return
        if self.process.poll() is not None:
            if strict:require(self.process.returncode==0,'Disposable app exited unsuccessfully')
            return
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        found = []
        @callback_type
        def close_window(window, unused):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            if pid.value == self.process.pid:
                found.append(window)
                user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE, our process only.
            return True
        end = time.monotonic() + 20
        while self.process.poll() is None and time.monotonic() < end:
            user32.EnumWindows(close_window, 0)
            try:
                self.process.wait(timeout=.25)
            except subprocess.TimeoutExpired:
                pass
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
            if strict:
                raise AssertionError('Disposable app did not shut down cleanly')
        elif strict:
            require(bool(found) and self.process.returncode == 0, 'Disposable app close was not successful')


def install(setup, destination):
    completed = subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
        '/DIR=' + str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=300, check=False, creationflags=subprocess.CREATE_NO_WINDOW)
    require(completed.returncode == 0, 'Disposable installer failed')
    require((destination / 'LoveHouse.exe').is_file(), 'Installed application is missing')


def graph_originals(value):
    return {node['id']: (node['text'], node.get('meta', {}).get('assistant_reply')) for node in value['nodes']}


def log_identity(path):
    try:
        stat=Path(path).stat()
        return {'identity':(stat.st_dev,stat.st_ino),'offset':stat.st_size}
    except OSError:return None


def startup_log_cursor(data):
    log=Path(data)/'logs/startup.log'
    return {'main':log_identity(log),'rotated':log_identity(log.with_name('startup.1.log'))}


def window_ready(data,cursor,version):
    """Read only this launch's new bytes, using the actual PID-free log schema.

    App.start independently checks runtime/app.json belongs to its new PID.
    If StartupLog rotates after our byte cursor, join the new tail of that
    same file (now startup.1.log) with the new current file in temporal order.
    Missing/truncated logs require a new start/version and a later ready event.
    """
    log=Path(data)/'logs/startup.log';rotated=log.with_name('startup.1.log')
    current=log_identity(log)
    if current is None:return False
    prior=cursor['main'];chunks=[]
    if prior and current['identity']==prior['identity'] and current['offset']>=prior['offset']:
        parts=[(log,prior['offset'])]
    else:
        previous=log_identity(rotated)
        if prior and previous and previous['identity']==prior['identity'] and previous['offset']>=prior['offset']:
            parts=[(rotated,prior['offset']),(log,0)]
        elif prior is None and previous and (cursor['rotated'] is None or previous['identity']!=cursor['rotated']['identity']):
            parts=[(rotated,0),(log,0)]
        else:parts=[(log,0)]
    try:
        for path,offset in parts:
            with path.open('rb') as stream:
                stream.seek(offset);chunks.append(stream.read())
    except OSError:return False
    active=False
    for line in b''.join(chunks).decode('utf-8',errors='replace').splitlines():
        try:item=json.loads(line)
        except ValueError:continue
        if item.get('event')=='start':active=item.get('version')==version
        if active and item.get('event')=='window' and item.get('phase')=='window_ready':return True
    return False


def queue_state(data):
    with closing(sqlite3.connect(data / 'organizer.sqlite3')) as db:
        return {name: db.execute('SELECT ' + fields + ' FROM ' + name + ' ORDER BY 1').fetchall()
            for name, fields in (('items', 'library_id,raw_id,status,progress,job_id'),
                ('jobs', 'id,library_id,raw_ids,status,attempts,error_code'), ('calls', 'id,library_id,at,chars'))}


def connection_token(connection,data):
    """The HTTP config intentionally contains a path rather than its token.

    Read only the just-created fixture's private file, after checking its exact
    owned data directory and the server-issued connection/library identities.
    """
    private=Path(connection['private_path']).resolve()
    require(private.is_relative_to(Path(data).resolve()),'Synthetic private configuration escaped the owned fixture')
    value=json.loads(private.read_text('utf-8'))
    require(value.get('connection_id')==connection['connection']['id'] and
        value.get('library_id')==connection['connection']['library_id'],
        'Synthetic private configuration belongs to another connection')
    token=value.get('token')
    require(isinstance(token,str) and bool(token),'Synthetic connection token is missing')
    return token


def cleanup_fixture(directory,attempts=12):
    """Retry only WebView2 descendant races in our explicitly owned scratch."""
    root=Path(directory).resolve()
    require(root.parent==Path(tempfile.gettempdir()).resolve() and root.name.startswith(FIXTURE_PREFIX),
        'Refusing upgrade cleanup outside the owned temporary scratch')
    marker=json.loads((root/'.upgrade-owner.json').read_text('utf-8'))
    require(marker=={'schema':'love-house-upgrade-owner/v1','pid':os.getpid(),'name':root.name},
        'Upgrade scratch owner marker does not match')
    profile=root/'合成 数据'/'WebView2'
    def vanished(function,path,exc):
        target=Path(path).resolve()
        if isinstance(exc,FileNotFoundError) and target.is_relative_to(profile) and not os.path.lexists(path):return
        raise exc
    def legacy_vanished(function,path,exc_info):return vanished(function,path,exc_info[1])
    for attempt in range(1,attempts+1):
        try:
            options={'onexc':vanished} if sys.version_info>=(3,12) else {'onerror':legacy_vanished}
            shutil.rmtree(root,**options)
            return
        except OSError as exc:
            name=getattr(exc,'filename',None)
            if (getattr(exc,'winerror',None) not in (32,33) or not name or
                not Path(name).resolve().is_relative_to(profile) or attempt==attempts):raise
            time.sleep(.2*attempt)


@contextmanager
def owned_fixture():
    root=Path(tempfile.mkdtemp(prefix=FIXTURE_PREFIX)).resolve()
    (root/'.upgrade-owner.json').write_text(json.dumps({'schema':'love-house-upgrade-owner/v1',
        'pid':os.getpid(),'name':root.name}),encoding='utf-8')
    primary=None
    try:yield root
    except BaseException as exc:
        primary=exc
        raise
    finally:
        try:cleanup_fixture(root)
        except Exception:
            if primary is None:raise
            primary.add_note('Owned upgrade scratch cleanup also failed; the initial test failure is preserved.')


def run(old_setup, new_setup):
    require(sys.platform == 'win32', 'This proof requires actual Windows applications')
    # Inno Setup updates its ordinary uninstall registration even with a custom
    # /DIR. Never run this installer proof on the owner's daily-use machine.
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('LOVE_HOUSE_DISPOSABLE_UPGRADE_RUNNER') == 'github-hosted',
        'Installer upgrade proof requires its disposable GitHub-hosted job')
    old_setup, new_setup = Path(old_setup).resolve(), Path(new_setup).resolve()
    require(digest(old_setup) == OLD_SETUP_SHA256, 'Old public setup bytes do not match the pinned release')
    new_sha = digest(new_setup)
    credential_ref = None
    old = new = restarted = None
    marker = uuid.uuid4().hex
    result = {'ok': False, 'process_complete': False, 'schema': 'love-house-windows-upgrade/v1',
        'from_version': OLD_VERSION, 'to_version': NEW_VERSION, 'old_setup_sha256': OLD_SETUP_SHA256,
        'new_setup_sha256': new_sha, 'real_model_calls': 0, 'real_credentials_accessed': False}
    with owned_fixture() as root:
        data, target = root / '合成 数据', root / '安装 App'
        try:
            install(old_setup, target)
            old = App(target / 'LoveHouse.exe', data)
            old.start(OLD_VERSION)
            library = old.request('/api/libraries', {'name': 'SYNTHETIC_UPGRADE_' + marker})['library']['id']
            second = old.request('/api/libraries', {'name': 'SYNTHETIC_SECOND_' + marker})['library']['id']
            trashed = old.request('/api/libraries', {'name': 'SYNTHETIC_TRASH_' + marker})['library']['id']
            old.request('/api/libraries/' + trashed + '/delete', {'confirm': True})
            old.request('/api/library/select', {'library_id': library})
            connection = old.request('/api/connections', {'host': 'agent', 'name': 'SYNTHETIC_UPGRADE_AGENT',
                'library_id': library, 'session_scope': 'next_session'})
            cid, token = connection['connection']['id'], connection_token(connection,data)
            original = 'SYNTHETIC_UPGRADE_USER_原文_' + marker
            assistant = 'SYNTHETIC_UPGRADE_ASSISTANT_回复_' + marker
            event = {'session_id': 'SYNTHETIC_WINDOW_' + marker, 'event_id': 'SYNTHETIC_EVENT_' + marker,
                'record': {'schema': 'love-house-agent-hook/v1'},
                'normalized': {'type': 'turn', 'status': 'complete', 'origin': 'agent_host_hook', 'turn_id': 'SYNTHETIC_TURN_' + marker,
                    'user': original, 'assistant': assistant}}
            saved = old.request('/api/connections/' + cid + '/events', event, bearer=token)
            require(saved['status'] == 'saved', 'Old application did not store the synthetic original turn')
            second_connection = old.request('/api/connections', {'host': 'agent',
                'name': 'SYNTHETIC_SECOND_AGENT', 'library_id': second, 'session_scope': 'next_session'})
            second_cid, second_token = second_connection['connection']['id'], connection_token(second_connection,data)
            second_event = {'session_id': 'SYNTHETIC_SECOND_WINDOW_' + marker, 'event_id': 'SYNTHETIC_SECOND_EVENT_' + marker,
                'record': {'schema': 'love-house-agent-hook/v1'},
                'normalized': {'type': 'turn', 'status': 'complete', 'origin': 'agent_host_hook', 'turn_id': 'SYNTHETIC_SECOND_TURN_' + marker,
                    'user': 'SYNTHETIC_SECOND_USER_' + marker, 'assistant': 'SYNTHETIC_SECOND_ASSISTANT_' + marker}}
            require(old.request('/api/connections/' + second_cid + '/events', second_event, bearer=second_token)['status'] == 'saved',
                'Old second-library original was not saved')
            old.request('/api/persona/import', {'text': 'SYNTHETIC_MANUAL_CORE_' + marker,
                'source': {'origin': 'synthetic_upgrade'}}, library=library)
            old.request('/api/persona/enabled', {'enabled': False, 'learning_enabled': False}, library=library)
            old.request('/api/persona/enabled', {'enabled': False, 'learning_enabled': False}, library=second)
            fake_base = 'https://synthetic-' + marker + '.invalid/v1'
            fake_key = 'FAKE-UPGRADE-ONLY-' + marker
            credential_ref = {'provider': 'organizer:' + hashlib.sha256((fake_base + '/chat/completions').encode()).hexdigest(),
                'library_id': library, 'connection_id': None}
            organizer = old.request('/api/organizer/settings', {'enabled': False, 'provider_mode': 'separate',
                'base_url': fake_base, 'model': 'FAKE-UPGRADE-MODEL', 'api_key': fake_key,
                'save_key': True}, library=library)
            require(organizer['provider']['key_saved'] is True and organizer['provider']['credential_ready'] is True,
                'Windows did not persist the synthetic credential in its secure storage')
            config = old.request('/api/connections/' + cid + '/config')
            private = Path(config['private_path']).resolve()
            require(private.is_relative_to(data.resolve()), 'Synthetic private configuration escaped the owned fixture')
            expected = {'nodes': graph_originals(old.request('/api/graph', library=library)),
                'persona': old.request('/api/persona', library=library),
                'settings': organizer['settings'], 'provider': organizer['provider'],
                'connection': config['connection'], 'private': digest(private),
                'trash': [v['id'] for v in old.request('/api/libraries/trash')['libraries']]}
            second_config = old.request('/api/connections/' + second_cid + '/config')
            second_private = Path(second_config['private_path']).resolve()
            require(second_private.is_relative_to(data.resolve()), 'Second private configuration escaped the owned fixture')
            expected['second'] = {'nodes': graph_originals(old.request('/api/graph', library=second)),
                'connection': second_config['connection'], 'private': digest(second_private),
                'provider': old.request('/api/organizer', library=second)['provider']}
            require(bool(expected['nodes']) and (original,assistant) in expected['nodes'].values(),
                'Old fixture is missing its exact original user and assistant roles')
            require(bool(expected['second']['nodes']) and
                (second_event['normalized']['user'],second_event['normalized']['assistant']) in expected['second']['nodes'].values(),
                'Old second-library fixture is missing its exact original roles')
            old.close()
            # Deliberately seeded durable old-schema fixtures exercise migration
            # preservation; these are not real model calls or model results.
            with closing(sqlite3.connect(data / 'organizer.sqlite3')) as db, db:
                require('purpose' not in {r[1] for r in db.execute('PRAGMA table_info(jobs)')},
                    'Old application fixture unexpectedly already has the new purpose column')
                job_ids=[]
                for index, identity in enumerate((library, second)):
                    item = db.execute('SELECT raw_id FROM items WHERE library_id=?', (identity,)).fetchone()
                    require(item is not None, 'Old capture was not enqueued durably')
                    job = 'SYNTHETIC_JOB_' + str(index) + marker
                    job_ids.append(job)
                    stamp = time.time()
                    db.execute('INSERT INTO jobs(id,library_id,raw_ids,status,attempts,next_run,lease_until,created,updated,error_code,error) VALUES(?,?,?,\'rejected\',3,0,0,?,?,\'synthetic_fixture\',\'synthetic fixture\')',
                        (job, identity, json.dumps([item[0]]), stamp, stamp))
                    db.execute('UPDATE items SET status=\'rejected\',job_id=? WHERE library_id=? AND raw_id=?', (job, identity, item[0]))
                    db.execute('INSERT INTO calls VALUES(?,?,?,?)', ('SYNTHETIC_CALL_' + str(index) + marker, identity, stamp, 123))
            durable = queue_state(data)
            install(new_setup, target)
            new = App(target / 'LoveHouse.exe', data)
            new.start(NEW_VERSION)
            require(new.request('/api/libraries')['selected_id'] == library, 'Selected library changed during upgrade')
            require(graph_originals(new.request('/api/graph', library=library)) == expected['nodes'], 'Original roles changed during upgrade')
            require(graph_originals(new.request('/api/graph', library=second)) == expected['second']['nodes'], 'Second-library original roles changed during upgrade')
            persona = new.request('/api/persona', library=library)
            require(persona['manual'] == expected['persona']['manual'] and persona['enabled'] is False and persona['learning_enabled'] is False,
                'Manual persona or explicit opt-out changed during upgrade')
            current = new.request('/api/organizer', library=library)
            require(current['settings'] == expected['settings'] and current['provider'] == expected['provider'], 'Organizer configuration or secure credential metadata changed')
            after = new.request('/api/connections/' + cid + '/config')
            for field in ('id', 'library_id', 'session_scope', 'session_scope_policy','bound_session_id', 'enabled', 'revoked', 'binding_revision'):
                require(field in after['connection'] and field in expected['connection'] and
                    after['connection'][field] == expected['connection'][field], 'Fixed connection scope changed')
            require(Path(after['private_path']).resolve() == private and digest(private) == expected['private'], 'Old private connection configuration changed')
            second_after = new.request('/api/connections/' + second_cid + '/config')
            for field in ('id', 'library_id', 'session_scope', 'session_scope_policy','bound_session_id', 'enabled', 'revoked', 'binding_revision'):
                require(field in second_after['connection'] and field in expected['second']['connection'] and
                    second_after['connection'][field] == expected['second']['connection'][field], 'Second fixed connection scope changed')
            require(Path(second_after['private_path']).resolve() == second_private and digest(second_private) == expected['second']['private'], 'Second private configuration changed')
            require(new.request('/api/organizer', library=second)['provider'] == expected['second']['provider'], 'Synthetic credential leaked to another library')
            second_persona = new.request('/api/persona', library=second)
            require(second_persona['enabled'] is False and second_persona['learning_enabled'] is False, 'Second explicit opt-out changed')
            require([v['id'] for v in new.request('/api/libraries/trash')['libraries']] == expected['trash'], 'Recycle bin changed')
            require(queue_state(data) == durable, 'Durable jobs, attempts or budget ledger changed during migration')
            with closing(sqlite3.connect(data / 'organizer.sqlite3')) as db:
                require('purpose' in {r[1] for r in db.execute('PRAGMA table_info(jobs)')}, 'Purpose column was not migrated')
                require(dict(db.execute('SELECT id,purpose FROM jobs')) == {identity:'memory' for identity in job_ids},
                    'Old jobs were not migrated to factual purpose')
            new.request('/api/connections', anonymous=True, status=401)
            new.request('/api/persona', library=library, bearer=token, anonymous=True, status=403)
            new.request('/api/connections/' + cid + '/context', {}, library=second, bearer=token, anonymous=True, status=403)
            other = new.request('/api/libraries', {'name': 'SYNTHETIC_SECOND_LIBRARY_' + marker})['library']['id']
            require(new.request('/api/graph', library=other)['nodes'] == [], 'Another library acquired old memories')
            new.request('/api/library/select', {'library_id': library})
            new.close()
            restarted = App(target / 'LoveHouse.exe', data)
            restarted.start(NEW_VERSION)
            require(restarted.request('/api/libraries')['selected_id'] == library, 'Upgrade restart lost selection')
            require(graph_originals(restarted.request('/api/graph', library=library)) == expected['nodes'], 'Upgrade restart lost originals')
            require(graph_originals(restarted.request('/api/graph', library=second)) == expected['second']['nodes'], 'Upgrade restart lost second-library originals')
            for identity,manual in ((library,expected['persona']['manual']),(second,'')):
                persona=restarted.request('/api/persona', library=identity)
                require(persona['enabled'] is False and persona['learning_enabled'] is False and persona['manual']==manual,
                    'Upgrade restart changed manual persona or explicit opt-out')
            for identity,prior,path,sha in ((cid,expected['connection'],private,expected['private']),
                    (second_cid,expected['second']['connection'],second_private,expected['second']['private'])):
                config=restarted.request('/api/connections/'+identity+'/config')
                for field in ('id','library_id','session_scope','session_scope_policy','bound_session_id','enabled','revoked','binding_revision'):
                    require(field in config['connection'] and field in prior and config['connection'][field]==prior[field],
                        'Upgrade restart changed a fixed connection scope')
                require(Path(config['private_path']).resolve()==path and digest(path)==sha,
                    'Upgrade restart changed a private connection file')
            require(restarted.request('/api/organizer', library=library)['provider'] == expected['provider'], 'Upgrade restart lost secure credential metadata')
            require(queue_state(data) == durable, 'Upgrade restart changed durable budget fixtures')
            restarted.close()
            result.update(same_install_path='passed', database_migration='passed', libraries='passed',
                connections='passed', credential_metadata='passed', explicit_opt_out='passed', restart='passed',
                source_library_contents='passed', old_private_connection_file='passed', recycle_bin='passed',
                management_isolation='passed', durable_attempts_and_budget='passed', synthetic_ledger_fixture=True)
        finally:
            primary=sys.exc_info()[1];cleanup_failures=[]
            for app in (restarted, new, old):
                if app:
                    try:app.close(strict=False)
                    except Exception as exc:cleanup_failures.append(exc)
            if credential_ref:
                from nkb.service.credentials import KeyStore
                try:
                    metadata = KeyStore(allow_source_build=False).delete(credential_ref)
                    require(metadata['credential_ready'] is False and metadata['key_saved'] is False,
                        'Synthetic secure credential cleanup failed')
                except Exception as exc:cleanup_failures.append(exc)
            if cleanup_failures:
                if primary is None:raise cleanup_failures[0]
                primary.add_note('Owned upgrade app or credential cleanup also failed; the initial test failure is preserved.')
    require(not root.exists(),'Owned upgrade scratch still exists after cleanup')
    result.update(ok=True, process_complete=True, phase='complete', cleanup={'status': 'removed', 'isolated': True})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-setup', type=Path, required=True)
    parser.add_argument('--new-setup', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.old_setup, arguments.new_setup)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
