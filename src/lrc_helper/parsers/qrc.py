"""QQ Music QRC parser."""

from __future__ import annotations

import html
import re

from ..models import Line, Word
from .lrc import ParsedLrc, _finalize_lines, looks_like_lrc, parse_lrc, parse_plaintext

_QRC_XML_RE = re.compile(r"<Lyric_1\b[^>]*\bLyricContent=\"(.*?)\"\s*/>", re.DOTALL)
_QRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_QRC_WORD_RE = re.compile(r"(?P<text>(?:(?!\(\d+,\d+\)).)*)\((?P<start>\d+),(?P<duration>\d+)\)", re.DOTALL)
_TAG_RE = re.compile(r"^\[([A-Za-z][\w-]*):([^\]]*)\]\s*$")


def extract_qrc_content(text: str) -> str:
    match = _QRC_XML_RE.search(text)
    if match:
        return html.unescape(match.group(1))
    return text


def parse_qrc(text: str) -> ParsedLrc:
    """Parse QRC's ``[lineStart,lineDuration](wordStart,wordDuration)text``."""
    content = extract_qrc_content(text)
    tags: dict[str, str] = {}
    lines: list[Line] = []

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _QRC_LINE_RE.match(line)
        if not match:
            tag_match = _TAG_RE.match(line)
            if tag_match and tag_match.group(1).lower() not in ("kana",):
                tags[tag_match.group(1).lower()] = tag_match.group(2).strip()
            continue

        line_start = int(match.group(1))
        line_duration = int(match.group(2))
        body = match.group(3)
        words: list[Word] = []
        for word_match in _QRC_WORD_RE.finditer(body):
            word_text = word_match.group("text")
            if not word_text:
                continue
            word_start = int(word_match.group("start"))
            word_duration = int(word_match.group("duration"))
            words.append(Word(word_start, word_start + word_duration, word_text))

        if not words and not _QRC_WORD_RE.search(body):
            plain = body.strip()
            if plain:
                words = [Word(line_start, line_start + line_duration, plain)]
        if words:
            lines.append(Line(line_start, line_start + line_duration, words))

    return ParsedLrc(tags=tags, lines=_finalize_lines(lines))


def parse_qrc_or_lrc(text: str) -> ParsedLrc:
    """Parse QRC XML/plain QRC, enhanced LRC, or plain text."""
    if not text or not text.strip():
        return ParsedLrc(tags={}, lines=[])
    content = extract_qrc_content(text)
    if any(_QRC_LINE_RE.match(line.strip()) for line in content.splitlines()):
        return parse_qrc(text)
    if looks_like_lrc(content):
        return parse_lrc(content)
    return parse_plaintext(content)
