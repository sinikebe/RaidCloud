"""Unit tests for RAID-0 (striping) mode."""

import pytest

from raidcloud.raid.striping import StripingRAID, _split
from tests.helpers import MockProvider


def test_split_empty():
    assert _split(b"", 4) == [b""]


def test_split_exact_multiple():
    data = b"abcdefgh"
    chunks = _split(data, 4)
    assert chunks == [b"abcd", b"efgh"]


def test_split_uneven():
    data = b"abcde"
    chunks = _split(data, 4)
    assert chunks == [b"abcd", b"e"]


def test_upload_download_roundtrip_single_provider():
    p = MockProvider("p1")
    raid = StripingRAID([p], chunk_size=4)
    data = b"Hello, World!"
    raid.upload("test.txt", data)
    assert raid.download("test.txt") == data


def test_upload_download_roundtrip_two_providers():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = StripingRAID([p1, p2], chunk_size=4)
    data = b"0123456789abcdef"
    raid.upload("file.bin", data)
    assert raid.download("file.bin") == data


def test_chunks_spread_across_providers():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = StripingRAID([p1, p2], chunk_size=4)
    data = b"12345678"
    raid.upload("spread.bin", data)
    # chunk_0 should be on p1, chunk_1 on p2
    assert any("chunk_0" in k for k in p1.store)
    assert any("chunk_1" in k for k in p2.store)


def test_delete_removes_all_chunks():
    p1, p2 = MockProvider("p1"), MockProvider("p2")
    raid = StripingRAID([p1, p2], chunk_size=4)
    raid.upload("del.bin", b"abcdefgh")
    raid.delete("del.bin")
    assert not any("del.bin" in k for k in p1.store)
    assert not any("del.bin" in k for k in p2.store)


def test_list_returns_logical_paths():
    p = MockProvider("p1")
    raid = StripingRAID([p], chunk_size=4)
    raid.upload("dir/file.txt", b"data")
    result = raid.list()
    assert "dir/file.txt" in result


def test_requires_at_least_one_provider():
    with pytest.raises(ValueError):
        StripingRAID([])
