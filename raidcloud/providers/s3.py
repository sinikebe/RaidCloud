"""AWS S3 (and S3-compatible) cloud provider.

Configuration keys (``providers.s3`` section in config.yaml)::

    enabled: true
    bucket: "my-raidcloud-bucket"
    region: "us-east-1"
    prefix: "raidcloud/"          # optional key prefix inside the bucket
    access_key_id: "AKI..."
    secret_access_key: "..."
    endpoint_url: ""              # optional, for S3-compatible services

Environment-variable overrides::

    RAIDCLOUD_S3_ACCESS_KEY_ID
    RAIDCLOUD_S3_SECRET_ACCESS_KEY
    RAIDCLOUD_S3_BUCKET
    RAIDCLOUD_S3_REGION
    RAIDCLOUD_S3_ENDPOINT_URL
"""

from __future__ import annotations

from typing import List

from raidcloud.providers.base import CloudProvider


class S3Provider(CloudProvider):
    """Store objects in an AWS S3 bucket (or any S3-compatible service)."""

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
        prefix: str = "raidcloud/",
        endpoint_url: str = "",
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._endpoint_url = endpoint_url or None
        self._s3 = None  # boto3 client, set in auth()

    # ------------------------------------------------------------------
    # CloudProvider interface
    # ------------------------------------------------------------------

    def auth(self) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "The 'boto3' package is required. Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {"region_name": self._region}
        if self._access_key_id and self._secret_access_key:
            kwargs["aws_access_key_id"] = self._access_key_id
            kwargs["aws_secret_access_key"] = self._secret_access_key
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        self._s3 = boto3.client("s3", **kwargs)
        # Light connectivity check — list up to 1 object
        self._s3.list_objects_v2(Bucket=self._bucket, MaxKeys=1)

    def upload(self, path: str, data: bytes) -> None:
        key = self._key(path)
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    def download(self, path: str) -> bytes:
        import botocore.exceptions  # type: ignore[import-untyped]

        key = self._key(path)
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"S3: key {key!r} not found") from exc
            raise

    def delete(self, path: str) -> None:
        import botocore.exceptions  # type: ignore[import-untyped]

        key = self._key(path)
        # S3 delete_object succeeds even if the key doesn't exist; check first.
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"S3: key {key!r} not found") from exc
            raise
        self._s3.delete_object(Bucket=self._bucket, Key=key)

    def list(self, prefix: str = "") -> List[str]:
        full_prefix = self._key(prefix)
        results: List[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                rel = key[len(self._prefix):]
                results.append(rel)
        return results

    @property
    def name(self) -> str:
        return "s3"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _key(self, path: str) -> str:
        return self._prefix + path.lstrip("/")

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: dict) -> "S3Provider":
        bucket = cfg.get("bucket", "")
        if not bucket:
            raise ValueError("S3 provider requires 'bucket' in config.")
        return cls(
            bucket=bucket,
            region=cfg.get("region", "us-east-1"),
            access_key_id=cfg.get("access_key_id", ""),
            secret_access_key=cfg.get("secret_access_key", ""),
            prefix=cfg.get("prefix", "raidcloud/"),
            endpoint_url=cfg.get("endpoint_url", ""),
        )
