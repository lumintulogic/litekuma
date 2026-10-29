from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class Status(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"
    PENDING = "PENDING"


class MonitorType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"
    PING = "ping"
    DNS = "dns"


class LogFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    TSV = "tsv"


@dataclass
class CheckResult:
    monitor_id: str
    name: str
    target: str
    monitor_type: MonitorType
    status: Status
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.now)
    status_code: Optional[int] = None
    message: str = "OK"
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == Status.UP


@dataclass
class MonitorConfig:
    id: str
    name: str
    target: str
    type: MonitorType = MonitorType.HTTP
    enabled: bool = True
    interval: int = 60           # check interval in seconds
    timeout: float = 10.0         # timeout in seconds
    max_retries: int = 1         # retries before declaring DOWN
    retry_interval: int = 5      # delay between retries in seconds
    tags: List[str] = field(default_factory=list)

    # HTTP / HTTPS options
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    expected_status: List[int] = field(default_factory=lambda: list(range(200, 300)))
    keyword: Optional[str] = None
    invert_keyword: bool = False
    verify_ssl: bool = True
    check_ssl_expiry: bool = False
    ssl_expiry_days_threshold: int = 14
    follow_redirects: bool = True

    # TCP options
    port: Optional[int] = None

    # DNS options
    dns_record_type: str = "A"
    expected_dns_value: Optional[str] = None
    nameserver: Optional[str] = None

    # Custom notifier routing (empty means all enabled notifiers)
    notifiers: List[str] = field(default_factory=list)


@dataclass
class NotifierConfig:
    id: str
    type: str  # "webhook", "telegram", "command"
    enabled: bool = True
    notify_on_down: bool = True
    notify_on_recovery: bool = True

    # Webhook
    url: Optional[str] = None
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)

    # Telegram
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

    # Command
    command: Optional[str] = None


@dataclass
class LoggingConfig:
    file_path: str = "uptime.log"
    event_file_path: Optional[str] = None
    format: LogFormat = LogFormat.TEXT
    max_bytes: int = 10 * 1024 * 1024  # 10 MB
    backup_count: int = 5
    console: bool = True
    log_all_heartbeats: bool = True  # If False, logs only state changes and failures
    timestamp_format: str = "%Y-%m-%d %H:%M:%S"


@dataclass
class SystemConfig:
    state_file: str = "litekuma_state.json"
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    monitors: List[MonitorConfig] = field(default_factory=list)
    notifiers: List[NotifierConfig] = field(default_factory=list)
