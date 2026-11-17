"""Tiny JSON-file cache for search results and fetched lyrics."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL = 30 * 24 * 3600


def default_cache_dir() -> Path:
    override = os.environ.get("LRC_HELPER_CACHE")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "lrc-helper" / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "lrc-helper"


class Cache:
    def __init__(self, directory: Path | str | None = None, enabled: bool = True, ttl: int = DEFAULT_TTL) -> None:
        self.dir = Path(directory) if directory else default_cache_dir()
        self.enabled = enabled
        self.ttl = ttl
        if self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.warning("cannot create cache directory %s; cache disabled", self.dir)
                self.enabled = False

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("expires", 0) < time.time():
                path.unlink(missing_ok=True)
                return None
            return raw.get("value")
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        payload = {"expires": time.time() + (ttl if ttl is not None else self.ttl), "value": value}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.dir, delete=False, suffix=".tmp") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                temp_name = handle.name
            os.replace(temp_name, path)
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("cache write failed for %s: %s", key, exc)
