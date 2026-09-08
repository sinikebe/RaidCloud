# Contributing to RaidCloud

Thanks for your interest in RaidCloud! This document covers how to get set up
and what we expect from a pull request.

## Development setup

```bash
git clone https://github.com/sinikebe/RaidCloud
cd RaidCloud
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The test suite covers the config, RAID and crypto layers and needs no cloud
credentials and no FUSE libraries:

```bash
pytest
```

To work on the mount layer you additionally need FUSE:

```bash
pip install -e ".[fuse]"
sudo apt install libfuse3-dev   # Linux
```

## Before you open a pull request

Run what CI runs:

```bash
pytest                              # all tests must pass
ruff check raidcloud tests scripts  # lint must be clean
```

`ruff format` is available if you want consistent formatting, but formatting is
not currently enforced in CI — please keep formatting changes in their own
commit so that they do not obscure behavioural changes.

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Backblaze B2 provider
fix: handle O_TRUNC in the FUSE open path
docs: clarify secret_sharing threshold semantics
chore: bump dependency pins
test: cover striping with a single provider
```

The `feat:` / `fix:` prefixes matter: the release workflow builds release notes
from commit history.

## Branching and releases

- `main` is the release branch. Every push to `main` triggers
  `.github/workflows/release.yml`, which bumps the patch version, tags it,
  builds Linux and Windows binaries, and publishes a GitHub Release.
- Work on a feature branch and open a pull request against `main`.
- Pushes to any non-`main` branch produce a beta binary artifact via
  `.github/workflows/beta.yml`.
- Do not hand-edit the version in `pyproject.toml` or `raidcloud/__init__.py` —
  the release workflow owns it.

## Adding a cloud provider

1. Subclass `CloudProvider` in `raidcloud/providers/base.py` and implement
   `auth`, `upload`, `download`, `delete` and `list`.
2. Import the SDK lazily inside `auth()` so the dependency stays optional and
   `raidcloud --help` works without it installed.
3. Raise `FileNotFoundError` for missing objects — the RAID layers rely on that
   to decide whether a provider is merely missing a file or is genuinely down.
4. Register it in `raidcloud/factory.py::_build_provider`.
5. Write any credential file with mode `0600`.

## Reporting security issues

Please do not open a public issue for a security problem — see
[SECURITY.md](SECURITY.md).
