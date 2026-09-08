"""Provider-level tests.

These exercise the pure logic and the ``exists()`` fast paths with mocked
SDK clients — no network access and no cloud credentials are required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from raidcloud.providers.base import CloudProvider
from raidcloud.providers.s3 import S3Provider

# ---------------------------------------------------------------------------
# Base class contract
# ---------------------------------------------------------------------------


class _Minimal(CloudProvider):
    """Concrete provider implementing only the abstract surface."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def auth(self) -> None: ...

    def upload(self, path: str, data: bytes) -> None:
        self.store[path] = data

    def download(self, path: str) -> bytes:
        if path not in self.store:
            raise FileNotFoundError(path)
        return self.store[path]

    def delete(self, path: str) -> None:
        del self.store[path]

    def list(self, prefix: str = ""):
        return [p for p in self.store if p.startswith(prefix)]


def test_base_exists_uses_download_fallback():
    p = _Minimal()
    p.upload("a.txt", b"x")
    assert p.exists("a.txt") is True
    assert p.exists("missing.txt") is False


def test_base_name_defaults_to_class_name():
    assert _Minimal().name == "_Minimal"


def test_cloud_provider_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CloudProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# S3 key handling
# ---------------------------------------------------------------------------


def test_s3_prefix_is_normalised():
    assert S3Provider(bucket="b", prefix="raidcloud")._key("f.txt") == "raidcloud/f.txt"
    assert S3Provider(bucket="b", prefix="raidcloud/")._key("f.txt") == "raidcloud/f.txt"
    assert S3Provider(bucket="b", prefix="")._key("f.txt") == "f.txt"


def test_s3_key_strips_leading_slash():
    assert S3Provider(bucket="b", prefix="p/")._key("/a/b.txt") == "p/a/b.txt"


def test_s3_from_config_requires_bucket():
    with pytest.raises(ValueError, match="bucket"):
        S3Provider.from_config({})


def test_s3_from_config_reads_settings():
    provider = S3Provider.from_config(
        {"bucket": "my-bucket", "region": "eu-west-1", "prefix": "pre/"}
    )
    assert provider._bucket == "my-bucket"
    assert provider._region == "eu-west-1"
    assert provider._key("x") == "pre/x"


# ---------------------------------------------------------------------------
# S3 exists() must be a HEAD, never a GET
# ---------------------------------------------------------------------------


def _client_error(code: str):
    import botocore.exceptions

    return botocore.exceptions.ClientError({"Error": {"Code": code}}, "HeadObject")


def _s3_with_mock_client() -> tuple[S3Provider, MagicMock]:
    provider = S3Provider(bucket="b", prefix="p/")
    client = MagicMock()
    provider._s3 = client
    return provider, client


def test_s3_exists_true_uses_head_object():
    provider, client = _s3_with_mock_client()

    assert provider.exists("f.txt") is True

    client.head_object.assert_called_once_with(Bucket="b", Key="p/f.txt")
    client.get_object.assert_not_called()


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_s3_exists_false_on_missing_key(code):
    provider, client = _s3_with_mock_client()
    client.head_object.side_effect = _client_error(code)

    assert provider.exists("f.txt") is False
    client.get_object.assert_not_called()


def test_s3_exists_propagates_real_errors():
    """An auth or throttling failure must not be reported as 'does not exist'."""
    provider, client = _s3_with_mock_client()
    client.head_object.side_effect = _client_error("AccessDenied")

    with pytest.raises(Exception) as exc:
        provider.exists("f.txt")
    assert "AccessDenied" in str(exc.value)


def test_s3_download_maps_missing_key_to_filenotfound():
    provider, client = _s3_with_mock_client()
    import botocore.exceptions

    client.get_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "GetObject"
    )

    with pytest.raises(FileNotFoundError):
        provider.download("f.txt")


def test_s3_delete_raises_when_absent():
    provider, client = _s3_with_mock_client()
    client.head_object.side_effect = _client_error("404")

    with pytest.raises(FileNotFoundError):
        provider.delete("f.txt")
    client.delete_object.assert_not_called()


# ---------------------------------------------------------------------------
# Dropbox exists() must be a metadata lookup, never a download
# ---------------------------------------------------------------------------


def _dropbox_not_found_error():
    """Build the ApiError shape Dropbox raises for a missing path."""
    dropbox = pytest.importorskip("dropbox")
    err = MagicMock(spec=dropbox.exceptions.ApiError)
    err.error = MagicMock()
    err.error.is_path.return_value = True
    err.error.get_path.return_value.is_not_found.return_value = True
    # ApiError is what the provider catches, so raise a real instance.
    real = dropbox.exceptions.ApiError("req-id", err.error, "msg", "en")
    return real


def _dropbox_with_mock_client():
    from raidcloud.providers.dropbox import DropboxProvider

    provider = DropboxProvider(access_token="tok", root="/RaidCloud")
    client = MagicMock()
    provider._client = client
    return provider, client


def test_dropbox_full_path_joins_root():
    provider, _ = _dropbox_with_mock_client()
    assert provider._full("a/b.txt") == "/RaidCloud/a/b.txt"


def test_dropbox_exists_true_uses_metadata_lookup():
    pytest.importorskip("dropbox")
    provider, client = _dropbox_with_mock_client()

    assert provider.exists("f.txt") is True

    client.files_get_metadata.assert_called_once_with("/RaidCloud/f.txt")
    client.files_download.assert_not_called()


def test_dropbox_exists_false_when_path_missing():
    pytest.importorskip("dropbox")
    provider, client = _dropbox_with_mock_client()
    client.files_get_metadata.side_effect = _dropbox_not_found_error()

    assert provider.exists("f.txt") is False
    client.files_download.assert_not_called()


def test_dropbox_download_maps_missing_path_to_filenotfound():
    pytest.importorskip("dropbox")
    provider, client = _dropbox_with_mock_client()
    client.files_download.side_effect = _dropbox_not_found_error()

    with pytest.raises(FileNotFoundError):
        provider.download("f.txt")


def test_dropbox_auth_reports_missing_sdk(monkeypatch):
    """A clear install hint beats an ImportError traceback."""
    import builtins as _builtins

    from raidcloud.providers.dropbox import DropboxProvider

    real_import = _builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dropbox":
            raise ImportError("no dropbox")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(_builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="pip install dropbox"):
        DropboxProvider(access_token="t").auth()
