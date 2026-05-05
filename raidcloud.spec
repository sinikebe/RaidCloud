# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RaidCloud.

Produces a single-file binary:
  - raidcloud      (Linux ELF)
  - raidcloud.exe  (Windows PE, when built via Wine or on Windows)
"""

import sys
import platform

# When cross-compiling via Wine, PyInstaller sets sys.platform = 'win32'
_is_windows = sys.platform == "win32"

block_cipher = None

# Modules that only exist on one platform — exclude from the other
_linux_only = [
    "pyfuse3",
    "trio",
    "trio_util",
    "raidcloud.mount.linux",
]
_windows_only = [
    # pyfuse3 for Windows (WinFsp) — not yet packaged, exclude everywhere for now
]

excludes = _linux_only if _is_windows else _windows_only

a = Analysis(
    ["raidcloud/cli.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Provider backends
        "raidcloud.providers.dropbox",
        "raidcloud.providers.s3",
        "raidcloud.providers.gdrive",
        "raidcloud.providers.onedrive",
        # RAID backends
        "raidcloud.raid.mirroring",
        "raidcloud.raid.striping",
        "raidcloud.raid.secret_sharing",
        # Mount backend (platform-appropriate)
        "raidcloud.mount.windows" if _is_windows else "raidcloud.mount.linux",
        # Cloud SDK internals that PyInstaller misses
        "dropbox",
        "boto3",
        "botocore",
        "google.auth",
        "google.oauth2",
        "google.auth.transport.requests",
        "google_auth_oauthlib.flow",
        "googleapiclient.discovery",
        "msal",
        "cryptography.hazmat.primitives.ciphers.aead",
    ],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="raidcloud",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
