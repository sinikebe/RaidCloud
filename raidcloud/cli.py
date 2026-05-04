"""RaidCloud CLI entry point.

Usage examples::

    # Show current configuration
    raidcloud config show

    # Initialize a default config file
    raidcloud config init

    # Mount the RAID filesystem
    raidcloud mount /mnt/raidcloud
    raidcloud mount R:                      # Windows drive letter

    # Manually push / pull files (without mounting)
    raidcloud push local_file.txt remote/path.txt
    raidcloud pull remote/path.txt local_file.txt

    # List files stored on the RAID backend
    raidcloud ls [PREFIX]

    # Delete a remote file
    raidcloud rm remote/path.txt
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from raidcloud import __version__


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="raidcloud")
@click.option(
    "--config", "-c",
    default=None,
    metavar="PATH",
    help="Path to config file (default: ~/.raidcloud/config.yaml).",
)
@click.pass_context
def main(ctx: click.Context, config: Optional[str]) -> None:
    """RaidCloud — aggregate cloud providers into a RAID-like virtual disk."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


# ---------------------------------------------------------------------------
# config sub-group
# ---------------------------------------------------------------------------

@main.group("config")
def config_group() -> None:
    """Manage the RaidCloud configuration file."""


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Print the current configuration (sensitive values redacted)."""
    import yaml
    from raidcloud import config as cfg_mod

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    # Redact secrets
    _redact(cfg)
    click.echo(yaml.dump(cfg, default_flow_style=False, sort_keys=False))


@config_group.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing config.")
@click.pass_context
def config_init(ctx: click.Context, force: bool) -> None:
    """Create a default config file at ~/.raidcloud/config.yaml."""
    from raidcloud import config as cfg_mod

    path = Path(ctx.obj.get("config_path") or cfg_mod.DEFAULT_CONFIG_PATH)
    if path.exists() and not force:
        click.echo(f"Config already exists at {path}. Use --force to overwrite.")
        sys.exit(1)

    example = {
        "raid_mode": "mirror",
        "mount_point": "/mnt/raidcloud",
        "chunk_size": 4 * 1024 * 1024,
        "providers": {
            "dropbox": {
                "enabled": False,
                "access_token": "YOUR_DROPBOX_TOKEN",
            },
            "s3": {
                "enabled": False,
                "bucket": "my-raidcloud-bucket",
                "region": "us-east-1",
                "access_key_id": "AKI...",
                "secret_access_key": "...",
            },
            "gdrive": {
                "enabled": False,
                "credentials_file": "~/.raidcloud/gdrive_credentials.json",
                "token_file": "~/.raidcloud/gdrive_token.json",
                "folder_id": "",
            },
            "onedrive": {
                "enabled": False,
                "client_id": "YOUR_CLIENT_ID",
                "tenant_id": "common",
            },
        },
        "secret_sharing": {
            "threshold": 2,
        },
    }
    cfg_mod.save(example, path)
    click.echo(f"Config written to {path}")
    click.echo("Edit it to enable providers and set credentials.")


# ---------------------------------------------------------------------------
# mount
# ---------------------------------------------------------------------------

@main.command("mount")
@click.argument("mountpoint")
@click.option(
    "--foreground/--background",
    default=True,
    help="Run in foreground (default) or background.",
)
@click.pass_context
def mount_cmd(ctx: click.Context, mountpoint: str, foreground: bool) -> None:
    """Mount the RaidCloud RAID filesystem at MOUNTPOINT."""
    from raidcloud import config as cfg_mod, factory

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    click.echo(
        f"Authenticating providers (raid_mode={cfg['raid_mode']})…"
    )
    providers = factory.build_providers(cfg)
    backend = factory.build_raid_backend(cfg, providers)

    click.echo(f"Mounting at {mountpoint} …")
    if sys.platform == "win32":
        from raidcloud.mount.windows import mount
    else:
        from raidcloud.mount.linux import mount

    mount(backend, mountpoint, foreground=foreground)


# ---------------------------------------------------------------------------
# push / pull
# ---------------------------------------------------------------------------

@main.command("push")
@click.argument("local_path")
@click.argument("remote_path")
@click.pass_context
def push(ctx: click.Context, local_path: str, remote_path: str) -> None:
    """Upload LOCAL_PATH to REMOTE_PATH on the RAID backend."""
    from raidcloud import config as cfg_mod, factory

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    providers = factory.build_providers(cfg)
    backend = factory.build_raid_backend(cfg, providers)

    src = Path(local_path)
    if not src.exists():
        click.echo(f"Error: {local_path!r} does not exist.", err=True)
        sys.exit(1)

    data = src.read_bytes()
    backend.upload(remote_path, data)
    click.echo(f"Uploaded {local_path} → {remote_path} ({len(data)} bytes)")


@main.command("pull")
@click.argument("remote_path")
@click.argument("local_path")
@click.pass_context
def pull(ctx: click.Context, remote_path: str, local_path: str) -> None:
    """Download REMOTE_PATH from the RAID backend to LOCAL_PATH."""
    from raidcloud import config as cfg_mod, factory

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    providers = factory.build_providers(cfg)
    backend = factory.build_raid_backend(cfg, providers)

    try:
        data = backend.download(remote_path)
    except FileNotFoundError:
        click.echo(f"Error: {remote_path!r} not found on any provider.", err=True)
        sys.exit(1)

    Path(local_path).write_bytes(data)
    click.echo(f"Downloaded {remote_path} → {local_path} ({len(data)} bytes)")


# ---------------------------------------------------------------------------
# ls
# ---------------------------------------------------------------------------

@main.command("ls")
@click.argument("prefix", default="")
@click.pass_context
def ls(ctx: click.Context, prefix: str) -> None:
    """List files stored on the RAID backend."""
    from raidcloud import config as cfg_mod, factory

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    providers = factory.build_providers(cfg)
    backend = factory.build_raid_backend(cfg, providers)

    paths = backend.list(prefix)
    if not paths:
        click.echo("(no files found)")
    else:
        for p in paths:
            click.echo(p)


# ---------------------------------------------------------------------------
# rm
# ---------------------------------------------------------------------------

@main.command("rm")
@click.argument("remote_path")
@click.pass_context
def rm(ctx: click.Context, remote_path: str) -> None:
    """Delete REMOTE_PATH from all RAID providers."""
    from raidcloud import config as cfg_mod, factory

    cfg = cfg_mod.load(ctx.obj.get("config_path"))
    providers = factory.build_providers(cfg)
    backend = factory.build_raid_backend(cfg, providers)

    try:
        backend.delete(remote_path)
        click.echo(f"Deleted {remote_path}")
    except FileNotFoundError:
        click.echo(f"Error: {remote_path!r} not found.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET_KEYS = {"access_token", "secret_access_key", "client_secret", "password"}


def _redact(obj: object) -> None:
    if isinstance(obj, dict):
        for k in obj:
            if k in _SECRET_KEYS and isinstance(obj[k], str) and obj[k]:
                obj[k] = "***"
            else:
                _redact(obj[k])
    elif isinstance(obj, list):
        for item in obj:
            _redact(item)


if __name__ == "__main__":
    main()
