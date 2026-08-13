"""Per-tenant token encryption.

Each tenant's AES-256 key is derived from the single root key
(APP_ENCRYPTION_KEY) via HKDF, using hub_id as derivation context, so no
tenant's key is ever derivable from another tenant's data. See
context/Hubspot/REPO_CLEANUP_DECISIONS.md and the spec's "tenant-scoped
decryption keys" requirement.
"""

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from config import settings

_NONCE_LEN = 12  # 96-bit nonce, standard for AES-GCM


def _root_key_bytes() -> bytes:
    if not settings.app_encryption_key:
        raise RuntimeError("APP_ENCRYPTION_KEY is not set")
    return base64.urlsafe_b64decode(settings.app_encryption_key)


def derive_tenant_key(hub_id: str) -> bytes:
    """Derives this tenant's 32-byte AES-256 key from the root key via HKDF."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"tenant:{hub_id}".encode("utf-8"),
    )
    return hkdf.derive(_root_key_bytes())


def encrypt(plaintext: str, key: bytes) -> str:
    """Encrypts plaintext with AES-256-GCM under the given per-tenant key.

    Returns a base64 string of nonce || ciphertext (ciphertext includes the
    GCM authentication tag).
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(token: str, key: bytes) -> str:
    """Decrypts a value produced by encrypt(). Raises ValueError on failure.

    A ValueError here (wrong key, or tampered/corrupted ciphertext) is the
    only outcome for a cross-tenant decryption attempt, this is what
    guarantees tenant A's key can never decrypt tenant B's stored token.
    """
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as exc:  # cryptography raises InvalidTag on mismatch
        raise ValueError("decryption failed") from exc
    return plaintext.decode("utf-8")
