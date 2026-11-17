"""Parser for Lrclib's experimental ``lyricsfile`` word-sync format."""

from __future__ import annotations

from typing import Any

import yaml

from ..models import Line, Word
from .lrc import ParsedLrc, _finalize_lines


def parse_lyricsfile(text: str) -> ParsedLrc:
    """Parse the YAML ``lyricsfile`` returned by lrclib.net.

    The structure is::

        lines:
        - text: ...
          start_ms: 29250
          end_ms: 35697
          words:
          - text: ...
            start_ms: 29250
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return ParsedLrc(tags={}, lines=[])

    if not isinstance(data, dict):
        return ParsedLrc(tags={}, lines=[])

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    tags: dict[str, str] = {}
    tag_map = {"title": "ti", "artist": "ar", "album": "al"}
    for key, target in tag_map.items():
        value = metadata.get(key)
        if isinstance(value, str) and value:
            tags[target] = value

    lines: list[Line] = []
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list):
        return ParsedLrc(tags=tags, lines=[])

    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        line_start = _as_int(raw_line.get("start_ms"))
        line_end = _as_int(raw_line.get("end_ms"))
        text = str(raw_line.get("text") or "")
        raw_words = raw_line.get("words")
        words: list[Word] = []
        if isinstance(raw_words, list):
            for raw_word in raw_words:
                if not isinstance(raw_word, dict):
                    continue
                word_text = str(raw_word.get("text") or "")
                if not word_text:
                    continue
                word_start = _as_int(raw_word.get("start_ms"))
                word_end = _as_int(raw_word.get("end_ms"))
                words.append(Word(word_start, word_end, word_text))
        if not words and text:
            words = [Word(line_start, line_end, text)]
        if words:
            lines.append(Line(line_start, line_end, words))

    return ParsedLrc(tags=tags, lines=_finalize_lines(lines))


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None
