"""Dropbox cloud provider.

Configuration keys (``providers.dropbox`` section in config.yaml)::

    enabled: true
    access_token: "sl.XXXX"   # long-lived token or use refresh flow

Environment-variable overrides::

    RAIDCLOUD_DROPBOX_ACCESS_TOKEN
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING

from raidcloud.providers.base import CloudProvider

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    import dropbox


class DropboxProvider(CloudProvider):
    """Store objects inside a Dropbox app folder using the Dropbox SDK."""

    def __init__(self, access_token: str, root: str = "/RaidCloud") -> None:
        """Create a provider instance.

        Args:
            access_token: Dropbox OAuth2 access token.
            root: Base path inside Dropbox (must start with ``/``).
        """
        self._token = access_token
        self._root = root.rstrip("/")
        self._client: dropbox.Dropbox | None = None

    # ------------------------------------------------------------------
    # CloudProvider interface
    # ------------------------------------------------------------------

    def auth(self) -> None:
        try:
            import dropbox  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "The 'dropbox' package is required. Install it with: pip install dropbox"
            ) from exc

        self._client = dropbox.Dropbox(self._token)
        # Verify credentials with a lightweight call
        self._client.users_get_current_account()

    def upload(self, path: str, data: bytes) -> None:
        import dropbox  # type: ignore[import-untyped]

        remote = self._full(path)
        self._client.files_upload(  # type: ignore[union-attr]
            data,
            remote,
            mode=dropbox.files.WriteMode.overwrite,
        )

    def download(self, path: str) -> bytes:
        import dropbox  # type: ignore[import-untyped]

        remote = self._full(path)
        try:
            _, response = self._client.files_download(remote)  # type: ignore[union-attr]
            return response.content
        except dropbox.exceptions.ApiError as exc:
            if exc.error.is_path() and exc.error.get_path().is_not_found():
                raise FileNotFoundError(f"Dropbox: {remote!r} not found") from exc
            raise

    def delete(self, path: str) -> None:
        import dropbox  # type: ignore[import-untyped]

        remote = self._full(path)
        try:
            self._client.files_delete_v2(remote)  # type: ignore[union-attr]
        except dropbox.exceptions.ApiError as exc:
            if exc.error.is_path_lookup() and exc.error.get_path_lookup().is_not_found():
                raise FileNotFoundError(f"Dropbox: {remote!r} not found") from exc
            raise

    def exists(self, path: str) -> bool:
        """Check existence via a metadata lookup rather than downloading."""
        import dropbox  # type: ignore[import-untyped]

        remote = self._full(path)
        try:
            self._client.files_get_metadata(remote)  # type: ignore[union-attr]
            return True
        except dropbox.exceptions.ApiError as exc:
            if exc.error.is_path() and exc.error.get_path().is_not_found():
                return False
            raise

    def list(self, prefix: str = "") -> builtins.list[str]:
        import dropbox  # type: ignore[import-untyped]

        folder = self._full(prefix) if prefix else self._root
        results: list[str] = []
        try:
            res = self._client.files_list_folder(folder, recursive=True)  # type: ignore[union-attr]
        except dropbox.exceptions.ApiError:
            return results

        while True:
            for entry in res.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    # Return path relative to root
                    rel = entry.path_lower[len(self._root):].lstrip("/")
                    results.append(rel)
            if not res.has_more:
                break
            res = self._client.files_list_folder_continue(res.cursor)  # type: ignore[union-attr]

        return results

    @property
    def name(self) -> str:
        return "dropbox"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _full(self, path: str) -> str:
        """Resolve a relative path to an absolute Dropbox path."""
        clean = path.lstrip("/")
        return f"{self._root}/{clean}" if clean else self._root

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> DropboxProvider:
        token = cfg.get("access_token", "")
        if not token:
            raise ValueError("Dropbox provider requires 'access_token' in config.")
        root = cfg.get("root", "/RaidCloud")
        return cls(access_token=token, root=root)
