"""Abstract base class for cloud storage providers."""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod


class CloudProvider(ABC):
    """Minimal interface every cloud backend must implement.

    All path arguments use forward-slash notation and are relative to the
    provider's configured root (bucket, folder, etc.).
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def auth(self) -> None:
        """Authenticate / refresh credentials.

        Called once before the provider is used.  Implementations should
        raise :class:`RuntimeError` on failure.
        """

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    @abstractmethod
    def upload(self, path: str, data: bytes) -> None:
        """Upload *data* to *path* on the remote provider.

        Creates parent "directories" as needed.
        Overwrites any existing object at *path*.
        """

    @abstractmethod
    def download(self, path: str) -> bytes:
        """Return the raw bytes stored at *path*.

        Raises :class:`FileNotFoundError` if the object does not exist.
        """

    @abstractmethod
    def delete(self, path: str) -> None:
        """Delete the object at *path*.

        Raises :class:`FileNotFoundError` if the object does not exist.
        """

    @abstractmethod
    def list(self, prefix: str = "") -> builtins.list[str]:
        """Return all object paths that start with *prefix*.

        Paths are returned relative to the provider's root, using
        forward-slash separators.
        """

    # ------------------------------------------------------------------
    # Optional helpers (default implementations provided)
    # ------------------------------------------------------------------

    def exists(self, path: str) -> bool:
        """Return ``True`` if *path* exists on the provider."""
        try:
            self.download(path)
            return True
        except FileNotFoundError:
            return False

    @property
    def name(self) -> str:
        """Human-readable provider name (defaults to class name)."""
        return type(self).__name__
