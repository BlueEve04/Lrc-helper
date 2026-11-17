"""Lyric sources."""

from __future__ import annotations

from .base import APIError, BaseSource, LyricsNotFoundError, SourceError, SourceOptions
from .kugou import KugouSource
from .lrclib import LrclibSource
from .netease import NeteaseSource
from .qq import QQSource

SOURCE_CLASSES: dict[str, type[BaseSource]] = {
    "qq": QQSource,
    "ne": NeteaseSource,
    "kg": KugouSource,
    "lrclib": LrclibSource,
}

SOURCE_LABELS = {
    "qq": "QQ Music",
    "ne": "NetEase Cloud Music",
    "kg": "Kugou Music",
    "lrclib": "lrclib.net",
}

DEFAULT_SOURCES = ("qq", "kg", "ne", "lrclib")

__all__ = [
    "APIError",
    "BaseSource",
    "DEFAULT_SOURCES",
    "KugouSource",
    "LrclibSource",
    "LyricsNotFoundError",
    "NeteaseSource",
    "QQSource",
    "SOURCE_CLASSES",
    "SOURCE_LABELS",
    "SourceError",
    "SourceOptions",
]
