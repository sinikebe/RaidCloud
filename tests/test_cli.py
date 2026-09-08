"""Unit tests for the RaidCloud command-line interface."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from raidcloud import cli, factory
from raidcloud.raid.mirroring import MirrorRAID
from tests.helpers import MockProvider


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def backend(monkeypatch) -> MirrorRAID:
    """Replace provider construction with an in-memory mirror backend."""
    providers = [MockProvider("p0"), MockProvider("p1")]
    raid = MirrorRAID(providers)
    # The CLI imports factory lazily inside each command, so patching the
    # module attributes is enough to intercept provider construction.
    monkeypatch.setattr(factory, "build_providers", lambda cfg: providers)
    monkeypatch.setattr(factory, "build_raid_backend", lambda cfg, provs: raid)
    return raid


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def test_version(runner):
    from raidcloud import __version__

    result = runner.invoke(cli.main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_every_command(runner):
    result = runner.invoke(cli.main, ["--help"])
    assert result.exit_code == 0
    for command in ("config", "mount", "push", "pull", "ls", "rm"):
        assert command in result.output


# ---------------------------------------------------------------------------
# config init / show
# ---------------------------------------------------------------------------


def test_config_init_writes_a_loadable_file(runner, tmp_path):
    path = tmp_path / "config.yaml"
    result = runner.invoke(cli.main, ["-c", str(path), "config", "init"])

    assert result.exit_code == 0
    assert path.exists()
    cfg = yaml.safe_load(path.read_text())
    assert cfg["raid_mode"] == "mirror"
    # Every provider ships disabled so a fresh install cannot half-authenticate.
    assert all(p["enabled"] is False for p in cfg["providers"].values())


def test_config_init_refuses_to_clobber(runner, tmp_path):
    path = tmp_path / "config.yaml"
    runner.invoke(cli.main, ["-c", str(path), "config", "init"])
    path.write_text("raid_mode: stripe\n")

    result = runner.invoke(cli.main, ["-c", str(path), "config", "init"])

    assert result.exit_code == 1
    assert "--force" in result.output
    assert path.read_text() == "raid_mode: stripe\n"  # untouched


def test_config_init_force_overwrites(runner, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("raid_mode: stripe\n")

    result = runner.invoke(cli.main, ["-c", str(path), "config", "init", "--force"])

    assert result.exit_code == 0
    assert yaml.safe_load(path.read_text())["raid_mode"] == "mirror"


def test_config_show_redacts_every_secret_key(runner, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "providers:\n"
        "  dropbox:\n"
        "    access_token: SECRET_ACCESS_TOKEN\n"
        "    refresh_token: SECRET_REFRESH_TOKEN\n"
        "  s3:\n"
        "    secret_access_key: SECRET_S3_KEY\n"
        "    session_token: SECRET_SESSION\n"
        "    bucket: my-bucket\n"
    )

    result = runner.invoke(cli.main, ["-c", str(path), "config", "show"])

    assert result.exit_code == 0
    for secret in ("SECRET_ACCESS_TOKEN", "SECRET_REFRESH_TOKEN", "SECRET_S3_KEY", "SECRET_SESSION"):
        assert secret not in result.output
    # Non-secret values stay visible so the command remains useful.
    assert "my-bucket" in result.output


def test_config_show_on_missing_file_shows_defaults(runner, tmp_path):
    result = runner.invoke(cli.main, ["-c", str(tmp_path / "nope.yaml"), "config", "show"])
    assert result.exit_code == 0
    assert "mirror" in result.output


# ---------------------------------------------------------------------------
# push / pull round trip
# ---------------------------------------------------------------------------


def test_push_then_pull_round_trips(runner, tmp_path, backend):
    src = tmp_path / "src.bin"
    payload = b"\x00\x01binary payload\xff"
    src.write_bytes(payload)

    push = runner.invoke(cli.main, ["push", str(src), "remote/f.bin"])
    assert push.exit_code == 0, push.output
    assert str(len(payload)) in push.output

    dst = tmp_path / "out.bin"
    pull = runner.invoke(cli.main, ["pull", "remote/f.bin", str(dst)])
    assert pull.exit_code == 0, pull.output
    assert dst.read_bytes() == payload


def test_push_missing_local_file_fails_cleanly(runner, tmp_path, backend):
    result = runner.invoke(cli.main, ["push", str(tmp_path / "absent.txt"), "remote/f"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_pull_missing_remote_file_fails_cleanly(runner, tmp_path, backend):
    result = runner.invoke(cli.main, ["pull", "remote/absent", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# ls / rm
# ---------------------------------------------------------------------------


def test_ls_reports_empty_backend(runner, backend):
    result = runner.invoke(cli.main, ["ls"])
    assert result.exit_code == 0
    assert "(no files found)" in result.output


def test_ls_lists_uploaded_paths(runner, backend):
    backend.upload("a.txt", b"a")
    backend.upload("dir/b.txt", b"b")

    result = runner.invoke(cli.main, ["ls"])

    assert result.exit_code == 0
    assert "a.txt" in result.output
    assert "dir/b.txt" in result.output


def test_ls_honours_prefix(runner, backend):
    backend.upload("keep/a.txt", b"a")
    backend.upload("other/b.txt", b"b")

    result = runner.invoke(cli.main, ["ls", "keep/"])

    assert result.exit_code == 0
    assert "keep/a.txt" in result.output
    assert "other/b.txt" not in result.output


def test_rm_deletes_from_every_provider(runner, backend):
    backend.upload("gone.txt", b"data")

    result = runner.invoke(cli.main, ["rm", "gone.txt"])

    assert result.exit_code == 0
    assert not backend.exists("gone.txt")
    assert all("gone.txt" not in p.store for p in backend.providers)


def test_rm_missing_file_fails_cleanly(runner, backend):
    result = runner.invoke(cli.main, ["rm", "absent.txt"])
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------------------------------------------------------------------------
# _redact helper
# ---------------------------------------------------------------------------


def test_redact_walks_nested_structures():
    cfg = {
        "providers": {"dropbox": {"access_token": "tok", "enabled": True}},
        "list_of": [{"password": "pw"}],
        "empty": {"access_token": ""},
    }
    cli._redact(cfg)

    assert cfg["providers"]["dropbox"]["access_token"] == "***"
    assert cfg["providers"]["dropbox"]["enabled"] is True
    assert cfg["list_of"][0]["password"] == "***"
    # An empty value is left alone rather than being masked into a fake secret.
    assert cfg["empty"]["access_token"] == ""
