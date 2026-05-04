"""RAID-1 (Mirror) mode — replicate every write across all providers.

All providers receive identical copies of every object.  Reads are served
from the first responsive provider, providing high availability even when
one or more backends are unavailable.
"""

from __future__ import annotations

import logging
from typing import List

from raidcloud.providers.base import CloudProvider

logger = logging.getLogger(__name__)


class MirrorRAID:
    """Write to every provider; read from the first available one.

    Args:
        providers: List of at least one :class:`~raidcloud.providers.base.CloudProvider`.
    """

    def __init__(self, providers: List[CloudProvider]) -> None:
        if not providers:
            raise ValueError("MirrorRAID requires at least one provider.")
        self.providers = providers

    # ------------------------------------------------------------------
    # Public API (mirrors the CloudProvider interface)
    # ------------------------------------------------------------------

    def upload(self, path: str, data: bytes) -> None:
        """Upload *data* to *path* on **all** providers.

        Raises the last exception encountered if all providers fail.
        """
        errors: list[Exception] = []
        for provider in self.providers:
            try:
                provider.upload(path, data)
                logger.debug("Mirrored %s → %s", path, provider.name)
            except Exception as exc:
                logger.warning("Upload to %s failed: %s", provider.name, exc)
                errors.append(exc)

        if len(errors) == len(self.providers):
            raise errors[-1]

    def download(self, path: str) -> bytes:
        """Download *path* from the first available provider.

        Tries each provider in order; raises :class:`FileNotFoundError` only
        when every provider raises it.  Other exceptions are logged and skipped.
        """
        last_exc: Exception = FileNotFoundError(f"No provider could serve {path!r}")
        for provider in self.providers:
            try:
                data = provider.download(path)
                logger.debug("Downloaded %s from %s", path, provider.name)
                return data
            except FileNotFoundError as exc:
                last_exc = exc
            except Exception as exc:
                logger.warning("Download from %s failed: %s", provider.name, exc)
                last_exc = exc
        raise last_exc

    def delete(self, path: str) -> None:
        """Delete *path* from all providers.

        Logs failures but does not re-raise so that a partial deletion
        doesn't leave the virtual filesystem in an inconsistent state.
        """
        found_on_any = False
        for provider in self.providers:
            try:
                provider.delete(path)
                found_on_any = True
            except FileNotFoundError:
                pass
            except Exception as exc:
                logger.warning("Delete from %s failed: %s", provider.name, exc)

        if not found_on_any:
            raise FileNotFoundError(f"{path!r} not found on any provider")

    def list(self, prefix: str = "") -> List[str]:
        """Return the union of paths from all providers matching *prefix*."""
        seen: set[str] = set()
        for provider in self.providers:
            try:
                for p in provider.list(prefix):
                    seen.add(p)
            except Exception as exc:
                logger.warning("List from %s failed: %s", provider.name, exc)
        return sorted(seen)

    def exists(self, path: str) -> bool:
        """Return ``True`` if *path* exists on at least one provider."""
        for provider in self.providers:
            try:
                if provider.exists(path):
                    return True
            except Exception:
                pass
        return False
