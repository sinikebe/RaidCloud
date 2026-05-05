"""Linux FUSE filesystem for RaidCloud.

Exposes a RaidCloud RAID backend as a FUSE filesystem using pyfuse3.
Mount with::

    raidcloud mount /mnt/raidcloud

Requires:
    - libfuse3-dev  (``apt install libfuse3-dev``)
    - pyfuse3       (``pip install pyfuse3``)

The filesystem keeps a simple flat namespace: files are stored as single
objects at their full path.  Directory entries are synthesised from the list
of known objects.

Inode table
-----------
Inodes are assigned lazily from a monotonically increasing counter.  A
bi-directional mapping between inode numbers and paths is kept in memory.
The root inode is always 1 (pyfuse3 convention).
"""

from __future__ import annotations

import errno
import logging
import os
import stat
import time
from typing import Any

logger = logging.getLogger(__name__)

_ROOT_INODE = 1


def mount(raid_backend: Any, mountpoint: str, foreground: bool = True) -> None:
    """Mount *raid_backend* at *mountpoint* using FUSE.

    Args:
        raid_backend: Any object with ``upload``, ``download``, ``delete``,
                      ``list``, and ``exists`` methods (MirrorRAID, StripingRAID,
                      SecretSharingRAID, or a plain CloudProvider).
        mountpoint:   Path to an existing directory on the local filesystem.
        foreground:   If ``True`` (default) block until the filesystem is
                      unmounted.  Set to ``False`` to daemonise (not yet
                      implemented).
    """
    try:
        import pyfuse3  # type: ignore[import-untyped]
        import trio  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "FUSE mount requires: pip install pyfuse3 trio\n"
            "and system package libfuse3-dev"
        ) from exc

    # Defined here so pyfuse3.Operations is available as a base class.
    class _RaidCloudFS(pyfuse3.Operations):  # type: ignore[misc]
        """pyfuse3 filesystem implementation backed by a RaidCloud RAID layer."""

        def __init__(self, backend: Any) -> None:
            super().__init__()
            self._backend = backend
            self._inode_to_path: dict[int, str] = {_ROOT_INODE: ""}
            self._path_to_inode: dict[str, int] = {"": _ROOT_INODE}
            self._next_inode = _ROOT_INODE + 1
            self._handles: dict[int, dict] = {}
            self._next_fh: int = 1
            self._timestamps: dict[int, int] = {}

        def _get_inode(self, path: str) -> int:
            if path not in self._path_to_inode:
                ino = self._next_inode
                self._next_inode += 1
                self._inode_to_path[ino] = path
                self._path_to_inode[path] = ino
            return self._path_to_inode[path]

        def _inode_path(self, inode: int) -> str:
            if inode not in self._inode_to_path:
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT))
            return self._inode_to_path[inode]

        def _is_dir(self, path: str) -> bool:
            if not path:
                return True
            prefix = path.rstrip("/") + "/"
            return any(p.startswith(prefix) for p in self._backend.list(path))

        async def getattr(self, inode: int, ctx=None):
            path = self._inode_path(inode)
            entry = pyfuse3.EntryAttributes()
            now_ns = int(time.time() * 1e9)

            if inode == _ROOT_INODE or self._is_dir(path):
                entry.st_mode = stat.S_IFDIR | 0o755
                entry.st_size = 0
            else:
                try:
                    data = self._backend.download(path)
                    entry.st_mode = stat.S_IFREG | 0o644
                    entry.st_size = len(data)
                except FileNotFoundError:
                    raise pyfuse3.FUSEError(errno.ENOENT)

            ts = self._timestamps.get(inode, now_ns)
            entry.st_ino = inode
            entry.st_nlink = 1
            entry.st_uid = os.getuid()
            entry.st_gid = os.getgid()
            entry.st_atime_ns = ts
            entry.st_mtime_ns = ts
            entry.st_ctime_ns = ts
            return entry

        async def setattr(self, inode: int, attr, fields, fh, ctx=None):
            # Accept timestamp and size updates; ignore permission/owner changes.
            if fields.update_atime or fields.update_mtime:
                ts = attr.st_mtime_ns if fields.update_mtime else int(time.time() * 1e9)
                self._timestamps[inode] = ts
            if fields.update_size:
                path = self._inode_path(inode)
                try:
                    data = self._backend.download(path)
                except FileNotFoundError:
                    data = b""
                new_size = attr.st_size
                if new_size < len(data):
                    data = data[:new_size]
                else:
                    data = data + b"\x00" * (new_size - len(data))
                self._backend.upload(path, data)
            return await self.getattr(inode)

        async def lookup(self, parent_inode: int, name: bytes, ctx=None):
            parent_path = self._inode_path(parent_inode)
            child_name = name.decode("utf-8")
            child_path = f"{parent_path}/{child_name}".lstrip("/")
            if self._is_dir(child_path) or self._backend.exists(child_path):
                inode = self._get_inode(child_path)
                return await self.getattr(inode)
            raise pyfuse3.FUSEError(errno.ENOENT)

        async def opendir(self, inode: int, ctx=None):
            return inode

        async def readdir(self, fh: int, start_id: int, token):
            path = self._inode_path(fh)
            prefix = path + "/" if path else ""
            all_paths = self._backend.list(path)
            children: dict[str, bool] = {}
            for p in all_paths:
                if p.startswith(prefix):
                    rest = p[len(prefix):]
                    if not rest:
                        continue
                    parts = rest.split("/", 1)
                    child_name = parts[0]
                    is_dir = len(parts) > 1
                    if child_name not in children:
                        children[child_name] = is_dir
                    elif is_dir:
                        children[child_name] = True
            entries = list(children.items())
            for idx, (child_name, _) in enumerate(entries):
                if idx < start_id:
                    continue
                child_path = f"{prefix}{child_name}".lstrip("/")
                inode = self._get_inode(child_path)
                attr = await self.getattr(inode)
                if not pyfuse3.readdir_reply(token, child_name.encode(), attr, idx + 1):
                    break

        async def open(self, inode: int, flags: int, ctx=None):
            path = self._inode_path(inode)
            writable = bool(flags & (os.O_WRONLY | os.O_RDWR))
            truncate = bool(flags & os.O_TRUNC)
            fh = self._next_fh
            self._next_fh += 1
            buf: bytearray
            if writable and not truncate:
                try:
                    buf = bytearray(self._backend.download(path))
                except FileNotFoundError:
                    buf = bytearray()
            else:
                buf = bytearray()
            self._handles[fh] = {"path": path, "writable": writable, "dirty": truncate, "buf": buf}
            return pyfuse3.FileInfo(fh=fh)

        async def read(self, fh: int, off: int, size: int) -> bytes:
            path = self._handles[fh]["path"]
            try:
                data = self._backend.download(path)
            except FileNotFoundError:
                raise pyfuse3.FUSEError(errno.ENOENT)
            return data[off:off + size]

        async def write(self, fh: int, off: int, buf: bytes) -> int:
            handle = self._handles[fh]
            current = handle["buf"]
            end = off + len(buf)
            if len(current) < end:
                current.extend(b"\x00" * (end - len(current)))
            current[off:end] = buf
            handle["dirty"] = True
            return len(buf)

        async def release(self, fh: int) -> None:
            handle = self._handles.pop(fh, None)
            if handle and handle["writable"] and handle.get("dirty"):
                self._backend.upload(handle["path"], bytes(handle["buf"]))

        async def create(self, parent_inode: int, name: bytes, mode: int, flags: int, ctx=None):
            parent_path = self._inode_path(parent_inode)
            child_name = name.decode("utf-8")
            child_path = f"{parent_path}/{child_name}".lstrip("/")
            inode = self._get_inode(child_path)
            self._backend.upload(child_path, b"")
            fh = self._next_fh
            self._next_fh += 1
            self._handles[fh] = {"path": child_path, "writable": True, "dirty": False, "buf": bytearray()}
            attr = await self.getattr(inode)
            return pyfuse3.FileInfo(fh=fh), attr

        async def unlink(self, parent_inode: int, name: bytes, ctx=None) -> None:
            parent_path = self._inode_path(parent_inode)
            child_path = f"{parent_path}/{name.decode()}".lstrip("/")
            try:
                self._backend.delete(child_path)
            except FileNotFoundError:
                raise pyfuse3.FUSEError(errno.ENOENT)
            inode = self._path_to_inode.pop(child_path, None)
            if inode:
                self._inode_to_path.pop(inode, None)

        async def mkdir(self, parent_inode: int, name: bytes, mode: int, ctx=None):
            parent_path = self._inode_path(parent_inode)
            child_path = f"{parent_path}/{name.decode()}".lstrip("/")
            inode = self._get_inode(child_path)
            return await self.getattr(inode)

        async def rmdir(self, parent_inode: int, name: bytes, ctx=None) -> None:
            parent_path = self._inode_path(parent_inode)
            child_path = f"{parent_path}/{name.decode()}".lstrip("/")
            if self._backend.list(child_path):
                raise pyfuse3.FUSEError(errno.ENOTEMPTY)
            inode = self._path_to_inode.pop(child_path, None)
            if inode:
                self._inode_to_path.pop(inode, None)

        async def rename(self, old_parent_inode: int, old_name: bytes,
                         new_parent_inode: int, new_name: bytes,
                         flags: int, ctx=None) -> None:
            old_parent = self._inode_path(old_parent_inode)
            new_parent = self._inode_path(new_parent_inode)
            old_path = f"{old_parent}/{old_name.decode()}".lstrip("/")
            new_path = f"{new_parent}/{new_name.decode()}".lstrip("/")

            try:
                data = self._backend.download(old_path)
            except FileNotFoundError:
                raise pyfuse3.FUSEError(errno.ENOENT)

            self._backend.upload(new_path, data)
            self._backend.delete(old_path)

            # Update inode mappings
            inode = self._path_to_inode.pop(old_path, None)
            if inode is not None:
                self._inode_to_path[inode] = new_path
                self._path_to_inode[new_path] = inode

    fs = _RaidCloudFS(raid_backend)
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add("fsname=raidcloud")
    if not foreground:
        fuse_options.add("allow_other")

    pyfuse3.init(fs, mountpoint, fuse_options)
    try:
        trio.run(pyfuse3.main)
    finally:
        pyfuse3.close(unmount=True)
