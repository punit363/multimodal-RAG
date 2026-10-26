import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.workspace import bind_vector_directory
from app import database


class WorkspaceTests(unittest.TestCase):
    def test_vector_directory_cannot_change_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            directory = str(Path(root) / "vectors")
            bind_vector_directory(directory, "team-a")
            bind_vector_directory(directory, "team-a")
            with self.assertRaises(RuntimeError):
                bind_vector_directory(directory, "team-b")

    def test_database_cannot_change_workspace(self):
        with tempfile.TemporaryDirectory() as root, patch.object(database, "DB_PATH", str(Path(root) / "history.db")):
            with patch.dict("os.environ", {"RAG_WORKSPACE_ID": "team-a"}):
                database.init_db()
            with patch.dict("os.environ", {"RAG_WORKSPACE_ID": "team-b"}):
                with self.assertRaises(RuntimeError):
                    database.init_db()
