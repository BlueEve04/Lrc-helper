"""NetEase eapi request encryption (AES-128-ECB)."""

from __future__ import annotations

import binascii
import hashlib
import json

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_EAPI_KEY = b"e82ckenh8dichen8"


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad = block_size - len(data) % block_size
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16:
        return data
    return data[:-pad]


def aes_encrypt(data: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(_EAPI_KEY), modes.ECB()).encryptor()
    return encryptor.update(_pkcs7_pad(data)) + encryptor.finalize()


def aes_decrypt(data: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(_EAPI_KEY), modes.ECB()).decryptor()
    return _pkcs7_unpad(decryptor.update(data) + decryptor.finalize())


def eapi_params_encrypt(path: bytes, params: dict) -> str:
    """Encrypt eapi parameters and return an ``params=...`` form body."""
    params_bytes = json.dumps(params, separators=(",", ":")).encode("utf-8")
    sign_src = b"nobody" + path + b"use" + params_bytes + b"md5forencrypt"
    sign = hashlib.md5(sign_src).hexdigest()  # noqa: S324
    aes_src = path + b"-36cd479b6b5-" + params_bytes + b"-36cd479b6b5-" + sign.encode("ascii")
    encrypted = aes_encrypt(aes_src)
    return f"params={binascii.hexlify(encrypted).upper().decode('ascii')}"


def eapi_response_decrypt(cipher_buffer: bytes) -> bytes:
    return aes_decrypt(cipher_buffer)
