from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict

from litekuma.models import CheckResult, NotifierConfig, Status
from litekuma.notifiers.base import BaseNotifier

logger = logging.getLogger("litekuma.notifier.command")


class CommandNotifier(BaseNotifier):
    """Executes a local command/script upon monitor state changes."""

    async def notify(self, result: CheckResult, previous_status: Status, is_recovery: bool) -> bool:
        if not self.config.command:
            return False

        if is_recovery and not self.config.notify_on_recovery:
            return True
        if not is_recovery and not self.config.notify_on_down:
            return True

        env: Dict[str, str] = os.environ.copy()
        env.update({
            "LITEKUMA_EVENT": "recovery" if is_recovery else "down",
            "LITEKUMA_MONITOR_ID": result.monitor_id,
            "LITEKUMA_MONITOR_NAME": result.name,
            "LITEKUMA_TARGET": result.target,
            "LITEKUMA_TYPE": result.monitor_type.value,
            "LITEKUMA_STATUS": result.status.value,
            "LITEKUMA_PREVIOUS_STATUS": previous_status.value,
            "LITEKUMA_LATENCY_MS": f"{result.latency_ms:.2f}",
            "LITEKUMA_STATUS_CODE": str(result.status_code or ""),
            "LITEKUMA_MESSAGE": result.message,
            "LITEKUMA_TIMESTAMP": result.timestamp.isoformat(),
        })

        try:
            proc = await asyncio.create_subprocess_shell(
                self.config.command,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="ignore").strip()
                logger.error(f"Command notifier exited with code {proc.returncode}: {err_msg}")
                return False
            return True
        except Exception as exc:
            logger.error(f"Command notifier error: {exc}")
            return False
