from __future__ import annotations

import os
import re
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from litekuma.models import (
    LogFormat,
    LoggingConfig,
    MonitorConfig,
    MonitorType,
    NotifierConfig,
    SystemConfig,
)

logger = logging.getLogger("litekuma.config")

# Regex to find ${VAR_NAME} or ${VAR_NAME:-default_value}
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def substitute_env_vars(data: Any) -> Any:
    """Recursively replaces ${VAR} and ${VAR:-default} with environment variables."""
    if isinstance(data, str):
        def repl(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.getenv(var_name, default_val)

        return ENV_VAR_PATTERN.sub(repl, data)
    elif isinstance(data, dict):
        return {k: substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [substitute_env_vars(item) for item in data]
    return data


def slugify(text: str) -> str:
    """Converts a text string into a clean alphanumeric slug."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-") or "monitor"


def parse_expected_status(val: Any) -> List[int]:
    """Parse expected HTTP status code(s) from int, list of ints/strings, or range string ('200-299')."""
    if val is None:
        return list(range(200, 300))
    if isinstance(val, int):
        return [val]
    if isinstance(val, str):
        val = val.strip()
        if "-" in val:
            parts = val.split("-", 1)
            try:
                start = int(parts[0].strip())
                end = int(parts[1].strip())
                return list(range(start, end + 1))
            except ValueError:
                pass
        try:
            return [int(val)]
        except ValueError:
            return list(range(200, 300))
    if isinstance(val, list):
        res = []
        for item in val:
            if isinstance(item, int):
                res.append(item)
            elif isinstance(item, str):
                item = item.strip()
                if "-" in item:
                    try:
                        p1, p2 = item.split("-", 1)
                        res.extend(range(int(p1.strip()), int(p2.strip()) + 1))
                    except ValueError:
                        pass
                else:
                    try:
                        res.append(int(item))
                    except ValueError:
                        pass
        return sorted(list(set(res)))
    return list(range(200, 300))


def parse_monitor(raw: Dict[str, Any], default_interval: int = 60, default_timeout: float = 10.0) -> MonitorConfig:
    name = raw.get("name", "Unnamed Monitor")
    monitor_id = raw.get("id") or slugify(name)
    m_type_raw = str(raw.get("type", "http")).lower()

    if m_type_raw in ("http", "https"):
        m_type = MonitorType.HTTP
    elif m_type_raw in ("tcp", "port"):
        m_type = MonitorType.TCP
    elif m_type_raw in ("ping", "icmp"):
        m_type = MonitorType.PING
    elif m_type_raw in ("dns",):
        m_type = MonitorType.DNS
    else:
        raise ValueError(f"Unknown monitor type: '{m_type_raw}' for monitor '{name}'")

    target = raw.get("target") or raw.get("url") or raw.get("host", "")
    if not target:
        raise ValueError(f"Monitor '{name}' is missing required 'target' or 'url' attribute")

    # If HTTP type and target doesn't specify protocol, add http://
    if m_type == MonitorType.HTTP and not (target.startswith("http://") or target.startswith("https://")):
        target = f"http://{target}"

    # Custom headers for HTTP
    headers = raw.get("headers", {})
    if not isinstance(headers, dict):
        raise ValueError(f"Headers for monitor '{name}' must be a key-value mapping")
    # Cast all header keys and values to strings
    headers = {str(k): str(v) for k, v in headers.items()}

    # TCP port parsing
    port = raw.get("port")
    if m_type == MonitorType.TCP and port is None:
        if ":" in target:
            try:
                host_part, port_part = target.rsplit(":", 1)
                target = host_part
                port = int(port_part)
            except ValueError:
                pass
        if port is None:
            raise ValueError(f"TCP monitor '{name}' requires a 'port' attribute")

    return MonitorConfig(
        id=monitor_id,
        name=name,
        target=target,
        type=m_type,
        enabled=bool(raw.get("enabled", True)),
        interval=int(raw.get("interval", default_interval)),
        timeout=float(raw.get("timeout", default_timeout)),
        max_retries=int(raw.get("max_retries", raw.get("retries", 1))),
        retry_interval=int(raw.get("retry_interval", 5)),
        tags=list(raw.get("tags", [])),
        method=str(raw.get("method", "GET")).upper(),
        headers=headers,
        body=raw.get("body"),
        expected_status=parse_expected_status(raw.get("expected_status")),
        keyword=raw.get("keyword"),
        invert_keyword=bool(raw.get("invert_keyword", False)),
        verify_ssl=bool(raw.get("verify_ssl", True)),
        check_ssl_expiry=bool(raw.get("check_ssl_expiry", False)),
        ssl_expiry_days_threshold=int(raw.get("ssl_expiry_days_threshold", 14)),
        follow_redirects=bool(raw.get("follow_redirects", True)),
        port=int(port) if port is not None else None,
        dns_record_type=str(raw.get("dns_record_type", "A")).upper(),
        expected_dns_value=raw.get("expected_dns_value"),
        nameserver=raw.get("nameserver"),
        notifiers=list(raw.get("notifiers", [])),
    )


def parse_notifier(raw: Dict[str, Any]) -> NotifierConfig:
    notifier_id = raw.get("id") or slugify(raw.get("name", raw.get("type", "notifier")))
    n_type = str(raw.get("type", "webhook")).lower()

    headers = raw.get("headers", {})
    if isinstance(headers, dict):
        headers = {str(k): str(v) for k, v in headers.items()}
    else:
        headers = {}

    return NotifierConfig(
        id=notifier_id,
        type=n_type,
        enabled=bool(raw.get("enabled", True)),
        notify_on_down=bool(raw.get("notify_on_down", True)),
        notify_on_recovery=bool(raw.get("notify_on_recovery", True)),
        url=raw.get("url"),
        method=str(raw.get("method", "POST")).upper(),
        headers=headers,
        bot_token=raw.get("bot_token") or raw.get("token"),
        chat_id=str(raw.get("chat_id")) if raw.get("chat_id") is not None else None,
        command=raw.get("command"),
    )


def parse_logging(raw: Dict[str, Any]) -> LoggingConfig:
    fmt_str = str(raw.get("format", "text")).lower()
    if fmt_str in ("json", "ndjson"):
        fmt = LogFormat.JSON
    elif fmt_str in ("tsv", "csv"):
        fmt = LogFormat.TSV
    else:
        fmt = LogFormat.TEXT

    return LoggingConfig(
        file_path=str(raw.get("file_path", raw.get("file", "uptime.log"))),
        event_file_path=raw.get("event_file_path") or raw.get("event_file"),
        format=fmt,
        max_bytes=int(raw.get("max_bytes", 10 * 1024 * 1024)),
        backup_count=int(raw.get("backup_count", 5)),
        console=bool(raw.get("console", True)),
        log_all_heartbeats=bool(raw.get("log_all_heartbeats", True)),
        timestamp_format=str(raw.get("timestamp_format", "%Y-%m-%d %H:%M:%S")),
    )


def load_config(path: Union[str, Path]) -> SystemConfig:
    """Loads and validates a LiteKuma configuration file (YAML or JSON)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    content = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".json",):
        raw = json.loads(content)
    else:
        raw = yaml.safe_load(content)

    if not isinstance(raw, dict):
        raise ValueError("Root of configuration must be a mapping/dictionary")

    # Substitute environment variables
    raw = substitute_env_vars(raw)

    settings = raw.get("settings", {})
    state_file = settings.get("state_file", raw.get("state_file", "litekuma_state.json"))
    default_interval = int(settings.get("default_interval", 60))
    default_timeout = float(settings.get("default_timeout", 10.0))

    logging_raw = raw.get("logging", {})
    logging_cfg = parse_logging(logging_raw)

    # Parse monitors
    raw_monitors = raw.get("monitors", [])
    if not isinstance(raw_monitors, list):
        raise ValueError("'monitors' must be a list")

    monitors: List[MonitorConfig] = []
    seen_ids = set()
    for m in raw_monitors:
        cfg = parse_monitor(m, default_interval=default_interval, default_timeout=default_timeout)
        if cfg.id in seen_ids:
            # disambiguate duplicate id
            count = 2
            while f"{cfg.id}-{count}" in seen_ids:
                count += 1
            cfg.id = f"{cfg.id}-{count}"
        seen_ids.add(cfg.id)
        monitors.append(cfg)

    # Parse notifiers
    raw_notifiers = raw.get("notifiers", [])
    notifiers: List[NotifierConfig] = []
    if isinstance(raw_notifiers, list):
        for n in raw_notifiers:
            notifiers.append(parse_notifier(n))

    return SystemConfig(
        state_file=state_file,
        logging=logging_cfg,
        monitors=monitors,
        notifiers=notifiers,
    )
