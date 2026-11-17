"""Data models shared by sources, parsers and writers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRACKS = ("orig", "ts", "roma")
TRACK_LABELS = {
    "orig": "original",
    "ts": "translation",
    "roma": "romaji",
}


def line_text(line: Line) -> str:
    """Return the plain text of a lyric line."""
    return "".join(word.text for word in line.words)


@dataclass(slots=True)
class Word:
    start: int | None
    end: int | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"s": self.start, "e": self.end, "t": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Word:
        return cls(start=data.get("s"), end=data.get("e"), text=str(data.get("t", "")))


@dataclass(slots=True)
class Line:
    start: int | None
    end: int | None
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"s": self.start, "e": self.end, "w": [word.to_dict() for word in self.words]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Line:
        return cls(
            start=data.get("s"),
            end=data.get("e"),
            words=[Word.from_dict(word) for word in data.get("w", [])],
        )

    @property
    def text(self) -> str:
        return line_text(self)


@dataclass(slots=True)
class Song:
    """A song returned by a lyric source (or a local file)."""

    source: str
    id: str
    title: str
    artist: str = ""
    album: str = ""
    duration: int | None = None  # milliseconds
    subtitle: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def artist_title(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist

    @property
    def full_title(self) -> str:
        return f"{self.title} ({self.subtitle})" if self.subtitle else self.title

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration,
            "subtitle": self.subtitle,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Song:
        return cls(
            source=str(data.get("source", "")),
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            artist=str(data.get("artist", "")),
            album=str(data.get("album", "")),
            duration=data.get("duration"),
            subtitle=str(data.get("subtitle", "")),
            extra=dict(data.get("extra") or {}),
        )


@dataclass(slots=True)
class Lyrics:
    song: Song
    tracks: dict[str, list[Line]] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> list[Line]:
        return self.tracks.get(name, [])

    def add(self, name: str, lines: Iterable[Line]) -> None:
        lines = [line for line in lines if line.words]
        if lines:
            self.tracks[name] = lines

    @property
    def has_word(self) -> bool:
        for line in self.tracks.get("orig", []):
            timed = [word for word in line.words if word.start is not None]
            if len(timed) > 1:
                return True
        return False

    @property
    def available_tracks(self) -> list[str]:
        return [name for name in TRACKS if self.tracks.get(name)]

    @property
    def has_timing(self) -> bool:
        for line in self.tracks.get("orig", []):
            if line.start is not None:
                return True
            if any(word.start is not None for word in line.words):
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "song": self.song.to_dict(),
            "tracks": {name: [line.to_dict() for line in lines] for name, lines in self.tracks.items()},
            "tags": self.tags,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lyrics:
        return cls(
            song=Song.from_dict(data["song"]),
            tracks={name: [Line.from_dict(line) for line in lines] for name, lines in data.get("tracks", {}).items()},
            tags=dict(data.get("tags") or {}),
            meta=dict(data.get("meta") or {}),
        )


@dataclass(slots=True)
class LocalSong:
    """A song read from a local audio file."""

    path: Path
    title: str
    artist: str = ""
    album: str = ""
    duration: int | None = None
    filename: str = ""
    track: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.path.stem

    def search_queries(self) -> list[str]:
        queries: list[str] = []
        if self.artist and self.title:
            queries.append(f"{self.artist} {self.title}")
            queries.append(f"{self.artist} - {self.title}")
        if self.title:
            queries.append(self.title)
        if self.filename:
            queries.append(self.filename)
        seen: set[str] = set()
        result = []
        for query in queries:
            query = " ".join(query.split())
            if query and query.lower() not in seen:
                seen.add(query.lower())
                result.append(query)
        return result
