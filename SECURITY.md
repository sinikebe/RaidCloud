# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report vulnerabilities privately through GitHub's
[private vulnerability reporting](https://github.com/sinikebe/RaidCloud/security/advisories/new)
on this repository. Please include a description of the issue, the steps to
reproduce it, and the impact you believe it has.

You can expect an initial response within 7 days.

## Supported versions

RaidCloud is pre-1.0. Only the latest release receives security fixes.

## Audit status

> **RaidCloud's cryptography has not been independently audited.**
> It is a hobby project. Do not rely on it as the only protection for data
> whose disclosure would seriously harm you.

## Threat model

### `secret_sharing` mode

Each upload generates a fresh AES-256 data encryption key (DEK). The file is
encrypted with AES-256-GCM, and the DEK is split into N shares using Shamir's
Secret Sharing over GF(2^8) with a K-of-N threshold.

**Every provider receives the complete ciphertext plus exactly one DEK share.**

What this protects against:

- A single provider — or any group of fewer than K providers — cannot recover
  the DEK. Shamir's scheme is information-theoretically secure for the key:
  fewer than K shares are consistent with every possible key.
- Without the DEK, the file contents are protected by AES-256-GCM, i.e. under
  standard computational assumptions about AES.

What this does **not** protect against:

- **Metadata.** Every provider learns the exact ciphertext length (so, the
  approximate file size) and the logical path of every object you store. Paths
  and sizes are not encrypted.
- **K colluding providers.** Any K providers together can reconstruct the DEK
  and decrypt everything. Choose K with that in mind; `threshold: 2` means any
  *two* of your providers can read your data.
- **Retained ciphertext.** Providers hold the full ciphertext indefinitely and
  may keep copies after deletion. A future break of AES-256-GCM, or a later
  leak of K shares, retroactively exposes data stored today.
- **A compromised client.** The DEK, your config file and your provider tokens
  all exist in plaintext in memory on the machine running RaidCloud.
- **Side channels.** The GF(2^8) arithmetic in
  `raidcloud/raid/secret_sharing.py` is straightforward pure Python and is
  **not** constant-time. It is intended for a local, trusted process; it is not
  hardened against an attacker who can measure its timing.

### Other RAID modes

`mirror`, `stripe` and `split` provide **no confidentiality**. Data is stored
as plaintext bytes on each provider:

- `mirror` gives every provider a complete copy of every file.
- `stripe` and `split` give each provider a contiguous byte range, which
  usually reveals a substantial amount about the file.

If you need confidentiality, use `secret_sharing`.

## Credential handling

- `~/.raidcloud/config.yaml` holds provider credentials. RaidCloud creates it
  with mode `0600` inside a `0700` directory, and tightens the permissions of
  an existing file when it rewrites it.
- Google Drive and OneDrive token caches are written with mode `0600`.
- `raidcloud config show` redacts known secret keys, but treat its output as
  sensitive anyway — an unrecognised key name will be printed verbatim.
- Credentials can be supplied via `RAIDCLOUD_<PROVIDER>_<KEY>` environment
  variables instead of the config file. Environment variables take precedence.
