from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from litekuma.models import CheckResult, Status

logger = logging.getLogger("litekuma.state")


@dataclass
class MonitorStats:
    monitor_id: str
    name: str
    target: str
    monitor_type: str
    current_status: Status = Status.PENDING
    previous_status: Status = Status.PENDING
    consecutive_failures: int = 0
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_check_time: Optional[str] = None
    last_status_change: Optional[str] = None
    last_status_code: Optional[int] = None
    last_message: str = "Awaiting first check"
    recent_history: List[int] = field(default_factory=list)  # 1 for up, 0 for down (last 60 checks)

    @property
    def uptime_percentage(self) -> float:
        if self.total_checks == 0:
            return 100.0
        return (self.successful_checks / self.total_checks) * 100.0

    @property
    def average_latency_ms(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return self.total_latency_ms / self.total_checks

    def record_result(self, result: CheckResult) -> None:
        self.total_checks += 1
        self.total_latency_ms += result.latency_ms
        self.last_latency_ms = result.latency_ms
        self.last_check_time = result.timestamp.isoformat()
        self.last_status_code = result.status_code
        self.last_message = result.message

        is_up = result.status in (Status.UP, Status.DEGRADED)
        if is_up:
            self.successful_checks += 1
            self.consecutive_failures = 0
            self.recent_history.append(1)
        else:
            self.failed_checks += 1
            self.consecutive_failures += 1
            self.recent_history.append(0)

        # Keep history bounded
        if len(self.recent_history) > 100:
            self.recent_history.pop(0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "name": self.name,
            "target": self.target,
            "monitor_type": self.monitor_type,
            "current_status": self.current_status.value,
            "previous_status": self.previous_status.value,
            "consecutive_failures": self.consecutive_failures,
            "total_checks": self.total_checks,
            "successful_checks": self.successful_checks,
            "failed_checks": self.failed_checks,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "uptime_percentage": round(self.uptime_percentage, 2),
            "average_latency_ms": round(self.average_latency_ms, 2),
            "last_latency_ms": round(self.last_latency_ms, 2),
            "last_check_time": self.last_check_time,
            "last_status_change": self.last_status_change,
            "last_status_code": self.last_status_code,
            "last_message": self.last_message,
            "recent_history": self.recent_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MonitorStats:
        return cls(
            monitor_id=data.get("monitor_id", ""),
            name=data.get("name", ""),
            target=data.get("target", ""),
            monitor_type=data.get("monitor_type", "http"),
            current_status=Status(data.get("current_status", Status.PENDING.value)),
            previous_status=Status(data.get("previous_status", Status.PENDING.value)),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            total_checks=int(data.get("total_checks", 0)),
            successful_checks=int(data.get("successful_checks", 0)),
            failed_checks=int(data.get("failed_checks", 0)),
            total_latency_ms=float(data.get("total_latency_ms", 0.0)),
            last_latency_ms=float(data.get("last_latency_ms", 0.0)),
            last_check_time=data.get("last_check_time"),
            last_status_change=data.get("last_status_change"),
            last_status_code=data.get("last_status_code"),
            last_message=data.get("last_message", ""),
            recent_history=list(data.get("recent_history", [])),
        )


class StateManager:
    """Persists and tracks monitor state across checks and runs."""

    def __init__(self, state_file_path: str):
        self.state_file_path = Path(state_file_path)
        self.monitors: Dict[str, MonitorStats] = {}
        self.load()

    def get_or_create(self, monitor_id: str, name: str, target: str, monitor_type: str) -> MonitorStats:
        if monitor_id not in self.monitors:
            self.monitors[monitor_id] = MonitorStats(
                monitor_id=monitor_id,
                name=name,
                target=target,
                monitor_type=monitor_type,
            )
        return self.monitors[monitor_id]

    def save(self) -> None:
        """Atomically saves state to disk."""
        data = {
            "saved_at": datetime.now().isoformat(),
            "monitors": {m_id: stats.to_dict() for m_id, stats in self.monitors.items()},
        }
        try:
            self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_file_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(self.state_file_path)
        except Exception as exc:
            logger.error(f"Failed to save state to {self.state_file_path}: {exc}")

    def load(self) -> None:
        """Loads state from disk if exists."""
        if not self.state_file_path.exists():
            return
        try:
            with open(self.state_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            monitors_data = data.get("monitors", {})
            for m_id, m_dict in monitors_data.items():
                self.monitors[m_id] = MonitorStats.from_dict(m_dict)
        except Exception as exc:
            logger.warning(f"Failed to load state from {self.state_file_path}: {exc}")
