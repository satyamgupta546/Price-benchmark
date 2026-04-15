"""
Proxy Rotator — wraps ProxyManager with rotation strategies for Playwright scrapers.

Strategies:
  - round_robin: cycle through proxies in order
  - best_health: always pick healthiest proxy
  - random: random selection from active pool
  - per_session: one proxy per browser session (change on restart)
  - per_request: rotate on every page.goto()

Integration with Playwright:
    rotator = ProxyRotator(manager, strategy="round_robin")
    proxy_config = rotator.next()  # returns Playwright-compatible dict or None

    context = await browser.new_context(
        proxy=proxy_config,  # None = direct connection
        ...
    )
"""
import random
import time
from typing import Optional
from .proxy_manager import ProxyManager, Proxy


class ProxyRotator:
    """Rotates proxies for Playwright browser contexts."""

    def __init__(self, manager: ProxyManager, strategy: str = "round_robin"):
        self.manager = manager
        self.strategy = strategy
        self._index = 0
        self._session_proxy: Optional[Proxy] = None
        self._request_count = 0

    def next(self) -> Optional[dict]:
        """Get next proxy config for Playwright. Returns None for direct connection."""
        if self.manager.is_direct:
            return None

        proxy = self._select()
        if proxy is None:
            return None

        proxy.last_used = time.time()
        self._request_count += 1
        return proxy.to_playwright_config()

    def _select(self) -> Optional[Proxy]:
        """Select proxy based on strategy."""
        active = self.manager.active_proxies
        if not active:
            return None

        if self.strategy == "round_robin":
            proxy = active[self._index % len(active)]
            self._index += 1
            return proxy

        elif self.strategy == "best_health":
            return self.manager.get_best()

        elif self.strategy == "random":
            return random.choice(active)

        elif self.strategy == "per_session":
            if self._session_proxy is None or not self._session_proxy.enabled:
                self._session_proxy = self.manager.get_best()
            return self._session_proxy

        elif self.strategy == "per_request":
            return self.manager.get_next()

        return self.manager.get_best()

    def report_success(self, response_ms: float = 0):
        """Report success for current proxy."""
        proxy = self._get_current()
        self.manager.report_success(proxy, response_ms)

    def report_failure(self, error: str = ""):
        """Report failure for current proxy."""
        proxy = self._get_current()
        self.manager.report_failure(proxy, error)

    def _get_current(self) -> Optional[Proxy]:
        """Get the most recently used proxy."""
        if self.manager.is_direct:
            return None
        active = self.manager.active_proxies
        if not active:
            return None
        return max(active, key=lambda p: p.last_used)

    def reset_session(self):
        """Reset session proxy (force pick a new one next time)."""
        self._session_proxy = None

    def get_status(self) -> dict:
        return {
            "strategy": self.strategy,
            "request_count": self._request_count,
            "pool": self.manager.get_stats(),
        }
