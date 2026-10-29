import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from litekuma.engine import MonitorEngine
from litekuma.models import CheckResult, LoggingConfig, MonitorConfig, MonitorType, NotifierConfig, Status, SystemConfig


class TestEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp_dir.name) / "state.json"
        self.log_file = Path(self.temp_dir.name) / "uptime.log"

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_engine_check_once(self):
        cfg = SystemConfig(
            state_file=str(self.state_file),
            logging=LoggingConfig(file_path=str(self.log_file), console=False),
            monitors=[
                MonitorConfig(
                    id="test-google",
                    name="Google DNS Ping",
                    type=MonitorType.TCP,
                    target="8.8.8.8",
                    port=53,
                    timeout=2.0,
                )
            ],
        )

        engine = MonitorEngine(cfg)
        results = await engine.check_once()

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.monitor_id, "test-google")
        self.assertEqual(r.status, Status.UP)

        # Verify state file was written
        self.assertTrue(self.state_file.exists())
        # Verify text log file was written
        self.assertTrue(self.log_file.exists())
        content = self.log_file.read_text(encoding="utf-8")
        self.assertIn("Google DNS Ping", content)
        self.assertIn("[UP  ]", content)

    async def test_retry_logic_and_state_transition(self):
        # Create a mock monitor that fails twice then succeeds, or fails max_retries times
        cfg = SystemConfig(
            state_file=str(self.state_file),
            logging=LoggingConfig(file_path=str(self.log_file), console=False),
            monitors=[
                MonitorConfig(
                    id="flaky-mon",
                    name="Flaky Monitor",
                    type=MonitorType.HTTP,
                    target="http://fake.local",
                    max_retries=2,
                    retry_interval=0.01,
                )
            ],
            notifiers=[
                NotifierConfig(
                    id="mock-notifier",
                    type="webhook",
                    url="http://fake.webhook",
                    notify_on_down=True,
                    notify_on_recovery=True,
                )
            ],
        )

        engine = MonitorEngine(cfg)
        monitor = engine._monitors["flaky-mon"]

        # Mock the monitor's check method to return DOWN
        down_result = CheckResult(
            monitor_id="flaky-mon",
            name="Flaky Monitor",
            target="http://fake.local",
            monitor_type=MonitorType.HTTP,
            status=Status.DOWN,
            latency_ms=10.0,
            message="Server Error 500",
        )
        up_result = CheckResult(
            monitor_id="flaky-mon",
            name="Flaky Monitor",
            target="http://fake.local",
            monitor_type=MonitorType.HTTP,
            status=Status.UP,
            latency_ms=15.0,
            message="OK",
        )

        notifier = engine._notifiers["mock-notifier"]
        notifier.notify = AsyncMock(return_value=True)

        # 1. First execution: fails -> transitions from PENDING to DOWN
        with patch.object(monitor, "check", AsyncMock(return_value=down_result)):
            res1 = await engine.execute_monitor_check(monitor)
            self.assertEqual(res1.status, Status.DOWN)

        # In first run, previous status was PENDING, so no alert notification yet
        self.assertEqual(notifier.notify.call_count, 0)

        # 2. Now run again while DOWN: transitions DOWN -> UP (RECOVERY)
        with patch.object(monitor, "check", AsyncMock(return_value=up_result)):
            res2 = await engine.execute_monitor_check(monitor)
            self.assertEqual(res2.status, Status.UP)

        # Notification should have triggered for recovery!
        self.assertEqual(notifier.notify.call_count, 1)
        args, kwargs = notifier.notify.call_args
        self.assertEqual(args[0].status, Status.UP)
        self.assertEqual(args[1], Status.DOWN)
        self.assertTrue(args[2])  # is_recovery is True

        # Check uptime statistics in StateManager
        stats = engine.state_mgr.monitors["flaky-mon"]
        self.assertEqual(stats.total_checks, 2)
        self.assertEqual(stats.successful_checks, 1)
        self.assertEqual(stats.failed_checks, 1)
        self.assertEqual(stats.uptime_percentage, 50.0)
        engine.logger.close()


if __name__ == "__main__":
    unittest.main()
