"""Unit tests for config module."""

import stat

import pytest

from raidcloud import config


def test_load_defaults_when_no_file():
    cfg = config.load("/nonexistent/path/config.yaml")
    assert cfg["raid_mode"] == "mirror"
    assert cfg["chunk_size"] == 4 * 1024 * 1024
    assert cfg["providers"] == {}


def test_load_and_save_roundtrip(tmp_path):
    path = tmp_path / "config.yaml"
    original = {
        "raid_mode": "stripe",
        "mount_point": "/mnt/test",
        "chunk_size": 1024,
        "providers": {
            "dropbox": {"enabled": True, "access_token": "tok"},
        },
        "secret_sharing": {"threshold": 3},
    }
    config.save(original, path)
    loaded = config.load(path)

    assert loaded["raid_mode"] == "stripe"
    assert loaded["chunk_size"] == 1024
    assert loaded["providers"]["dropbox"]["access_token"] == "tok"
    assert loaded["secret_sharing"]["threshold"] == 3


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "config.yaml"
    config.save({"raid_mode": "mirror"}, path)
    assert path.exists()


def test_load_merges_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    # Only write a partial config
    config.save({"raid_mode": "stripe"}, path)
    cfg = config.load(path)
    # Defaults for missing keys should be filled in
    assert "chunk_size" in cfg
    assert "providers" in cfg


def test_get_provider_cfg_env_override(monkeypatch):
    cfg = {"providers": {"s3": {"bucket": "my-bucket", "region": "us-east-1"}}}
    monkeypatch.setenv("RAIDCLOUD_S3_REGION", "eu-west-1")
    pcfg = config.get_provider_cfg(cfg, "s3")
    assert pcfg["region"] == "eu-west-1"
    assert pcfg["bucket"] == "my-bucket"


def test_load_invalid_yaml(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("- this is a list\n- not a mapping\n")
    with pytest.raises(ValueError, match="YAML mapping"):
        config.load(path)


def test_save_writes_owner_only_permissions(tmp_path):
    """The config file holds provider credentials — it must not be world-readable."""
    path = tmp_path / "sub" / "config.yaml"
    config.save({"providers": {"dropbox": {"access_token": "sl.SECRET"}}}, path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_save_tightens_existing_loose_permissions(tmp_path):
    """A config file left world-readable by an earlier version gets locked down."""
    path = tmp_path / "config.yaml"
    config.save({"raid_mode": "mirror"}, path)
    path.chmod(0o644)

    config.save({"raid_mode": "stripe"}, path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
