from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional

from litekuma import __version__

DEFAULT_CONFIG_FILES = [
    "monitors.yaml",
    "monitors.yml",
    "config.yaml",
    "config.yml",
    "monitors.json",
]

SAMPLE_CONFIG_YAML = """# ==============================================================================
# LiteKuma - Lightweight Headless Uptime Monitor Configuration
# ==============================================================================

settings:
  default_interval: 60      # Global default check interval in seconds
  default_timeout: 10.0     # Global default request timeout in seconds
  state_file: litekuma_state.json

# ------------------------------------------------------------------------------
# Logging Configuration
# All check results and alert events are stored in structured text files.
# ------------------------------------------------------------------------------
logging:
  file_path: uptime.log              # Path to the primary text log file
  event_file_path: uptime_events.log # Optional: separate log for UP/DOWN alerts only
  format: text                       # Formats: 'text' (human-readable), 'tsv', or 'json'
  max_bytes: 10485760                # 10 MB per file before automatic rotation
  backup_count: 5                    # Keep up to 5 rotated backup logs
  console: true                      # Print color-coded status to terminal / stdout
  log_all_heartbeats: true           # If false, only logs errors and state changes

# ------------------------------------------------------------------------------
# Alert Notification Channels (Optional)
# ------------------------------------------------------------------------------
notifiers:
  - id: discord-webhook
    type: webhook
    enabled: false
    url: "https://discord.com/api/webhooks/your/webhook/url"
    notify_on_down: true
    notify_on_recovery: true

  - id: slack-webhook
    type: webhook
    enabled: false
    url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
    notify_on_down: true
    notify_on_recovery: true

  - id: telegram-alert
    type: telegram
    enabled: false
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
    notify_on_down: true
    notify_on_recovery: true

  - id: failover-action
    type: command
    enabled: false
    command: "/bin/bash wan-failover.sh --trigger-litekuma"
    notify_on_down: true
    notify_on_recovery: false

# ------------------------------------------------------------------------------
# Monitored Targets
# ------------------------------------------------------------------------------
monitors:
  # HTTP Monitor with Custom Headers and Keyword Validation
  - id: internal-api
    name: Internal Microservice API
    type: http
    target: "https://httpbin.org/get"
    interval: 30
    timeout: 5.0
    max_retries: 2
    retry_interval: 3
    method: GET
    # Custom headers for authentication, tenant routing, and custom agents:
    headers:
      Authorization: "Bearer ${API_KEY:-my-secret-token}"
      X-Custom-Client: "LiteKuma-Daemon"
      X-Environment: "Production"
      Accept: "application/json"
    expected_status: "200-299"
    keyword: "LiteKuma-Daemon"     # Verifies this string is returned in the response
    verify_ssl: true
    check_ssl_expiry: true
    ssl_expiry_days_threshold: 14

  # Simple Public Website Check
  - id: google-search
    name: Google Web Search
    type: http
    target: "https://www.google.com"
    interval: 60
    timeout: 5.0
    method: GET
    expected_status: 200

  # Authenticated POST Webhook / Endpoint Check
  - id: auth-post-endpoint
    name: Backend Ingestion Endpoint
    type: http
    target: "https://httpbin.org/post"
    interval: 120
    method: POST
    headers:
      Content-Type: "application/json"
      X-API-Key: "secret-key-12345"
    body: '{"healthcheck": true, "source": "litekuma"}'
    expected_status: [200, 201]

  # TCP Port Monitor (e.g. DNS, Database, SSH)
  - id: cloudflare-dns-tcp
    name: Cloudflare DNS Port 53
    type: tcp
    target: "1.1.1.1"
    port: 53
    interval: 60
    timeout: 3.0

  # ICMP Ping Monitor
  - id: quad9-ping
    name: Quad9 Anycast Gateway
    type: ping
    target: "9.9.9.9"
    interval: 60
    timeout: 3.0

  # Domain Name Resolution (DNS) Monitor
  - id: domain-dns-check
    name: Example Domain DNS
    type: dns
    target: "example.com"
    interval: 300
    # expected_dns_value: "93.184.215.14" # Optional: assert domain resolves to specific IP
"""


