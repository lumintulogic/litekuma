from __future__ import annotations

import abc
from litekuma.models import CheckResult, NotifierConfig, Status


class BaseNotifier(abc.ABC):
    """Abstract base class for alert notification channels."""

    def __init__(self, config: NotifierConfig):
        self.config = config

    @abc.abstractmethod
    async def notify(self, result: CheckResult, previous_status: Status, is_recovery: bool) -> bool:
        """Send notification for status change. Return True if successful."""
        raise NotImplementedError
