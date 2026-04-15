"""
Proxy Manager — manages a pool of proxies with health checks, auto-failover,
and statistics tracking.

Supports:
  - Free proxy lists (file/URL)
  - Paid residential proxies (BrightData, Oxylabs, SmartProxy)
  - Local proxies (SOCKS5, HTTP)
  - No-proxy mode (direct connection)

Usage:
    manager = ProxyManager()
    manager.load_from_file("config/proxies.json")
    # or
    manager.add_proxy("http://user:pass@proxy.example.com:8080")

    proxy = manager.get_best()  # returns healthiest proxy
    manager.report_success(proxy)  # track success
    manager.report_failure(proxy)  # track failure, auto-disable if too many
"""
import json
import time
import asyncio
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Proxy:
    """Single proxy with health tracking."""
    server: str                     # "http://host:port" or "socks5://host:port"
    username: str = ""
    password: str = ""
    label: str = ""                 # friendly name ("brightdata-1", "free-india-3")
    proxy_type: str = "http"        # "http", "https", "socks5"

    # Health tracking
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_used: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0
    avg_response_ms: float = 0.0
    enabled: bool = True

    # Auto-disable threshold
    max_consecutive_failures: int = 5

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0  # untested = assume good
        return self.success_count / self.total_requests

    @property
    def health_score(self) -> float:
        """0-1 score. Higher = healthier."""
        if not self.enabled:
            return 0.0
        rate = self.success_rate
        recency = 1.0  # boost for recently successful
        if self.last_success > 0:
            age = time.time() - self.last_success
            recency = max(0.1, 1.0 - (age / 3600))  # decay over 1 hour
        return rate * 0.7 + recency * 0.3

    def to_playwright_config(self) -> dict:
        """Convert to Playwright proxy format."""
        config = {"server": self.server}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config

    def to_dict(self) -> dict:
        return {
            "server": self.server,
            "username": self.username,
            "password": "***" if self.password else "",
            "label": self.label,
            "proxy_type": self.proxy_type,
            "enabled": self.enabled,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 3),
            "health_score": round(self.health_score, 3),
            "avg_response_ms": round(self.avg_response_ms, 1),
        }


class ProxyManager:
    """Manages a pool of proxies with health tracking."""

    def __init__(self):
        self.proxies: list[Proxy] = []
        self._direct_mode = True  # no proxy by default

    @property
    def active_proxies(self) -> list[Proxy]:
        return [p for p in self.proxies if p.enabled]

    @property
    def is_direct(self) -> bool:
        return self._direct_mode or len(self.active_proxies) == 0

    def add_proxy(self, server: str, username: str = "", password: str = "",
                  label: str = "", proxy_type: str = "http") -> Proxy:
        """Add a proxy to the pool."""
        proxy = Proxy(
            server=server, username=username, password=password,
            label=label or server, proxy_type=proxy_type,
        )
        self.proxies.append(proxy)
        self._direct_mode = False
        return proxy

    def remove_proxy(self, server: str):
        """Remove a proxy by server URL."""
        self.proxies = [p for p in self.proxies if p.server != server]
        if not self.proxies:
            self._direct_mode = True

    def load_from_file(self, path: str):
        """Load proxies from JSON config file."""
        config_path = Path(path)
        if not config_path.exists():
            print(f"[proxy] Config not found: {path}")
            return

        with open(config_path) as f:
            data = json.load(f)

        for p in data.get("proxies", []):
            self.add_proxy(
                server=p["server"],
                username=p.get("username", ""),
                password=p.get("password", ""),
                label=p.get("label", ""),
                proxy_type=p.get("type", "http"),
            )
        print(f"[proxy] Loaded {len(self.proxies)} proxies from {path}")

    def load_from_env(self):
        """Load proxy from environment variables."""
        import os
        proxy_url = os.environ.get("PROXY_URL", "")
        if proxy_url:
            user = os.environ.get("PROXY_USER", "")
            passwd = os.environ.get("PROXY_PASS", "")
            self.add_proxy(proxy_url, user, passwd, label="env-proxy")
            print(f"[proxy] Loaded proxy from env: {proxy_url}")

    def get_best(self) -> Optional[Proxy]:
        """Get the healthiest active proxy. Returns None if direct mode."""
        if self.is_direct:
            return None
        active = self.active_proxies
        if not active:
            return None
        # Sort by health score (highest first), then by least recently used
        active.sort(key=lambda p: (-p.health_score, p.last_used))
        return active[0]

    def get_next(self) -> Optional[Proxy]:
        """Get next proxy in round-robin. Returns None if direct mode."""
        if self.is_direct:
            return None
        active = self.active_proxies
        if not active:
            return None
        # Pick least recently used
        active.sort(key=lambda p: p.last_used)
        proxy = active[0]
        proxy.last_used = time.time()
        return proxy

    def report_success(self, proxy: Optional[Proxy], response_ms: float = 0):
        """Report successful request through a proxy."""
        if proxy is None:
            return
        proxy.total_requests += 1
        proxy.success_count += 1
        proxy.consecutive_failures = 0
        proxy.last_success = time.time()
        proxy.last_used = time.time()
        if response_ms > 0:
            # Running average
            if proxy.avg_response_ms == 0:
                proxy.avg_response_ms = response_ms
            else:
                proxy.avg_response_ms = proxy.avg_response_ms * 0.8 + response_ms * 0.2

    def report_failure(self, proxy: Optional[Proxy], error: str = ""):
        """Report failed request. Auto-disables after too many consecutive failures."""
        if proxy is None:
            return
        proxy.total_requests += 1
        proxy.failure_count += 1
        proxy.consecutive_failures += 1
        proxy.last_failure = time.time()
        proxy.last_used = time.time()

        if proxy.consecutive_failures >= proxy.max_consecutive_failures:
            proxy.enabled = False
            print(f"[proxy] DISABLED {proxy.label} — {proxy.consecutive_failures} consecutive failures")

    def re_enable_all(self):
        """Re-enable all disabled proxies (for periodic retry)."""
        for p in self.proxies:
            if not p.enabled:
                p.enabled = True
                p.consecutive_failures = 0
                print(f"[proxy] Re-enabled {p.label}")

    async def health_check(self, proxy: Proxy, test_url: str = "https://httpbin.org/ip",
                           timeout: int = 10) -> bool:
        """Test if a proxy is working."""
        try:
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy.server,
                "https": proxy.server,
            })
            opener = urllib.request.build_opener(proxy_handler)
            start = time.time()
            req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0"})
            with opener.open(req, timeout=timeout) as r:
                if r.status == 200:
                    ms = (time.time() - start) * 1000
                    self.report_success(proxy, ms)
                    return True
        except Exception as e:
            self.report_failure(proxy, str(e))
        return False

    async def health_check_all(self, test_url: str = "https://httpbin.org/ip"):
        """Run health check on all proxies."""
        print(f"[proxy] Health checking {len(self.proxies)} proxies...")
        for p in self.proxies:
            ok = await self.health_check(p, test_url)
            status = "✅" if ok else "❌"
            print(f"  {status} {p.label} — {p.server[:40]}")

    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "total": len(self.proxies),
            "active": len(self.active_proxies),
            "disabled": len(self.proxies) - len(self.active_proxies),
            "direct_mode": self.is_direct,
            "proxies": [p.to_dict() for p in self.proxies],
        }

    def save_stats(self, path: str = "data/logs/proxy_stats.json"):
        """Save current proxy stats to file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(self.get_stats(), f, indent=2)
