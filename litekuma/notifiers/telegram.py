from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

from litekuma.models import CheckResult, NotifierConfig, Status
from litekuma.notifiers.base import BaseNotifier

logger = logging.getLogger("litekuma.notifier.telegram")


class TelegramNotifier(BaseNotifier):
    """Sends alert messages via Telegram Bot API."""

    async def notify(self, result: CheckResult, previous_status: Status, is_recovery: bool) -> bool:
        bot_token = self.config.bot_token
        chat_id = self.config.chat_id

        if not bot_token or not chat_id:
            return False

        if is_recovery and not self.config.notify_on_recovery:
            return True
        if not is_recovery and not self.config.notify_on_down:
            return True

        icon = "✅" if is_recovery else "🔴"
        title = "RECOVERY" if is_recovery else "DOWN ALERT"

        text = (
            f"{icon} <b>LiteKuma: {title}</b>\n\n"
            f"<b>Target:</b> {result.name} (<code>{result.target}</code>)\n"
            f"<b>Status:</b> {result.status.value}\n"
            f"<b>Response Time:</b> {result.latency_ms:.1f}ms\n"
            f"<b>Status Code:</b> {result.status_code or 'N/A'}\n"
            f"<b>Message:</b> {result.message}\n"
            f"<b>Time:</b> {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        if HAS_HTTPX:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(api_url, json=payload)
                    return resp.is_success
            except Exception as exc:
                logger.error(f"Failed to send Telegram alert: {exc}")
                return False
        else:
            loop = asyncio.get_running_loop()

            def _send_sync():
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url=api_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    return 200 <= resp.status < 300

            try:
                return await loop.run_in_executor(None, _send_sync)
            except Exception as exc:
                logger.error(f"Failed to send Telegram alert: {exc}")
                return False
