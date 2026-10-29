from __future__ import annotations

from litekuma.models import MonitorConfig, MonitorType
from litekuma.monitors.base import BaseMonitor
from litekuma.monitors.dns import DnsMonitor
from litekuma.monitors.http import HttpMonitor
from litekuma.monitors.ping import PingMonitor
from litekuma.monitors.tcp import TcpMonitor


def create_monitor(config: MonitorConfig) -> BaseMonitor:
    """Factory creating appropriate monitor instance for the given configuration."""
    if config.type in (MonitorType.HTTP, MonitorType.HTTPS):
        return HttpMonitor(config)
    elif config.type == MonitorType.TCP:
        return TcpMonitor(config)
    elif config.type == MonitorType.PING:
        return PingMonitor(config)
    elif config.type == MonitorType.DNS:
        return DnsMonitor(config)
    else:
        raise ValueError(f"Unsupported monitor type: {config.type}")


__all__ = ["BaseMonitor", "HttpMonitor", "TcpMonitor", "PingMonitor", "DnsMonitor", "create_monitor"]
