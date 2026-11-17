"""Parsers for the lyric formats returned by the supported sources."""

from __future__ import annotations

from .krc import parse_krc
from .lrc import parse_lrc, parse_plaintext
from .lrclib import parse_lyricsfile
from .qrc import parse_qrc, parse_qrc_or_lrc
from .yrc import parse_yrc

__all__ = [
    "parse_krc",
    "parse_lrc",
    "parse_lyricsfile",
    "parse_plaintext",
    "parse_qrc",
    "parse_qrc_or_lrc",
    "parse_yrc",
]
