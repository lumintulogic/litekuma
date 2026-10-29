from __future__ import annotations

import asyncio
import time
from datetime import datetime

from litekuma.models import CheckResult, MonitorConfig, Status
from litekuma.monitors.base import BaseMonitor


class TcpMonitor(BaseMonitor):
    """TCP Port monitor testing socket connection to host:port."""

    async def perform_check(self) -> CheckResult:
        host = self.config.target
        port = self.config.port
        if port is None:
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=0.0,
                message="TCP port not configured",
            )

        start_time = time.perf_counter()
        try:
            conn = asyncio.open_connection(host=host, port=port)
            reader, writer = await asyncio.wait_for(conn, timeout=self.config.timeout)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=f"{host}:{port}",
                monitor_type=self.config.type,
                status=Status.UP,
                latency_ms=elapsed_ms,
                message=f"TCP port {port} open and reachable",
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=f"{host}:{port}",
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Connection timed out after {self.config.timeout:.1f}s",
            )
        except OSError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=f"{host}:{port}",
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Connection failed: {str(exc)}",
            )