def find_default_config() -> Optional[str]:
    for candidate in DEFAULT_CONFIG_FILES:
        if Path(candidate).is_file():
            return candidate
    return None


def print_table(headers: List[str], rows: List[List[str]]) -> None:
    """Renders a clean ASCII/Unicode table to stdout."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            # Strip ANSI color codes when computing width
            clean_cell = cell
            for c in ("\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m", "\033[1m"):
                clean_cell = clean_cell.replace(c, "")
            col_widths[idx] = max(col_widths[idx], len(clean_cell))

    sep_line = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "| " + " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths)) + " |"

    print(sep_line)
    print(header_line)
    print(sep_line)
    for row in rows:
        formatted_cells = []
        for cell, w in zip(row, col_widths):
            clean_cell = cell
            for c in ("\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m", "\033[1m"):
                clean_cell = clean_cell.replace(c, "")
            padding = " " * (w - len(clean_cell))
            formatted_cells.append(f"{cell}{padding}")
        print("| " + " | ".join(formatted_cells) + " |")
    print(sep_line)


def run_daemon(args: argparse.Namespace) -> int:
    config_path = args.config or find_default_config()
    if not config_path:
        sys.stderr.write("Error: No configuration file found. Run 'litekuma init' to generate monitors.yaml\n")
        return 1

    from litekuma.config import load_config
    from litekuma.engine import MonitorEngine
    from litekuma.models import LogFormat

    try:
        config = load_config(config_path)
    except Exception as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        return 1

    # CLI overrides
    if args.log_file:
        config.logging.file_path = args.log_file
    if args.format:
        config.logging.format = LogFormat(args.format)
    if args.no_console:
        config.logging.console = False

    engine = MonitorEngine(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal():
        loop.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            pass

    # Optional SIGHUP hot reloading
    def handle_sighup():
        try:
            new_cfg = load_config(config_path)
            engine.reload(new_cfg)
        except Exception as e:
            sys.stderr.write(f"Failed to reload config: {e}\n")

    if hasattr(signal, "SIGHUP"):
        try:
            loop.add_signal_handler(signal.SIGHUP, handle_sighup)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        loop.run_until_complete(engine.start())
        return 0
    except KeyboardInterrupt:
        loop.run_until_complete(engine.stop())
        return 0
    finally:
        loop.close()


def run_check(args: argparse.Namespace) -> int:
    """Executes a single check pass across targets."""
    from litekuma.config import load_config
    from litekuma.engine import MonitorEngine
    from litekuma.models import CheckResult, LogFormat, LoggingConfig, MonitorConfig, MonitorType, Status, SystemConfig

    # Ad-hoc target mode
    if args.target:
        headers_dict = {}
        if args.header:
            for h in args.header:
                if ":" in h:
                    k, v = h.split(":", 1)
                    headers_dict[k.strip()] = v.strip()

        m_type = MonitorType.HTTP
        if args.type:
            m_type = MonitorType(args.type.lower())

        port = args.port
        if m_type == MonitorType.TCP and port is None and ":" in args.target:
            try:
                host_p, port_p = args.target.rsplit(":", 1)
                args.target = host_p
                port = int(port_p)
            except ValueError:
                pass

        monitors = [
            MonitorConfig(
                id="adhoc",
                name=args.name or args.target,
                target=args.target,
                type=m_type,
                method=args.method or "GET",
                headers=headers_dict,
                port=port,
                timeout=args.timeout or 10.0,
            )
        ]
        log_cfg = LoggingConfig(
            file_path=args.log_file or "uptime.log",
            format=LogFormat(args.format or "text"),
            console=False,
        )
        config = SystemConfig(logging=log_cfg, monitors=monitors)
    else:
        config_path = args.config or find_default_config()
        if not config_path:
            sys.stderr.write("Error: No configuration file found. Run 'litekuma init' to generate monitors.yaml\n")
            return 1
        try:
            config = load_config(config_path)
        except Exception as exc:
            sys.stderr.write(f"Configuration error: {exc}\n")
            return 1

        if args.log_file:
            config.logging.file_path = args.log_file
        if args.format:
            config.logging.format = LogFormat(args.format)
        # In check mode, we format our own summary table, disable continuous console logger
        config.logging.console = False

    engine = MonitorEngine(config)
    results: List[CheckResult] = asyncio.run(engine.check_once())

    if args.json:
        output = [
            {
                "id": r.monitor_id,
                "name": r.name,
                "target": r.target,
                "type": r.monitor_type.value,
                "status": r.status.value,
                "latency_ms": round(r.latency_ms, 2),
                "status_code": r.status_code,
                "message": r.message,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        headers = ["Status", "Type", "Name", "Target", "Code", "Latency", "Message"]
        rows = []
        for r in results:
            if r.status == Status.UP:
                status_str = "\033[32mUP\033[0m"
            elif r.status == Status.DEGRADED:
                status_str = "\033[33mDEGRADED\033[0m"
            else:
                status_str = "\033[31mDOWN\033[0m"

            code_str = str(r.status_code) if r.status_code is not None else "-"
            rows.append([
                status_str,
                r.monitor_type.value.upper(),
                r.name,
                r.target,
                code_str,
                f"{r.latency_ms:.1f}ms",
                r.message,
            ])

        print(f"\nLiteKuma Check Results ({len(results)} target{'s' if len(results) != 1 else ''}):")
        print_table(headers, rows)
        print(f"Results appended to log file: {config.logging.file_path}\n")

    # Exit code: 0 if all UP, 1 if any DOWN
    any_down = any(r.status == Status.DOWN for r in results)
    return 1 if any_down else 0


def run_status(args: argparse.Namespace) -> int:
    """Reads and displays monitor uptime stats from state file."""
    from litekuma.config import load_config
    from litekuma.models import Status
    from litekuma.state import StateManager

    config_path = args.config or find_default_config()
    state_file = args.state_file or "litekuma_state.json"
    if config_path and Path(config_path).is_file():
        try:
            cfg = load_config(config_path)
            state_file = args.state_file or cfg.state_file
        except Exception:
            pass

    state_mgr = StateManager(state_file)
    if not state_mgr.monitors:
        print(f"No status data found in '{state_file}'. Has LiteKuma run yet?")
        return 0

    if args.json:
        data = {m_id: s.to_dict() for m_id, s in state_mgr.monitors.items()}
        print(json.dumps(data, indent=2))
        return 0

    headers = ["Status", "Name", "Target", "Uptime", "Avg Latency", "Checks", "Last Checked"]
    rows = []
    for s in state_mgr.monitors.values():
        if s.current_status == Status.UP:
            st = "\033[32mUP\033[0m"
        elif s.current_status == Status.DEGRADED:
            st = "\033[33mDEGRADED\033[0m"
        elif s.current_status == Status.DOWN:
            st = "\033[31mDOWN\033[0m"
        else:
            st = "\033[36mPENDING\033[0m"

        uptime_str = f"{s.uptime_percentage:.1f}%"
        last_time = s.last_check_time.replace("T", " ")[:19] if s.last_check_time else "Never"
        rows.append([
            st,
            s.name,
            s.target,
            uptime_str,
            f"{s.average_latency_ms:.1f}ms",
            f"{s.successful_checks}/{s.total_checks}",
            last_time,
        ])

    print(f"\nLiteKuma Status Summary (from {state_file}):")
    print_table(headers, rows)
    return 0


def run_validate(args: argparse.Namespace) -> int:
    from litekuma.config import load_config

    config_path = args.config or find_default_config()
    if not config_path:
        sys.stderr.write("Error: No configuration file specified or found.\n")
        return 1

    try:
        cfg = load_config(config_path)
        print(f"✓ Configuration file '{config_path}' is valid!")
        print(f"  • Monitors configured: {len(cfg.monitors)}")
        for idx, m in enumerate(cfg.monitors, 1):
            h_count = len(m.headers)
            h_str = f" ({h_count} custom headers)" if h_count else ""
            print(f"    {idx}. [{m.type.value.upper()}] {m.name} -> {m.target}{h_str} (every {m.interval}s)")
        print(f"  • Notifiers configured: {len(cfg.notifiers)}")
        for idx, n in enumerate(cfg.notifiers, 1):
            print(f"    {idx}. [{n.type}] {n.id} (enabled={n.enabled})")
        print(f"  • Log file: {cfg.logging.file_path} (format: {cfg.logging.format.value})")
        print(f"  • State file: {cfg.state_file}")
        return 0
    except Exception as exc:
        sys.stderr.write(f"✗ Configuration error in '{config_path}': {exc}\n")
        return 1


def run_init(args: argparse.Namespace) -> int:
    out_file = Path(args.output or "monitors.yaml")
    if out_file.exists() and not args.force:
        sys.stderr.write(f"Error: '{out_file}' already exists. Use --force to overwrite.\n")
        return 1

    out_file.write_text(SAMPLE_CONFIG_YAML, encoding="utf-8")
    print(f"✓ Created sample configuration file at '{out_file}'")
    print("  You can now customize it and run:")
    print(f"    litekuma check -c {out_file}")
    print(f"    litekuma run -c {out_file}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="litekuma",
        description="LiteKuma - Lightweight headless uptime monitor without WebUI (logs to text file).",
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run (daemon mode)
    p_run = subparsers.add_parser("run", help="Run the continuous monitoring daemon")
    p_run.add_argument("-c", "--config", help="Path to config file (YAML/JSON)")
    p_run.add_argument("-l", "--log-file", help="Override log file path")
    p_run.add_argument("--format", choices=["text", "json", "tsv"], help="Log format")
    p_run.add_argument("--no-console", action="store_true", help="Disable console output (log to file only)")

    # Command: check (one-off mode)
    p_check = subparsers.add_parser("check", help="Run a single check pass across all targets")
    p_check.add_argument("-c", "--config", help="Path to config file (YAML/JSON)")
    p_check.add_argument("-t", "--target", help="Ad-hoc target URL/host to check directly")
    p_check.add_argument("-H", "--header", action="append", help="Custom header in 'Key: Value' format (can repeat)")
    p_check.add_argument("--method", default="GET", help="HTTP method for ad-hoc check (default: GET)")
    p_check.add_argument("--type", default="http", choices=["http", "tcp", "ping", "dns"], help="Monitor type")
    p_check.add_argument("--port", type=int, help="Port for TCP check")
    p_check.add_argument("--name", help="Name for ad-hoc target")
    p_check.add_argument("--timeout", type=float, help="Timeout in seconds")
    p_check.add_argument("-l", "--log-file", help="Override log file path")
    p_check.add_argument("--format", choices=["text", "json", "tsv"], help="Log format")
    p_check.add_argument("--json", action="store_true", help="Output check results as JSON to stdout")

    # Command: status
    p_status = subparsers.add_parser("status", help="Show current monitor status and uptime percentages")
    p_status.add_argument("-c", "--config", help="Path to config file")
    p_status.add_argument("-s", "--state-file", help="Path to state file")
    p_status.add_argument("--json", action="store_true", help="Output as JSON")

    # Command: validate
    p_validate = subparsers.add_parser("validate", help="Validate configuration file")
    p_validate.add_argument("-c", "--config", help="Path to config file")

    # Command: init
    p_init = subparsers.add_parser("init", help="Generate a sample monitors.yaml configuration file")
    p_init.add_argument("-o", "--output", default="monitors.yaml", help="Output filename (default: monitors.yaml)")
    p_init.add_argument("-f", "--force", action="store_true", help="Overwrite existing file if present")

    args = parser.parse_args()

    if not args.command:
        # Default behavior if config file exists: run daemon; otherwise show help
        default_cfg = find_default_config()
        if default_cfg:
            args.command = "run"
            args.config = default_cfg
            args.log_file = None
            args.format = None
            args.no_console = False
        else:
            parser.print_help()
            sys.exit(1)

    cmd_handlers = {
        "run": run_daemon,
        "check": run_check,
        "status": run_status,
        "validate": run_validate,
        "init": run_init,
    }

    exit_code = cmd_handlers[args.command](args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
