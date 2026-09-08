"""Unit tests for the provider / RAID backend factory."""

from __future__ import annotations

import pytest

from raidcloud import factory
from raidcloud.raid.mirroring import MirrorRAID
from raidcloud.raid.secret_sharing import SecretSharingRAID
from raidcloud.raid.striping import StripingRAID
from tests.helpers import MockProvider

# ---------------------------------------------------------------------------
# build_raid_backend
# ---------------------------------------------------------------------------


def _providers(n: int = 3) -> list[MockProvider]:
    return [MockProvider(f"p{i}") for i in range(n)]


@pytest.mark.parametrize("mode", ["mirror", "MIRROR", "Mirror"])
def test_mirror_mode_is_case_insensitive(mode):
    backend = factory.build_raid_backend({"raid_mode": mode}, _providers())
    assert isinstance(backend, MirrorRAID)


@pytest.mark.parametrize("mode", ["stripe", "striping", "raid0"])
def test_stripe_aliases(mode):
    backend = factory.build_raid_backend({"raid_mode": mode}, _providers())
    assert isinstance(backend, StripingRAID)
    assert backend.split_by_provider is False


@pytest.mark.parametrize("mode", ["split", "split_stripe"])
def test_split_aliases_produce_one_part_per_provider(mode):
    backend = factory.build_raid_backend({"raid_mode": mode}, _providers())
    assert isinstance(backend, StripingRAID)
    assert backend.split_by_provider is True


@pytest.mark.parametrize("mode", ["secret_sharing", "secretsharing", "confidential"])
def test_secret_sharing_aliases(mode):
    backend = factory.build_raid_backend({"raid_mode": mode}, _providers())
    assert isinstance(backend, SecretSharingRAID)


def test_default_mode_is_mirror():
    assert isinstance(factory.build_raid_backend({}, _providers()), MirrorRAID)


def test_chunk_size_is_passed_through():
    backend = factory.build_raid_backend({"raid_mode": "stripe", "chunk_size": 1024}, _providers())
    assert backend.chunk_size == 1024


def test_secret_sharing_threshold_is_passed_through():
    cfg = {"raid_mode": "secret_sharing", "secret_sharing": {"threshold": 3}}
    backend = factory.build_raid_backend(cfg, _providers(3))
    assert backend.threshold == 3


def test_unknown_raid_mode_lists_valid_values():
    with pytest.raises(ValueError, match="Unknown raid_mode") as exc:
        factory.build_raid_backend({"raid_mode": "raid5"}, _providers())
    # The message should tell the user what they can actually use.
    for valid in ("mirror", "stripe", "split", "secret_sharing"):
        assert valid in str(exc.value)


# ---------------------------------------------------------------------------
# build_providers
# ---------------------------------------------------------------------------


def test_build_providers_errors_when_none_enabled():
    cfg = {"providers": {"dropbox": {"enabled": False}, "s3": {"enabled": False}}}
    with pytest.raises(RuntimeError, match="No cloud providers are enabled"):
        factory.build_providers(cfg)


def test_build_providers_errors_on_empty_config():
    with pytest.raises(RuntimeError, match="No cloud providers are enabled"):
        factory.build_providers({})


def test_build_providers_ignores_non_dict_entries():
    # A user typo such as `dropbox: true` must not crash the factory.
    with pytest.raises(RuntimeError, match="No cloud providers are enabled"):
        factory.build_providers({"providers": {"dropbox": True, "s3": None}})


def test_build_providers_authenticates_each_enabled_provider(monkeypatch):
    built: list[MockProvider] = []

    def fake_build(name: str, pcfg: dict) -> MockProvider:
        p = MockProvider(name)
        built.append(p)
        return p

    monkeypatch.setattr(factory, "_build_provider", fake_build)
    cfg = {"providers": {"dropbox": {"enabled": True}, "s3": {"enabled": True}}}

    providers = factory.build_providers(cfg)

    assert [p.name for p in providers] == ["dropbox", "s3"]
    # build_providers is responsible for calling auth() — mounting relies on it.
    assert all(p._authed for p in built)


def test_build_providers_skips_disabled_ones(monkeypatch):
    monkeypatch.setattr(factory, "_build_provider", lambda name, pcfg: MockProvider(name))
    cfg = {"providers": {"dropbox": {"enabled": True}, "s3": {"enabled": False}}}

    providers = factory.build_providers(cfg)

    assert [p.name for p in providers] == ["dropbox"]


def test_build_providers_applies_env_overrides(monkeypatch):
    seen: dict[str, dict] = {}

    def fake_build(name: str, pcfg: dict) -> MockProvider:
        seen[name] = pcfg
        return MockProvider(name)

    monkeypatch.setattr(factory, "_build_provider", fake_build)
    monkeypatch.setenv("RAIDCLOUD_S3_SECRET_ACCESS_KEY", "from-env")
    cfg = {"providers": {"s3": {"enabled": True, "bucket": "b", "secret_access_key": "from-file"}}}

    factory.build_providers(cfg)

    assert seen["s3"]["secret_access_key"] == "from-env"
    assert seen["s3"]["bucket"] == "b"


# ---------------------------------------------------------------------------
# _build_provider dispatch
# ---------------------------------------------------------------------------


def test_build_provider_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown provider"):
        factory._build_provider("azure", {})


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("gdrive", "GDriveProvider"),
        ("google_drive", "GDriveProvider"),
        ("googledrive", "GDriveProvider"),
        ("onedrive", "OneDriveProvider"),
        ("one_drive", "OneDriveProvider"),
        ("GDrive", "GDriveProvider"),
    ],
)
def test_provider_name_aliases_resolve(alias, expected):
    """Aliases must reach the right class; construction may still fail on config."""
    pytest.importorskip("googleapiclient" if "drive" in alias.lower() else "msal")
    try:
        provider = factory._build_provider(alias, {"client_id": "x", "bucket": "b"})
    except (ValueError, ImportError) as exc:  # missing required config is fine here
        assert "Unknown provider" not in str(exc)
    else:
        assert type(provider).__name__ == expected
