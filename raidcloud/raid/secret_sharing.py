"""Secret-sharing (confidentiality) mode using Shamir's Secret Sharing.

Each file is split into N shares (one per provider) using a *K*-of-*N*
threshold scheme.  Any K shares suffice to reconstruct the original data;
fewer than K shares reveal nothing about the content.

This is implemented entirely in pure Python over GF(2^8) — no third-party
cryptography library is required (though the `cryptography` package is used
for the AES-GCM envelope below).

Protocol
--------
1. Generate a random 256-bit AES key *DEK* (data-encryption key).
2. Encrypt the file with AES-256-GCM → *ciphertext* + *tag* + *nonce*.
3. Split *DEK* into N Shamir shares over GF(2^8) byte-by-byte.
4. Store (share_i || ciphertext || tag || nonce) on provider i.

Reconstruction
--------------
1. Collect ≥ K shares from any K providers.
2. Lagrange-interpolate to recover *DEK*.
3. Decrypt the ciphertext.

On-disk layout per provider (path ``<logical_path>.shares/<share_index>``)::

    4 bytes:  magic "RCS\x01"
    2 bytes:  share index (1-based, big-endian uint16)
    2 bytes:  N (total shares, big-endian uint16)
    2 bytes:  K (threshold, big-endian uint16)
    12 bytes: AES-GCM nonce (fixed _NONCE_LEN = 12)
    8 bytes:  ciphertext length M (big-endian uint64)
    M bytes:  ciphertext
    16 bytes: GCM authentication tag
    32 bytes: DEK share (_AES_KEY_LEN = 32)
"""

from __future__ import annotations

import builtins
import os
import struct

from raidcloud.providers.base import CloudProvider

# ---------------------------------------------------------------------------
# GF(2^8) arithmetic (irreducible polynomial x^8 + x^4 + x^3 + x + 1 = 0x11b)
# ---------------------------------------------------------------------------

_POLY = 0x11B


def _gf_mul(a: int, b: int) -> int:
    """Multiply two elements in GF(2^8)."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a & 0x100:
            a ^= _POLY
        b >>= 1
    return result & 0xFF


def _gf_pow(base: int, exp: int) -> int:
    result = 1
    while exp:
        if exp & 1:
            result = _gf_mul(result, base)
        base = _gf_mul(base, base)
        exp >>= 1
    return result


def _gf_inv(a: int) -> int:
    """Multiplicative inverse in GF(2^8) via Fermat's little theorem."""
    if a == 0:
        raise ZeroDivisionError("GF inverse of zero is undefined")
    return _gf_pow(a, 254)


# ---------------------------------------------------------------------------
# Shamir's Secret Sharing over GF(2^8)
# ---------------------------------------------------------------------------

def _shamir_split(secret_bytes: bytes, n: int, k: int) -> list[bytes]:
    """Split *secret_bytes* into *n* shares, *k* of which can reconstruct.

    Each share is the same length as *secret_bytes*.  Shares are indexed 1..N.
    Returns a list of length *n*; element i is the share for x-coordinate (i+1).
    """
    if k > n:
        raise ValueError("Threshold k must be ≤ n.")
    if k < 2:
        raise ValueError("Threshold k must be ≥ 2.")

    shares = [bytearray() for _ in range(n)]
    for byte_val in secret_bytes:
        # Random polynomial of degree k-1 with constant term = byte_val
        coeffs = [byte_val] + [int.from_bytes(os.urandom(1), "big") for _ in range(k - 1)]
        for x in range(1, n + 1):
            y = 0
            for coeff in reversed(coeffs):
                y = _gf_mul(y, x) ^ coeff
            shares[x - 1].append(y)

    return [bytes(s) for s in shares]


