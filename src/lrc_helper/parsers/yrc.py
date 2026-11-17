"""NetEase YRC parser."""

from __future__ import annotations

import re

from ..models import Line, Word
from .lrc import ParsedLrc, _finalize_lines

_YRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD_RE = re.compile(
    r"(?:\[\d+,\d+\])?\((?P<start>\d+),(?P<duration>\d+),\d+\)(?P<text>(?:.(?!\d+,\d+,\d+\)))*)",
    re.DOTALL,
)
_TAG_RE = re.compile(r"^\[([A-Za-z][\w-]*):([^\]]*)\]\s*$")


def parse_yrc(text: str) -> ParsedLrc:
    """Parse YRC's ``[lineStart,lineDuration](wordStart,wordDuration,0)text``."""
    tags: dict[str, str] = {}
    lines: list[Line] = []

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _YRC_LINE_RE.match(line)
        if not match:
            tag_match = _TAG_RE.match(line)
            if tag_match:
                tags[tag_match.group(1).lower()] = tag_match.group(2).strip()
            continue

        line_start = int(match.group(1))
        line_duration = int(match.group(2))
        body = match.group(3)
        words: list[Word] = []
        for word_match in _YRC_WORD_RE.finditer(body):
            word_text = word_match.group("text")
            if not word_text:
                continue
            word_start = int(word_match.group("start"))
            word_duration = int(word_match.group("duration"))
            words.append(Word(word_start, word_start + word_duration, word_text))

        if not words and not _YRC_WORD_RE.search(body):
            plain = body.strip()
            if plain:
                words = [Word(line_start, line_start + line_duration, plain)]
        elif all(word.start is not None and word.start < line_start for word in words):
            # A few services emit offsets relative to the line instead of
            # absolute timestamps.
            for word in words:
                if word.start is not None:
                    word.start += line_start
                if word.end is not None:
                    word.end += line_start

        if words:
            lines.append(Line(line_start, line_start + line_duration, words))

    return ParsedLrc(tags=tags, lines=_finalize_lines(lines))
