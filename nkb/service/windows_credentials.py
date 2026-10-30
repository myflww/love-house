"""Current-user Windows Credential Manager access, no file or plaintext fallback.

Only this application's hashed accounts are addressable; credentials use generic
blobs and CRED_PERSIST_LOCAL_MACHINE (same user and computer, not roaming).
Native API contract: https://learn.microsoft.com/windows/win32/api/wincred/ns-wincred-credentialw
"""
from __future__ import annotations

import ctypes
import re
import sys

SERVICE = 'local.neural-knowledge.ai-credentials.v1'
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_MAX_CREDENTIAL_BLOB_SIZE = 5 * 512
ERROR_NOT_FOUND = 1168
DWORD = ctypes.c_uint32
BYTE = ctypes.c_ubyte
BOOL = ctypes.c_int32


class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', DWORD), ('dwHighDateTime', DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [('Flags', DWORD), ('Type', DWORD), ('TargetName', ctypes.c_wchar_p),
                ('Comment', ctypes.c_wchar_p), ('LastWritten', FILETIME),
                ('CredentialBlobSize', DWORD), ('CredentialBlob', ctypes.POINTER(BYTE)),
                ('Persist', DWORD), ('AttributeCount', DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', ctypes.c_wchar_p), ('UserName', ctypes.c_wchar_p)]


class WindowsCredentialBackend:
    """Internal-only op adapter with the same private response shape as the Mac helper.

    ``api`` and ``last_error`` permit a pure mock on non-Windows test runners.
    Default construction never loads a Windows DLL on another operating system.
    """
    def __init__(self, api=None, last_error=None):
        if api is None:
            if sys.platform != 'win32':
                raise OSError('Windows credential storage is unavailable on this platform')
            api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api = api
        self.last_error = last_error or getattr(ctypes, 'get_last_error', lambda: 0)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), DWORD]
        self.api.CredWriteW.restype = BOOL
        self.api.CredReadW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self.api.CredReadW.restype = BOOL
        self.api.CredDeleteW.argtypes = [ctypes.c_wchar_p, DWORD, DWORD]
        self.api.CredDeleteW.restype = BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    @staticmethod
    def _target(account):
        if not isinstance(account, str) or not re.fullmatch(r'[a-f0-9]{64}', account):
            raise ValueError('credential account must be an application-scoped digest')
        return SERVICE + '/' + account

    @staticmethod
    def _failed():
        # Never echo native exception text, request values or credential contents.
        return {'ok': False, 'code': 'windows_credential_unavailable'}

    def call(self, op, account, value=None):
        target = self._target(account)
        if op not in ('set', 'get', 'delete'): return self._failed()
        try:
            if op == 'set':
                if not isinstance(value, str) or not value or '\0' in value: return self._failed()
                blob = value.encode('utf-8')
                if len(blob) > CRED_MAX_CREDENTIAL_BLOB_SIZE: return self._failed()
                buffer = (BYTE * len(blob)).from_buffer_copy(blob)
                credential = CREDENTIALW()
                credential.Type = CRED_TYPE_GENERIC
                credential.TargetName = target
                credential.Comment = 'Love House model credential'
                credential.CredentialBlobSize = len(blob)
                credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(BYTE))
                credential.Persist = CRED_PERSIST_LOCAL_MACHINE
                credential.UserName = 'LoveHouse'
                try:
                    return {'ok': bool(self.api.CredWriteW(ctypes.byref(credential), 0))}
                finally:
                    ctypes.memset(buffer, 0, len(blob))
            if op == 'delete':
                deleted = bool(self.api.CredDeleteW(target, CRED_TYPE_GENERIC, 0))
                return {'ok': True} if deleted or self.last_error() == ERROR_NOT_FOUND else self._failed()
            pointer = ctypes.POINTER(CREDENTIALW)()
            if not self.api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
                return {'ok': True, 'found': False, 'value': ''} if self.last_error() == ERROR_NOT_FOUND else self._failed()
            size = 0
            try:
                if not pointer: return self._failed()
                credential = pointer.contents
                if (credential.Type != CRED_TYPE_GENERIC or not credential.TargetName
                        or credential.TargetName.casefold() != target.casefold()
                        or credential.CredentialBlobSize > CRED_MAX_CREDENTIAL_BLOB_SIZE):
                    return self._failed()
                size = int(credential.CredentialBlobSize)
                if size and not credential.CredentialBlob: return self._failed()
                key = ctypes.string_at(credential.CredentialBlob, size).decode('utf-8') if size else ''
                if '\0' in key: return self._failed()
                return {'ok': True, 'found': bool(key), 'value': key}
            finally:
                if pointer:
                    if size and pointer.contents.CredentialBlob:
                        ctypes.memset(pointer.contents.CredentialBlob, 0, size)
                    self.api.CredFree(pointer)
        except Exception:
            return self._failed()
