"""Local encrypted credentials, deliberately separate from portable library backups."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile

from .security import UserError


def _dpapi(data: bytes, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = api.CryptUnprotectData if decrypt else api.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows credential protection failed')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def private_write(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class SecretStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def _fernet(self):
        from cryptography.fernet import Fernet
        path = self.directory / 'x-secret.key'
        if not path.exists():
            # Exclusive creation avoids replacing a key used by another process.
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, 'wb') as output:
                    output.write(Fernet.generate_key())
            except FileExistsError:
                pass
        if path.stat().st_mode & 0o077:
            raise OSError('Credential key permissions must be 0600')
        return Fernet(path.read_bytes())

    def write(self, name: str, value: dict):
        raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        try:
            encrypted = b'DP1' + _dpapi(raw) if os.name == 'nt' else b'FE1' + self._fernet().encrypt(raw)
            private_write(self.directory / name, encrypted)
        except Exception:
            raise UserError('无法安全保存 X 授权信息，请检查本地数据目录权限。', 500) from None

    def read(self, name: str):
        path = self.directory / name
        if not path.exists():
            return None
        try:
            data = path.read_bytes()
            if data[:3] == b'DP1' and os.name == 'nt':
                raw = _dpapi(data[3:], decrypt=True)
            elif data[:3] == b'FE1' and os.name != 'nt':
                raw = self._fernet().decrypt(data[3:])
            else:
                raise ValueError('Different credential protection platform')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError('Invalid credential payload')
            return value
        except Exception:
            raise UserError('无法解密 X 授权信息。请在原系统用户下运行，或断开连接后重新授权。', 409) from None

    def delete(self, name: str):
        (self.directory / name).unlink(missing_ok=True)
