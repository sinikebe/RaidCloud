"""RAID-0 (Stripe) mode — split data across providers in fixed-size chunks.

Data is divided into N chunks (one per provider) and distributed in a
round-robin fashion.  All providers must be available for reads; the mode
trades fault-tolerance for speed and distributed storage utilisation.

On-disk layout::

    <path>.stripe/
        meta           — JSON: {"chunk_size": int, "n_chunks": int, "total_size": int}
        chunk_0        — bytes [0 : chunk_size]
        chunk_1        — bytes [chunk_size : 2*chunk_size]
        ...
"""

from __future__ import annotations

import json
import math
from typing import List

from raidcloud.providers.base import CloudProvider

_META_SUFFIX = ".stripe/meta"
_CHUNK_PATTERN = ".stripe/chunk_{i}"


class StripingRAID:
    """Distribute file data across providers in equal-sized chunks.

    Args:
        providers:  List of at least one provider (more = better parallelism).
        chunk_size: Maximum bytes per chunk (default 4 MiB).
    """

    def __init__(self, providers: List[CloudProvider], chunk_size: int = 4 * 1024 * 1024,
                 split_by_provider: bool = False) -> None:
        if not providers:
            raise ValueError("StripingRAID requires at least one provider.")
        self.providers = providers
        self.chunk_size = chunk_size
        self.split_by_provider = split_by_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upload(self, path: str, data: bytes) -> None:
        """Stripe *data* across providers and save the stripe metadata."""
        n = len(self.providers)
        chunk_size = max(1, math.ceil(len(data) / n)) if self.split_by_provider else self.chunk_size
        chunks = _split(data, chunk_size)
        n_chunks = len(chunks)

        # Write each chunk to its provider (round-robin)
        for i, chunk in enumerate(chunks):
            provider = self.providers[i % n]
            provider.upload(_chunk_path(path, i), chunk)

        # Write metadata to all providers for redundancy
        meta = json.dumps({
            "chunk_size": chunk_size,
            "n_chunks": n_chunks,
            "total_size": len(data),
            "n_providers": n,
        }).encode()
        for provider in self.providers:
            provider.upload(_meta_path(path), meta)

    def download(self, path: str) -> bytes:
        """Reassemble striped data from all providers."""
        # Read meta from any provider
        meta = self._read_meta(path)
        n_chunks: int = meta["n_chunks"]
        n_providers_meta: int = meta["n_providers"]
        if n_providers_meta != len(self.providers):
            raise RuntimeError(
                f"Provider count mismatch: file was uploaded with "
                f"{n_providers_meta} providers but {len(self.providers)} are "
                f"configured. Chunk routing would be incorrect."
            )
        n = len(self.providers)

        chunks: list[bytes] = []
        for i in range(n_chunks):
            provider = self.providers[i % n]
            chunk = provider.download(_chunk_path(path, i))
            chunks.append(chunk)

        return b"".join(chunks)

    def delete(self, path: str) -> None:
        """Delete all chunks and metadata for *path*."""
        meta = self._read_meta(path)
        n_chunks: int = meta["n_chunks"]
        n_providers_meta: int = meta["n_providers"]
        if n_providers_meta != len(self.providers):
            raise RuntimeError(
                f"Provider count mismatch: file was uploaded with "
                f"{n_providers_meta} providers but {len(self.providers)} are "
                f"configured. Chunk routing would be incorrect."
            )
        n = len(self.providers)

        for i in range(n_chunks):
            provider = self.providers[i % n]
            try:
                provider.delete(_chunk_path(path, i))
            except FileNotFoundError:
                pass

        for provider in self.providers:
            try:
                provider.delete(_meta_path(path))
            except FileNotFoundError:
                pass

    def list(self, prefix: str = "") -> List[str]:
        # Walk folder tree from root (or prefix sub-folder)
        seen: set[str] = set()
        marker = ".stripe/meta"
        for provider in self.providers:
            for p in provider.list(prefix):
                if p.endswith(marker):
                    logical = p[: -len(marker)].rstrip("/")
                    if logical:
                        seen.add(logical)
        return sorted(seen)

    def exists(self, path: str) -> bool:
        return self.providers[0].exists(_meta_path(path))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_meta(self, path: str) -> dict:
        last_exc: Exception = FileNotFoundError(f"Stripe meta not found for {path!r}")
        for provider in self.providers:
            try:
                raw = provider.download(_meta_path(path))
                return json.loads(raw)
            except FileNotFoundError as exc:
                last_exc = exc
        raise last_exc


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _split(data: bytes, chunk_size: int) -> list[bytes]:
    """Divide *data* into chunks of at most *chunk_size* bytes."""
    if not data:
        return [b""]
    n = math.ceil(len(data) / chunk_size)
    return [data[i * chunk_size:(i + 1) * chunk_size] for i in range(n)]


def _meta_path(path: str) -> str:
    return path.rstrip("/") + _META_SUFFIX


def _chunk_path(path: str, i: int) -> str:
    return path.rstrip("/") + _CHUNK_PATTERN.format(i=i)
