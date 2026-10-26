"""Optional S3-compatible durable storage for validated source originals."""

import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def enabled() -> bool:
    return bool(os.getenv("RAG_ORIGINALS_BUCKET"))


def _name(storage_name: str) -> str:
    if not storage_name or Path(storage_name).name != storage_name or storage_name in {".", ".."}:
        raise ValueError("Invalid source storage name.")
    return storage_name


def _key(storage_name: str) -> str:
    prefix = os.getenv("RAG_ORIGINALS_PREFIX", "originals").strip("/")
    return f"{prefix}/{_name(storage_name)}" if prefix else _name(storage_name)


def _client():
    import boto3

    endpoint = os.getenv("RAG_S3_ENDPOINT_URL")
    return boto3.client("s3", endpoint_url=endpoint or None)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def put(storage_name: str, source: Path) -> None:
    """Upload a validated original and verify its content length and digest metadata."""
    if not enabled():
        return
    source = Path(source)
    bucket = os.environ["RAG_ORIGINALS_BUCKET"]
    key = _key(storage_name)
    size = source.stat().st_size
    digest = _digest(source)
    client = _client()
    extra = {"Metadata": {"sha256": digest}}
    encryption = os.getenv("RAG_S3_SERVER_SIDE_ENCRYPTION")
    if encryption:
        extra["ServerSideEncryption"] = encryption
    client.upload_file(str(source), bucket, key, ExtraArgs=extra)
    head = client.head_object(Bucket=bucket, Key=key)
    if head.get("ContentLength") != size or head.get("Metadata", {}).get("sha256") != digest:
        raise OSError("Uploaded original failed storage verification.")


def delete(storage_name: str) -> None:
    """Delete an object after vector cleanup, if object storage is active."""
    if enabled():
        _client().delete_object(Bucket=os.environ["RAG_ORIGINALS_BUCKET"], Key=_key(storage_name))


def download_to_temp(storage_name: str, directory: str) -> Path:
    """Fetch and checksum an original into a caller-owned temporary file."""
    if not enabled():
        raise RuntimeError("Object storage is not configured.")
    bucket = os.environ["RAG_ORIGINALS_BUCKET"]
    key = _key(storage_name)
    client = _client()
    head = client.head_object(Bucket=bucket, Key=key)
    with tempfile.NamedTemporaryFile(prefix=".source-", suffix=Path(storage_name).suffix,
                                     dir=directory, delete=False) as temporary:
        path = Path(temporary.name)
    try:
        client.download_file(bucket, key, str(path))
        if (path.stat().st_size != head.get("ContentLength")
                or _digest(path) != head.get("Metadata", {}).get("sha256")):
            raise OSError("Downloaded original failed storage verification.")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def materialize(storage_name: str, directory: str):
    """Yield a local source path and remove S3 download cache afterward."""
    if not enabled():
        yield Path(directory) / _name(storage_name)
        return
    path = download_to_temp(storage_name, directory)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def ready() -> bool:
    if not enabled():
        return True
    try:
        _client().head_bucket(Bucket=os.environ["RAG_ORIGINALS_BUCKET"])
        return True
    except Exception:
        return False
