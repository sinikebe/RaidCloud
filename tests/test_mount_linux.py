"""Tests for the Linux FUSE filesystem.

These drive the real ``pyfuse3.Operations`` subclass — no mount point is
created.  The whole module is skipped where pyfuse3 is not installed, since
it is an optional dependency (extra ``fuse``).
"""

from __future__ import annotations

import asyncio
import errno
import os
import stat

import pytest

pyfuse3 = pytest.importorskip("pyfuse3", reason="requires the 'fuse' extra")

from raidcloud.mount import linux  # noqa: E402
from raidcloud.raid.mirroring import MirrorRAID  # noqa: E402
from tests.helpers import MockProvider  # noqa: E402


def run(coro):
    """Drive one filesystem coroutine to completion."""
    return asyncio.run(coro)


@pytest.fixture
def fs():
    backend = MirrorRAID([MockProvider("p0"), MockProvider("p1")])
    return linux.create_filesystem(backend)


@pytest.fixture
def backend(fs):
    return fs._backend


ROOT = linux._ROOT_INODE


# ---------------------------------------------------------------------------
# Inode bookkeeping
# ---------------------------------------------------------------------------


def test_root_inode_maps_to_empty_path(fs):
    assert fs._inode_path(ROOT) == ""


def test_inodes_are_stable_and_unique(fs):
    a1 = fs._get_inode("a.txt")
    a2 = fs._get_inode("a.txt")
    b = fs._get_inode("b.txt")

    assert a1 == a2
    assert a1 != b
    assert fs._inode_path(a1) == "a.txt"


def test_unknown_inode_raises(fs):
    with pytest.raises(FileNotFoundError):
        fs._inode_path(99999)


# ---------------------------------------------------------------------------
# getattr / setattr
# ---------------------------------------------------------------------------


def test_getattr_root_is_a_directory(fs):
    attr = run(fs.getattr(ROOT))
    assert stat.S_ISDIR(attr.st_mode)


def test_getattr_reports_file_size(fs, backend):
    backend.upload("f.txt", b"hello world")
    inode = fs._get_inode("f.txt")

    attr = run(fs.getattr(inode))

    assert stat.S_ISREG(attr.st_mode)
    assert attr.st_size == 11
    assert attr.st_ino == inode


def test_getattr_missing_file_raises_enoent(fs):
    inode = fs._get_inode("absent.txt")
    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.getattr(inode))
    assert exc.value.errno == errno.ENOENT


def test_getattr_synthesises_directories_from_paths(fs, backend):
    backend.upload("dir/child.txt", b"x")
    inode = fs._get_inode("dir")

    attr = run(fs.getattr(inode))

    assert stat.S_ISDIR(attr.st_mode)


def test_setattr_truncates_file(fs, backend):
    backend.upload("f.txt", b"0123456789")
    inode = fs._get_inode("f.txt")

    attr = pyfuse3.EntryAttributes()
    attr.st_size = 4
    fields = _Fields(update_size=True)

    run(fs.setattr(inode, attr, fields, None))

    assert backend.download("f.txt") == b"0123"


def test_setattr_extends_file_with_zeros(fs, backend):
    backend.upload("f.txt", b"ab")
    inode = fs._get_inode("f.txt")

    attr = pyfuse3.EntryAttributes()
    attr.st_size = 5
    run(fs.setattr(inode, attr, _Fields(update_size=True), None))

    assert backend.download("f.txt") == b"ab\x00\x00\x00"


class _Fields:
    """Stand-in for pyfuse3's SetattrFields."""

    def __init__(self, update_size=False, update_atime=False, update_mtime=False):
        self.update_size = update_size
        self.update_atime = update_atime
        self.update_mtime = update_mtime


# ---------------------------------------------------------------------------
# lookup / readdir
# ---------------------------------------------------------------------------


def test_lookup_finds_existing_file(fs, backend):
    backend.upload("f.txt", b"data")
    attr = run(fs.lookup(ROOT, b"f.txt"))
    assert attr.st_size == 4


def test_lookup_missing_name_raises_enoent(fs):
    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.lookup(ROOT, b"absent.txt"))
    assert exc.value.errno == errno.ENOENT


