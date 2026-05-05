"""Windows virtual filesystem for RaidCloud.

Exposes a RaidCloud RAID backend as a virtual drive on Windows using either:

* **WinFsp** via ``pyfuse3`` (preferred — same code-path as Linux)
* **Dokan** via the ``dokan`` Python binding (fallback)

Usage::

    raidcloud mount R:

Requirements (choose one):
    - WinFsp  (https://winfsp.dev)  +  ``pip install pyfuse3``
    - Dokan   (https://dokan-dev.github.io)  +  ``pip install dokan``

This module tries WinFsp first, then Dokan, then raises ImportError.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def mount(raid_backend: Any, mountpoint: str, foreground: bool = True) -> None:
    """Mount *raid_backend* at *mountpoint* (a drive letter like ``R:``).

    Delegates to WinFsp (pyfuse3) if available, otherwise tries Dokan.

    Args:
        raid_backend: RaidCloud RAID backend (MirrorRAID, StripingRAID, etc.)
        mountpoint:   Drive letter string, e.g. ``"R:"`` or ``"R:\\"``
        foreground:   Block until unmounted when ``True``.
    """
    if sys.platform != "win32":
        raise RuntimeError("Windows mount is only available on Windows.")

    # Try WinFsp via pyfuse3 (which supports Windows when WinFsp is installed)
    try:
        from raidcloud.mount.linux import mount as _fuse_mount  # re-use FUSE impl
        _fuse_mount(raid_backend, mountpoint, foreground=foreground)
        return
    except ImportError:
        logger.debug("pyfuse3 not available, trying Dokan…")

    # Try Dokan
    try:
        _mount_dokan(raid_backend, mountpoint, foreground=foreground)
        return
    except ImportError:
        pass

    raise ImportError(
        "Windows filesystem mount requires either:\n"
        "  WinFsp (https://winfsp.dev) + pip install pyfuse3\n"
        "  or Dokan (https://dokan-dev.github.io) + pip install dokan"
    )


# ---------------------------------------------------------------------------
# Dokan backend
# ---------------------------------------------------------------------------

def _mount_dokan(backend: Any, mountpoint: str, foreground: bool = True) -> None:
    """Mount using the ``dokan`` Python binding."""
    try:
        import dokan  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("Dokan Python binding not installed: pip install dokan") from exc

    drive_letter = mountpoint.rstrip("\\:/") or "R"
    if len(drive_letter) != 1:
        raise ValueError(f"Invalid Windows drive letter: {mountpoint!r}")

    class _DokanOps(dokan.Operations):
        def CreateFile(self, path, access, share, disposition, options, info):
            info.Context = 1
            return dokan.DOKAN_SUCCESS

        def GetFileInformation(self, path, info):
            import pywintypes  # type: ignore[import-untyped]
            import win32con  # type: ignore[import-untyped]
            logical = _win_to_posix(path)
            if logical == "":
                # root directory
                return {
                    "FileAttributes": win32con.FILE_ATTRIBUTE_DIRECTORY,
                    "CreationTime": pywintypes.Time(0),
                    "LastAccessTime": pywintypes.Time(0),
                    "LastWriteTime": pywintypes.Time(0),
                    "FileSize": 0,
                }
            try:
                data = backend.download(logical)
                return {
                    "FileAttributes": win32con.FILE_ATTRIBUTE_NORMAL,
                    "CreationTime": pywintypes.Time(0),
                    "LastAccessTime": pywintypes.Time(0),
                    "LastWriteTime": pywintypes.Time(0),
                    "FileSize": len(data),
                }
            except FileNotFoundError:
                raise dokan.DokanError(dokan.ERROR_FILE_NOT_FOUND)

        def FindFiles(self, path, fill_find_data, info):
            import pywintypes  # type: ignore[import-untyped]
            import win32con  # type: ignore[import-untyped]
            logical = _win_to_posix(path)
            all_paths = backend.list(logical)
            prefix = (logical + "/") if logical else ""
            seen: set[str] = set()
            for p in all_paths:
                rest = p[len(prefix):]
                name = rest.split("/")[0]
                if name and name not in seen:
                    seen.add(name)
                    attrs = win32con.FILE_ATTRIBUTE_NORMAL
                    fill_find_data({
                        "FileName": name,
                        "FileAttributes": attrs,
                        "FileSize": 0,
                        "CreationTime": pywintypes.Time(0),
                        "LastAccessTime": pywintypes.Time(0),
                        "LastWriteTime": pywintypes.Time(0),
                    }, info)

        def ReadFile(self, path, buffer, bufferLength, offset, info):
            logical = _win_to_posix(path)
            try:
                data = backend.download(logical)
            except FileNotFoundError:
                raise dokan.DokanError(dokan.ERROR_FILE_NOT_FOUND)
            chunk = data[offset:offset + bufferLength]
            buffer[:len(chunk)] = chunk
            return len(chunk)

        def WriteFile(self, path, buffer, numberOfBytesToWrite, offset, info):
            logical = _win_to_posix(path)
            try:
                existing = backend.download(logical)
            except FileNotFoundError:
                existing = b""
            data = bytearray(existing)
            end = offset + numberOfBytesToWrite
            if len(data) < end:
                data.extend(b"\x00" * (end - len(data)))
            data[offset:end] = bytes(buffer[:numberOfBytesToWrite])
            backend.upload(logical, bytes(data))
            return numberOfBytesToWrite

        def DeleteFile(self, path, info):
            logical = _win_to_posix(path)
            try:
                backend.delete(logical)
            except FileNotFoundError:
                raise dokan.DokanError(dokan.ERROR_FILE_NOT_FOUND)

        def CreateDirectory(self, path, info):
            # Directories are virtual; nothing to persist
            pass

        def GetDiskFreeSpace(self, info):
            return {"FreeBytesAvailable": 10 * 1024**3, "TotalNumberOfBytes": 100 * 1024**3, "TotalNumberOfFreeBytes": 10 * 1024**3}

        def GetVolumeInformation(self, info):
            return {"VolumeName": "RaidCloud", "VolumeSerialNumber": 0x52434C44, "MaximumComponentLength": 255, "FileSystemFlags": 0, "FileSystemName": "RaidCloud"}

    def _win_to_posix(win_path: str) -> str:
        return win_path.replace("\\", "/").strip("/")

    dokan.mount(drive_letter + ":\\", _DokanOps(), foreground=foreground)
