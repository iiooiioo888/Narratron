"""L0–L3：明文、checksum+HMAC、資產 AES-GCM、整包 AES-GCM。金鑰由呼叫端帶入。"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Final

from narratron.charpass.exceptions import CharpassCryptoError, CharpassSignatureError

L2_MAGIC: Final = b"NRTNCP2\0"
L3_MAGIC: Final = b"NRTNCP3\0"
NONCE_SIZE: Final = 12


def normalize_key(key: str | bytes) -> bytes:
    raw = key.encode("utf-8") if isinstance(key, str) else key
    if len(raw) == 32:
        return raw
    return hashlib.sha256(raw).digest()


def hmac_signature(checksum: str, key: str | bytes) -> bytes:
    return hmac.new(normalize_key(key), checksum.encode("utf-8"), hashlib.sha256).digest()


def verify_hmac(checksum: str, signature: bytes, key: str | bytes) -> None:
    expected = hmac_signature(checksum, key)
    if not hmac.compare_digest(expected, signature):
        raise CharpassSignatureError("signature.sig HMAC 校驗失敗")


def _aesgcm(key: str | bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise CharpassCryptoError("L2/L3 需要 cryptography：pip install cryptography") from exc
    return AESGCM(normalize_key(key))


def encrypt_blob(plaintext: bytes, key: str | bytes, *, aad: bytes, magic: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = _aesgcm(key).encrypt(nonce, plaintext, aad)
    return magic + nonce + ciphertext


def decrypt_blob(blob: bytes, key: str | bytes, *, aad: bytes, magic: bytes) -> bytes:
    if not blob.startswith(magic):
        raise CharpassCryptoError("密文魔數不符")
    nonce = blob[len(magic) : len(magic) + NONCE_SIZE]
    ciphertext = blob[len(magic) + NONCE_SIZE :]
    if len(nonce) != NONCE_SIZE or not ciphertext:
        raise CharpassCryptoError("密文長度不足")
    try:
        return _aesgcm(key).decrypt(nonce, ciphertext, aad)
    except Exception as exc:
        raise CharpassCryptoError("AES-256-GCM 解密失敗") from exc


def is_l2_blob(data: bytes) -> bool:
    return data.startswith(L2_MAGIC)


def is_l3_blob(data: bytes) -> bool:
    return data.startswith(L3_MAGIC)


def encrypt_asset(path: str, plaintext: bytes, key: str | bytes) -> bytes:
    return encrypt_blob(plaintext, key, aad=path.encode("utf-8"), magic=L2_MAGIC)


def decrypt_asset(path: str, blob: bytes, key: str | bytes) -> bytes:
    return decrypt_blob(blob, key, aad=path.encode("utf-8"), magic=L2_MAGIC)


def encrypt_zip(data: bytes, key: str | bytes) -> bytes:
    return encrypt_blob(data, key, aad=b"charpass-l3", magic=L3_MAGIC)


def decrypt_zip(data: bytes, key: str | bytes) -> bytes:
    return decrypt_blob(data, key, aad=b"charpass-l3", magic=L3_MAGIC)
