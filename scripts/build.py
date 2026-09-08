#!/usr/bin/env python3
"""Unified build script — produces Linux and/or Windows binaries.

Usage:
    python scripts/build.py --target linux
    python scripts/build.py --target windows
    python scripts/build.py --target all

Requirements:
    - Linux build:   pip install pyinstaller
    - Windows build: run scripts/setup_wine.sh first (installs Wine + Windows Python)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DIST = ROOT / "dist"
SPEC = ROOT / "raidcloud.spec"

# Wine Python path set by setup_wine.sh
WINE_PYTHON = Path.home() / ".wine" / "drive_c" / "python312" / "python.exe"


def run(cmd: list[str], env: dict | None = None, **kwargs) -> None:
    merged_env = {**os.environ, **(env or {})}
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, env=merged_env, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_linux() -> None:
    print("\n=== Building Linux binary ===")
    run([
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST / "linux"),
        "--workpath", str(ROOT / "build" / "linux"),
        "--noconfirm",
        str(SPEC),
    ])
    binary = DIST / "linux" / "raidcloud"
    print(f"\nLinux binary: {binary}")
    print(f"Size: {binary.stat().st_size / 1024 / 1024:.1f} MiB")


def build_windows() -> None:
    print("\n=== Building Windows binary (via Wine) ===")
    if not WINE_PYTHON.exists():
        print(f"ERROR: Wine Python not found at {WINE_PYTHON}")
        print("Run scripts/setup_wine.sh first.")
        sys.exit(1)

    # Convert Linux path to Wine path (Z: maps to /)
    def to_wine_path(p: Path) -> str:
        return "Z:" + str(p).replace("/", "\\")

    run([
        "wine", str(WINE_PYTHON), "-m", "PyInstaller",
        "--distpath", to_wine_path(DIST / "windows"),
        "--workpath", to_wine_path(ROOT / "build" / "windows"),
        "--noconfirm",
        to_wine_path(SPEC),
    ], env={"WINEDEBUG": "-all", "PYTHONPATH": to_wine_path(ROOT)})

    binary = DIST / "windows" / "raidcloud.exe"
    print(f"\nWindows binary: {binary}")
    print(f"Size: {binary.stat().st_size / 1024 / 1024:.1f} MiB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build RaidCloud binaries")
    parser.add_argument(
        "--target",
        choices=["linux", "windows", "all"],
        default="all",
        help="Build target (default: all)",
    )
    args = parser.parse_args()

    DIST.mkdir(parents=True, exist_ok=True)

    if args.target in ("linux", "all"):
        build_linux()
    if args.target in ("windows", "all"):
        build_windows()

    print("\nDone.")


if __name__ == "__main__":
    main()
