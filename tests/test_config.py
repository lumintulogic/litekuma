import os
import tempfile
import unittest
from pathlib import Path

from litekuma.config import load_config, parse_expected_status, substitute_env_vars
from litekuma.models import LogFormat, MonitorType


class TestConfig(unittest.TestCase):
    def test_parse_expected_status(self):
        self.assertEqual(parse_expected_status(200), [200])
        self.assertEqual(parse_expected_status("200"), [200])
        self.assertEqual(parse_expected_status("200-204"), [200, 201, 202, 203, 204])
        self.assertEqual(parse_expected_status([200, 204, "301-302"]), [200, 204, 301, 302])
        self.assertEqual(parse_expected_status(None), list(range(200, 300)))

    def test_substitute_env_vars(self):
        os.environ["TEST_SECRET_API_KEY"] = "super-secret-123"
        data = {
            "token": "${TEST_SECRET_API_KEY}",
            "fallback": "${NON_EXISTENT_VAR:-default_val}",
            "empty": "${ANOTHER_NON_EXISTENT}",
            "nested": ["${TEST_SECRET_API_KEY}"],
        }
        res = substitute_env_vars(data)
        self.assertEqual(res["token"], "super-secret-123")
        self.assertEqual(res["fallback"], "default_val")
        self.assertEqual(res["empty"], "")
        self.assertEqual(res["nested"], ["super-secret-123"])

    def test_load_yaml_config_with_custom_headers(self):
        os.environ["API_HEADER_TOKEN"] = "Bearer token-xyz"
        yaml_content = """
settings:
  default_interval: 45
  default_timeout: 8.5
  state_file: /tmp/test_state.json

logging:
  file_path: /tmp/test_uptime.log
  format: text
  console: false

monitors:
  - id: custom-headers-test
    name: Custom Headers Target
    type: http
    target: "https://api.example.com/health"
    headers:
      Authorization: "${API_HEADER_TOKEN}"
      X-Custom-Header: "LiteKuma-Test"
      X-Environment: "Staging"
    expected_status: "200-202"
    keyword: "healthy"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = f.name

        try:
            cfg = load_config(config_path)
            self.assertEqual(cfg.state_file, "/tmp/test_state.json")
            self.assertEqual(cfg.logging.file_path, "/tmp/test_uptime.log")
            self.assertEqual(cfg.logging.format, LogFormat.TEXT)
            self.assertFalse(cfg.logging.console)

            self.assertEqual(len(cfg.monitors), 1)
            m = cfg.monitors[0]
            self.assertEqual(m.id, "custom-headers-test")
            self.assertEqual(m.name, "Custom Headers Target")
            self.assertEqual(m.target, "https://api.example.com/health")
            self.assertEqual(m.type, MonitorType.HTTP)
            self.assertEqual(m.interval, 45)
            self.assertEqual(m.timeout, 8.5)
            self.assertEqual(m.expected_status, [200, 201, 202])
            self.assertEqual(m.keyword, "healthy")

            # Verify custom headers
            self.assertEqual(m.headers["Authorization"], "Bearer token-xyz")
            self.assertEqual(m.headers["X-Custom-Header"], "LiteKuma-Test")
            self.assertEqual(m.headers["X-Environment"], "Staging")
        finally:
            Path(config_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