def test_readdir_lists_children_once(fs, backend, monkeypatch):
    backend.upload("a.txt", b"a")
    backend.upload("b.txt", b"b")
    backend.upload("sub/c.txt", b"c")

    seen: list[str] = []
    monkeypatch.setattr(
        pyfuse3, "readdir_reply",
        lambda token, name, attr, next_id: (seen.append(name.decode()), True)[1],
    )

    run(fs.readdir(ROOT, 0, token=None))

    # 'sub' appears once as a directory, not once per file underneath it.
    assert sorted(seen) == ["a.txt", "b.txt", "sub"]


def test_readdir_honours_start_id(fs, backend, monkeypatch):
    for name in ("a.txt", "b.txt", "c.txt"):
        backend.upload(name, b"x")

    seen: list[str] = []
    monkeypatch.setattr(
        pyfuse3, "readdir_reply",
        lambda token, name, attr, next_id: (seen.append(name.decode()), True)[1],
    )

    run(fs.readdir(ROOT, 2, token=None))

    assert len(seen) == 1


def test_readdir_stops_when_buffer_is_full(fs, backend, monkeypatch):
    for name in ("a.txt", "b.txt", "c.txt"):
        backend.upload(name, b"x")

    seen: list[str] = []

    def full_after_one(token, name, attr, next_id):
        seen.append(name.decode())
        return False  # buffer full

    monkeypatch.setattr(pyfuse3, "readdir_reply", full_after_one)
    run(fs.readdir(ROOT, 0, token=None))

    assert len(seen) == 1


# ---------------------------------------------------------------------------
# open / read / write / release
# ---------------------------------------------------------------------------


def test_open_readonly_does_not_prefetch(fs, backend):
    backend.upload("f.txt", b"contents")
    inode = fs._get_inode("f.txt")

    info = run(fs.open(inode, os.O_RDONLY))

    handle = fs._handles[info.fh]
    assert handle["writable"] is False
    assert handle["buf"] == bytearray()


def test_open_for_write_loads_existing_content(fs, backend):
    backend.upload("f.txt", b"existing")
    inode = fs._get_inode("f.txt")

    info = run(fs.open(inode, os.O_RDWR))

    assert fs._handles[info.fh]["buf"] == bytearray(b"existing")


def test_open_with_o_trunc_discards_content_and_marks_dirty(fs, backend):
    """Regression: `truncate` was referenced here but never assigned."""
    backend.upload("f.txt", b"existing")
    inode = fs._get_inode("f.txt")

    info = run(fs.open(inode, os.O_WRONLY | os.O_TRUNC))

    handle = fs._handles[info.fh]
    assert handle["buf"] == bytearray()
    # dirty must be set so closing without a write still persists the truncation.
    assert handle["dirty"] is True

    run(fs.release(info.fh))
    assert backend.download("f.txt") == b""


def test_open_missing_file_for_write_starts_empty(fs):
    inode = fs._get_inode("new.txt")
    info = run(fs.open(inode, os.O_WRONLY))
    assert fs._handles[info.fh]["buf"] == bytearray()


def test_read_returns_requested_slice(fs, backend):
    backend.upload("f.txt", b"0123456789")
    inode = fs._get_inode("f.txt")
    info = run(fs.open(inode, os.O_RDONLY))

    assert run(fs.read(info.fh, 2, 4)) == b"2345"


def test_read_missing_file_raises_enoent(fs):
    inode = fs._get_inode("gone.txt")
    info = run(fs.open(inode, os.O_RDONLY))

    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.read(info.fh, 0, 10))
    assert exc.value.errno == errno.ENOENT


def test_write_then_release_persists(fs, backend):
    inode = fs._get_inode("new.txt")
    info = run(fs.open(inode, os.O_WRONLY))

    assert run(fs.write(info.fh, 0, b"hello")) == 5
    run(fs.release(info.fh))

    assert backend.download("new.txt") == b"hello"


def test_write_at_offset_zero_fills_the_gap(fs, backend):
    inode = fs._get_inode("sparse.txt")
    info = run(fs.open(inode, os.O_WRONLY))

    run(fs.write(info.fh, 3, b"XY"))
    run(fs.release(info.fh))

    assert backend.download("sparse.txt") == b"\x00\x00\x00XY"


def test_release_of_clean_readonly_handle_writes_nothing(fs, backend):
    backend.upload("f.txt", b"original")
    inode = fs._get_inode("f.txt")
    info = run(fs.open(inode, os.O_RDONLY))

    run(fs.release(info.fh))

    assert backend.download("f.txt") == b"original"
    assert info.fh not in fs._handles


