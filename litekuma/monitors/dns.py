from __future__ import annotations

import asyncio
import socket
import time

from litekuma.models import CheckResult, MonitorConfig, Status
from litekuma.monitors.base import BaseMonitor


class DnsMonitor(BaseMonitor):
    """DNS resolution monitor testing if domain resolves or matches expected record."""

    async def perform_check(self) -> CheckResult:
        host = self.config.target
        start_time = time.perf_counter()
        loop = asyncio.get_running_loop()

        try:
            # If nameserver is custom, or just standard resolver
            addr_info = await asyncio.wait_for(
                loop.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
                timeout=self.config.timeout,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            resolved_ips = list({info[4][0] for info in addr_info if info[4]})

            if not resolved_ips:
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=host,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message="No IP addresses resolved",
                )

            if self.config.expected_dns_value:
                if self.config.expected_dns_value not in resolved_ips:
                    return CheckResult(
                        monitor_id=self.config.id,
                        name=self.config.name,
                        target=host,
                        monitor_type=self.config.type,
                        status=Status.DOWN,
                        latency_ms=elapsed_ms,
                        message=f"Expected IP '{self.config.expected_dns_value}' not in resolved {resolved_ips}",
                        details={"resolved": resolved_ips},
                    )

            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=host,
                monitor_type=self.config.type,
                status=Status.UP,
                latency_ms=elapsed_ms,
                message=f"Resolved to {', '.join(resolved_ips[:3])}",
                details={"resolved": resolved_ips},
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
                message=f"DNS resolution timed out after {self.config.timeout:.1f}s",
            )
        except socket.gaierror as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=host,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"DNS resolution failed: {exc.strerror or str(exc)}",
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
                message=f"DNS check error: {str(exc)}",
            )
