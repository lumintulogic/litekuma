# LiteKuma 🐻⚡

**LiteKuma** is a lightweight, headless uptime monitoring engine inspired by Uptime Kuma, designed for environments that require reliable endpoint health tracking **without the overhead of a WebUI**.

All heartbeat checks and status alerts are written directly to a structured **text file** with automatic log rotation. Target configurations support **custom HTTP headers**, SSL certificate expiration tracking, retry thresholds, and alerting integrations.

---

## Key Features

- **No WebUI Overhead**: Pure headless CLI / daemon running with an ultra-low memory footprint (< 25MB RAM).
- **Text File Logging**: Appends structured, human-readable entries (or TSV/JSON) directly to a text log file with automatic rotation.
- **Custom HTTP Headers**: Full support for custom headers (e.g., `Authorization: Bearer ...`, `X-API-Key`, custom `User-Agent`, tenant headers) with environment variable interpolation (`${API_KEY}`).
- **Multiple Monitor Types**:
  - **HTTP / HTTPS**: Status code checking (e.g. `200-299`), keyword matching, inverted keyword checks, SSL certificate expiry warnings, custom methods (GET, POST, etc.) and payloads.
  - **TCP Port**: Socket connectivity testing (databases, Redis, SMTP, SSH).
  - **ICMP Ping**: Latency and packet drop measurement.
  - **DNS**: Hostname resolution checks against expected IP records.
- **False-Alarm Mitigation**: Configurable `max_retries` and `retry_interval` before transitioning status to `DOWN`.
- **Alert Notifiers**: Webhook (with native Discord and Slack formatters), Telegram Bot, and local command execution (e.g., failover scripts).
- **Uptime & Latency State**: Maintains uptime percentages and latency stats in a lightweight JSON state file.
- **Zero-Downtime Hot Reload**: Re-reads configuration on `SIGHUP` without restarting the process.

---

## Quick Start

### 1. Make the CLI Accessible
Run directly with python or through the wrapper scripts:

```bash
# Directly via Python module
python3 -m litekuma --help

# Or via wrapper script
./run_litekuma.sh --help
# or
./bin/litekuma --help
```

### 2. Generate a Starter Configuration
Create a sample `monitors.yaml` configuration file:

```bash
./bin/litekuma init -o monitors.yaml
```

### 3. Validate Configuration
Verify monitor targets and custom headers:

```bash
./bin/litekuma validate -c monitors.yaml
```

### 4. Run a One-Off Health Check (`check` mode)
Performs a single concurrent check across all targets, prints a status table, writes to the text log, and exits with code `0` (all UP) or `1` (any DOWN). Great for CI/CD pipelines or cron jobs:

```bash
./bin/litekuma check -c monitors.yaml
```

You can also run an ad-hoc check directly from the command line with custom headers:

```bash
./bin/litekuma check -t "https://httpbin.org/headers" \
  -H "Authorization: Bearer secret_token_123" \
  -H "X-Client: LiteKuma"
```

### 5. Run the Continuous Daemon (`run` mode)
Runs the background monitoring engine continuously:

```bash
./bin/litekuma run -c monitors.yaml
```

### 6. View Live Status and Uptime
Inspect historical uptime stats and average latency recorded in the state file:

```bash
./bin/litekuma status
```

---

## Configuration Guide (`monitors.yaml`)

### Target Configuration with Custom Headers

Custom headers are defined under the `headers` key in any HTTP monitor. Environment variables in the format `${VAR_NAME}` or `${VAR_NAME:-default_value}` are dynamically resolved:

