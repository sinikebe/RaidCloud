"""Provider factory — build providers and RAID backends from config."""

from __future__ import annotations

import sys
from typing import Any, List

from raidcloud.providers.base import CloudProvider


def build_providers(cfg: dict) -> List[CloudProvider]:
    """Instantiate and authenticate all enabled providers from *cfg*."""
    from raidcloud import config as _cfg_mod

    providers: List[CloudProvider] = []
    providers_cfg: dict = cfg.get("providers", {})

    for name, pcfg in providers_cfg.items():
        if not (isinstance(pcfg, dict) and pcfg.get("enabled", False)):
            continue
        merged_cfg = _cfg_mod.get_provider_cfg(cfg, name)
        provider = _build_provider(name, merged_cfg)
        provider.auth()
        providers.append(provider)

    if not providers:
        raise RuntimeError(
            "No cloud providers are enabled. "
            "Edit ~/.raidcloud/config.yaml and set at least one provider.enabled = true."
        )
    return providers


def _build_provider(name: str, pcfg: dict) -> CloudProvider:
    name_lower = name.lower()
    if name_lower == "dropbox":
        from raidcloud.providers.dropbox import DropboxProvider
        return DropboxProvider.from_config(pcfg)
    elif name_lower == "s3":
        from raidcloud.providers.s3 import S3Provider
        return S3Provider.from_config(pcfg)
    elif name_lower in ("gdrive", "google_drive", "googledrive"):
        from raidcloud.providers.gdrive import GDriveProvider
        return GDriveProvider.from_config(pcfg)
    elif name_lower in ("onedrive", "one_drive"):
        from raidcloud.providers.onedrive import OneDriveProvider
        return OneDriveProvider.from_config(pcfg)
    else:
        raise ValueError(f"Unknown provider: {name!r}")


def build_raid_backend(cfg: dict, providers: List[CloudProvider]) -> Any:
    """Build the appropriate RAID layer from *cfg*."""
    mode = cfg.get("raid_mode", "mirror").lower()
    chunk_size: int = int(cfg.get("chunk_size", 4 * 1024 * 1024))

    if mode == "mirror":
        from raidcloud.raid.mirroring import MirrorRAID
        return MirrorRAID(providers)
    elif mode in ("stripe", "striping", "raid0"):
        from raidcloud.raid.striping import StripingRAID
        return StripingRAID(providers, chunk_size=chunk_size)
    elif mode in ("split", "split_stripe"):
        from raidcloud.raid.striping import StripingRAID
        return StripingRAID(providers, split_by_provider=True)
    elif mode in ("secret_sharing", "secretsharing", "confidential"):
        from raidcloud.raid.secret_sharing import SecretSharingRAID
        k = int(cfg.get("secret_sharing", {}).get("threshold", 2))
        return SecretSharingRAID(providers, threshold=k)
    else:
        raise ValueError(
            f"Unknown raid_mode: {mode!r}. "
            "Valid values: mirror, stripe, split, secret_sharing"
        )
