from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

from litekuma.models import CheckResult, NotifierConfig, Status
from litekuma.notifiers.base import BaseNotifier

logger = logging.getLogger("litekuma.notifier.webhook")


class WebhookNotifier(BaseNotifier):
    """Sends HTTP POST alerts to custom endpoints, Slack, or Discord webhooks."""

    async def notify(self, result: CheckResult, previous_status: Status, is_recovery: bool) -> bool:
        if not self.config.url:
            return False

        if is_recovery and not self.config.notify_on_recovery:
            return True
        if not is_recovery and not self.config.notify_on_down:
            return True

        payload: Dict[str, Any]
        url = self.config.url.lower()

        title = f"[{'RECOVERY' if is_recovery else 'ALERT'}] {result.name} is {result.status.value}"
        color = 0x2ECC71 if is_recovery else 0xE74C3C  # Green or Red

        if "discord.com/api/webhooks" in url:
            # Discord format
            payload = {
                "embeds": [
                    {
                        "title": title,
                        "description": result.message,
                        "color": color,
                        "fields": [
                            {"name": "Target", "value": f"`{result.target}`", "inline": True},
                            {"name": "Latency", "value": f"{result.latency_ms:.1f}ms", "inline": True},
                            {"name": "Status Code", "value": str(result.status_code or "N/A"), "inline": True},
                        ],
                        "timestamp": result.timestamp.isoformat(),
                    }
                ]
            }
        elif "hooks.slack.com" in url:
            # Slack format
            payload = {
                "text": f"*{title}*\n*Target:* {result.target}\n*Latency:* {result.latency_ms:.1f}ms\n*Message:* {result.message}",
            }
        else:
            # Standard generic webhook format
            payload = {
                "event": "recovery" if is_recovery else "down",
                "monitor_id": result.monitor_id,
                "name": result.name,
                "target": result.target,
                "status": result.status.value,
                "previous_status": previous_status.value,
                "latency_ms": round(result.latency_ms, 2),
                "status_code": result.status_code,
                "message": result.message,
                "timestamp": result.timestamp.isoformat(),
                "details": result.details,
            }

        headers = {"Content-Type": "application/json"}
        headers.update(self.config.headers)

        if HAS_HTTPX:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.request(
                        method=self.config.method,
                        url=self.config.url,
                        json=payload,
                        headers=headers,
                    )
                    return resp.is_success
            except Exception as exc:
                logger.error(f"Failed to deliver webhook to {self.config.url}: {exc}")
                return False
        else:
            loop = asyncio.get_running_loop()

            def _send_sync():
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url=self.config.url,
                    data=data,
                    headers=headers,
                    method=self.config.method,
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    return 200 <= resp.status < 300

            try:
                return await loop.run_in_executor(None, _send_sync)
            except Exception as exc:
                logger.error(f"Failed to deliver webhook to {self.config.url}: {exc}")
                return False
