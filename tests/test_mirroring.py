"""Unit tests for RAID-1 (mirror) mode."""

import pytest

from raidcloud.raid.mirroring import MirrorRAID
from tests.helpers import MockProvider


def _make_raid(*providers):
    return MirrorRAID(list(providers))


def test_upload_writes_to_all_providers():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = _make_raid(p1, p2)
    raid.upload("foo/bar.txt", b"hello")
    assert p1.store["foo/bar.txt"] == b"hello"
    assert p2.store["foo/bar.txt"] == b"hello"


def test_download_returns_from_first_available():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    p1.store["a.txt"] = b"data"
    p2.store["a.txt"] = b"data"
    raid = _make_raid(p1, p2)
    assert raid.download("a.txt") == b"data"


def test_download_falls_back_when_first_unavailable():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    # p1 does not have the file, p2 does
    p2.store["a.txt"] = b"fallback"
    raid = _make_raid(p1, p2)
    assert raid.download("a.txt") == b"fallback"


def test_download_raises_when_no_provider_has_file():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = _make_raid(p1, p2)
    with pytest.raises(FileNotFoundError):
        raid.download("missing.txt")


def test_delete_removes_from_all():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    p1.store["x.txt"] = b"x"
    p2.store["x.txt"] = b"x"
    raid = _make_raid(p1, p2)
    raid.delete("x.txt")
    assert "x.txt" not in p1.store
    assert "x.txt" not in p2.store


def test_delete_raises_when_missing_everywhere():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = _make_raid(p1, p2)
    with pytest.raises(FileNotFoundError):
        raid.delete("nope.txt")


def test_list_returns_union():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    p1.store["a.txt"] = b""
    p2.store["b.txt"] = b""
    raid = _make_raid(p1, p2)
    result = raid.list()
    assert sorted(result) == ["a.txt", "b.txt"]


def test_upload_raises_when_all_providers_fail():
    p1 = MockProvider("p1", fail_upload=True)
    p2 = MockProvider("p2", fail_upload=True)
    raid = _make_raid(p1, p2)
    with pytest.raises(RuntimeError, match="upload deliberately failed"):
        raid.upload("f.txt", b"data")


def test_requires_at_least_one_provider():
    with pytest.raises(ValueError):
        MirrorRAID([])
