"""Configuration loading and saving for RaidCloud.

Config file location: ``~/.raidcloud/config.yaml``

Example config::

    raid_mode: mirror          # mirror | stripe | secret_sharing
    mount_point: /mnt/raidcloud  # Linux path or Windows drive letter, e.g. R:
    chunk_size: 4194304          # bytes (4 MiB default)

    providers:
      dropbox:
        enabled: true
        access_token: "YOUR_TOKEN"

      s3:
        enabled: true
        bucket: "my-raidcloud-bucket"
        region: "us-east-1"
        access_key_id: "AKI..."
        secret_access_key: "..."

      gdrive:
        enabled: true
        credentials_file: "~/.raidcloud/gdrive_credentials.json"
        token_file: "~/.raidcloud/gdrive_token.json"
        folder_id: ""          # root if empty

      onedrive:
        enabled: true
        client_id: "..."
        tenant_id: "common"
        # token is cached in ~/.raidcloud/onedrive_token.json

    secret_sharing:
      threshold: 2             # minimum shares needed to reconstruct
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".raidcloud"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"

_DEFAULTS: dict[str, Any] = {
    "raid_mode": "mirror",
    "mount_point": "/mnt/raidcloud",
    "chunk_size": 4 * 1024 * 1024,  # 4 MiB
    "providers": {},
    "secret_sharing": {
        "threshold": 2,
    },
}


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Load config from *path* (default: ``~/.raidcloud/config.yaml``).

    Missing keys are filled in from built-in defaults.  The file need not
    exist; an all-default config is returned in that case.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg: dict[str, Any] = {}

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Config file {config_path} must contain a YAML mapping.")
        cfg = loaded

    # Merge defaults (shallow for top-level keys, preserve user values)
    merged: dict[str, Any] = {**_DEFAULTS, **cfg}
    # Deep-merge nested dicts that exist in defaults
    for key in ("secret_sharing",):
        if key in _DEFAULTS:
            merged[key] = {**_DEFAULTS[key], **cfg.get(key, {})}

    return merged


def save(cfg: dict[str, Any], path: str | Path | None = None) -> None:
    """Persist *cfg* to *path* (default: ``~/.raidcloud/config.yaml``)."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)


def get_provider_cfg(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    """Return provider sub-config, substituting env-var overrides.

    Environment variables follow the pattern ``RAIDCLOUD_<PROVIDER>_<KEY>``
    (upper-cased), e.g. ``RAIDCLOUD_S3_ACCESS_KEY_ID``.
    """
    provider_cfg: dict[str, Any] = dict(cfg.get("providers", {}).get(name, {}))
    prefix = f"RAIDCLOUD_{name.upper()}_"
    for env_key, env_val in os.environ.items():
        if env_key.startswith(prefix):
            cfg_key = env_key[len(prefix):].lower()
            provider_cfg[cfg_key] = env_val
    return provider_cfg
