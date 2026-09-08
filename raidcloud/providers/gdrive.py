"""Google Drive cloud provider.

Configuration keys (``providers.gdrive`` section in config.yaml)::

    enabled: true
    credentials_file: "~/.raidcloud/gdrive_credentials.json"
    token_file: "~/.raidcloud/gdrive_token.json"
    folder_id: ""         # Drive folder ID to use as root; empty = root of My Drive

The *credentials_file* is the OAuth 2.0 client secrets JSON downloaded from
Google Cloud Console (Desktop application type).

On first use ``auth()`` will open a browser for the consent flow and cache the
token in *token_file*.
"""

from __future__ import annotations

import builtins
import io
import json
from pathlib import Path

from raidcloud.providers.base import CloudProvider

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_MIME_FOLDER = "application/vnd.google-apps.folder"
_MIME_BINARY = "application/octet-stream"


class GDriveProvider(CloudProvider):
    """Store objects as files inside a Google Drive folder tree."""

    def __init__(
        self,
        credentials_file: str,
        token_file: str,
        folder_id: str = "",
    ) -> None:
        self._creds_file = Path(credentials_file).expanduser()
        self._token_file = Path(token_file).expanduser()
        self._root_folder_id = folder_id or "root"
        self._service = None  # googleapiclient.discovery.Resource

    # ------------------------------------------------------------------
    # CloudProvider interface
    # ------------------------------------------------------------------

    def auth(self) -> None:
        try:
            from google.auth.transport.requests import Request  # type: ignore[import-untyped]
            from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
            from googleapiclient.discovery import build  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "Google Drive requires: pip install google-api-python-client google-auth-oauthlib"
            ) from exc

        creds = None
        if self._token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_file), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self._creds_file.exists():
                    raise FileNotFoundError(
                        f"Google Drive credentials file not found: {self._creds_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._creds_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.touch(mode=0o600, exist_ok=True)
            self._token_file.write_text(creds.to_json())

        self._service = build("drive", "v3", credentials=creds)

    def upload(self, path: str, data: bytes) -> None:
        from googleapiclient.http import MediaIoBaseUpload  # type: ignore[import-untyped]

        parts = [p for p in path.strip("/").split("/") if p]
        filename = parts[-1]
        parent_id = self._ensure_path(parts[:-1])

        # Check if file already exists → update, else create
        existing_id = self._find_file(filename, parent_id)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=_MIME_BINARY, resumable=False)

        if existing_id:
            self._service.files().update(fileId=existing_id, media_body=media).execute()
        else:
            metadata = {"name": filename, "parents": [parent_id]}
            self._service.files().create(
                body=metadata, media_body=media, fields="id"
            ).execute()

    def download(self, path: str) -> bytes:
        file_id = self._resolve_path(path)
        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        from googleapiclient.http import MediaIoBaseDownload  # type: ignore[import-untyped]
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def delete(self, path: str) -> None:
        file_id = self._resolve_path(path)
        self._service.files().delete(fileId=file_id).execute()

    def exists(self, path: str) -> bool:
        """Resolve the path's file ID; no content is transferred."""
        try:
            self._resolve_path(path)
            return True
        except FileNotFoundError:
            return False

    def list(self, prefix: str = "") -> builtins.list[str]:
        # Walk folder tree from root (or prefix sub-folder)
        start_id = self._root_folder_id
        if prefix:
            try:
                start_id = self._resolve_path(prefix)
            except FileNotFoundError:
                return []
        return self._walk(start_id, "")

    @property
    def name(self) -> str:
        return "gdrive"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_file(self, name: str, parent_id: str) -> str | None:
        """Return Drive file ID for *name* in *parent_id*, or None."""
        q = (
            f"name = {json.dumps(name)} "
            f"and '{parent_id}' in parents "
            f"and trashed = false"
        )
        res = self._service.files().list(q=q, fields="files(id)").execute()
        files = res.get("files", [])
        return files[0]["id"] if files else None

    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        fid = self._find_file(name, parent_id)
        if fid:
            return fid
        metadata = {
            "name": name,
            "mimeType": _MIME_FOLDER,
            "parents": [parent_id],
        }
        resp = self._service.files().create(body=metadata, fields="id").execute()
        return resp["id"]

    def _ensure_path(self, parts: list[str]) -> str:
        """Ensure the folder hierarchy exists; return the leaf folder ID."""
        parent = self._root_folder_id
        for part in parts:
            parent = self._find_or_create_folder(part, parent)
        return parent

    def _resolve_path(self, path: str) -> str:
        """Return Drive file/folder ID for *path*; raise FileNotFoundError."""
        parts = [p for p in path.strip("/").split("/") if p]
        parent = self._root_folder_id
        for part in parts[:-1]:
            fid = self._find_file(part, parent)
            if not fid:
                raise FileNotFoundError(f"GDrive: path segment {part!r} not found in {path!r}")
            parent = fid
        name = parts[-1] if parts else ""
        if not name:
            return parent
        fid = self._find_file(name, parent)
        if not fid:
            raise FileNotFoundError(f"GDrive: {path!r} not found")
        return fid

    def _walk(self, folder_id: str, rel_base: str) -> builtins.list[str]:
        q = f"'{folder_id}' in parents and trashed = false"
        res = self._service.files().list(
            q=q, fields="files(id,name,mimeType)"
        ).execute()
        results: list[str] = []
        for item in res.get("files", []):
            rel = f"{rel_base}/{item['name']}".lstrip("/")
            if item["mimeType"] == _MIME_FOLDER:
                results.extend(self._walk(item["id"], rel))
            else:
                results.append(rel)
        return results

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> GDriveProvider:
        creds = cfg.get("credentials_file", "~/.raidcloud/gdrive_credentials.json")
        token = cfg.get("token_file", "~/.raidcloud/gdrive_token.json")
        folder_id = cfg.get("folder_id", "")
        return cls(credentials_file=creds, token_file=token, folder_id=folder_id)