# ---------------------------------------------------------------------------
# create / unlink / mkdir / rmdir / rename
# ---------------------------------------------------------------------------


def test_create_makes_an_empty_file(fs, backend):
    info, attr = run(fs.create(ROOT, b"new.txt", 0o644, os.O_WRONLY))

    assert backend.download("new.txt") == b""
    assert attr.st_size == 0
    assert fs._handles[info.fh]["path"] == "new.txt"


def test_unlink_removes_file_and_forgets_inode(fs, backend):
    backend.upload("f.txt", b"x")
    inode = fs._get_inode("f.txt")

    run(fs.unlink(ROOT, b"f.txt"))

    assert not backend.exists("f.txt")
    assert inode not in fs._inode_to_path


def test_unlink_missing_file_raises_enoent(fs):
    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.unlink(ROOT, b"absent.txt"))
    assert exc.value.errno == errno.ENOENT


def test_mkdir_returns_a_directory_attr(fs):
    attr = run(fs.mkdir(ROOT, b"newdir", 0o755))
    assert stat.S_ISDIR(attr.st_mode)


def test_rmdir_refuses_non_empty_directory(fs, backend):
    backend.upload("dir/child.txt", b"x")

    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.rmdir(ROOT, b"dir"))
    assert exc.value.errno == errno.ENOTEMPTY


def test_rmdir_removes_empty_directory(fs):
    inode = fs._get_inode("emptydir")
    run(fs.rmdir(ROOT, b"emptydir"))
    assert inode not in fs._inode_to_path


def test_rename_moves_content_and_remaps_inode(fs, backend):
    backend.upload("old.txt", b"payload")
    inode = fs._get_inode("old.txt")

    run(fs.rename(ROOT, b"old.txt", ROOT, b"new.txt", 0))

    assert backend.download("new.txt") == b"payload"
    assert not backend.exists("old.txt")
    assert fs._inode_to_path[inode] == "new.txt"
    assert fs._path_to_inode["new.txt"] == inode


def test_rename_missing_source_raises_enoent(fs):
    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.rename(ROOT, b"absent.txt", ROOT, b"new.txt", 0))
    assert exc.value.errno == errno.ENOENT


def test_mkdir_then_lookup_and_readdir_see_the_new_directory(fs, monkeypatch):
    """Regression: an empty directory has no objects, so it must be tracked."""
    run(fs.mkdir(ROOT, b"fresh", 0o755))

    # lookup must find it...
    attr = run(fs.lookup(ROOT, b"fresh"))
    assert stat.S_ISDIR(attr.st_mode)

    # ...and it must appear in the parent listing.
    seen: list[str] = []
    monkeypatch.setattr(
        pyfuse3, "readdir_reply",
        lambda token, name, attr_, next_id: (seen.append(name.decode()), True)[1],
    )
    run(fs.readdir(ROOT, 0, token=None))
    assert "fresh" in seen


def test_mkdir_then_write_into_it(fs, backend):
    run(fs.mkdir(ROOT, b"d", 0o755))
    d_inode = fs._get_inode("d")

    info, _ = run(fs.create(d_inode, b"f.txt", 0o644, os.O_WRONLY))
    run(fs.write(info.fh, 0, b"inside"))
    run(fs.release(info.fh))

    assert backend.download("d/f.txt") == b"inside"


def test_rmdir_then_lookup_fails(fs):
    run(fs.mkdir(ROOT, b"tmp", 0o755))
    run(fs.rmdir(ROOT, b"tmp"))

    with pytest.raises(pyfuse3.FUSEError) as exc:
        run(fs.lookup(ROOT, b"tmp"))
    assert exc.value.errno == errno.ENOENT


def test_nested_explicit_dir_not_listed_at_root(fs, monkeypatch):
    """A directory two levels down must not leak into the root listing."""
    run(fs.mkdir(ROOT, b"a", 0o755))
    a_inode = fs._get_inode("a")
    run(fs.mkdir(a_inode, b"b", 0o755))

    seen: list[str] = []
    monkeypatch.setattr(
        pyfuse3, "readdir_reply",
        lambda token, name, attr_, next_id: (seen.append(name.decode()), True)[1],
    )
    run(fs.readdir(ROOT, 0, token=None))

    assert "a" in seen
    assert "b" not in seen
