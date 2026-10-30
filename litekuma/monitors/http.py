from __future__ import annotations

import asyncio
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    httpx = None
    HAS_HTTPX = False

from litekuma.models import CheckResult, MonitorConfig, Status
from litekuma.monitors.base import BaseMonitor


class HttpMonitor(BaseMonitor):
    """HTTP/HTTPS monitor supporting custom headers, methods, keywords, and SSL expiry.
    Works seamlessly using httpx if installed, or Python standard library urllib.request as fallback.
    """

    def __init__(self, config: MonitorConfig):
        super().__init__(config)
        # Ensure default User-Agent if not specified in headers
        self._headers = dict(config.headers)
        if not any(k.lower() == "user-agent" for k in self._headers):
            self._headers["User-Agent"] = "LiteKuma/1.0"

    def _evaluate_response(
        self,
        status_code: int,
        reason_phrase: str,
        headers: dict,
        body_text: str,
        elapsed_ms: float,
    ) -> CheckResult:
        # 1. Validate status code
        if status_code not in self.config.expected_status:
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                status_code=status_code,
                message=f"Status {status_code} ({reason_phrase}) not in expected list",
                details={"headers": headers},
            )

        # 2. Validate keyword if configured
        if self.config.keyword:
            has_kw = self.config.keyword in body_text
            if self.config.invert_keyword and has_kw:
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    status_code=status_code,
                    message=f"Inverted keyword check failed: found forbidden '{self.config.keyword}'",
                )
            elif not self.config.invert_keyword and not has_kw:
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    status_code=status_code,
                    message=f"Keyword check failed: '{self.config.keyword}' not found in response",
                )

        # 3. Optional SSL certificate expiry check
        details: dict = {}
        if self.config.check_ssl_expiry and self.config.target.startswith("https://"):
            ssl_info = self._check_ssl_expiry()
            details["ssl"] = ssl_info
            days_remaining = ssl_info.get("days_remaining")
            if days_remaining is not None and days_remaining <= self.config.ssl_expiry_days_threshold:
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DEGRADED,
                    latency_ms=elapsed_ms,
                    status_code=status_code,
                    message=f"SSL certificate expires in {days_remaining} day(s) (threshold: {self.config.ssl_expiry_days_threshold}d)",
                    details=details,
                )

        return CheckResult(
            monitor_id=self.config.id,
            name=self.config.name,
            target=self.config.target,
            monitor_type=self.config.type,
            status=Status.UP,
            latency_ms=elapsed_ms,
            status_code=status_code,
            message="OK",
            details=details,
        )

    async def perform_check(self) -> CheckResult:
        if HAS_HTTPX:
            return await self._perform_check_httpx()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._perform_check_urllib)

    async def _perform_check_httpx(self) -> CheckResult:
        start_time = time.perf_counter()
        timeout = httpx.Timeout(self.config.timeout)

        req_kwargs = {
            "method": self.config.method,
            "url": self.config.target,
            "headers": self._headers,
            "follow_redirects": self.config.follow_redirects,
            "timeout": timeout,
        }
        if self.config.body and self.config.method not in ("GET", "HEAD"):
            req_kwargs["content"] = self.config.body.encode("utf-8")

        async with httpx.AsyncClient(verify=self.config.verify_ssl) as client:
            try:
                response = await client.request(**req_kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return self._evaluate_response(
                    status_code=response.status_code,
                    reason_phrase=response.reason_phrase,
                    headers=dict(response.headers),
                    body_text=response.text,
                    elapsed_ms=elapsed_ms,
                )
            except httpx.TimeoutException:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message=f"Connection timed out after {self.config.timeout:.1f}s",
                )
            except httpx.ConnectError as err:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message=f"Connection failed: {str(err)}",
                )
            except httpx.HTTPError as err:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message=f"HTTP error: {str(err)}",
                )

    def _perform_check_urllib(self) -> CheckResult:
        start_time = time.perf_counter()
        ctx = ssl.create_default_context()
        if not self.config.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req_data = None
        if self.config.body and self.config.method not in ("GET", "HEAD"):
            req_data = self.config.body.encode("utf-8")

        req = urllib.request.Request(
            url=self.config.target,
            data=req_data,
            headers=self._headers,
            method=self.config.method,
        )

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        handlers = [urllib.request.HTTPSHandler(context=ctx)]
        if not self.config.follow_redirects:
            handlers.append(NoRedirectHandler())

        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(req, timeout=self.config.timeout) as resp:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                body = resp.read().decode("utf-8", errors="ignore")
                return self._evaluate_response(
                    status_code=resp.status,
                    reason_phrase=getattr(resp, "reason", "OK"),
                    headers=dict(resp.headers),
                    body_text=body,
                    elapsed_ms=elapsed_ms,
                )
        except urllib.error.HTTPError as err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            body = err.read().decode("utf-8", errors="ignore")
            return self._evaluate_response(
                status_code=err.code,
                reason_phrase=getattr(err, "reason", "Error"),
                headers=dict(err.headers),
                body_text=body,
                elapsed_ms=elapsed_ms,
            )
        except urllib.error.URLError as err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if isinstance(err.reason, (socket.timeout, TimeoutError)):
                return CheckResult(
                    monitor_id=self.config.id,
                    name=self.config.name,
                    target=self.config.target,
                    monitor_type=self.config.type,
                    status=Status.DOWN,
                    latency_ms=elapsed_ms,
                    message=f"Connection timed out after {self.config.timeout:.1f}s",
                )
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Connection failed: {err.reason}",
            )
        except (socket.timeout, TimeoutError):
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"Connection timed out after {self.config.timeout:.1f}s",
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return CheckResult(
                monitor_id=self.config.id,
                name=self.config.name,
                target=self.config.target,
                monitor_type=self.config.type,
                status=Status.DOWN,
                latency_ms=elapsed_ms,
                message=f"HTTP check error: {str(exc)}",
            )

    def _check_ssl_expiry(self) -> dict:
        """Inspects the SSL certificate of target host and calculates remaining validity."""
        try:
            parsed = urlparse(self.config.target)
            hostname = parsed.hostname or self.config.target
            port = parsed.port or 443

            context = ssl.create_default_context()
            if not self.config.verify_ssl:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

            with socket.create_connection((hostname, port), timeout=self.config.timeout) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert()
                    if not cert:
                        return {"valid": True, "details": "Unverified SSL cert"}

                    # notAfter format: 'Jan 15 12:00:00 2027 GMT'
                    not_after_str = cert.get("notAfter")
                    if not_after_str:
                        not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                        now_utc = datetime.now(timezone.utc)
                        days = (not_after - now_utc).days
                        return {
                            "valid": days > 0,
                            "days_remaining": days,
                            "expires_at": not_after.isoformat(),
                        }
            return {"valid": True}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}
