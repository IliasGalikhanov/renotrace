"""Private object-store adapters. Keys and service credentials never reach the UI."""

import os
import secrets
from typing import Protocol

import boto3  # type: ignore[import-untyped]
import httpx2 as httpx
from botocore.config import Config  # type: ignore[import-untyped]


class Objects(Protocol):
    def put(self, key: str, content: bytes, media_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class SupabaseObjects:
    def __init__(self, url: str, service_key: str, bucket: str) -> None:
        self.url = url.rstrip("/") + "/storage/v1/object"
        self.bucket = bucket
        self.client = httpx.Client(
            headers={"Authorization": f"Bearer {service_key}", "apikey": service_key},
            timeout=20,
            follow_redirects=False,
        )

    def put(self, key: str, content: bytes, media_type: str) -> None:
        response = self.client.post(
            f"{self.url}/{self.bucket}/{key}",
            content=content,
            headers={"Content-Type": media_type, "x-upsert": "false", "Cache-Control": "no-store"},
        )
        response.raise_for_status()

    def get(self, key: str) -> bytes:
        response = self.client.get(
            f"{self.url}/authenticated/{self.bucket}/{key}",
            params={"cacheNonce": secrets.token_hex(12)},
            headers={"Cache-Control": "no-store"},
        )
        response.raise_for_status()
        return response.content

    def delete(self, key: str) -> None:
        response = self.client.request(
            "DELETE", f"{self.url}/{self.bucket}", json={"prefixes": [key]}
        )
        response.raise_for_status()


class S3Objects:
    """S3-compatible private storage; local integration tests use real SeaweedFS."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=20,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )

    def put(self, key: str, content: bytes, media_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=media_type,
            IfNoneMatch="*",
            CacheControl="no-store",
        )

    def get(self, key: str) -> bytes:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        try:
            return bytes(body.read())
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def configured_store() -> Objects:
    bucket = os.environ.get("REVIEW_STORAGE_BUCKET", "guest-originals")
    if os.environ.get("SUPABASE_URL"):
        return SupabaseObjects(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"], bucket
        )
    return S3Objects(
        os.environ["S3_ENDPOINT"], os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"], bucket
    )
