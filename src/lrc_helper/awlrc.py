"""Build LRC files with an embedded LX Music ``[awlrc:...]`` container.

Container layout (same as LX Music's local-file format)::

    [awlrc:lrc:<base64>,tlrc:<base64>,rlrc:<base64>,awlrc:<base64>]

The four base64 sections are UTF-8 lyric text:

* ``lrc``   line-level original lyrics
* ``tlrc``  line-level translation
* ``rlrc``  line-level romaji
* ``awlrc`` word-level LX lyrics: ``[mm:ss.mmm]<offset,duration>text...``
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

from . import __version__
from .align import align_to_orig
from .models import Line, Lyrics, Word, line_text
from .timeutil import format_timestamp

_CONTAINER_ORDER = (("lrc", "lrc"), ("tlrc", "ts"), ("rlrc", "roma"), ("awlrc", "awlrc"))

_CREDIT_RE = re.compile(
    r"^\s*(?:"
    r"(?:作词|作詞|作曲|编曲|編曲|制作|製作|词|詞|曲|录音|錄音|混音|母带|母帶|"
    r"和声|和聲|合声|合聲|吉他|贝斯|貝斯|鼓|弦乐|弦樂|监制|監製|出品|发行|發行|演唱|歌手)"
    r"[^：:\n]{0,8}[：:]"
    r"|(?:producer|composer|lyricist|arranger|mixing|mastering|guitar|bass|drums|vocal|"
    r"recorded|engineer|lyrics|music)[^:\n]{0,24}:"
    r")\s*",
    re.IGNORECASE,
)


@dataclass(slots=True)
class OutputOptions:
    contents: tuple[str, ...] = ("orig", "ts", "roma")
    visible_tracks: tuple[str, ...] = ("orig",)
    include_container: bool = True
    offset_ms: int = 0
    include_tags: bool = True
    drop_credits: bool = True


@dataclass(slots=True)
class OutputResult:
    text: str
    tracks_written: list[str] = field(default_factory=list)
    has_word: bool = False
    line_count: int = 0


def _clip(value: int | None, fallback: int) -> int:
    if value is None:
        return fallback
    return max(0, int(value))


def _line_start(line: Line) -> int:
    if line.start is not None:
        return max(0, line.start)
    for word in line.words:
        if word.start is not None:
            return max(0, word.start)
    return 0


def _line_end(line: Line, start: int) -> int:
    if line.end is not None:
        return max(start, line.end)
    for word in reversed(line.words):
        if word.end is not None:
            return max(start, word.end)
    return start + 1000


def shift_lines(lines: list[Line], offset_ms: int) -> list[Line]:
    if not offset_ms:
        return lines
    shifted: list[Line] = []
    for line in lines:
        words = [
            Word(
                max(0, word.start + offset_ms) if word.start is not None else None,
                max(0, word.end + offset_ms) if word.end is not None else None,
                word.text,
            )
            for word in line.words
        ]
        shifted.append(
            Line(
                max(0, line.start + offset_ms) if line.start is not None else None,
                max(0, line.end + offset_ms) if line.end is not None else None,
                words,
            )
        )
    return shifted


def build_line_track(lines: list[Line]) -> str:
    """Build a line-level LRC track (no word timestamps)."""
    output: list[str] = []
    for line in lines:
        text = line_text(line).replace("\r", " ").replace("\n", " ").strip()
        if not text:
            continue
        start = _line_start(line)
        output.append(f"[{format_timestamp(start)}]{text}")
    return "\n".join(output)


def build_word_track(lines: list[Line]) -> str:
    """Build an LX word-level track.

    Returns an empty string when the source is only line-synced, so we never
    pretend that a line-level track is word-synced.
    """
    has_multiple = any(
        len([word for word in line.words if word.text and word.start is not None]) > 1
        for line in lines
    )
    if not has_multiple:
        return ""

    output: list[str] = []
    for line in lines:
        text_words = [word for word in line.words if word.text]
        if not text_words:
            continue
        start = _line_start(line)
        end = _line_end(line, start)
        pieces: list[str] = [f"[{format_timestamp(start)}]"]
        timed: list[tuple[int, int, str]] = []
        for index, word in enumerate(text_words):
            word_start = _clip(word.start, start)
            if index + 1 < len(text_words):
                next_start = _clip(text_words[index + 1].start, end)
            else:
                next_start = end
            word_end = _clip(word.end, next_start)
            if word_end < word_start:
                word_end = word_start
            timed.append((word_start, word_end, word.text))

        # KRC sometimes emits all-zero word durations for credit lines.  Spread
        # the line duration evenly so players still animate the line.
        if timed and all(word_end == word_start for word_start, word_end, _text in timed):
            spread_end = end if end > start else start + max(1000, 100 * len(timed))
            base, remainder = divmod(spread_end - start, len(timed))
            cursor = start
            spread: list[tuple[int, int, str]] = []
            for index, (_word_start, _word_end, text) in enumerate(timed):
                duration = base + (1 if index < remainder else 0)
                spread.append((cursor, cursor + duration, text))
                cursor += duration
            timed = spread

        for word_start, word_end, text in timed:
            offset = max(0, word_start - start)
            duration = max(0, word_end - word_start)
            text = text.replace("\r", " ").replace("\n", " ")
            pieces.append(f"<{offset},{duration}>{text}")
        output.append("".join(pieces))
    return "\n".join(output)


def build_container(tracks: dict[str, str]) -> str:
    parts: list[str] = []
    for name, _key in _CONTAINER_ORDER:
        content = tracks.get(name, "")
        if not content:
            continue
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        parts.append(f"{name}:{encoded}")
    return f"[awlrc:{','.join(parts)}]" if parts else ""


def _clean_tag(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace("]", ")").strip()


def build_tags(lyrics: Lyrics) -> list[tuple[str, str]]:
    tags: dict[str, str] = {}
    for key, value in (
        ("ti", lyrics.song.title or lyrics.tags.get("ti", "")),
        ("ar", lyrics.song.artist or lyrics.tags.get("ar", "")),
        ("al", lyrics.song.album or lyrics.tags.get("al", "")),
        ("by", lyrics.tags.get("by", "")),
        ("tool", f"Lrc-helper {__version__}"),
    ):
        value = _clean_tag(str(value or ""))
        if value:
            tags[key] = value
    return list(tags.items())


def _is_credit_at_start(line: Line, lyrics: Lyrics | None = None) -> bool:
    if line.start is None or line.start > 20000:
        return False
    text = line.text.strip()
    if _CREDIT_RE.match(text):
        return True
    if lyrics is not None:
        artist = _compact(lyrics.song.artist)
        title = _compact(lyrics.song.title)
        if artist and title:
            compact = _compact(text)
            return artist in compact and title in compact
    return False


def _compact(text: str) -> str:
    return re.sub(r"[\s\-–—_·・:：()\[\]（）【】]", "", text.lower())


def _strip_leading_credits(lines: list[Line], lyrics: Lyrics) -> list[Line]:
    """Drop the credit block at the start of a lyric (作词/作曲/编曲/...)."""
    artist = _compact(lyrics.song.artist)
    title = _compact(lyrics.song.title)
    drop = 0
    for line in lines:
        text = line.text.strip()
        if not text:
            drop += 1
            continue
        is_credit = bool(_CREDIT_RE.match(text))
        if not is_credit and artist and title:
            compact = _compact(text)
            is_credit = artist in compact and title in compact
        if not is_credit:
            break
        drop += 1
    return lines[drop:]


def build_output(lyrics: Lyrics, options: OutputOptions) -> OutputResult:
    source_lines = lyrics.get("orig")
    if options.drop_credits:
        source_lines = _strip_leading_credits(source_lines, lyrics)
    orig = shift_lines(source_lines, options.offset_ms)
    if not orig:
        return OutputResult(text="", tracks_written=[], has_word=False, line_count=0)

    ts = lyrics.get("ts")
    roma = lyrics.get("roma")
    if options.drop_credits:
        ts = [line for line in ts if not _is_credit_at_start(line, lyrics)]
        roma = [line for line in roma if not _is_credit_at_start(line, lyrics)]
    ts = shift_lines(ts, options.offset_ms)
    roma = shift_lines(roma, options.offset_ms)
    if ts:
        ts = align_to_orig(orig, ts)
    if roma:
        roma = align_to_orig(orig, roma)

    track_lines: dict[str, list[Line]] = {"orig": orig, "ts": ts, "roma": roma}
    selected = set(options.contents)
    selected.add("orig")

    container_tracks: dict[str, str] = {"lrc": build_line_track(orig)}
    if "ts" in selected and ts:
        container_tracks["tlrc"] = build_line_track(ts)
    if "roma" in selected and roma:
        container_tracks["rlrc"] = build_line_track(roma)
    word_track = build_word_track(orig)
    if word_track:
        container_tracks["awlrc"] = word_track

    visible_names = [name for name in options.visible_tracks if name in track_lines and track_lines[name]]
    if not visible_names:
        visible_names = ["orig"]
    sections = [build_line_track(track_lines[name]) for name in visible_names]
    body = "\n\n".join(section for section in sections if section)

    header = ""
    if options.include_tags:
        header = "\n".join(f"[{key}:{value}]" for key, value in build_tags(lyrics)) + "\n"

    text = header + body
    if options.include_container:
        container = build_container(container_tracks)
        if container:
            text = text + "\n\n" + container
    text = text.strip() + "\n"

    written = ["orig"]
    if "ts" in selected and ts:
        written.append("ts")
    if "roma" in selected and roma:
        written.append("roma")
    if word_track and options.include_container:
        written.append("awlrc")

    return OutputResult(
        text=text,
        tracks_written=written,
        has_word=bool(word_track and options.include_container),
        line_count=len(orig),
    )


def parse_container(text: str) -> dict[str, str]:
    """Parse an ``[awlrc:...]`` line (used by tests and verification)."""
    match = re.search(r"\[awlrc:([^\]]+)]", text, re.IGNORECASE)
    if not match:
        return {}
    result: dict[str, str] = {}
    for part in match.group(1).split(","):
        name, sep, encoded = part.partition(":")
        if not sep:
            continue
        try:
            result[name.strip().lower()] = base64.b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
    return result
