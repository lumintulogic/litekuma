import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PYTHON_EXEC = sys.executable
BASE_DIR = Path(__file__).resolve().parent.parent


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "monitors.yaml"
        self.log_path = Path(self.temp_dir.name) / "uptime.log"
        self.state_path = Path(self.temp_dir.name) / "state.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_cli(self, args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BASE_DIR)
        cmd = [PYTHON_EXEC, "-m", "litekuma"] + args
        proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc

    def test_init_and_validate(self):
        # 1. Run init
        proc_init = self._run_cli(["init", "-o", str(self.config_path)])
        self.assertEqual(proc_init.returncode, 0)
        self.assertTrue(self.config_path.exists())
        self.assertIn("Created sample configuration", proc_init.stdout)

        # 2. Run validate on the generated file
        proc_val = self._run_cli(["validate", "-c", str(self.config_path)])
        self.assertEqual(proc_val.returncode, 0)
        self.assertIn("is valid!", proc_val.stdout)
        self.assertIn("custom headers", proc_val.stdout)

    def test_adhoc_check(self):
        proc = self._run_cli([
            "check",
            "-t", "127.0.0.1",
            "--type", "ping",
            "-l", str(self.log_path),
        ])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("LiteKuma Check Results", proc.stdout)
        self.assertTrue(self.log_path.exists())

        # Check log file contains text entry
        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("[UP  ]", log_content)
        self.assertIn("127.0.0.1", log_content)

    def test_status_command(self):
        # Create minimal state file
        self.state_path.write_text(
            """{
  "saved_at": "2026-10-29T20:00:00",
  "monitors": {
    "test-mon": {
      "monitor_id": "test-mon",
      "name": "Test Service",
      "target": "http://127.0.0.1:8000",
      "monitor_type": "http",
      "current_status": "UP",
      "previous_status": "PENDING",
      "total_checks": 10,
      "successful_checks": 9,
      "failed_checks": 1,
      "total_latency_ms": 250.0,
      "last_check_time": "2026-10-29T20:00:00",
      "last_message": "OK"
    }
  }
}""",
            encoding="utf-8",
        )

        proc = self._run_cli(["status", "-s", str(self.state_path)])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("LiteKuma Status Summary", proc.stdout)
        self.assertIn("Test Service", proc.stdout)
        self.assertIn("90.0%", proc.stdout)  # 9/10 uptime


if __name__ == "__main__":
    unittest.main()
