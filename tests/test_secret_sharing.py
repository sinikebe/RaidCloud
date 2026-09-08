"""Unit tests for secret sharing (Shamir SSS + AES-GCM)."""

import pytest

from raidcloud.raid.secret_sharing import (
    SecretSharingRAID,
    _decode_blob,
    _decrypt,
    _encode_blob,
    _encrypt,
    _shamir_reconstruct,
    _shamir_split,
)
from tests.helpers import MockProvider

# ---------------------------------------------------------------------------
# GF arithmetic / Shamir primitives
# ---------------------------------------------------------------------------

def test_shamir_2_of_3_roundtrip():
    secret = b"\xde\xad\xbe\xef" * 8  # 32 bytes
    shares = _shamir_split(secret, n=3, k=2)
    assert len(shares) == 3
    # Any 2 shares should reconstruct
    for i in range(3):
        for j in range(i + 1, 3):
            pairs = [(i + 1, shares[i]), (j + 1, shares[j])]
            reconstructed = _shamir_reconstruct(pairs)
            assert reconstructed == secret, f"Failed with shares {i+1}, {j+1}"


def test_shamir_3_of_3_roundtrip():
    secret = bytes(range(32))
    shares = _shamir_split(secret, n=3, k=3)
    reconstructed = _shamir_reconstruct([(1, shares[0]), (2, shares[1]), (3, shares[2])])
    assert reconstructed == secret


def test_shamir_insufficient_shares():
    """Reconstructing with too few shares should NOT return the secret."""
    secret = b"mysecretdata1234" * 2
    shares = _shamir_split(secret, n=3, k=3)
    # Only 2 of 3 shares — should NOT reconstruct correctly
    result = _shamir_reconstruct([(1, shares[0]), (2, shares[1])])
    assert result != secret


def test_shamir_single_byte():
    for secret_byte in [0x00, 0x01, 0xFF, 0x80]:
        secret = bytes([secret_byte])
        shares = _shamir_split(secret, n=3, k=2)
        reconstructed = _shamir_reconstruct([(1, shares[0]), (3, shares[2])])
        assert reconstructed == secret


def test_shamir_requires_k_lte_n():
    with pytest.raises(ValueError):
        _shamir_split(b"data", n=2, k=3)


def test_shamir_requires_k_gte_2():
    with pytest.raises(ValueError):
        _shamir_split(b"data", n=3, k=1)


# ---------------------------------------------------------------------------
# AES-GCM envelope
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    import os
    key = os.urandom(32)
    plaintext = b"Top secret data!"
    nonce, ct, tag = _encrypt(key, plaintext)
    recovered = _decrypt(key, nonce, ct, tag)
    assert recovered == plaintext


def test_decrypt_fails_with_wrong_key():
    import os

    from cryptography.exceptions import InvalidTag
    key = os.urandom(32)
    bad_key = os.urandom(32)
    nonce, ct, tag = _encrypt(key, b"hello")
    with pytest.raises(InvalidTag):
        _decrypt(bad_key, nonce, ct, tag)


# ---------------------------------------------------------------------------
# Blob encoding
# ---------------------------------------------------------------------------

def test_encode_decode_blob_roundtrip():
    import os
    nonce = os.urandom(12)
    ct = b"encrypted_data"
    tag = os.urandom(16)
    dek_share = os.urandom(32)
    blob = _encode_blob(1, 3, 2, nonce, ct, tag, dek_share)
    info = _decode_blob(blob)
    assert info["index"] == 1
    assert info["n"] == 3
    assert info["k"] == 2
    assert info["nonce"] == nonce
    assert info["ciphertext"] == ct
    assert info["tag"] == tag
    assert info["dek_share"] == dek_share


def test_decode_blob_invalid_magic():
    with pytest.raises(ValueError, match="magic"):
        _decode_blob(b"BAAD" + b"\x00" * 100)


# ---------------------------------------------------------------------------
# SecretSharingRAID integration
# ---------------------------------------------------------------------------

def _make_raid(n=3, k=2):
    providers = [MockProvider(f"p{i}") for i in range(n)]
    return SecretSharingRAID(providers, threshold=k), providers


def test_upload_download_roundtrip():
    raid, _ = _make_raid(n=3, k=2)
    plaintext = b"Confidential cloud file content!"
    raid.upload("secret.txt", plaintext)
    assert raid.download("secret.txt") == plaintext


def test_reconstruct_with_subset_of_providers():
    """Should reconstruct with only K providers available."""
    n, k = 3, 2
    providers = [MockProvider(f"p{i}") for i in range(n)]
    raid = SecretSharingRAID(providers, threshold=k)
    plaintext = b"Reconstruct me!"
    raid.upload("partial.txt", plaintext)

    # Create a new RAID that only uses providers[0] and providers[1]
    partial_raid = SecretSharingRAID(providers[:2], threshold=k)
    # providers[:2] have share_1 and share_2 — enough for k=2
    assert partial_raid.download("partial.txt") == plaintext


def test_download_fails_below_threshold():
    n, k = 3, 3
    providers = [MockProvider(f"p{i}") for i in range(n)]
    raid = SecretSharingRAID(providers, threshold=k)
    raid.upload("locked.txt", b"secret")

    # Simulate provider 2 being unavailable by clearing its store
    providers[2].store.clear()

    # Only 2 of 3 shares remain — below threshold k=3
    with pytest.raises(FileNotFoundError):
        raid.download("locked.txt")


def test_delete():
    raid, providers = _make_raid(n=3, k=2)
    raid.upload("todel.txt", b"bye")
    raid.delete("todel.txt")
    for p in providers:
        # All share blobs should be gone
        assert not any("todel.txt" in k for k in p.store)


def test_list():
    raid, _ = _make_raid(n=3, k=2)
    raid.upload("dir/file.txt", b"data")
    paths = raid.list()
    assert "dir/file.txt" in paths


def test_requires_at_least_2_providers():
    with pytest.raises(ValueError):
        SecretSharingRAID([MockProvider("p1")], threshold=2)


def test_requires_valid_threshold():
    providers = [MockProvider(f"p{i}") for i in range(3)]
    with pytest.raises(ValueError):
        SecretSharingRAID(providers, threshold=4)
