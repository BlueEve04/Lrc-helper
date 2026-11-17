"""QQ Music QRC decryption.

The QRC cipher is the custom QQ Music 3DES variant implemented in
``triple_des.py`` (adapted from LDDC).  The decrypted payload is zlib-compressed
UTF-8 text.
"""

from __future__ import annotations

import zlib

from .triple_des import DECRYPT, tripledes_crypt, tripledes_key_setup

QRC_KEY = b"!@#)(*$%123ZXC!@!@#)(NHL"


class QrcDecryptError(ValueError):
    pass


def decrypt_qrc(encrypted_hex: str) -> str:
    """Decrypt a cloud QRC hex string into plain QRC text."""
    if not encrypted_hex or not encrypted_hex.strip():
        raise QrcDecryptError("empty QRC payload")
    try:
        data = bytearray.fromhex(encrypted_hex.strip())
    except ValueError as exc:
        raise QrcDecryptError("invalid QRC hex payload") from exc

    try:
        schedule = tripledes_key_setup(QRC_KEY, DECRYPT)
        decrypted = bytearray()
        for index in range(0, len(data), 8):
            decrypted += tripledes_crypt(data[index:], schedule)
        return zlib.decompress(bytes(decrypted)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - all failures mean the payload is unusable
        raise QrcDecryptError(f"QRC decryption failed: {exc}") from exc
