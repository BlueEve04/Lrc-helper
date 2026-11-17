"""Kugou KRC parser (decrypted plain-text KRC)."""

from __future__ import annotations

import base64
import json
import re

from ..models import Line, Word
from .lrc import ParsedLrc, _finalize_lines

_KRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_KRC_WORD_RE = re.compile(
    r"(?:\[\d+,\d+\])?<(?P<start>\d+),(?P<duration>\d+),\d+>(?P<text>(?:.(?!\d+,\d+,\d+>))*)",
    re.DOTALL,
)
_TAG_RE = re.compile(r"^\[([A-Za-z][\w-]*):([^\]]*)\]\s*$")
_LANGUAGE_RE = re.compile(r"\[language:([^\]]+)\]")


def _language_tracks(all_lines: list[Line], language_b64: str) -> dict[str, list[Line]]:
    try:
        raw = base64.b64decode(language_b64)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    tracks: dict[str, list[Line]] = {}
    content_items = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content_items, list):
        return tracks

    for item in content_items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        rows = item.get("lyricContent")
        if not isinstance(rows, list):
            continue
        track: list[Line] = []
        for row_index, line in enumerate(all_lines):
            if row_index >= len(rows):
                break
            row = rows[row_index]
            words: list[Word] = []
            if line.text.strip():
                if kind == 0:
                    # Word-level romaji: one string per original word.
                    if isinstance(row, list) and len(row) == len(line.words):
                        words = [
                            Word(word.start, word.end, str(text))
                            for word, text in zip(line.words, row)
                            if str(text)
                        ]
                    elif isinstance(row, list):
                        text = "".join(str(part) for part in row)
                        words = [Word(line.start, line.end, text)] if text else []
                    else:
                        text = str(row)
                        words = [Word(line.start, line.end, text)] if text else []
                elif kind == 1:
                    # Line-level translation.
                    if isinstance(row, list):
                        text = "".join(str(part) for part in row)
                    else:
                        text = str(row)
                    if text:
                        words = [Word(line.start, line.end, text)]
            # Keep a placeholder line so the track stays index-aligned with the
            # original, even when this row has no translation.
            track.append(Line(line.start, line.end, words))
        name = "roma" if kind == 0 else "ts" if kind == 1 else None
        if name and track and any(line.text for line in track):
            tracks[name] = track
    return tracks


def parse_krc(text: str) -> ParsedLrc:
    """Parse KRC text into original, translation and romaji tracks."""
    tags: dict[str, str] = {}
    language_b64 = ""

    language_match = _LANGUAGE_RE.search(text)
    if language_match:
        language_b64 = language_match.group(1)

    all_lines: list[Line] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = _KRC_LINE_RE.match(line)
        if not match:
            tag_match = _TAG_RE.match(line)
            if tag_match:
                key = tag_match.group(1).lower()
                if key != "language":
                    tags[key] = tag_match.group(2).strip()
            continue

        line_start = int(match.group(1))
        line_duration = int(match.group(2))
        body = match.group(3)
        words: list[Word] = []
        for word_match in _KRC_WORD_RE.finditer(body):
            word_text = word_match.group("text")
            if not word_text:
                continue
            word_start = line_start + int(word_match.group("start"))
            word_end = word_start + int(word_match.group("duration"))
            words.append(Word(word_start, word_end, word_text))
        if not words and not _KRC_WORD_RE.search(body):
            plain = body.strip()
            if plain:
                words = [Word(line_start, line_start + line_duration, plain)]
        all_lines.append(Line(line_start, line_start + line_duration, words))

    all_lines = _finalize_lines(all_lines, keep_empty=True)
    orig_lines = [line for line in all_lines if line.text.strip()]
    tracks: dict[str, list[Line]] = {}
    if orig_lines:
        tracks["orig"] = orig_lines
    if language_b64:
        tracks.update(_language_tracks(all_lines, language_b64))
    return ParsedLrc(tags=tags, lines=tracks.get("orig", []), tracks=tracks)
