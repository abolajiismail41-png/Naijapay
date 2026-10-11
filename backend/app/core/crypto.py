"""Field-level encryption for secrets we must store (e.g. electricity tokens). AES-256-GCM, versioned."""
import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"


def _key(secret: str) -> bytes:
    return hashlib.sha256(b"naijapay-field-encryption|" + _VERSION.encode() + b"|" + secret.encode()).digest()


def encrypt(secret: str, plaintext: str, aad: str) -> str:
    """`aad` binds the ciphertext to its record: a blob copied onto another row will not decrypt."""
    nonce = os.urandom(12)
    ct = AESGCM(_key(secret)).encrypt(nonce, plaintext.encode(), aad.encode())
    return f"{_VERSION}:" + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(secret: str, blob: str, aad: str) -> str:
    version, _, body = blob.partition(":")
    if version != _VERSION:
        raise ValueError("unsupported ciphertext version")
    raw = base64.urlsafe_b64decode(body.encode())
    try:
        return AESGCM(_key(secret)).decrypt(raw[:12], raw[12:], aad.encode()).decode()
    except InvalidTag as exc:
        raise ValueError("ciphertext failed authentication") from exc
