"""Audio file discovery and metadata reading (mutagen)."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

import mutagen
from mutagen import File as MutagenFile
from mutagen import MutagenError

from .models import LocalSong

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".ape",
    ".dff",
    ".dsf",
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".mp4",
    ".mpc",
    ".ogg",
    ".opus",
    ".tak",
    ".tta",
    ".wav",
    ".wma",
    ".wv",
}

_TRACK_PREFIX_RE = re.compile(r"^\s*(?:\d{1,3}|[A-Za-z])\s*[.\-_、]\s*")
_BRACKET_SUFFIX_RE = re.compile(r"\s*(?:\[[^\]]*]|\([^)]*\))\s*$")


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def iter_audio_files(paths: Iterable[Path], recursive: bool = True) -> list[Path]:
    """Expand files/directories into a sorted list of audio files."""
    result: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        result.append(path)

    for input_path in paths:
        if input_path.is_file():
            if is_audio_file(input_path):
                add(input_path)
            else:
                logger.warning("跳过非音频文件: %s", input_path)
            continue
        if not input_path.is_dir():
            logger.warning("路径不存在: %s", input_path)
            continue
        if recursive:
            for root, dirs, files in os.walk(input_path):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in {"$recycle.bin", "system volume information"})
                for name in sorted(files):
                    path = Path(root) / name
                    if is_audio_file(path):
                        add(path)
        else:
            for path in sorted(input_path.iterdir()):
                if path.is_file() and is_audio_file(path):
                    add(path)
    return result


def _first_tag(tags, *keys: str) -> str:
    if not tags:
        return ""
    for key in keys:
        try:
            value = tags.get(key)
        except (KeyError, AttributeError):
            continue
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            for item in value:
                text = str(item).strip()
                if text:
                    return text
        else:
            text = str(value).strip()
            if text:
                return text
    return ""


def _duration_ms(audio) -> int | None:
    try:
        length = audio.info.length
    except (AttributeError, TypeError, ZeroDivisionError):
        return None
    if not length:
        return None
    return int(round(float(length) * 1000))


def parse_filename(stem: str) -> tuple[str, str]:
    """Best-effort ``(artist, title)`` from a file stem."""
    text = _TRACK_PREFIX_RE.sub("", stem).strip()
    text = _BRACKET_SUFFIX_RE.sub("", text).strip()
    if not text:
        text = stem.strip()
    if " - " in text:
        left, right = text.split(" - ", 1)
        left, right = left.strip(), right.strip()
        if left and right:
            return left, right
    if "–" in text:
        left, right = text.split("–", 1)
        left, right = left.strip(), right.strip()
        if left and right:
            return left, right
    return "", text


def read_local_song(path: Path) -> LocalSong:
    """Read title/artist/album/duration from an audio file."""
    title = artist = album = ""
    track: int | None = None
    duration: int | None = None

    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            duration = _duration_ms(audio)
            title = _first_tag(audio.tags, "title")
            artist = _first_tag(audio.tags, "artist", "albumartist")
            album = _first_tag(audio.tags, "album")
            track_text = _first_tag(audio.tags, "tracknumber", "track")
            if track_text:
                match = re.match(r"\s*(\d+)", track_text)
                if match:
                    track = int(match.group(1))
    except (MutagenError, OSError, ValueError, TypeError) as exc:
        logger.debug("mutagen easy read failed for %s: %s", path, exc)

    if not title or not artist:
        try:
            audio = MutagenFile(path)
            if audio is not None:
                if duration is None:
                    duration = _duration_ms(audio)
                title = title or _first_tag(audio.tags, "TIT2")
                artist = artist or _first_tag(audio.tags, "TPE1")
                album = album or _first_tag(audio.tags, "TALB")
        except (MutagenError, OSError, ValueError, TypeError) as exc:
            logger.debug("mutagen full read failed for %s: %s", path, exc)

    filename_artist, filename_title = parse_filename(path.stem)
    if not title:
        title = filename_title
    if not artist:
        artist = filename_artist
    if not album:
        album = ""

    return LocalSong(
        path=path,
        title=title.strip(),
        artist=artist.strip(),
        album=album.strip(),
        duration=duration,
        filename=path.stem.strip(),
        track=track,
    )


def read_duration(path: Path) -> int | None:
    try:
        audio = mutagen.File(path)
        if audio is not None:
            return _duration_ms(audio)
    except (MutagenError, OSError):
        pass
    return None
