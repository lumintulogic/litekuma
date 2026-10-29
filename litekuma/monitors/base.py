from __future__ import annotations

import abc
import time
from datetime import datetime
from litekuma.models import CheckResult, MonitorConfig, Status


class BaseMonitor(abc.ABC):
    """Abstract base class for all monitors."""

    def __init__(self, config: MonitorConfig):
        self.config = config

    @abc.abstractmethod
    async def perform_check(self) -> CheckResult:
        """Subclasses implement this to perform the actual network/service check."""
        raise NotImplementedError

    async def check(self) -> CheckResult:
        """Wraps perform_check with timing and top-level error handling."""
        start_time = time.perf_counter()
        try:
            result = await self.perform_check()
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                timestamp=datetime.now(),
                message=f"Check failed with unexpected error: {str(exc)}",
                details={"error": str(exc)},
            )
