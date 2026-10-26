import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.deployment import validate_deployment_config
from app.secrets import load_managed_secrets, load_secret_files


class DeploymentTests(unittest.TestCase):
    def test_production_rejects_unsafe_defaults(self):
        with patch.dict(os.environ, {"RAG_DEPLOYMENT_MODE": "production", "RAG_OWNER_API_KEY": "short",
                                  "RAG_DATABASE_URL": "", "RAG_ORIGINALS_BUCKET": "",
                                  "RAG_WORKSPACE_ID": "default", "RAG_COOKIE_SECURE": "false",
                                  "RAG_INGEST_MODE": "inline", "RAG_CORS_ORIGINS": "http://localhost:3000"}):
            with self.assertRaises(RuntimeError) as failure:
                validate_deployment_config()
        self.assertIn("RAG_DATABASE_URL", str(failure.exception))
        self.assertIn("RAG_COOKIE_SECURE", str(failure.exception))

    def test_staging_accepts_isolated_settings(self):
        with patch.dict(os.environ, {"RAG_DEPLOYMENT_MODE": "staging", "RAG_OWNER_API_KEY": "o" * 40,
                                  "RAG_DATABASE_URL": "postgresql://localhost/db", "RAG_ORIGINALS_BUCKET": "bucket",
                                  "RAG_WORKSPACE_ID": "staging-team", "RAG_ORIGINALS_PREFIX": "staging-team/originals",
                                  "RAG_COOKIE_SECURE": "true",
                                  "RAG_INGEST_MODE": "worker", "RAG_CORS_ORIGINS": "https://app.example.test"}):
            validate_deployment_config()

    def test_secret_file_loading_and_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            secret = Path(root) / "key"
            secret.write_text("private-value\n")
            with patch.dict(os.environ, {"RAG_OWNER_API_KEY_FILE": str(secret), "RAG_OWNER_API_KEY": ""}):
                load_secret_files()
                self.assertEqual(os.environ["RAG_OWNER_API_KEY"], "private-value")
                with self.assertRaises(RuntimeError):
                    load_secret_files()

    def test_managed_secret_loader_accepts_allowlisted_keys(self):
        payload = {"SecretString": '{"OPENAI_API_KEY":"managed-key"}'}
        with patch.dict(os.environ, {"RAG_SECRETS_MANAGER_ID": "staging/keys", "OPENAI_API_KEY": ""}), \
                patch("boto3.client") as client:
            client.return_value.get_secret_value.return_value = payload
            load_managed_secrets()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "managed-key")
            client.return_value.get_secret_value.assert_called_once_with(SecretId="staging/keys")


if __name__ == "__main__":
    unittest.main()
