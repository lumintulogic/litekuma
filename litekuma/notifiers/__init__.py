from __future__ import annotations

from typing import Optional

from litekuma.models import NotifierConfig
from litekuma.notifiers.base import BaseNotifier
from litekuma.notifiers.command import CommandNotifier
from litekuma.notifiers.telegram import TelegramNotifier
from litekuma.notifiers.webhook import WebhookNotifier


def create_notifier(config: NotifierConfig) -> Optional[BaseNotifier]:
    n_type = config.type.lower()
    if n_type in ("webhook", "slack", "discord"):
        return WebhookNotifier(config)
    elif n_type == "telegram":
        return TelegramNotifier(config)
    elif n_type in ("command", "script", "exec"):
        return CommandNotifier(config)
    return None


__all__ = ["BaseNotifier", "WebhookNotifier", "TelegramNotifier", "CommandNotifier", "create_notifier"]
