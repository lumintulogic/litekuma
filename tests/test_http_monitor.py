import asyncio
import http.server
import socket
import threading
import unittest

from litekuma.models import CheckResult, MonitorConfig, MonitorType, Status
from litekuma.monitors.http import HttpMonitor


class MockServerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # Echo back received headers in body or handle special endpoints
        if self.path == "/test-headers":
            auth_header = self.headers.get("Authorization", "")
            custom_hdr = self.headers.get("X-Custom-Test", "")
            response_body = f"Auth:{auth_header}|Custom:{custom_hdr}|LiteKuma-Success"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(response_body.encode("utf-8"))
        elif self.path == "/error500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Error")
        elif self.path == "/slow":
            # Delay response to test timeout
            import time
            time.sleep(1.0)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Delayed")
            except Exception:
                pass
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    def log_message(self, format, *args):
        # Silence standard HTTP server output
        pass


class TestHttpMonitor(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Start a local HTTP server on an ephemeral port
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockServerHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    async def test_custom_headers_and_keyword_success(self):
        config = MonitorConfig(
            id="test-headers",
            name="Test Headers Target",
            target=f"http://127.0.0.1:{self.port}/test-headers",
            type=MonitorType.HTTP,
            headers={
                "Authorization": "Bearer token12345",
                "X-Custom-Test": "MyValue99",
            },
            keyword="Auth:Bearer token12345|Custom:MyValue99|LiteKuma-Success",
            expected_status=[200],
        )
        monitor = HttpMonitor(config)
        result: CheckResult = await monitor.check()

        self.assertEqual(result.status, Status.UP)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.message, "OK")
        self.assertGreater(result.latency_ms, 0)

    async def test_status_code_mismatch_down(self):
        config = MonitorConfig(
            id="test-error",
            name="Test Error Target",
            target=f"http://127.0.0.1:{self.port}/error500",
            type=MonitorType.HTTP,
            expected_status=[200, 201],
        )
        monitor = HttpMonitor(config)
        result = await monitor.check()

        self.assertEqual(result.status, Status.DOWN)
        self.assertEqual(result.status_code, 500)
        self.assertIn("not in expected list", result.message)

    async def test_keyword_missing_down(self):
        config = MonitorConfig(
            id="test-keyword-fail",
            name="Test Keyword Fail",
            target=f"http://127.0.0.1:{self.port}/test-headers",
            type=MonitorType.HTTP,
            keyword="NonExistentKeywordXYZ",
        )
        monitor = HttpMonitor(config)
        result = await monitor.check()

        self.assertEqual(result.status, Status.DOWN)
        self.assertIn("Keyword check failed", result.message)

    async def test_inverted_keyword(self):
        config = MonitorConfig(
            id="test-invert-kw",
            name="Test Invert KW",
            target=f"http://127.0.0.1:{self.port}/test-headers",
            type=MonitorType.HTTP,
            headers={"X-Custom-Test": "ForbiddenWord"},
            keyword="ForbiddenWord",
            invert_keyword=True,
        )
        monitor = HttpMonitor(config)
        result = await monitor.check()

        self.assertEqual(result.status, Status.DOWN)
        self.assertIn("Inverted keyword check failed", result.message)

    async def test_timeout(self):
        config = MonitorConfig(
            id="test-timeout",
            name="Test Timeout Target",
            target=f"http://127.0.0.1:{self.port}/slow",
            type=MonitorType.HTTP,
            timeout=0.2,
        )
        monitor = HttpMonitor(config)
        result = await monitor.check()

        self.assertEqual(result.status, Status.DOWN)
        self.assertIn("timed out", result.message)


if __name__ == "__main__":
    unittest.main()
