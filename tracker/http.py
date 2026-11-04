"""Shared HTTP session: retries, backoff, polite rate limiting."""
from __future__ import annotations

import logging
import os
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_UA = "ai-adoption-tracker (github.com/kechunwu/ai-adoption-tracker)"


def make_session(user_agent: str | None = None, extra_headers: dict | None = None) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=6,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = user_agent or DEFAULT_UA
    if extra_headers:
        s.headers.update(extra_headers)
    return s


class RateLimiter:
    """Simple minimum-interval limiter (e.g. SEC: <=10 req/s)."""

    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v else default
