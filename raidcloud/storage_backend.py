"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional


class StorageBackend(ABC):
    """Abstract interface for cloud storage backends."""

    @abstractmethod
    def __init__(self, credentials: Optional[dict] = None):
        """Initialize the storage backend with credentials.

        Args:
            credentials: Optional dictionary containing authentication credentials
        """
        pass

    @abstractmethod
    def sync(self, local_path: Path, remote_path: str) -> None:
        """Sync a local folder to cloud storage.

        Args:
            local_path: Path to the local folder to sync
            remote_path: Path to the remote folder in cloud storage
        """
        pass

    @abstractmethod
    def upload_file(self, local_file: Path, remote_path: str) -> None:
        """Upload a single file to cloud storage.

        Args:
            local_file: Path to the local file to upload
            remote_path: Path to the remote location in cloud storage
        """
        pass

    @abstractmethod
    def list_files(self, remote_path: str) -> List[str]:
        """List files in a remote folder.

        Args:
            remote_path: Path to the remote folder in cloud storage

        Returns:
            List of file paths in the remote folder
        """
        pass

    @abstractmethod
    def download_file(self, remote_path: str, local_file: Path) -> None:
        """Download a file from cloud storage.

        Args:
            remote_path: Path to the remote file in cloud storage
            local_file: Path to save the downloaded file locally
        """
        pass
