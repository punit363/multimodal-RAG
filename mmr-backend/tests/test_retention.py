import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app import database
from scripts.retention import main


class RetentionCommandTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as root:
            missing = Path(root) / "missing.db"
            with patch("sys.argv", ["retention", "--database", str(missing)]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main()
            self.assertFalse(missing.exists())

    def test_command_defaults_to_dry_run(self):
        with tempfile.TemporaryDirectory() as root:
            database_path = Path(root) / "registry.db"
            with patch.object(database, "DB_PATH", str(database_path)):
                database.init_db()
                output = io.StringIO()
                with patch("sys.argv", ["retention", "--database", str(database_path)]), redirect_stdout(output):
                    main()
            self.assertEqual(json.loads(output.getvalue())["mode"], "dry_run")
