"""Task 2.10: proves tenant A's derived key can never decrypt tenant B's
stored token. Also covers round-trip correctness and plaintext-never-stored."""

import pytest

from auth import decrypt, derive_tenant_key, encrypt


def test_encrypt_decrypt_round_trip():
    key = derive_tenant_key("hub_1")
    ciphertext = encrypt("super-secret-token", key)
    assert decrypt(ciphertext, key) == "super-secret-token"


def test_ciphertext_never_contains_plaintext():
    key = derive_tenant_key("hub_1")
    ciphertext = encrypt("super-secret-token", key)
    assert "super-secret-token" not in ciphertext


def test_cross_tenant_key_cannot_decrypt():
    key_a = derive_tenant_key("hub_a")
    key_b = derive_tenant_key("hub_b")
    ciphertext = encrypt("tenant-a-token", key_a)

    with pytest.raises(ValueError):
        decrypt(ciphertext, key_b)


def test_derived_keys_differ_per_tenant():
    assert derive_tenant_key("hub_a") != derive_tenant_key("hub_b")


def test_derived_key_is_deterministic_for_same_tenant():
    assert derive_tenant_key("hub_a") == derive_tenant_key("hub_a")
