"""Align translation/romaji tracks to the original lyric lines."""

from __future__ import annotations

import re

from .models import Line, Word

_PLACEHOLDER_RE = re.compile(r"^(?:/{2,}|\\{2,}|…+|\.{3,}|-+)$")


def _is_placeholder(text: str) -> bool:
    text = text.strip()
    return not text or bool(_PLACEHOLDER_RE.match(text))


def _with_text(line: Line, text: str) -> Line:
    return Line(line.start, line.end, [Word(line.start, line.end, text)])


def align_to_orig(orig: list[Line], other: list[Line], tolerance_ms: int = 1200) -> list[Line]:
    """Return ``other`` lines re-timed to the matching original lines.

    Matching is primarily by start time.  When timestamps are unavailable (or
    do not line up), equal-length tracks fall back to index alignment.
    """
    if not orig or not other:
        return []

    # Already index-aligned tracks (KRC language data, exact-count translations)
    # should keep their original order even when several lines share a timestamp.
    meaningful = [line for line in other if not _is_placeholder(line.text)]
    for candidate_lines in (other, meaningful):
        if len(orig) != len(candidate_lines):
            continue
        aligned = sum(
            1
            for orig_line, other_line in zip(orig, candidate_lines)
            if orig_line.start is None or other_line.start is None or abs(orig_line.start - other_line.start) <= tolerance_ms
        )
        if aligned >= len(orig) * 0.8:
            return [
                _with_text(orig_line, other_line.text.strip())
                for orig_line, other_line in zip(orig, candidate_lines)
                if not _is_placeholder(other_line.text)
            ]

    candidates: list[tuple[int, int, int]] = []
    for other_index, other_line in enumerate(other):
        if _is_placeholder(other_line.text) or other_line.start is None:
            continue
        for orig_index, orig_line in enumerate(orig):
            if orig_line.start is None:
                continue
            diff = abs(other_line.start - orig_line.start)
            if diff <= tolerance_ms:
                candidates.append((diff, orig_index, other_index))

    matched: dict[int, list[Line]] = {}
    if candidates:
        candidates.sort(key=lambda item: item[0])
        used_orig: set[int] = set()
        used_other: set[int] = set()
        for _diff, orig_index, other_index in candidates:
            if orig_index in used_orig or other_index in used_other:
                continue
            used_orig.add(orig_index)
            used_other.add(other_index)
            matched.setdefault(orig_index, []).append(other[other_index])

    if not matched:
        meaningful = [line for line in other if not _is_placeholder(line.text)]
        if len(meaningful) == len(orig):
            for index, other_line in enumerate(meaningful):
                matched[index] = [other_line]
        elif len(meaningful) > len(orig) and orig:
            # Too many lines: distribute extras onto the nearest original line.
            for index, other_line in enumerate(meaningful):
                orig_index = min(index, len(orig) - 1)
                matched.setdefault(orig_index, []).append(other_line)

    result: list[Line] = []
    for orig_index, orig_line in enumerate(orig):
        other_lines = matched.get(orig_index)
        if not other_lines:
            continue
        text = " ".join(line.text.strip() for line in other_lines if line.text.strip())
        if text and not _is_placeholder(text):
            result.append(_with_text(orig_line, text))
    return result
