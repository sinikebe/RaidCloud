"""Shared test helpers — mock CloudProvider implementation."""

from __future__ import annotations

import builtins

from raidcloud.providers.base import CloudProvider


class MockProvider(CloudProvider):
    """In-memory provider for unit tests."""

    def __init__(self, provider_name: str = "mock", fail_upload: bool = False) -> None:
        self._name = provider_name
        self.store: dict[str, bytes] = {}
        self._fail_upload = fail_upload
        self._authed = False

    def auth(self) -> None:
        self._authed = True

    def upload(self, path: str, data: bytes) -> None:
        if self._fail_upload:
            raise RuntimeError(f"MockProvider {self._name}: upload deliberately failed")
        self.store[path] = data

    def download(self, path: str) -> bytes:
        if path not in self.store:
            raise FileNotFoundError(f"MockProvider {self._name}: {path!r} not found")
        return self.store[path]

    def delete(self, path: str) -> None:
        if path not in self.store:
            raise FileNotFoundError(f"MockProvider {self._name}: {path!r} not found")
        del self.store[path]

    def list(self, prefix: str = "") -> builtins.list[str]:
        return [p for p in self.store if p.startswith(prefix)]

    @property
    def name(self) -> str:
        return self._name