def _shamir_reconstruct(shares: list[tuple[int, bytes]]) -> bytes:
    """Reconstruct secret from *shares*.

    *shares* is a list of (x_coordinate, share_bytes) pairs where
    x-coordinates are 1-based integers matching the original split.
    """
    if not shares:
        raise ValueError("Need at least one share.")

    xs = [x for x, _ in shares]
    if any(x < 1 for x in xs):
        raise ValueError("Share x-coordinates must be positive integers (1-based).")
    if len(xs) != len(set(xs)):
        raise ValueError("Duplicate share x-coordinates detected.")

    length = len(shares[0][1])
    if any(len(s) != length for _, s in shares):
        raise ValueError("All shares must have equal length.")
    secret = bytearray()

    for byte_idx in range(length):
        ys = [(x, share[byte_idx]) for x, share in shares]
        # Lagrange interpolation at x=0
        result = 0
        for i, (xi, yi) in enumerate(ys):
            num = yi
            den = 1
            for j, (xj, _) in enumerate(ys):
                if i == j:
                    continue
                num = _gf_mul(num, xj)
                den = _gf_mul(den, xi ^ xj)
            result ^= _gf_mul(num, _gf_inv(den))
        secret.append(result)

    return bytes(secret)


# ---------------------------------------------------------------------------
# AES-GCM envelope
# ---------------------------------------------------------------------------

_AES_KEY_LEN = 32  # 256-bit
_NONCE_LEN = 12    # 96-bit


