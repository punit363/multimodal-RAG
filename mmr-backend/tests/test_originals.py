import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import originals
from app import database
from scripts.migrate_originals_to_s3 import migrate


class FakeS3:
    def __init__(self):
        self.objects = {}

    def upload_file(self, source, bucket, key, ExtraArgs):
        self.objects[(bucket, key)] = (Path(source).read_bytes(), ExtraArgs["Metadata"])

    def head_object(self, Bucket, Key):
        body, metadata = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}

    def download_file(self, bucket, key, destination):
        Path(destination).write_bytes(self.objects[(bucket, key)][0])

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def head_bucket(self, Bucket):
        if Bucket != "test-bucket":
            raise ValueError("missing bucket")


class OriginalsTests(unittest.TestCase):
    def test_upload_download_checksum_and_delete(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as root, \
                patch.dict("os.environ", {"RAG_ORIGINALS_BUCKET": "test-bucket", "RAG_ORIGINALS_PREFIX": "sources"}), \
                patch.object(originals, "_client", return_value=client):
            source = Path(root) / "source.pdf"
            source.write_bytes(b"private source")
            originals.put("source.pdf", source)
            self.assertEqual(client.objects[("test-bucket", "sources/source.pdf")][1]["sha256"],
                             hashlib.sha256(b"private source").hexdigest())
            self.assertTrue(originals.ready())
            with originals.materialize("source.pdf", root) as temporary:
                self.assertEqual(temporary.read_bytes(), b"private source")
            self.assertFalse(temporary.exists())
            originals.delete("source.pdf")
            self.assertFalse(client.objects)

    def test_download_rejects_modified_bytes_and_cleans_temp(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as root, \
                patch.dict("os.environ", {"RAG_ORIGINALS_BUCKET": "test-bucket", "RAG_ORIGINALS_PREFIX": "sources"}), \
                patch.object(originals, "_client", return_value=client):
            source = Path(root) / "source.pdf"
            source.write_bytes(b"original")
            originals.put("source.pdf", source)
            client.objects[("test-bucket", "sources/source.pdf")] = (
                b"tampered", client.objects[("test-bucket", "sources/source.pdf")][1])
            with self.assertRaises(OSError):
                originals.download_to_temp("source.pdf", root)
            self.assertEqual(list(Path(root).glob(".source-*")), [])

    def test_rejects_unsafe_storage_name(self):
        with patch.dict("os.environ", {"RAG_ORIGINALS_BUCKET": "test-bucket"}):
            with self.assertRaises(ValueError):
                originals.delete("../other")

    def test_migration_copies_registered_originals(self):
        client = FakeS3()
        with tempfile.TemporaryDirectory() as root, \
                patch.object(database, "DB_PATH", str(Path(root) / "history.db")), \
                patch.dict("os.environ", {"RAG_ORIGINALS_BUCKET": "test-bucket", "RAG_ORIGINALS_PREFIX": "sources"}), \
                patch.object(originals, "_client", return_value=client):
            database.init_db()
            database.add_document("report.pdf", doc_id="report", storage_name="report.pdf")
            (Path(root) / "report.pdf").write_bytes(b"report")
            self.assertEqual(migrate(Path(root)), {"documents": 1, "objects_verified": 1})
            self.assertEqual(client.objects[("test-bucket", "sources/report.pdf")][0], b"report")
            (Path(root) / "report.pdf").unlink()
            with self.assertRaises(FileNotFoundError):
                migrate(Path(root))


if __name__ == "__main__":
    unittest.main()
