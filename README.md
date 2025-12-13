# RaidCloud

A Python project that syncs local folders to cloud storage.

## Features

- **StorageBackend Interface**: Abstract base class for implementing cloud storage backends
- **Google Drive Backend**: Basic implementation for syncing to Google Drive
- **Dropbox Backend**: Basic implementation for syncing to Dropbox
- **CLI Tool**: Command-line interface for triggering sync operations

## Installation

Install the project in development mode:

```bash
pip install -e .
```

For development with testing tools:

```bash
pip install -e ".[dev]"
```

## Usage

### Command Line Interface

Sync a local folder to Google Drive:

```bash
raidcloud sync /path/to/local/folder /remote/folder --backend googledrive
```

Sync a local folder to Dropbox:

```bash
raidcloud sync /path/to/local/folder /remote/folder --backend dropbox
```

Enable verbose logging:

```bash
raidcloud sync /path/to/local/folder /remote/folder --backend googledrive --verbose
```

### Python API

```python
from pathlib import Path
from raidcloud.google_drive import GoogleDriveBackend
from raidcloud.dropbox import DropboxBackend

# Use Google Drive backend
gdrive = GoogleDriveBackend()
gdrive.sync(Path("/path/to/local/folder"), "/remote/folder")

# Use Dropbox backend
dropbox = DropboxBackend()
dropbox.sync(Path("/path/to/local/folder"), "/remote/folder")
```

## Project Structure

```
raidcloud/
├── raidcloud/
│   ├── __init__.py           # Package initialization
│   ├── storage_backend.py    # Abstract StorageBackend interface
│   ├── google_drive.py       # Google Drive implementation
│   ├── dropbox.py            # Dropbox implementation
│   └── cli.py                # Command-line interface
├── tests/
│   ├── __init__.py
│   ├── test_storage_backend.py
│   ├── test_google_drive.py
│   ├── test_dropbox.py
│   └── test_cli.py
├── setup.py                  # Package configuration
├── requirements.txt          # Project dependencies
├── pytest.ini                # Pytest configuration
└── README.md                 # This file
```

## Development

### Running Tests

Run all tests:

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov=raidcloud
```

Run tests for a specific module:

```bash
pytest tests/test_google_drive.py
```

### Code Style

The project follows Python best practices. To check code style:

```bash
flake8 raidcloud tests
```

Format code with Black:

```bash
black raidcloud tests
```

Type checking with mypy:

```bash
mypy raidcloud
```

## Implementation Notes

The current implementations of Google Drive and Dropbox backends are **stub implementations** that provide the structure and basic error handling but do not yet connect to actual cloud APIs. To use them with real cloud services, you would need to:

1. Install the appropriate SDK libraries (e.g., `google-api-python-client`, `dropbox`)
2. Implement authentication and API calls in the `upload_file`, `download_file`, and `list_files` methods
3. Add credential management (OAuth tokens, API keys, etc.)

## License

MIT License