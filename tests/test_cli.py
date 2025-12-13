"""Tests for the CLI module."""

import pytest
from pathlib import Path
from raidcloud.cli import get_backend, sync_command, main
from raidcloud.google_drive import GoogleDriveBackend
from raidcloud.dropbox import DropboxBackend
from argparse import Namespace


def test_get_backend_google_drive():
    """Test getting Google Drive backend."""
    backend = get_backend("googledrive")
    assert isinstance(backend, GoogleDriveBackend)


def test_get_backend_google_drive_aliases():
    """Test Google Drive backend aliases."""
    assert isinstance(get_backend("google_drive"), GoogleDriveBackend)
    assert isinstance(get_backend("gdrive"), GoogleDriveBackend)
    assert isinstance(get_backend("GoogleDrive"), GoogleDriveBackend)


def test_get_backend_dropbox():
    """Test getting Dropbox backend."""
    backend = get_backend("dropbox")
    assert isinstance(backend, DropboxBackend)


def test_get_backend_dropbox_aliases():
    """Test Dropbox backend aliases."""
    assert isinstance(get_backend("Dropbox"), DropboxBackend)
    assert isinstance(get_backend("dbx"), DropboxBackend)


def test_get_backend_with_credentials():
    """Test getting backend with credentials."""
    credentials = {"api_key": "test_key"}
    backend = get_backend("googledrive", credentials)
    assert isinstance(backend, GoogleDriveBackend)
    assert backend.credentials == credentials


def test_get_backend_invalid():
    """Test getting invalid backend raises ValueError."""
    with pytest.raises(ValueError) as excinfo:
        get_backend("invalid_backend")
    assert "Unsupported backend" in str(excinfo.value)


def test_sync_command_success(tmp_path):
    """Test sync command with valid arguments."""
    args = Namespace(
        local_path=str(tmp_path),
        remote_path="/remote/path",
        backend="googledrive",
        verbose=False,
    )
    result = sync_command(args)
    assert result == 0


def test_sync_command_nonexistent_path(tmp_path):
    """Test sync command with nonexistent path."""
    nonexistent = tmp_path / "nonexistent"
    args = Namespace(
        local_path=str(nonexistent),
        remote_path="/remote/path",
        backend="googledrive",
        verbose=False,
    )
    result = sync_command(args)
    assert result == 1


def test_sync_command_invalid_backend(tmp_path):
    """Test sync command with invalid backend."""
    args = Namespace(
        local_path=str(tmp_path),
        remote_path="/remote/path",
        backend="invalid_backend",
        verbose=False,
    )
    result = sync_command(args)
    assert result == 1


def test_sync_command_file_not_directory(tmp_path):
    """Test sync command with file instead of directory."""
    file_path = tmp_path / "test_file.txt"
    file_path.write_text("test content")
    args = Namespace(
        local_path=str(file_path),
        remote_path="/remote/path",
        backend="googledrive",
        verbose=False,
    )
    result = sync_command(args)
    assert result == 1
