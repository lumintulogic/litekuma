import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from litekuma.logger import UptimeLogger
from litekuma.models import CheckResult, LogFormat, LoggingConfig, MonitorType, Status


class TestLogger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "uptime.log"
        self.event_file = Path(self.temp_dir.name) / "events.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_text_format_logging(self):
        config = LoggingConfig(
            file_path=str(self.log_file),
            format=LogFormat.TEXT,
            console=False,
        )
        logger = UptimeLogger(config)

        res = CheckResult(
            monitor_id="api-check",
            name="Production API",
            target="https://api.example.com",
            monitor_type=MonitorType.HTTP,
            status=Status.UP,
            latency_ms=45.2,
            timestamp=datetime(2026, 10, 29, 20, 0, 0),
            status_code=200,
            message="OK",
        )
        logger.log_result(res)
        logger.close()

        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("[2026-10-29 20:00:00]", content)
        self.assertIn("[UP  ]", content)
        self.assertIn("[HTTP 200]", content)
        self.assertIn("Production API (https://api.example.com) - OK", content)

    def test_event_logging(self):
        config = LoggingConfig(
            file_path=str(self.log_file),
            event_file_path=str(self.event_file),
            format=LogFormat.TEXT,
            console=False,
        )
        logger = UptimeLogger(config)

        ts = datetime(2026, 10, 29, 20, 5, 0)
        logger.log_event("DOWN ALERT", "Database Server", "Connection refused on port 5432", ts)
        logger.close()

        main_log = self.log_file.read_text(encoding="utf-8")
        event_log = self.event_file.read_text(encoding="utf-8")

        expected = "[2026-10-29 20:05:00] [DOWN ALERT] Database Server: Connection refused on port 5432\n"
        self.assertEqual(main_log, expected)
        self.assertEqual(event_log, expected)

    def test_json_format_logging(self):
        config = LoggingConfig(
            file_path=str(self.log_file),
            format=LogFormat.JSON,
            console=False,
        )
        logger = UptimeLogger(config)

        res = CheckResult(
            monitor_id="auth-service",
            name="Auth Service",
            target="https://auth.internal",
            monitor_type=MonitorType.HTTP,
            status=Status.DOWN,
            latency_ms=105.4,
            timestamp=datetime(2026, 10, 29, 20, 10, 0),
            status_code=503,
            message="Service Unavailable",
            details={"retry_after": 30},
        )
        logger.log_result(res)
        logger.close()

        line = self.log_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        self.assertEqual(data["monitor_id"], "auth-service")
        self.assertEqual(data["status"], "DOWN")
        self.assertEqual(data["status_code"], 503)
        self.assertEqual(data["message"], "Service Unavailable")
        self.assertEqual(data["details"]["retry_after"], 30)

    def test_tsv_format_logging(self):
        config = LoggingConfig(
            file_path=str(self.log_file),
            format=LogFormat.TSV,
            console=False,
        )
        logger = UptimeLogger(config)

        res = CheckResult(
            monitor_id="dns-check",
            name="Internal DNS",
            target="dns.corp",
            monitor_type=MonitorType.DNS,
            status=Status.UP,
            latency_ms=12.0,
            timestamp=datetime(2026, 10, 29, 20, 15, 0),
            message="Resolved successfully",
        )
        logger.log_result(res)
        logger.close()

        line = self.log_file.read_text(encoding="utf-8").strip()
        parts = line.split("\t")
        self.assertEqual(parts[0], "2026-10-29 20:15:00")
        self.assertEqual(parts[1], "UP")
        self.assertEqual(parts[2], "dns-check")
        self.assertEqual(parts[5], "dns")
        self.assertEqual(parts[6], "-")  # no HTTP code
        self.assertEqual(parts[8], "Resolved successfully")

    def test_rotation(self):
        config = LoggingConfig(
            file_path=str(self.log_file),
            format=LogFormat.TEXT,
            max_bytes=100,  # small max bytes to trigger rotation
            backup_count=2,
            console=False,
        )
        logger = UptimeLogger(config)

        for i in range(15):
            res = CheckResult(
                monitor_id=f"mon-{i}",
                name=f"Monitor Number {i}",
                target=f"https://example{i}.com",
                monitor_type=MonitorType.HTTP,
                status=Status.UP,
                latency_ms=10.0,
                status_code=200,
                message="OK",
            )
            logger.log_result(res)

        logger.close()

        # Check that backup files were generated
        backup_1 = Path(str(self.log_file) + ".1")
        self.assertTrue(backup_1.exists(), "Rotated backup file should exist")


if __name__ == "__main__":
    unittest.main()
