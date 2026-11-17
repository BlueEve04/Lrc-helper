"""Common source interface."""

from __future__ import annotations

from dataclasses import dataclass

from ..cache import Cache
from ..models import Lyrics, Song
from ..net import RateLimiter


class SourceError(RuntimeError):
    """Base class for source failures."""


class LyricsNotFoundError(SourceError):
    """The source could not provide lyrics for a song."""


class APIError(SourceError):
    """The source returned an error or unusable response."""


@dataclass(slots=True)
class SourceOptions:
    timeout: float = 20.0
    retries: int = 2
    delay: float = 0.25
    cache: Cache | None = None


class BaseSource:
    name: str = ""
    label: str = ""
    default_interval: float = 0.25

    def __init__(self, options: SourceOptions) -> None:
        self.options = options
        self.cache = options.cache
        self.limiter = RateLimiter(options.delay)

    def search(self, query: str, limit: int = 20) -> list[Song]:
        raise NotImplementedError

    def fetch(self, song: Song) -> Lyrics:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def cache_get(self, key: str):
        return self.cache.get(f"{self.name}:{key}") if self.cache else None

    def cache_set(self, key: str, value, ttl: int | None = None) -> None:
        if self.cache:
            self.cache.set(f"{self.name}:{key}", value, ttl)
