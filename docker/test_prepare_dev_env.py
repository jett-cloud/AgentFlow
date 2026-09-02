from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = REPOSITORY_ROOT / "docker" / "prepare_dev_env.py"
LOCAL_COMPOSE = REPOSITORY_ROOT / "docker" / "docker-compose.local.yaml"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class PrepareDevEnvTest(unittest.TestCase):
    def test_local_compose_builds_repository_backends_and_exposes_api(self) -> None:
        self.assertTrue(LOCAL_COMPOSE.is_file(), "local Compose override is missing")
        content = LOCAL_COMPOSE.read_text(encoding="utf-8")
        self.assertIn("context: ..", content)
        self.assertIn("dockerfile: api/Dockerfile", content)
        self.assertIn('"5001:5001"', content)
        self.assertIn("dockerfile: dify-agent/Dockerfile", content)
        self.assertIn("context: ../dify-agent-runtime", content)
        self.assertIn("dockerfile: docker/Dockerfile", content)

    def test_generates_consistent_secrets_and_refuses_to_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / ".env"
            command = [sys.executable, str(PREPARE_SCRIPT), "--output", str(output)]

            first = subprocess.run(command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)

            self.assertEqual(first.returncode, 0, first.stderr)
            content = output.read_text(encoding="utf-8")
            values = parse_env(output)
            self.assertNotIn("CHANGE_ME_", content)
            for left, right in (
                ("CODE_EXECUTION_API_KEY", "SANDBOX_API_KEY"),
                ("WEAVIATE_API_KEY", "WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS"),
                ("PLUGIN_DAEMON_KEY", "DIFY_AGENT_PLUGIN_DAEMON_API_KEY"),
                ("PLUGIN_DIFY_INNER_API_KEY", "DIFY_AGENT_INNER_API_KEY"),
            ):
                self.assertEqual(values[left], values[right])
                self.assertGreaterEqual(len(values[left]), 32)

            original = output.read_bytes()
            second = subprocess.run(command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
