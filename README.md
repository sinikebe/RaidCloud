# RaidCloud

Aggregate multiple cloud storage providers into a RAID-like virtual disk for Linux and Windows.

## Features

| RAID mode | Description |
|-----------|-------------|
| **mirror** (RAID-1) | Every file is replicated on all providers — high availability |
| **stripe** (RAID-0) | Files are split in equal-size chunks across providers — parallel I/O |
| **secret_sharing** | Files are encrypted with AES-256-GCM; the key is split via Shamir's Secret Sharing (K-of-N threshold) — **no single provider can read your data** |

### Supported cloud providers

| Provider | SDK |
|----------|-----|
| Dropbox | `dropbox` |
| AWS S3 / S3-compatible (Backblaze, MinIO, …) | `boto3` |
| Google Drive | `google-api-python-client` |
| OneDrive | `msal` + Microsoft Graph |

---

## Installation

```bash
pip install .
# or for development
pip install -e ".[dev]"
```

For FUSE mounting (Linux / Windows via WinFsp):

```bash
pip install pyfuse3 trio
# Linux also needs: sudo apt install libfuse3-dev
```

---

## Quick start

### 1. Create a config file

```bash
raidcloud config init
```

Edit `~/.raidcloud/config.yaml` and enable at least one provider:

```yaml
raid_mode: mirror          # mirror | stripe | secret_sharing
mount_point: /mnt/raidcloud

providers:
  dropbox:
    enabled: true
    access_token: "sl.XXXX"

  s3:
    enabled: true
    bucket: my-raidcloud-bucket
    region: us-east-1
    access_key_id: AKI...
    secret_access_key: "..."

  gdrive:
    enabled: true
    credentials_file: ~/.raidcloud/gdrive_credentials.json
    token_file: ~/.raidcloud/gdrive_token.json

  onedrive:
    enabled: true
    client_id: "YOUR_CLIENT_ID"
    tenant_id: "common"

secret_sharing:
  threshold: 2   # only relevant for secret_sharing mode
```

Credentials can also be provided via environment variables:

```
RAIDCLOUD_DROPBOX_ACCESS_TOKEN=...
RAIDCLOUD_S3_ACCESS_KEY_ID=...
RAIDCLOUD_S3_SECRET_ACCESS_KEY=...
```

### 2. Mount the virtual filesystem

```bash
# Linux
sudo mkdir -p /mnt/raidcloud
raidcloud mount /mnt/raidcloud

# Windows (requires WinFsp or Dokan)
raidcloud mount R:
```

### 3. Transfer files without mounting

```bash
# Upload
raidcloud push ./local_file.txt remote/path/file.txt

# Download
raidcloud pull remote/path/file.txt ./local_file.txt

# List
raidcloud ls

# Delete
raidcloud rm remote/path/file.txt
```

---

## Architecture

```
raidcloud/
├── cli.py             CLI entry point (click)
├── config.py          Config loading/saving
├── factory.py         Provider & RAID backend factory
├── providers/
│   ├── base.py        Abstract CloudProvider interface
│   ├── dropbox.py     Dropbox backend
│   ├── s3.py          AWS S3 / S3-compatible backend
│   ├── gdrive.py      Google Drive backend
│   └── onedrive.py    OneDrive (Microsoft Graph) backend
├── raid/
│   ├── mirroring.py   RAID-1: write to all, read from first available
│   ├── striping.py    RAID-0: split chunks across providers
│   └── secret_sharing.py  Shamir SSS + AES-256-GCM confidentiality
└── mount/
    ├── linux.py       pyfuse3 FUSE filesystem
    └── windows.py     WinFsp (pyfuse3) or Dokan filesystem
```

### Confidentiality design

In `secret_sharing` mode:

1. A fresh AES-256 Data Encryption Key (DEK) is generated per upload.
2. The file is encrypted with AES-256-GCM.
3. The DEK is split into N shares using **Shamir's Secret Sharing** over GF(2⁸).
4. Share `i` is stored on provider `i` alongside the ciphertext.
5. Any K of the N providers can reconstruct the DEK and decrypt the file.
6. **Fewer than K providers reveal zero information** about the DEK or file contents.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT