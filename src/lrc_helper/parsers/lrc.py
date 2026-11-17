"""Standard LRC, enhanced LRC and inline word-timestamp LRC parser."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..models import Line, Word
from ..timeutil import time_to_ms

_TAG_RE = re.compile(r"^\[([A-Za-z][\w-]*):([^\]]*)\]\s*$")
_LEADING_TS_RE = re.compile(r"^\s*\[(\d{1,4}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_ENHANCED_RE = re.compile(r"<(\d{1,4}):(\d{1,2})(?:[.:](\d{1,3}))?>")
_INLINE_TS_RE = re.compile(r"\[(\d{1,4}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


@dataclass(slots=True)
class ParsedLrc:
    tags: dict[str, str]
    lines: list[Line]
    tracks: dict[str, list[Line]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.lines and "orig" not in self.tracks:
            self.tracks["orig"] = self.lines


def _ms_from_match(match: re.Match[str]) -> int | None:
    groups = match.groups()
    if not groups or groups[0] is None or groups[1] is None:
        return None
    return time_to_ms(groups[0], groups[1], groups[2])


def _words_from_enhanced(content: str, line_start: int | None) -> list[Word]:
    """Parse ``<mm:ss.xx>word`` enhanced LRC content."""
    matches = list(_ENHANCED_RE.finditer(content))
    if not matches:
        return []
    words: list[Word] = []
    first_start = _ms_from_match(matches[0])
    leading = content[: matches[0].start()].strip()
    if leading:
        words.append(Word(line_start, first_start, leading))

    for index, match in enumerate(matches):
        start = _ms_from_match(match)
        end = match.end()
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[end:next_start]
        if text:
            words.append(Word(start, None, text))
    return words


def _words_from_inline_timestamps(content: str, line_start: int | None) -> list[Word]:
    """Parse ESLyric-style ``[mm:ss.xx]word[mm:ss.xx]word`` content.

    This is only used when the square-bracket timestamps are *inside* the line,
    after the leading line timestamps have already been removed.
    """
    matches = list(_INLINE_TS_RE.finditer(content))
    if not matches:
        return []
    words: list[Word] = []
    leading = content[: matches[0].start()].strip()
    if leading:
        words.append(Word(line_start, _ms_from_match(matches[0]), leading))
    for index, match in enumerate(matches):
        start = _ms_from_match(match)
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[match.end() : next_start]
        if text:
            words.append(Word(start, None, text))
    return words


def _split_leading_timestamps_line(line: str) -> tuple[list[int], str]:
    starts: list[int] = []
    rest = line
    while True:
        match = _LEADING_TS_RE.match(rest)
        if not match:
            break
        start = _ms_from_match(match)
        if start is not None:
            starts.append(start)
        rest = rest[match.end() :]
    return starts, rest


def _json_credit_line(line: str) -> tuple[int, str] | None:
    """Parse NetEase's JSON credit lines (``{"t":0,"c":[{"tx":"..."}]}``)."""
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "t" not in data or "c" not in data:
        return None
    try:
        start = int(data["t"])
        text = "".join(str(part.get("tx", "")) for part in data["c"] if isinstance(part, dict))
    except (TypeError, ValueError):
        return None
    return start, text


def _finalize_lines(lines: list[Line], keep_empty: bool = False) -> list[Line]:
    if not keep_empty:
        lines = [line for line in lines if line.words]
    lines.sort(key=lambda item: (item.start if item.start is not None else 0))
    for index, line in enumerate(lines):
        if line.start is None:
            line.start = lines[index - 1].end if index else 0
        if line.end is None or (line.end <= line.start and index + 1 < len(lines) and lines[index + 1].start is not None and lines[index + 1].start > line.start):
            if index + 1 < len(lines) and lines[index + 1].start is not None and lines[index + 1].start > line.start:
                line.end = lines[index + 1].start
            elif line.words and line.words[-1].end is not None:
                line.end = line.words[-1].end
            else:
                line.end = line.start + 1000

        for word_index, word in enumerate(line.words):
            if word.start is None:
                if word_index and line.words[word_index - 1].end is not None:
                    word.start = line.words[word_index - 1].end
                else:
                    word.start = line.start
            if word.end is None:
                if word_index + 1 < len(line.words) and line.words[word_index + 1].start is not None:
                    word.end = line.words[word_index + 1].start
                else:
                    word.end = line.end
            if word.end is not None and word.start is not None and word.end < word.start:
                word.end = word.start
        if line.end is not None and line.start is not None and line.end < line.start:
            line.end = line.start
    return lines


def parse_lrc(text: str) -> ParsedLrc:
    """Parse standard, enhanced, and multi-timestamp LRC text."""
    tags: dict[str, str] = {}
    lines: list[Line] = []

    if text.startswith("﻿"):
        text = text.lstrip("﻿")
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        credit = _json_credit_line(line)
        if credit is not None:
            start, credit_text = credit
            if credit_text:
                lines.append(Line(start, None, [Word(start, None, credit_text)]))
            continue

        if line.startswith("["):
            starts, content = _split_leading_timestamps_line(line)
            if not starts:
                tag_match = _TAG_RE.match(line)
                if tag_match:
                    key = tag_match.group(1).strip().lower()
                    if key not in ("kana", "language"):
                        tags[key] = tag_match.group(2).strip()
                    continue
                # A bracketed annotation such as [Chorus] in plain text.
                content = line
                starts = []

            content = content.strip()
            if not starts:
                # No line timestamp.  LRC cannot position this line; keep it out
                # of the timed tracks (plaintext fallback handles it separately).
                continue

            for start in starts:
                if not content:
                    continue
                if _ENHANCED_RE.search(content):
                    words = _words_from_enhanced(content, start)
                elif _INLINE_TS_RE.search(content):
                    words = _words_from_inline_timestamps(content, start)
                else:
                    words = [Word(start, None, content.strip())]
                if words:
                    lines.append(Line(start, None, words))
            continue

        # A non-bracketed line in an LRC file is usually a plain-text line or a
        # trailing remark.  Ignore it; parse_plaintext handles pure text files.

    offset_value = tags.get("offset")
    if offset_value:
        try:
            offset = int(float(offset_value))
        except ValueError:
            offset = 0
        if offset:
            for line in lines:
                if line.start is not None:
                    line.start = max(0, line.start - offset)
                if line.end is not None:
                    line.end = max(0, line.end - offset)
                for word in line.words:
                    if word.start is not None:
                        word.start = max(0, word.start - offset)
                    if word.end is not None:
                        word.end = max(0, word.end - offset)
            tags["offset"] = "0"

    return ParsedLrc(tags=tags, lines=_finalize_lines(lines))


def parse_plaintext(text: str) -> ParsedLrc:
    """Parse a plain-text lyric file (no timestamps)."""
    lines: list[Line] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if line:
            lines.append(Line(None, None, [Word(None, None, line)]))
    return ParsedLrc(tags={}, lines=lines)


def looks_like_lrc(text: str) -> bool:
    return any(_LEADING_TS_RE.match(line.strip()) for line in text.splitlines())
