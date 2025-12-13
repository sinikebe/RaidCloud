"""Tests for the Dropbox backend."""

import pytest
from pathlib import Path
from raidcloud.dropbox import DropboxBackend


@pytest.fixture
def backend():
    """Create a DropboxBackend instance for testing."""
    return DropboxBackend()


@pytest.fixture
def backend_with_credentials():
    """Create a DropboxBackend instance with credentials."""
    credentials = {"access_token": "test_token"}
    return DropboxBackend(credentials)


def test_dropbox_backend_instantiation(backend):
    """Test that DropboxBackend can be instantiated."""
    assert backend is not None


def test_dropbox_backend_with_credentials(backend_with_credentials):
    """Test that DropboxBackend can be instantiated with credentials."""
    assert backend_with_credentials.credentials == {"access_token": "test_token"}


def test_dropbox_backend_has_required_methods(backend):
    """Test that DropboxBackend has all required methods."""
    assert hasattr(backend, "sync")
    assert hasattr(backend, "upload_file")
    assert hasattr(backend, "list_files")
    assert hasattr(backend, "download_file")
    assert callable(backend.sync)
    assert callable(backend.upload_file)
    assert callable(backend.list_files)
    assert callable(backend.download_file)


def test_dropbox_list_files(backend):
    """Test that list_files returns an empty list (stub implementation)."""
    files = backend.list_files("/test/path")
    assert files == []


def test_dropbox_sync_nonexistent_path(backend, tmp_path):
    """Test that sync raises FileNotFoundError for nonexistent path."""
    nonexistent_path = tmp_path / "nonexistent"
    with pytest.raises(FileNotFoundError):
        backend.sync(nonexistent_path, "/remote/path")


def test_dropbox_sync_with_file_not_dir(backend, tmp_path):
    """Test that sync raises NotADirectoryError when path is a file."""
    file_path = tmp_path / "test_file.txt"
    file_path.write_text("test content")
    with pytest.raises(NotADirectoryError):
        backend.sync(file_path, "/remote/path")


def test_dropbox_sync_empty_directory(backend, tmp_path):
    """Test that sync works with an empty directory."""
    backend.sync(tmp_path, "/remote/path")
    # Should complete without errors


def test_dropbox_sync_with_files(backend, tmp_path):
    """Test that sync processes files in a directory."""
    # Create test files
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.txt").write_text("content2")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "file3.txt").write_text("content3")
    
    # Should complete without errors
    backend.sync(tmp_path, "/remote/path")


def test_dropbox_upload_nonexistent_file(backend, tmp_path):
    """Test that upload_file raises FileNotFoundError for nonexistent file."""
    nonexistent_file = tmp_path / "nonexistent.txt"
    with pytest.raises(FileNotFoundError):
        backend.upload_file(nonexistent_file, "/remote/path/file.txt")
