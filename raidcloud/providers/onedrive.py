"""OneDrive (Microsoft Graph) cloud provider.

Configuration keys (``providers.onedrive`` section in config.yaml)::

    enabled: true
    client_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    tenant_id: "common"           # or your AAD tenant GUID
    token_cache_file: "~/.raidcloud/onedrive_token.json"
    root_path: "/drive/root:/RaidCloud"   # Graph API path prefix

On first use ``auth()`` will open a browser for the interactive login flow
and cache the token in *token_cache_file*.

Environment-variable overrides::

    RAIDCLOUD_ONEDRIVE_CLIENT_ID
    RAIDCLOUD_ONEDRIVE_TENANT_ID
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import requests

from raidcloud.providers.base import CloudProvider

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = ["Files.ReadWrite", "offline_access"]


class OneDriveProvider(CloudProvider):
    """Store objects as files in a OneDrive folder via Microsoft Graph API."""

    def __init__(
        self,
        client_id: str,
        tenant_id: str = "common",
        token_cache_file: str = "~/.raidcloud/onedrive_token.json",
        root_path: str = "/drive/root:/RaidCloud",
    ) -> None:
        self._client_id = client_id
        self._tenant_id = tenant_id
        self._cache_path = Path(token_cache_file).expanduser()
        # root_path: Graph path to root folder, e.g. "/drive/root:/RaidCloud"
        self._root_path = root_path.rstrip(":/")
        self._token: str = ""
        self._app = None  # msal.PublicClientApplication

    # ------------------------------------------------------------------
    # CloudProvider interface
    # ------------------------------------------------------------------

    def auth(self) -> None:
        try:
            import msal  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "OneDrive provider requires: pip install msal"
            ) from exc

        cache = msal.SerializableTokenCache()
        if self._cache_path.exists():
            cache.deserialize(self._cache_path.read_text())

        self._app = msal.PublicClientApplication(
            self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            token_cache=cache,
        )

        token_response = self._acquire_token()
        if "error" in token_response:
            raise RuntimeError(f"OneDrive auth failed: {token_response.get('error_description')}")

        self._token = token_response["access_token"]
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.touch(mode=0o600, exist_ok=True)
        self._cache_path.write_text(cache.serialize())

    def upload(self, path: str, data: bytes) -> None:
        # Graph "upload or replace" via PUT for files ≤4 MiB
        url = self._item_url(path) + "/content"
        self._request("PUT", url, data=data)

    def download(self, path: str) -> bytes:
        url = self._item_url(path) + "/content"
        resp = self._request("GET", url, stream=True)
        return resp.content

    def delete(self, path: str) -> None:
        url = self._item_url(path)
        self._request("DELETE", url, expect_no_body=True)

    def list(self, prefix: str = "") -> builtins.list[str]:
        base = f"{self._root_path}/{prefix}".rstrip("/") if prefix else self._root_path
        return self._walk(base, "")

    @property
    def name(self) -> str:
        return "onedrive"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _item_url(self, path: str) -> str:
        clean = path.strip("/")
        full = f"{self._root_path}/{clean}" if clean else self._root_path
        return f"{_GRAPH_BASE}/me{full}:"

    def _request(
        self,
        method: str,
        url: str,
        data: bytes | None = None,
        stream: bool = False,
        expect_no_body: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/octet-stream"
        resp = requests.request(
            method, url, headers=headers, data=data, stream=stream, **kwargs
        )
        if resp.status_code == 404:
            raise FileNotFoundError(f"OneDrive: {url!r} not found")
        if not expect_no_body:
            resp.raise_for_status()
        elif resp.status_code not in (200, 204):
            resp.raise_for_status()
        return resp

    def _walk(self, graph_path: str, rel_base: str) -> builtins.list[str]:
        url = f"{_GRAPH_BASE}/me{graph_path}:/children"
        try:
            resp = self._request("GET", url)
        except FileNotFoundError:
            return []
        items = resp.json().get("value", [])
        results: list[str] = []
        for item in items:
            rel = f"{rel_base}/{item['name']}".lstrip("/")
            if "folder" in item:
                child_path = f"{graph_path}/{item['name']}"
                results.extend(self._walk(child_path, rel))
            else:
                results.append(rel)
        return results

    def _acquire_token(self) -> dict:
        accounts = self._app.get_accounts()
        if accounts:
            result = self._app.acquire_token_silent(_SCOPES, account=accounts[0])
            if result:
                return result
        # Interactive device-code flow (works in headless/server environments)
        flow = self._app.initiate_device_flow(scopes=_SCOPES)
        print(flow["message"])  # "Go to https://... and enter code XXXXX"
        return self._app.acquire_token_by_device_flow(flow)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> OneDriveProvider:
        client_id = cfg.get("client_id", "")
        if not client_id:
            raise ValueError("OneDrive provider requires 'client_id' in config.")
        return cls(
            client_id=client_id,
            tenant_id=cfg.get("tenant_id", "common"),
            token_cache_file=cfg.get("token_cache_file", "~/.raidcloud/onedrive_token.json"),
            root_path=cfg.get("root_path", "/drive/root:/RaidCloud"),
        )
