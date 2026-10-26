import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("owner", "database", "openai"):
            (self.root / name).write_text("secret")
        self.config = self.root / "staging.env"
        self.config.write_text("\n".join((
            "MMD_ENVIRONMENT=staging", "MMD_WORKSPACE_ID=test-workspace",
            "MMD_PUBLIC_API_URL=https://api.example.test",
            "MMD_CORS_ORIGINS=https://app.example.test",
            "MMD_ORIGINALS_BUCKET=test-bucket", "MMD_ORIGINALS_PREFIX=test-workspace/originals",
            f"MMD_OWNER_KEY_FILE={self.root / 'owner'}",
            f"MMD_DATABASE_URL_FILE={self.root / 'database'}",
            f"MMD_OPENAI_KEY_FILE={self.root / 'openai'}",
        )))

    def tearDown(self):
        self.temporary.cleanup()

    def test_load_env_rejects_non_https_public_api(self):
        self.config.write_text(self.config.read_text().replace("https://api", "http://api"))
        with self.assertRaises(ValueError):
            release.load_env(self.config)

    def test_failed_health_check_restores_previous_images(self):
        state = self.root / "state"
        state.mkdir()
        (state / "mmdrag-staging-test-workspace.json").write_text(json.dumps({"current": "previous-sha"}))
        compose_calls = []

        def compose(_path, _project, env, *args):
            compose_calls.append((env["MMD_BACKEND_IMAGE"], args))
            if args[0] == "up" and "new-sha" in env["MMD_BACKEND_IMAGE"]:
                raise subprocess.CalledProcessError(1, "docker compose up")

        with patch.object(release, "STATE_DIR", state), \
                patch.object(release, "_compose", side_effect=compose), \
                patch.object(release, "_run"), \
                patch.object(release.subprocess, "check_output", side_effect=["", "new-sha\n"]):
            with self.assertRaises(subprocess.CalledProcessError):
                release.release(self.config)
        self.assertEqual(len([call for call in compose_calls if call[1][0] == "up"]), 2)
        self.assertIn("previous-sha", compose_calls[-1][0])
        self.assertEqual(json.loads((state / "mmdrag-staging-test-workspace.json").read_text())["current"],
                         "previous-sha")


if __name__ == "__main__":
    unittest.main()
