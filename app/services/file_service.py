"""File Service — Fase 7.4  S3/MinIO presigned upload + lifecycle

Works with real boto3 if installed + S3_* configured, else falls back to
in-memory/local stub that still returns a presigned-like URL for tests.
"""
import time
import uuid
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Simple in-memory registry for local stub
_file_registry: dict[str, dict] = {}


def _presigned_stub(file_name: str, mime_type: str, expires_in: int = 3600) -> dict:
    file_id = str(uuid.uuid4())
    token = hashlib.sha256(f"{file_id}{time.time()}".encode()).hexdigest()[:16]
    url = f"/files/presigned/{file_id}?token={token}"
    _file_registry[file_id] = {
        "file_name": file_name,
        "mime_type": mime_type,
        "expires_at": time.time() + expires_in,
        "token": token,
    }
    return {
        "file_id": file_id,
        "upload_url": url,
        "method": "PUT",
        "expires_in": expires_in,
        "headers": {"Content-Type": mime_type},
    }


def create_presigned_upload(file_name: str, mime_type: str = "application/octet-stream", expires_in: int = 3600) -> dict:
    """Create a presigned upload URL. Tries boto3 S3, falls back to stub."""
    from app.core.config import settings

    # If S3 not configured, use stub
    if not getattr(settings, "S3_BUCKET", None) or not getattr(settings, "S3_ENDPOINT", None):
        # Check if boto3 available but minimal config — still stub unless all present
        s3_bucket = getattr(settings, "S3_BUCKET", None)
        if not s3_bucket:
            return _presigned_stub(file_name, mime_type, expires_in)

    try:
        import boto3  # type: ignore

        s3 = boto3.client(
            "s3",
            endpoint_url=getattr(settings, "S3_ENDPOINT", None),
            aws_access_key_id=getattr(settings, "S3_ACCESS_KEY", None),
            aws_secret_access_key=getattr(settings, "S3_SECRET_KEY", None),
            region_name=getattr(settings, "S3_REGION", "us-east-1"),
        )
        bucket = settings.S3_BUCKET  # type: ignore
        key = f"uploads/{uuid.uuid4()}-{file_name}"
        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": mime_type},
            ExpiresIn=expires_in,
        )
        return {
            "file_id": key,
            "upload_url": url,
            "method": "PUT",
            "expires_in": expires_in,
            "headers": {"Content-Type": mime_type},
            "bucket": bucket,
            "key": key,
        }
    except Exception as e:
        logger.warning(f"S3 presigned failed, using stub: {e}")
        return _presigned_stub(file_name, mime_type, expires_in)


def get_file_info(file_id: str) -> Optional[dict]:
    return _file_registry.get(file_id)


def cleanup_expired(ttl_seconds: int = 86400) -> int:
    """Remove expired stub entries. Returns count removed."""
    now = time.time()
    to_del = [k for k, v in _file_registry.items() if v.get("expires_at", 0) < now - ttl_seconds]
    for k in to_del:
        _file_registry.pop(k, None)
    return len(to_del)
