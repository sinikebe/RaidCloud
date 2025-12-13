"""Command-line interface for RaidCloud."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .dropbox import DropboxBackend
from .google_drive import GoogleDriveBackend
from .storage_backend import StorageBackend

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def get_backend(backend_name: str, credentials: Optional[dict] = None) -> StorageBackend:
    """Get a storage backend instance by name.

    Args:
        backend_name: Name of the backend ('googledrive' or 'dropbox')
        credentials: Optional credentials dictionary

    Returns:
        StorageBackend instance

    Raises:
        ValueError: If backend_name is not supported
    """
    backend_name = backend_name.lower()
    
    if backend_name in ("googledrive", "google_drive", "gdrive"):
        return GoogleDriveBackend(credentials)
    elif backend_name in ("dropbox", "dbx"):
        return DropboxBackend(credentials)
    else:
        raise ValueError(
            f"Unsupported backend: {backend_name}. "
            f"Supported backends: googledrive, dropbox"
        )


def sync_command(args: argparse.Namespace) -> int:
    """Execute the sync command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    try:
        local_path = Path(args.local_path).resolve()
        remote_path = args.remote_path
        backend_name = args.backend
        
        logger.info(f"Starting sync: {local_path} -> {remote_path} ({backend_name})")
        
        # Get the appropriate backend
        backend = get_backend(backend_name)
        
        # Perform the sync
        backend.sync(local_path, remote_path)
        
        logger.info("Sync completed successfully")
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except NotADirectoryError as e:
        logger.error(f"Not a directory: {e}")
        return 1
    except ValueError as e:
        logger.error(f"Invalid argument: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


def main() -> int:
    """Main entry point for the CLI.

    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(
        prog="raidcloud",
        description="Sync local folders to cloud storage",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Sync command
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync a local folder to cloud storage",
    )
    sync_parser.add_argument(
        "local_path",
        type=str,
        help="Path to the local folder to sync",
    )
    sync_parser.add_argument(
        "remote_path",
        type=str,
        help="Path to the remote folder in cloud storage",
    )
    sync_parser.add_argument(
        "--backend",
        "-b",
        type=str,
        default="googledrive",
        choices=["googledrive", "dropbox"],
        help="Cloud storage backend to use (default: googledrive)",
    )
    sync_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    # Set logging level based on verbose flag
    if hasattr(args, "verbose") and args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Execute the appropriate command
    if args.command == "sync":
        return sync_command(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
