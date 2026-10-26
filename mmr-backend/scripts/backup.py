"""Offline, checksum-verified bundle for the local SQLite/uploads/Chroma state."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.database import SCHEMA_VERSION


MANIFEST = "manifest.json"
DATABASE_MEMBER = "data/rag_history.db"


def _digest(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


def _check_database(path: Path) -> int:
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed.")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported SQLite schema version: {version}.")
        conn.execute("SELECT id FROM documents LIMIT 1").fetchone()
    return version


def _source_files(directory: Path, prefix: str):
    if not directory.is_dir():
        raise FileNotFoundError(f"Required directory is missing: {directory}")
    for root, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            if (Path(root) / name).is_symlink():
                raise ValueError("Backup input contains a symlink.")
        for name in sorted(files):
            source = Path(root) / name
            member = PurePosixPath(prefix, *source.relative_to(directory).parts).as_posix()
            yield member, source


def _write_member(bundle: zipfile.ZipFile, member: str, source: Path) -> dict:
    bundle.write(source, arcname=member)
    with bundle.open(member) as stream:
        digest, size = _digest(stream)
    return {"sha256": digest, "size": size}


def create_backup(database: Path, uploads: Path, vectors: Path, archive: Path) -> dict:
    """Bundle an offline deployment; refuse to replace any existing archive."""
    database, uploads, vectors, archive = map(Path, (database, uploads, vectors, archive))
    if archive.exists():
        raise FileExistsError("Backup archive already exists.")
    if not database.is_file():
        raise FileNotFoundError("SQLite database is missing.")
    for directory in (uploads, vectors):
        if archive.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Backup archive cannot be inside a source directory.")
    _check_database(database)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=archive.parent) as stage:
        snapshot = Path(stage) / "rag_history.db"
        with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as source, sqlite3.connect(snapshot) as target:
            source.backup(target)
        _check_database(snapshot)
        temporary_archive = Path(stage) / "backup.zip"
        members = {}
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as bundle:
            members[DATABASE_MEMBER] = _write_member(bundle, DATABASE_MEMBER, snapshot)
            for directory, prefix in ((uploads, "docs"), (vectors, "db/chroma_db")):
                for member, source in _source_files(directory, prefix):
                    members[member] = _write_member(bundle, member, source)
            manifest = {"format_version": 1, "schema_version": SCHEMA_VERSION,
                        "created_at": datetime.now(timezone.utc).isoformat(), "members": members}
            bundle.writestr(MANIFEST, json.dumps(manifest, sort_keys=True))
        verify_backup(temporary_archive)
        os.replace(temporary_archive, archive)
    return manifest


def verify_backup(archive: Path) -> dict:
    """Verify exact member set, checksums, SQLite schema, and registered originals."""
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or MANIFEST not in names:
            raise ValueError("Backup has missing or duplicate members.")
        manifest = json.loads(bundle.read(MANIFEST))
        if manifest.get("format_version") != 1 or manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported backup format or schema version.")
        members = manifest.get("members")
        if not isinstance(members, dict) or set(names) != set(members) | {MANIFEST} or DATABASE_MEMBER not in members:
            raise ValueError("Backup member list does not match its manifest.")
        for name, details in members.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not (
                name == DATABASE_MEMBER or name.startswith("docs/") or name.startswith("db/chroma_db/")
            ):
                raise ValueError("Unsafe backup member path.")
            info = bundle.getinfo(name)
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Backup contains a link or directory member.")
            with bundle.open(name) as stream:
                digest, size = _digest(stream)
            if digest != details.get("sha256") or size != details.get("size"):
                raise ValueError(f"Backup checksum mismatch: {name}")
        with tempfile.TemporaryDirectory() as stage:
            snapshot = Path(stage) / "database.db"
            with bundle.open(DATABASE_MEMBER) as source, snapshot.open("wb") as target:
                shutil.copyfileobj(source, target)
            _check_database(snapshot)
            with sqlite3.connect(snapshot) as conn:
                for (storage_name,) in conn.execute("SELECT storage_name FROM documents WHERE status = 'ready'"):
                    if not storage_name or Path(storage_name).name != storage_name or f"docs/{storage_name}" not in members:
                        raise ValueError("Backup is missing a registered original.")
    return manifest


def restore_backup(archive: Path, destination: Path) -> dict:
    """Restore only into a new directory after full archive verification."""
    archive, destination = Path(archive), Path(destination)
    manifest = verify_backup(archive)
    if destination.exists():
        raise FileExistsError("Restore destination already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".rag-restore-") as stage:
        root = Path(stage)
        with zipfile.ZipFile(archive) as bundle:
            for member in manifest["members"]:
                target = root.joinpath(*PurePosixPath(member).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        (root / "docs").mkdir(exist_ok=True)
        (root / "db" / "chroma_db").mkdir(parents=True, exist_ok=True)
        os.replace(root, destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, verify, or restore an offline local-state backup.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--database", required=True, type=Path)
    create.add_argument("--uploads", required=True, type=Path)
    create.add_argument("--vectors", required=True, type=Path)
    create.add_argument("--archive", required=True, type=Path)
    create.add_argument("--offline-confirmed", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True, type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    restore.add_argument("--offline-confirmed", action="store_true")
    args = parser.parse_args()
    if args.command in {"create", "restore"} and not args.offline_confirmed:
        parser.error("Stop the application and pass --offline-confirmed to create or restore state.")
    if args.command == "create":
        result = create_backup(args.database, args.uploads, args.vectors, args.archive)
    elif args.command == "verify":
        result = verify_backup(args.archive)
    else:
        result = restore_backup(args.archive, args.destination)
    print(json.dumps({"status": "ok", "command": args.command, "members": len(result["members"]),
                      "schema_version": result["schema_version"]}, sort_keys=True))


if __name__ == "__main__":
    main()
