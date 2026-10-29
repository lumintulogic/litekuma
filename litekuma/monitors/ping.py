from __future__ import annotations

import asyncio
import re
import sys
import time

from litekuma.models import CheckResult, MonitorConfig, Status
from litekuma.monitors.base import BaseMonitor

RTT_PATTERN = re.compile(r"(?:rtt|round-trip)\s+(?:min/avg/max/(?:mdev|stddev))\s*=\s*[\d\.]+/([\d\.]+)/")


class PingMonitor(BaseMonitor):
    """ICMP Ping monitor utilizing system ping utility."""

    async def perform_check(self) -> CheckResult:
        host = self.config.target
        start_time = time.perf_counter()

        timeout_sec = max(1, int(self.config.timeout))
        cmd = ["ping", "-c", "1", "-W", str(timeout_sec), host]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.config.timeout + 1.0,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if proc.returncode == 0:
                out_str = stdout.decode("utf-8", errors="ignore")
                match = RTT_PATTERN.search(out_str)
                if match:
                    try:
                        elapsed_ms = float(match.group(1))
                    except ValueError:
                        pass

                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=host,
                    monitor_type=self.config.type,
                    status=Status.UP,
                    latency_ms=elapsed_ms,
                    message=f"Ping reply received ({elapsed_ms:.1f}ms)",
                )
            else:
                err_str = stderr.decode("utf-8", errors="ignore").strip() or stdout.decode("utf-8", errors="ignore").strip()
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=host,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message=f"Ping failed (exit code {proc.returncode}): {err_str[:120]}",
                )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=host,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Ping timed out after {self.config.timeout:.1f}s",
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=host,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Ping execution error: {str(exc)}",
            )
