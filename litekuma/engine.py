from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from typing import Dict, List, Optional, Set

from litekuma.logger import UptimeLogger
from litekuma.models import CheckResult, MonitorConfig, Status, SystemConfig
from litekuma.monitors import BaseMonitor, create_monitor
from litekuma.notifiers import BaseNotifier, create_notifier
from litekuma.state import StateManager

logger = logging.getLogger("litekuma.engine")


class MonitorEngine:
    """Core asynchronous scheduler and executor for LiteKuma monitors."""

    def __init__(self, config: SystemConfig):
        self.config = config
        self.logger = UptimeLogger(config.logging)
        self.state_mgr = StateManager(config.state_file)

        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._monitors: Dict[str, BaseMonitor] = {}
        self._notifiers: Dict[str, BaseNotifier] = {}

        self._init_components()

    def _init_components(self) -> None:
        # Initialize notifiers
        self._notifiers.clear()
        for n_cfg in self.config.notifiers:
            if n_cfg.enabled:
                n = create_notifier(n_cfg)
                if n:
                    self._notifiers[n_cfg.id] = n

        # Initialize monitors
        self._monitors.clear()
        for m_cfg in self.config.monitors:
            if m_cfg.enabled:
                self._monitors[m_cfg.id] = create_monitor(m_cfg)
                # Seed state manager
                self.state_mgr.get_or_create(
                    monitor_id=m_cfg.id,
                    name=m_cfg.name,
                    target=m_cfg.target,
                    monitor_type=m_cfg.type.value,
                )

    async def execute_monitor_check(self, monitor: BaseMonitor) -> CheckResult:
        """Executes a check with retry logic matching Uptime Kuma behavior."""
        cfg = monitor.config
        max_retries = max(1, cfg.max_retries)
        stats = self.state_mgr.get_or_create(cfg.id, cfg.name, cfg.target, cfg.type.value)

        last_result: Optional[CheckResult] = None
        for attempt in range(1, max_retries + 1):
            result = await monitor.check()
            last_result = result

            if result.is_success:
                break

            # If failed and more retries remain, wait retry_interval before retrying
            if attempt < max_retries and self._running:
                await asyncio.sleep(cfg.retry_interval)

        assert last_result is not None

        # Check for state transition
        prev_status = stats.current_status
        new_status = last_result.status

        # Transition detection
        status_changed = (prev_status != Status.PENDING and prev_status != new_status)

        # Update stats
        stats.previous_status = prev_status
        stats.current_status = new_status
        stats.record_result(last_result)

        if status_changed:
            stats.last_status_change = last_result.timestamp.isoformat()
            if new_status == Status.UP:
                event_type = "RECOVERY"
                event_msg = f"Target is UP ({last_result.latency_ms:.1f}ms) - {last_result.message}"
                is_recovery = True
            else:
                event_type = "DOWN ALERT"
                event_msg = f"Target is DOWN - {last_result.message}"
                is_recovery = False

            # Log to text file and console
            self.logger.log_event(event_type, cfg.name, event_msg, last_result.timestamp)

            # Trigger notifiers
            await self._dispatch_notifications(last_result, prev_status, is_recovery, cfg)

        # Log heartbeat to text file
        self.logger.log_result(last_result)

        # Save state to disk
        self.state_mgr.save()

        return last_result

    async def _dispatch_notifications(
        self, result: CheckResult, previous_status: Status, is_recovery: bool, cfg: MonitorConfig
    ) -> None:
        """Send notifications to all matching notifiers."""
        tasks = []
        for n_id, notifier in self._notifiers.items():
            # If monitor specifies specific notifiers, filter by that list
            if cfg.notifiers and n_id not in cfg.notifiers:
                continue
            tasks.append(notifier.notify(result, previous_status, is_recovery))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _monitor_loop(self, monitor_id: str) -> None:
        """Continuous polling loop for an individual monitor."""
        monitor = self._monitors.get(monitor_id)
        if not monitor:
            return

        interval = max(1, monitor.config.interval)

        while self._running:
            try:
                await self.execute_monitor_check(monitor)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in monitor loop '{monitor.config.name}': {exc}", exc_info=True)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Starts monitoring all configured targets continuously."""
        self._running = True
        self.logger.log_event("SYSTEM", "LiteKuma", f"Starting engine with {len(self._monitors)} monitor(s)")

        # Launch a background task for each monitor
        for m_id in self._monitors.keys():
            task = asyncio.create_task(self._monitor_loop(m_id))
            self._tasks[m_id] = task

        # Keep running until cancelled or stopped
        try:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully halts all monitor tasks and flushes state."""
        if not self._running:
            return
        self._running = False
        self.logger.log_event("SYSTEM", "LiteKuma", "Stopping engine gracefully")

        for task in self._tasks.values():
            if not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        self.state_mgr.save()
        self.logger.close()

    async def check_once(self) -> List[CheckResult]:
        """Runs a single round of checks on all monitors concurrently and returns the results."""
        self._running = True
        tasks = [self.execute_monitor_check(monitor) for monitor in self._monitors.values()]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        self.state_mgr.save()
        self.logger.close()
        self._running = False
        return list(results)

    def reload(self, new_config: SystemConfig) -> None:
        """Hot-reloads monitors and notifiers without restarting the engine."""
        self.config = new_config
        self.logger.log_event("SYSTEM", "LiteKuma", "Hot-reloading configuration")

        old_monitor_ids = set(self._monitors.keys())
        new_monitor_cfgs = {m.id: m for m in new_config.monitors if m.enabled}
        new_monitor_ids = set(new_monitor_cfgs.keys())

        # Stop removed monitors
        for m_id in old_monitor_ids - new_monitor_ids:
            task = self._tasks.pop(m_id, None)
            if task and not task.done():
                task.cancel()
            self._monitors.pop(m_id, None)

        # Update or add monitors
        for m_id, m_cfg in new_monitor_cfgs.items():
            self._monitors[m_id] = create_monitor(m_cfg)
            self.state_mgr.get_or_create(m_id, m_cfg.name, m_cfg.target, m_cfg.type.value)
            if self._running and (m_id not in self._tasks or self._tasks[m_id].done()):
                self._tasks[m_id] = asyncio.create_task(self._monitor_loop(m_id))

        # Re-initialize notifiers
        self._notifiers.clear()
        for n_cfg in new_config.notifiers:
            if n_cfg.enabled:
                n = create_notifier(n_cfg)
                if n:
                    self._notifiers[n_cfg.id] = n
