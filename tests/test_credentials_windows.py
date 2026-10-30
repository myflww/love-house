"""WinCred tests run entirely against in-memory fakes, including the ctypes ABI.

No test accesses macOS Keychain, Windows Credential Manager, vendor keys or disk
credential files. The production Windows backend stores opaque UTF-8 blobs.
"""
import contextlib
import ctypes
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from nkb.service import credentials
from nkb.service.credentials import KeyStore, KeyStoreError, _account
from nkb.service.windows_credentials import (WindowsCredentialBackend, CREDENTIALW,
    CRED_MAX_CREDENTIAL_BLOB_SIZE, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    ERROR_NOT_FOUND, SERVICE)


class FakeProc:
    def __init__(self, fn): self.fn = fn
    def __call__(self, *args): return self.fn(*args)


class FakeWinCredAPI:
    """Models WinCred's native pointer ownership; backing store remains in RAM."""
    def __init__(self):
        self.store = {}; self.allocations = {}; self.error = 0; self.freed = 0
        self.reads = self.writes = self.deletes = 0
        self.deny_read = self.deny_write = self.deny_delete = False
        self.bad_target = False; self.bad_size = False; self.bad_utf8 = False
        self.CredWriteW = FakeProc(self.write); self.CredReadW = FakeProc(self.read)
        self.CredDeleteW = FakeProc(self.delete); self.CredFree = FakeProc(self.free)
        self.last_read_blob_wiped = None

    def write(self, pointer, flags):
        self.writes += 1
        if self.deny_write: self.error = 5; return 0
        assert flags == 0
        value = ctypes.cast(pointer, ctypes.POINTER(CREDENTIALW)).contents
        assert value.Type == CRED_TYPE_GENERIC
        assert value.Persist == CRED_PERSIST_LOCAL_MACHINE
        assert value.AttributeCount == 0
        self.store[value.TargetName] = (ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize), value.Persist)
        return 1

    def read(self, target, kind, flags, output):
        self.reads += 1
        if self.deny_read: self.error = 5; return 0
        assert kind == CRED_TYPE_GENERIC and flags == 0
        if target not in self.store: self.error = ERROR_NOT_FOUND; return 0
        raw = b'\xff' if self.bad_utf8 else self.store[target][0]
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        value = CREDENTIALW(); value.Type = CRED_TYPE_GENERIC
        value.TargetName = 'wrong-target' if self.bad_target else target
        value.CredentialBlobSize = CRED_MAX_CREDENTIAL_BLOB_SIZE + 1 if self.bad_size else len(raw)
        value.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        pointer = ctypes.pointer(value)
        self.allocations[ctypes.addressof(value)] = (value, buffer)
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(CREDENTIALW)))[0] = pointer
        return 1

    def delete(self, target, kind, flags):
        self.deletes += 1
        if self.deny_delete: self.error = 5; return 0
        assert kind == CRED_TYPE_GENERIC and flags == 0
        if target not in self.store: self.error = ERROR_NOT_FOUND; return 0
        self.store.pop(target); return 1

    def free(self, pointer):
        value = ctypes.cast(pointer, ctypes.POINTER(CREDENTIALW)).contents
        original, buffer = self.allocations.pop(ctypes.addressof(value))
        self.last_read_blob_wiped = not any(buffer)
        self.freed += 1

    def backend(self): return WindowsCredentialBackend(self, last_error=lambda: self.error)


class NativeWinCredTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeWinCredAPI(); self.backend = self.api.backend()
        self.account = _account({'provider': 'FAKE', 'library_id': 'FAKE-lib', 'connection_id': uuid.uuid4().hex})
        self.key = 'FAKE-WINDOWS-KEY-中文-' + uuid.uuid4().hex

    def test_native_write_read_delete_are_generic_current_user_local_nonroaming(self):
        self.assertTrue(self.backend.call('set', self.account, self.key)['ok'])
        target = SERVICE + '/' + self.account
        self.assertEqual(self.api.store[target], (self.key.encode('utf-8'), CRED_PERSIST_LOCAL_MACHINE))
        self.assertNotIn(self.key, target)
        self.assertEqual(self.backend.call('get', self.account), {'ok': True, 'found': True, 'value': self.key})
        self.assertEqual(self.api.freed, 1); self.assertTrue(self.api.last_read_blob_wiped)
        self.assertEqual(self.backend.call('delete', self.account), {'ok': True})
        self.assertEqual(self.backend.call('get', self.account), {'ok': True, 'found': False, 'value': ''})
        self.assertEqual(self.api.store, {})
        self.assertEqual(self.api.allocations, {})

    def test_only_app_hashed_accounts_are_addressable_no_enumeration_or_foreign_target(self):
        for invalid in ('', 'OTHER-SERVICE/name', 'a'*63, 'G'*64, '../target', None):
            with self.assertRaises(ValueError): self.backend.call('get', invalid)
        self.assertEqual(self.api.reads, 0)
        self.assertEqual(self.backend.call('arbitrary-native-code', self.account)['ok'], False)

    def test_not_found_delete_is_idempotent_but_permission_denial_is_not_success(self):
        self.assertTrue(self.backend.call('delete', self.account)['ok'])
        self.api.deny_delete = True
        self.assertFalse(self.backend.call('delete', self.account)['ok'])
        self.api.deny_read = True
        result = self.backend.call('get', self.account)
        self.assertFalse(result['ok']); self.assertNotIn('value', result)

    def test_blob_limit_uses_bytes_and_never_writes_oversized_secret(self):
        self.assertTrue(self.backend.call('set', self.account, 'A'*CRED_MAX_CREDENTIAL_BLOB_SIZE)['ok'])
        writes = self.api.writes
        self.assertFalse(self.backend.call('set', self.account, '中文'*(CRED_MAX_CREDENTIAL_BLOB_SIZE//6+1))['ok'])
        self.assertFalse(self.backend.call('set', self.account, 'A'*(CRED_MAX_CREDENTIAL_BLOB_SIZE+1))['ok'])
        self.assertEqual(writes, self.api.writes)

    def test_read_frees_memory_even_for_wrong_target_corruption_and_invalid_utf8(self):
        self.backend.call('set', self.account, self.key)
        for field in ('bad_target', 'bad_size', 'bad_utf8'):
            setattr(self.api, field, True)
            self.assertFalse(self.backend.call('get', self.account)['ok'])
            setattr(self.api, field, False)
            self.assertEqual(self.api.allocations, {})
        self.assertEqual(self.api.freed, 3)

    def test_native_exceptions_do_not_expose_secret_or_exception_detail(self):
        self.api.CredWriteW = FakeProc(lambda *args: (_ for _ in ()).throw(OSError(self.key)))
        stdout = io.StringIO(); stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            response = self.backend.call('set', self.account, self.key)
        self.assertFalse(response['ok'])
        self.assertNotIn(self.key, json.dumps(response) + stdout.getvalue() + stderr.getvalue())


class WindowsKeyStoreTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeWinCredAPI(); self.backend = self.api.backend()
        self.session = patch.object(credentials, '_SESSION', {}); self.session.start()
        self.store = KeyStore(allow_source_build=False, windows_backend=self.backend)
        self.ref = {'provider': 'FAKE-provider', 'library_id': 'FAKE-lib', 'connection_id': uuid.uuid4().hex}
        self.key = 'FAKE-NOT-A-REAL-WINDOWS-KEY-' + uuid.uuid4().hex

    def tearDown(self): self.session.stop()

    def test_persistence_verified_by_readback_public_metadata_stays_compatible_and_secret_free(self):
        with patch.object(credentials.subprocess, 'run', side_effect=AssertionError('must not spawn a helper')):
            result = self.store.set(self.ref, self.key)
            self.assertEqual(result, {'storage': 'keychain', 'credential_ready': True, 'key_saved': True})
            self.assertNotIn(self.key, json.dumps(result)); self.assertEqual(self.store.get(self.ref), self.key)
            another = KeyStore(allow_source_build=False, windows_backend=self.backend)
            self.assertEqual(another.get(self.ref), self.key)
            self.assertEqual(another.metadata(self.ref), result)
            self.assertEqual(self.api.writes, 1)
            self.assertFalse(another.delete(self.ref)['credential_ready'])
            self.assertEqual(self.store.get(self.ref), '')

    def test_provider_library_connection_and_mapping_order_are_independent(self):
        self.store.set(self.ref, self.key)
        for field in ('provider', 'library_id', 'connection_id'):
            changed = {**self.ref, field: 'other'}
            self.assertEqual(self.store.get(changed), '')
            self.assertFalse(self.store.metadata(changed)['credential_ready'])
        reversed_ref = dict(reversed(list(self.ref.items())))
        self.assertEqual(self.store.get(reversed_ref), self.key)
        self.assertTrue(all(target.startswith(SERVICE + '/') and len(target.split('/')[-1]) == 64 for target in self.api.store))
        self.assertNotIn('FAKE-lib', '\n'.join(self.api.store))

    def test_denied_or_oversized_persistence_falls_back_to_session_without_plaintext_files(self):
        self.api.deny_write = True
        self.assertEqual(self.store.set(self.ref, self.key), {'storage': 'session', 'credential_ready': True, 'key_saved': False})
        self.assertEqual(self.store.get(self.ref), self.key); self.assertEqual(self.api.store, {})
        self.api.deny_write = False
        big = 'B' * (CRED_MAX_CREDENTIAL_BLOB_SIZE + 1)
        result = self.store.set(self.ref, big)
        self.assertEqual(result['storage'], 'session'); self.assertFalse(result['key_saved'])
        self.assertEqual(self.api.store, {})
        self.store.delete(self.ref); self.assertEqual(self.store.get(self.ref), '')

    def test_session_choice_and_disabled_secure_store_never_call_native_api(self):
        self.assertEqual(self.store.set(self.ref, self.key, persist=False)['storage'], 'session')
        self.assertEqual(self.api.writes + self.api.reads, 0)
        credentials._SESSION.clear()
        disabled = KeyStore(allow_keychain=False, windows_backend=self.backend)
        self.assertEqual(disabled.set(self.ref, self.key)['storage'], 'session')
        self.assertEqual(disabled.get(self.ref), self.key)
        self.assertFalse(disabled.metadata(self.ref)['key_saved'])
        disabled.delete(self.ref)
        self.assertEqual(self.api.writes + self.api.reads + self.api.deletes, 0)

    def test_unverified_readback_does_not_claim_saved_even_when_write_returned_success(self):
        self.api.deny_read = True
        result = self.store.set(self.ref, self.key)
        self.assertEqual(result['storage'], 'session'); self.assertFalse(result['key_saved'])
        self.assertEqual(self.store.get(self.ref), self.key)

    def test_delete_denial_reports_generic_uncertainty_not_false_success_or_secret(self):
        self.store.set(self.ref, self.key)
        self.api.deny_delete = True
        with self.assertRaises(KeyStoreError) as error: self.store.delete(self.ref)
        self.assertNotIn(self.key, str(error.exception)); self.assertIn('无法确认', str(error.exception))
        self.assertIn(SERVICE + '/' + _account(self.ref), self.api.store)

    def test_win32_default_selects_backend_without_mac_build_or_subprocess(self):
        with patch.object(credentials.sys, 'platform', 'win32'), \
             patch('nkb.service.windows_credentials.WindowsCredentialBackend', return_value=self.backend) as factory, \
             patch.object(credentials, '_source_helper', side_effect=AssertionError('Mac helper selected')), \
             patch.object(credentials.subprocess, 'run', side_effect=AssertionError('No subprocess allowed')):
            store = KeyStore(allow_source_build=False)
            self.assertTrue(store.set(self.ref, self.key)['key_saved'])
            self.assertEqual(store.get(self.ref), self.key)
            self.assertFalse(store.delete(self.ref)['credential_ready'])
            self.assertEqual(factory.call_count, 1)

    def test_unavailable_native_store_is_truthful_and_exception_never_logged(self):
        stdout = io.StringIO(); stderr = io.StringIO()
        with patch.object(credentials.sys, 'platform', 'win32'), \
             patch('nkb.service.windows_credentials.WindowsCredentialBackend', side_effect=OSError(self.key)), \
             patch.object(credentials.subprocess, 'run', side_effect=AssertionError('No subprocess allowed')), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            store = KeyStore(allow_source_build=False)
            self.assertFalse(store.metadata(self.ref)['credential_ready'])
            result = store.set(self.ref, self.key)
            self.assertEqual(result['storage'], 'session'); self.assertFalse(result['key_saved'])
            self.assertEqual(store.get(self.ref), self.key)
            with self.assertRaises(KeyStoreError) as error: store.delete(self.ref)
        self.assertNotIn(self.key, json.dumps(result) + str(error.exception) + stdout.getvalue() + stderr.getvalue())

    def test_fresh_user_native_store_does_not_read_another_mock_users_credential(self):
        self.store.set(self.ref, self.key)
        other_user = KeyStore(allow_source_build=False, windows_backend=FakeWinCredAPI().backend())
        self.assertEqual(other_user.get(self.ref), '')
        self.assertFalse(other_user.metadata(self.ref)['credential_ready'])


if __name__ == '__main__': unittest.main()