def _encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes, bytes]:
    """Return (nonce, ciphertext, tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(_NONCE_LEN)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, None)
    # cryptography appends the 16-byte tag at the end
    ciphertext = ct_and_tag[:-16]
    tag = ct_and_tag[-16:]
    return nonce, ciphertext, tag


def _decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext + tag, None)


# ---------------------------------------------------------------------------
# Share encoding / decoding
# ---------------------------------------------------------------------------
# Binary layout per provider blob:
#   4 bytes:  magic "RCS\x01"
#   2 bytes:  share index (1-based, big-endian uint16)
#   2 bytes:  N (big-endian uint16)
#   2 bytes:  K (big-endian uint16)
#   12 bytes: AES-GCM nonce (fixed length _NONCE_LEN = 12)
#   8 bytes:  length of ciphertext (big-endian uint64)
#   M bytes:  ciphertext (M = length field value)
#   16 bytes: GCM tag
#   32 bytes: DEK share bytes

_MAGIC = b"RCS\x01"
_HEADER_FMT = ">HHH"   # index, N, K
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _encode_blob(
    index: int, n: int, k: int, nonce: bytes, ciphertext: bytes, tag: bytes, dek_share: bytes
) -> bytes:
    header = struct.pack(_HEADER_FMT, index, n, k)
    ct_len = struct.pack(">Q", len(ciphertext))
    return _MAGIC + header + nonce + ct_len + ciphertext + tag + dek_share


def _decode_blob(blob: bytes) -> dict:
    _MIN_FIXED = 4 + _HEADER_SIZE + _NONCE_LEN + 8 + 16 + _AES_KEY_LEN  # no ciphertext
    if len(blob) < _MIN_FIXED:
        raise ValueError(f"Share blob too short: {len(blob)} bytes (minimum {_MIN_FIXED}).")
    offset = 0
    if blob[:4] != _MAGIC:
        raise ValueError("Invalid share blob magic.")
    offset += 4
    index, n, k = struct.unpack_from(_HEADER_FMT, blob, offset)
    offset += _HEADER_SIZE
    nonce = blob[offset:offset + _NONCE_LEN]
    if len(nonce) != _NONCE_LEN:
        raise ValueError(f"Truncated nonce: expected {_NONCE_LEN} bytes, got {len(nonce)}.")
    offset += _NONCE_LEN
    ct_len = struct.unpack_from(">Q", blob, offset)[0]
    offset += 8
    remaining = len(blob) - offset
    if remaining < ct_len + 16 + _AES_KEY_LEN:
        raise ValueError(
            f"Blob declares ciphertext length {ct_len} but only "
            f"{remaining} bytes remain (need {ct_len + 16 + _AES_KEY_LEN})."
        )
    ciphertext = blob[offset:offset + ct_len]
    offset += ct_len
    tag = blob[offset:offset + 16]
    offset += 16
    dek_share = blob[offset:offset + _AES_KEY_LEN]
    if len(dek_share) != _AES_KEY_LEN:
        raise ValueError(f"Truncated DEK share: expected {_AES_KEY_LEN} bytes, got {len(dek_share)}.")
    return {
        "index": index,
        "n": n,
        "k": k,
        "nonce": nonce,
        "ciphertext": ciphertext,
        "tag": tag,
        "dek_share": dek_share,
    }


# ---------------------------------------------------------------------------
# SecretSharingRAID
# ---------------------------------------------------------------------------

def _share_path(path: str, index: int) -> str:
    return path.rstrip("/") + f".shares/share_{index}"


class SecretSharingRAID:
    """K-of-N confidentiality mode: split DEK via Shamir SSS, encrypt with AES-GCM.

    Args:
        providers:  Exactly N cloud providers.
        threshold:  Minimum number of shares (K) required to reconstruct.
    """

    def __init__(self, providers: builtins.list[CloudProvider], threshold: int = 2) -> None:
        if len(providers) < 2:
            raise ValueError("SecretSharingRAID requires at least 2 providers.")
        if threshold < 2 or threshold > len(providers):
            raise ValueError(f"Threshold must be between 2 and {len(providers)}.")
        self.providers = providers
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload(self, path: str, data: bytes) -> None:
        n = len(self.providers)
        k = self.threshold

        # Generate fresh DEK, encrypt data
        dek = os.urandom(_AES_KEY_LEN)
        nonce, ciphertext, tag = _encrypt(dek, data)

        # Split DEK byte-by-byte using Shamir
        dek_shares = _shamir_split(dek, n, k)

        # Store one blob per provider
        for i, provider in enumerate(self.providers):
            blob = _encode_blob(
                index=i + 1,
                n=n,
                k=k,
                nonce=nonce,
                ciphertext=ciphertext,
                tag=tag,
                dek_share=dek_shares[i],
            )
            provider.upload(_share_path(path, i + 1), blob)

    def download(self, path: str) -> bytes:
        k = self.threshold

        # Probe every provider for any share index it holds.
        # This preserves the "any K of N" guarantee regardless of provider order.
        collected: list[tuple[int, bytes]] = []
        meta: dict | None = None
        seen_indices: set[int] = set()

        for provider in self.providers:
            if len(collected) >= k:
                break
            # Try all possible share indices this provider might hold.
            for idx in range(1, len(self.providers) + 1):
                if idx in seen_indices:
                    continue
                try:
                    blob = provider.download(_share_path(path, idx))
                    info = _decode_blob(blob)
                    share_idx = info["index"]
                    if share_idx not in seen_indices:
                        collected.append((share_idx, info["dek_share"]))
                        seen_indices.add(share_idx)
                        if meta is None:
                            meta = info
                except (FileNotFoundError, ValueError):
                    pass

        if len(collected) < k:
            raise FileNotFoundError(
                f"Only {len(collected)}/{k} shares available for {path!r}; "
                f"cannot reconstruct."
            )

        # Reconstruct DEK
        dek = _shamir_reconstruct(collected)

        # Decrypt
        return _decrypt(dek, meta["nonce"], meta["ciphertext"], meta["tag"])  # type: ignore[index]

    def delete(self, path: str) -> None:
        found = False
        for i, provider in enumerate(self.providers):
            try:
                provider.delete(_share_path(path, i + 1))
                found = True
            except FileNotFoundError:
                pass
        if not found:
            raise FileNotFoundError(f"{path!r} not found on any provider")

    def list(self, prefix: str = "") -> builtins.list[str]:
        seen: set[str] = set()
        # Match any share index, not just share_1, so listings survive provider 0 being down.
        shares_marker = ".shares/share_"
        for provider in self.providers:
            try:
                for p in provider.list(prefix):
                    idx = p.find(shares_marker)
                    if idx != -1:
                        logical = p[:idx].rstrip("/.")
                        if logical:
                            seen.add(logical)
            except Exception:
                pass
        return sorted(seen)

    def exists(self, path: str) -> bool:
        count = 0
        for i, provider in enumerate(self.providers):
            try:
                provider.download(_share_path(path, i + 1))
                count += 1
                if count >= self.threshold:
                    return True
            except Exception:
                pass
        return False
