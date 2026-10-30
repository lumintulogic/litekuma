import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class TestStdlibFallback(unittest.TestCase):
    """Verifies that LiteKuma functions seamlessly even without httpx and pyyaml installed."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "monitors.yaml"
        self.log_path = Path(self.temp_dir.name) / "uptime.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_with_blocked_modules(self, script: str):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BASE_DIR)
        code = f"""
import sys
sys.modules['httpx'] = None
sys.modules['yaml'] = None

{script}
"""
        proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        return proc

    def test_init_without_external_dependencies(self):
        script = f"""
from litekuma.cli import main
import sys
sys.argv = ['litekuma', 'init', '-o', '{self.config_path}', '-f']
main()
"""
        proc = self._run_with_blocked_modules(script)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertTrue(self.config_path.exists())

    def test_validate_without_external_dependencies(self):
        # 1. First generate config
        self.test_init_without_external_dependencies()

        # 2. Validate without PyYAML
        script = f"""
from litekuma.cli import main
import sys
sys.argv = ['litekuma', 'validate', '-c', '{self.config_path}']
main()
"""
        proc = self._run_with_blocked_modules(script)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertIn("is valid!", proc.stdout)

    def test_check_tcp_without_external_dependencies(self):
        # Ad-hoc TCP check using standard library
        script = f"""
from litekuma.cli import main
import sys
sys.argv = ['litekuma', 'check', '-t', '1.1.1.1', '--type', 'tcp', '--port', '53', '-l', '{self.log_path}']
main()
"""
        proc = self._run_with_blocked_modules(script)
        self.assertEqual(proc.returncode, 0, f"Error: {proc.stderr}")
        self.assertTrue(self.log_path.exists())
        log_content = self.log_path.read_text(encoding="utf-8")
        self.assertIn("[UP  ]", log_content)


if __name__ == "__main__":
    unittest.main()
