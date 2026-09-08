"""Tests for the Windows mount dispatcher.

The Dokan backend itself needs the Windows-only ``dokan`` binding, so what is
covered here is the platform guard and the WinFsp -> Dokan -> error fallback
chain, which is where the user-facing behaviour lives.
"""

from __future__ import annotations

import sys

import pytest

from raidcloud.mount import windows
from raidcloud.raid.mirroring import MirrorRAID
from tests.helpers import MockProvider


@pytest.fixture
def backend() -> MirrorRAID:
    return MirrorRAID([MockProvider("p0")])


def test_mount_refuses_to_run_off_windows(backend, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="only available on Windows"):
        windows.mount(backend, "R:")


def test_mount_prefers_winfsp_via_pyfuse3(backend, monkeypatch):
    """On Windows the FUSE implementation is reused when WinFsp is present."""
    monkeypatch.setattr(sys, "platform", "win32")
    called: dict = {}

    def fake_fuse_mount(raid_backend, mountpoint, foreground=True):
        called["args"] = (raid_backend, mountpoint, foreground)

    monkeypatch.setattr("raidcloud.mount.linux.mount", fake_fuse_mount)

    windows.mount(backend, "R:", foreground=False)

    assert called["args"] == (backend, "R:", False)


def test_mount_falls_back_to_dokan_when_pyfuse3_missing(backend, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def no_pyfuse3(*args, **kwargs):
        raise ImportError("no pyfuse3")

    called: dict = {}

    def fake_dokan(raid_backend, mountpoint, foreground=True):
        called["args"] = (raid_backend, mountpoint, foreground)

    monkeypatch.setattr("raidcloud.mount.linux.mount", no_pyfuse3)
    monkeypatch.setattr(windows, "_mount_dokan", fake_dokan)

    windows.mount(backend, "R:")

    assert called["args"] == (backend, "R:", True)


def test_mount_reports_both_options_when_neither_is_installed(backend, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def missing(*args, **kwargs):
        raise ImportError("missing")

    monkeypatch.setattr("raidcloud.mount.linux.mount", missing)
    monkeypatch.setattr(windows, "_mount_dokan", missing)

    with pytest.raises(ImportError) as exc:
        windows.mount(backend, "R:")

    message = str(exc.value)
    assert "WinFsp" in message
    assert "Dokan" in message


def test_mount_dokan_reports_missing_binding(backend):
    """Without the dokan package the error must name the install command."""
    if "dokan" in sys.modules:  # pragma: no cover - not installable on Linux
        pytest.skip("dokan is installed")

    with pytest.raises(ImportError, match="pip install dokan"):
        windows._mount_dokan(backend, "R:")
