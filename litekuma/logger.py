from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from litekuma.models import CheckResult, LogFormat, LoggingConfig, Status

# ANSI color codes for pretty terminal logging
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[32m"
COLOR_RED = "\033[31m"
COLOR_YELLOW = "\033[33m"
COLOR_CYAN = "\033[36m"
COLOR_BOLD = "\033[1m"
COLOR_DIM = "\033[2m"

STATUS_COLORS = {
    Status.UP: COLOR_GREEN,
    Status.DOWN: COLOR_RED,
    Status.DEGRADED: COLOR_YELLOW,
    Status.PENDING: COLOR_CYAN,
}


class UptimeTextFormatter(logging.Formatter):
    """Formats log records into clean, structured human-readable text."""

    def __init__(self, fmt_pattern: str = "%Y-%m-%d %H:%M:%S", color: bool = False):
        super().__init__()
        self.fmt_pattern = fmt_pattern
        self.color = color

    def format_heartbeat(self, result: CheckResult) -> str:
        ts = result.timestamp.strftime(self.fmt_pattern)
        status_str = result.status.value
        code_str = f"HTTP {result.status_code}" if result.status_code is not None else result.monitor_type.value.upper()
        latency_str = f"{result.latency_ms:.1f}ms"

        if self.color:
            color = STATUS_COLORS.get(result.status, "")
            status_tag = f"[{color}{status_str:4s}{COLOR_RESET}]"
            latency_tag = f"[{COLOR_DIM}{latency_str:>8s}{COLOR_RESET}]"
            code_tag = f"[{COLOR_CYAN}{code_str:<8s}{COLOR_RESET}]"
            name_str = f"{COLOR_BOLD}{result.name}{COLOR_RESET}"
            msg_str = f"{color}{result.message}{COLOR_RESET}" if result.status != Status.UP else result.message
            return f"[{ts}] {status_tag} {code_tag} {latency_tag} {name_str} ({result.target}) - {msg_str}"
        else:
            return f"[{ts}] [{status_str:4s}] [{code_str:<8s}] [{latency_str:>8s}] {result.name} ({result.target}) - {result.message}"

    def format_event(self, timestamp: datetime, event_type: str, monitor_name: str, message: str) -> str:
        ts = timestamp.strftime(self.fmt_pattern)
        event_tag = f"[{event_type.upper()}]"
        if self.color:
            color = COLOR_RED if "DOWN" in event_type.upper() or "ALERT" in event_type.upper() else COLOR_GREEN
            return f"[{ts}] {COLOR_BOLD}{color}{event_tag}{COLOR_RESET} {COLOR_BOLD}{monitor_name}{COLOR_RESET}: {message}"
        else:
            return f"[{ts}] {event_tag} {monitor_name}: {message}"


class UptimeLogger:
    """Manages file and console logging for LiteKuma."""

    def __init__(self, config: LoggingConfig):
        self.config = config
        self.formatter_text = UptimeTextFormatter(fmt_pattern=config.timestamp_format, color=False)
        self.formatter_color = UptimeTextFormatter(fmt_pattern=config.timestamp_format, color=sys.stdout.isatty())

        # Ensure parent directory for log file exists
        log_path = Path(config.file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Main heartbeat / audit file handler
        self.file_handler = RotatingFileHandler(
            filename=str(log_path),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        self.file_handler.setFormatter(logging.Formatter("%(message)s"))

        # Event file handler (optional separate file for UP/DOWN alerts only)
        self.event_file_handler: Optional[RotatingFileHandler] = None
        if config.event_file_path:
            event_path = Path(config.event_file_path)
            event_path.parent.mkdir(parents=True, exist_ok=True)
            self.event_file_handler = RotatingFileHandler(
                filename=str(event_path),
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
                encoding="utf-8",
            )
            self.event_file_handler.setFormatter(logging.Formatter("%(message)s"))

    def log_result(self, result: CheckResult) -> None:
        """Logs a single check result to the text file and console."""
        # If log_all_heartbeats is False, only log failures (DOWN / DEGRADED)
        if not self.config.log_all_heartbeats and result.status == Status.UP:
            return

        line = self._format_result(result)
        self._write_file(line)

        if self.config.console:
            console_line = self.formatter_color.format_heartbeat(result)
            print(console_line, flush=True)

    def log_event(self, event_type: str, monitor_name: str, message: str, timestamp: Optional[datetime] = None) -> None:
        """Logs an event (e.g. ALERT, RECOVERY, RELOAD, STARTUP) to file and console."""
        ts = timestamp or datetime.now()
        plain_line = self.formatter_text.format_event(ts, event_type, monitor_name, message)
        self._write_file(plain_line)

        if self.event_file_handler:
            try:
                rec = logging.LogRecord(
                    name="litekuma.event",
                    level=logging.INFO,
                    pathname="",
                    lineno=0,
                    msg=plain_line,
                    args=(),
                    exc_info=None,
                )
                self.event_file_handler.emit(rec)
            except Exception:
                pass

        if self.config.console:
            color_line = self.formatter_color.format_event(ts, event_type, monitor_name, message)
            print(color_line, flush=True)

    def _format_result(self, result: CheckResult) -> str:
        if self.config.format == LogFormat.JSON:
            data = {
                "timestamp": result.timestamp.isoformat(),
                "monitor_id": result.monitor_id,
                "name": result.name,
                "target": result.target,
                "type": result.monitor_type.value,
                "status": result.status.value,
                "latency_ms": round(result.latency_ms, 2),
                "status_code": result.status_code,
                "message": result.message,
                "details": result.details,
            }
            return json.dumps(data)
        elif self.config.format == LogFormat.TSV:
            ts = result.timestamp.strftime(self.config.timestamp_format)
            code = str(result.status_code) if result.status_code is not None else "-"
            # sanitize tabs and newlines in message
            clean_msg = result.message.replace("\t", " ").replace("\n", " ")
            return f"{ts}\t{result.status.value}\t{result.monitor_id}\t{result.name}\t{result.target}\t{result.monitor_type.value}\t{code}\t{result.latency_ms:.1f}\t{clean_msg}"
        else:
            return self.formatter_text.format_heartbeat(result)

    def _write_file(self, line: str) -> None:
        try:
            rec = logging.LogRecord(
                name="litekuma.file",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=line,
                args=(),
                exc_info=None,
            )
            self.file_handler.emit(rec)
        except Exception as e:
            sys.stderr.write(f"LiteKuma logging error: {e}\n")

    def close(self) -> None:
        try:
            self.file_handler.close()
            if self.event_file_handler:
                self.event_file_handler.close()
        except Exception:
            pass
