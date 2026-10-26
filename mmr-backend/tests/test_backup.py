import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import database
from scripts.backup import create_backup, restore_backup, verify_backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "live" / "data" / "rag_history.db"
        self.database_path.parent.mkdir(parents=True)
        self.uploads = self.root / "live" / "docs"
        self.vectors = self.root / "live" / "db" / "chroma_db"
        self.uploads.mkdir(parents=True)
        self.vectors.mkdir(parents=True)
        self.database_patch = patch.object(database, "DB_PATH", str(self.database_path))
        self.database_patch.start()
        database.init_db()
        database.add_document("report.pdf", doc_id="report", storage_name="report.pdf")
        (self.uploads / "report.pdf").write_bytes(b"%PDF-fixture")
        (self.vectors / "chroma.sqlite3").write_bytes(b"vector-fixture")

    def tearDown(self):
        self.database_patch.stop()
        self.temporary.cleanup()

    def test_backup_verifies_and_restores_isolated_state(self):
        archive = self.root / "snapshot.zip"
        manifest = create_backup(self.database_path, self.uploads, self.vectors, archive)
        self.assertEqual(manifest["schema_version"], database.SCHEMA_VERSION)
        self.assertEqual(verify_backup(archive)["members"].keys(), manifest["members"].keys())
        (self.uploads / "report.pdf").write_bytes(b"changed-live-source")
        destination = self.root / "restored"
        restore_backup(archive, destination)
        self.assertEqual((destination / "docs" / "report.pdf").read_bytes(), b"%PDF-fixture")
        self.assertEqual((destination / "db" / "chroma_db" / "chroma.sqlite3").read_bytes(), b"vector-fixture")
        with patch.object(database, "DB_PATH", str(destination / "data" / "rag_history.db")):
            self.assertEqual(database.get_document("report")["filename"], "report.pdf")
        with self.assertRaises(FileExistsError):
            restore_backup(archive, destination)
        with self.assertRaises(FileExistsError):
            create_backup(self.database_path, self.uploads, self.vectors, archive)

    def test_verify_rejects_tampered_or_missing_original(self):
        archive = self.root / "snapshot.zip"
        create_backup(self.database_path, self.uploads, self.vectors, archive)
        tampered = self.root / "tampered.zip"
        with zipfile.ZipFile(archive) as original, zipfile.ZipFile(tampered, "w") as changed:
            for name in original.namelist():
                changed.writestr(name, b"tampered" if name == "docs/report.pdf" else original.read(name))
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            verify_backup(tampered)
        with zipfile.ZipFile(archive, "a") as bundle:
            bundle.writestr("docs/extra.pdf", b"unexpected")
        with self.assertRaisesRegex(ValueError, "member list"):
            verify_backup(archive)
        archive.unlink()
        (self.uploads / "report.pdf").unlink()
        with self.assertRaisesRegex(ValueError, "missing a registered original"):
            create_backup(self.database_path, self.uploads, self.vectors, archive)
        self.assertFalse(archive.exists())