```yaml
monitors:
  - id: api-service
    name: Production API Gateway
    type: http
    target: "https://api.example.com/v1/health"
    interval: 30                  # Check every 30 seconds
    timeout: 5.0                  # 5-second timeout
    max_retries: 2                # Retry twice before declaring DOWN
    retry_interval: 3             # 3 seconds between retries
    method: GET
    
    # Custom headers
    headers:
      Authorization: "Bearer ${API_BEARER_TOKEN}"
      X-API-Key: "prod-secret-987"
      X-Tenant-ID: "customer-42"
      User-Agent: "LiteKuma-HealthCheck/1.0"
      Accept: "application/json"

    expected_status: "200-299"    # Status code ranges or lists [200, 204]
    keyword: "healthy"            # Must exist in response body
    verify_ssl: true
    check_ssl_expiry: true        # Alert if SSL cert is nearing expiration
    ssl_expiry_days_threshold: 14 # Threshold in days
```

### Text File Logging Options

Configure where and how logs are stored:

```yaml
logging:
  file_path: uptime.log              # Path to the primary text log
  event_file_path: uptime_events.log # Optional: separate text log for UP/DOWN alerts only
  format: text                       # Options: 'text' (human-readable), 'tsv', or 'json'
  max_bytes: 10485760                # 10 MB maximum file size before rotating
  backup_count: 5                    # Keep 5 rotated backup archives (uptime.log.1, etc.)
  console: true                      # Print colorized logs to console / journal
  log_all_heartbeats: true           # If false, only logs errors and state changes
```

#### Example Text Log Entries (`uptime.log`):
```text
[2026-10-29 20:30:15] [UP  ] [HTTP 200] [  42.1ms] Production API Gateway (https://api.example.com/v1/health) - OK
[2026-10-29 20:30:16] [DOWN] [HTTP 503] [ 120.4ms] Database Service (http://db.local:8080/health) - Status 503 (Service Unavailable) not in expected list
[2026-10-29 20:30:17] [DOWN ALERT] Database Service: Target is DOWN - Status 503 (Service Unavailable) not in expected list
[2026-10-29 20:31:17] [RECOVERY] Database Service: Target is UP (35.2ms) - OK
```

---

## Other Monitor Types

### TCP Port Check
```yaml
- id: postgres-db
  name: PostgreSQL Main
  type: tcp
  target: "db.internal.net"
  port: 5432
  interval: 15
  timeout: 3.0
```

### ICMP Ping Check
```yaml
- id: gateway-ping
  name: Core Router Gateway
  type: ping
  target: "192.168.1.1"
  interval: 60
  timeout: 2.0
```

### DNS Check
```yaml
- id: dns-check
  name: Cloudflare DNS Resolution
  type: dns
  target: "cloudflare.com"
  expected_dns_value: "104.16.132.229"
  interval: 120
```

---

## Notifier Channels

LiteKuma supports multi-channel alerting on status transitions:

```yaml
notifiers:
  - id: discord
    type: webhook
    url: "https://discord.com/api/webhooks/..."
    notify_on_down: true
    notify_on_recovery: true

  - id: telegram
    type: telegram
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
    notify_on_down: true
    notify_on_recovery: true

  - id: failover-script
    type: command
    command: "/bin/bash wan-failover.sh --trigger-litekuma"
    notify_on_down: true
    notify_on_recovery: false
```

When a command notifier runs, it injects environment variables describing the incident:
- `LITEKUMA_EVENT` (`down` or `recovery`)
- `LITEKUMA_MONITOR_ID`, `LITEKUMA_MONITOR_NAME`, `LITEKUMA_TARGET`
- `LITEKUMA_STATUS`, `LITEKUMA_PREVIOUS_STATUS`
- `LITEKUMA_LATENCY_MS`, `LITEKUMA_STATUS_CODE`, `LITEKUMA_MESSAGE`

---

## Running as a Systemd Service

1. Copy the provided unit file:
   ```bash
   sudo cp litekuma.service /etc/systemd/system/litekuma.service
   ```
2. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now litekuma
   ```
3. Check status:
   ```bash
   systemctl status litekuma
   journalctl -u litekuma -f
   ```

---

## Testing

Run the full automated test suite (20 unit & integration tests):

```bash
python3 -m unittest discover -s tests
```
