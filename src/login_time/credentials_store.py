"""Password storage in the Windows Credential Manager, stdlib only (ctypes).

The entry is a "generic credential" named TARGET_NAME: it is visible and removable
from Control Panel > Credential Manager > Windows Credentials.

On other platforms (or if the Windows API call fails) is_supported() is False and
config.py falls back to the old credentials.json behaviour.
"""

from __future__ import annotations

import sys

TARGET_NAME = "login_time/support.quixant.com"

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)

    try:
        _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        _CredWriteW = _advapi32.CredWriteW
        _CredWriteW.argtypes = [_PCREDENTIALW, wintypes.DWORD]
        _CredWriteW.restype = wintypes.BOOL

        _CredReadW = _advapi32.CredReadW
        _CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIALW)]
        _CredReadW.restype = wintypes.BOOL

        _CredDeleteW = _advapi32.CredDeleteW
        _CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        _CredDeleteW.restype = wintypes.BOOL

        _CredFree = _advapi32.CredFree
        _CredFree.argtypes = [ctypes.c_void_p]
        _CredFree.restype = None
        _AVAILABLE = True
    except (OSError, AttributeError):
        _AVAILABLE = False
else:
    _AVAILABLE = False


def is_supported() -> bool:
    return _AVAILABLE


def read_credential() -> tuple[str, str] | None:
    """Return (username, password) or None if nothing is stored."""
    if not _AVAILABLE:
        return None
    pointer = _PCREDENTIALW()
    if not _CredReadW(TARGET_NAME, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return None
    try:
        cred = pointer.contents
        size = int(cred.CredentialBlobSize)
        raw = ctypes.string_at(cred.CredentialBlob, size) if size else b""
        password = raw.decode("utf-16-le", errors="replace")
        username = cred.UserName or ""
        return username, password
    finally:
        _CredFree(pointer)


def write_credential(username: str, password: str) -> bool:
    """Create or replace the stored credential. Returns False on failure."""
    if not _AVAILABLE:
        return False
    blob_bytes = password.encode("utf-16-le")
    blob = (ctypes.c_ubyte * max(len(blob_bytes), 1)).from_buffer_copy(blob_bytes or b"\0")
    cred = _CREDENTIALW()
    cred.Flags = 0
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = TARGET_NAME
    cred.Comment = "login_time - Quixant Hub"
    cred.CredentialBlobSize = len(blob_bytes)
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = username
    return bool(_CredWriteW(ctypes.byref(cred), 0))


def delete_credential() -> bool:
    if not _AVAILABLE:
        return False
    if _CredDeleteW(TARGET_NAME, _CRED_TYPE_GENERIC, 0):
        return True
    return ctypes.get_last_error() == _ERROR_NOT_FOUND
