"""Tests for the StorageBackend interface."""

import pytest
from pathlib import Path
from raidcloud.storage_backend import StorageBackend


class ConcreteBackend(StorageBackend):
    """Concrete implementation for testing purposes."""

    def __init__(self, credentials=None):
        self.credentials = credentials

    def sync(self, local_path: Path, remote_path: str) -> None:
        pass

    def upload_file(self, local_file: Path, remote_path: str) -> None:
        pass

    def list_files(self, remote_path: str):
        return []

    def download_file(self, remote_path: str, local_file: Path) -> None:
        pass


def test_storage_backend_instantiation():
    """Test that StorageBackend can be instantiated through concrete class."""
    backend = ConcreteBackend()
    assert backend is not None


def test_storage_backend_with_credentials():
    """Test that StorageBackend can be instantiated with credentials."""
    credentials = {"api_key": "test_key"}
    backend = ConcreteBackend(credentials)
    assert backend.credentials == credentials


def test_storage_backend_has_required_methods():
    """Test that StorageBackend has all required abstract methods."""
    backend = ConcreteBackend()
    assert hasattr(backend, "sync")
    assert hasattr(backend, "upload_file")
    assert hasattr(backend, "list_files")
    assert hasattr(backend, "download_file")
    assert callable(backend.sync)
    assert callable(backend.upload_file)
    assert callable(backend.list_files)
    assert callable(backend.download_file)
