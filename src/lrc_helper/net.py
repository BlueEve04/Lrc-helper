"""HTTP helpers: retries and per-source rate limiting."""

from __future__ import annotations

import logging
import random
import threading
import time

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "Lrc-helper/0.1.0 (+https://github.com/BlueEve04/Lrc-helper)"


class RequestError(RuntimeError):
    pass


def make_client(timeout: float = 20.0, http2: bool = True, headers: dict[str, str] | None = None) -> httpx.Client:
    default_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }
    if headers:
        default_headers.update(headers)
    return httpx.Client(
        headers=default_headers,
        timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
        follow_redirects=True,
        http2=http2,
    )


def request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 2,
    backoff: float = 0.6,
    **kwargs,
) -> httpx.Response:
    """Send a request, retrying transient network and HTTP errors."""
    last_error: Exception | None = None
    retries = max(0, retries)
    for attempt in range(retries + 1):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code in (429, 500, 502, 503, 504):
                raise RequestError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response
        except (httpx.HTTPError, RequestError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            delay = backoff * (2**attempt) + random.random() * 0.2  # noqa: S311
            logger.debug("request %s failed (%s), retrying in %.1fs", url, exc, delay)
            time.sleep(delay)
    raise RequestError(str(last_error)) from last_error


class RateLimiter:
    """Serialize requests from one source and enforce a minimum interval."""

    def __init__(self, min_interval: float = 0.2) -> None:
        self.min_interval = max(0.0, min_interval)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self.min_interval - (now - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()

    def set_interval(self, value: float) -> None:
        self.min_interval = max(0.0, value)
