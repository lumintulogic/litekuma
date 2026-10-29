import asyncio
import socket
import unittest

from litekuma.models import CheckResult, MonitorConfig, MonitorType, Status
from litekuma.monitors.tcp import TcpMonitor


class TestTcpMonitor(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Bind a local TCP server
        self.server = await asyncio.start_server(self._handle_client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def _handle_client(self, reader, writer):
        writer.close()
        await writer.wait_closed()

    async def test_tcp_port_open(self):
        config = MonitorConfig(
            id="tcp-test",
            name="TCP Test",
            target="127.0.0.1",
            type=MonitorType.TCP,
            port=self.port,
            timeout=2.0,
        )
        monitor = TcpMonitor(config)
        result: CheckResult = await monitor.check()

        self.assertEqual(result.status, Status.UP)
        self.assertIn("open and reachable", result.message)
        self.assertGreater(result.latency_ms, 0)

    async def test_tcp_port_closed(self):
        # Pick an unused port by creating and closing a socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        closed_port = s.getsockname()[1]
        s.close()

        config = MonitorConfig(
            id="tcp-closed",
            name="TCP Closed",
            target="127.0.0.1",
            type=MonitorType.TCP,
            port=closed_port,
            timeout=1.0,
        )
        monitor = TcpMonitor(config)
        result = await monitor.check()

        self.assertEqual(result.status, Status.DOWN)
        self.assertIn("failed", result.message.lower())


if __name__ == "__main__":
    unittest.main()
