"""lrclib.net source (line-synced, plus its experimental word-sync file)."""

from __future__ import annotations

import logging

from ..models import Lyrics, Song
from ..net import RequestError, make_client, request
from ..parsers.lrc import parse_lrc, parse_plaintext
from ..parsers.lrclib import parse_lyricsfile
from .base import BaseSource, LyricsNotFoundError, SourceOptions

logger = logging.getLogger(__name__)

_BASE = "https://lrclib.net/api"


class LrclibSource(BaseSource):
    name = "lrclib"
    label = "lrclib.net"
    default_interval = 0.2

    def __init__(self, options: SourceOptions) -> None:
        super().__init__(options)
        self.client = make_client(timeout=options.timeout, http2=False)

    @staticmethod
    def _parse_item(item: dict) -> Song:
        return Song(
            source="lrclib",
            id=str(item.get("id", "")),
            title=str(item.get("trackName") or ""),
            artist=str(item.get("artistName") or ""),
            album=str(item.get("albumName") or ""),
            duration=int(float(item.get("duration") or 0) * 1000) or None,
            extra={"instrumental": bool(item.get("instrumental")), "hasWordSync": bool(item.get("hasWordSync"))},
        )

    def search(self, query: str, limit: int = 20) -> list[Song]:
        cache_key = f"search:{query}:{limit}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, list):
            return [Song.from_dict(item) for item in cached]

        self.limiter.wait()
        try:
            response = request(self.client, "GET", f"{_BASE}/search", params={"q": query}, retries=self.options.retries)
            items = response.json()
        except (RequestError, ValueError) as exc:
            logger.debug("lrclib search failed for %r: %s", query, exc)
            return []
        if not isinstance(items, list):
            return []

        songs = [self._parse_item(item) for item in items[: max(1, limit)] if isinstance(item, dict)]
        self.cache_set(cache_key, [song.to_dict() for song in songs], ttl=7 * 24 * 3600)
        return songs

    def _get_exact(self, song: Song) -> dict | None:
        params = {
            "track_name": song.title,
            "artist_name": song.artist,
            "album_name": song.album,
            "duration": f"{(song.duration or 0) / 1000:.3f}",
        }
        try:
            self.limiter.wait()
            response = request(self.client, "GET", f"{_BASE}/get", params=params, retries=self.options.retries)
            data = response.json()
            return data if isinstance(data, dict) and "id" in data else None
        except (RequestError, ValueError):
            return None

    def _find_by_search(self, song: Song) -> dict | None:
        query = song.artist_title or song.title
        self.limiter.wait()
        try:
            response = request(self.client, "GET", f"{_BASE}/search", params={"q": query}, retries=self.options.retries)
            items = response.json()
        except (RequestError, ValueError):
            return None
        if not isinstance(items, list):
            return None

        from pathlib import Path

        from ..models import LocalSong
        from ..text import candidate_score, duration_ok  # local import avoids a cycle

        local = LocalSong(
            path=Path(song.title or "song"),
            title=song.title,
            artist=song.artist,
            album=song.album,
            duration=song.duration,
        )
        best = None
        best_score = 0.0
        for item in items:
            if not isinstance(item, dict):
                continue
            cand = self._parse_item(item)
            if not duration_ok(song.duration, cand.duration):
                continue
            score = candidate_score(local, cand)
            if score > best_score:
                best, best_score = item, score
        return best

    def fetch(self, song: Song) -> Lyrics:
        cache_key = f"lyrics:{song.id or song.artist_title}:{song.duration or 0}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, dict):
            return Lyrics.from_dict(cached)

        data = self._get_exact(song) or self._find_by_search(song)
        if not data:
            raise LyricsNotFoundError(f"lrclib has no lyrics for {song.artist_title}")

        tags = {
            "ti": str(data.get("trackName") or song.title or ""),
            "ar": str(data.get("artistName") or song.artist or ""),
            "al": str(data.get("albumName") or song.album or ""),
        }
        tags = {key: value for key, value in tags.items() if value}

        tracks = {}
        if data.get("hasWordSync") and data.get("lyricsfile"):
            parsed = parse_lyricsfile(str(data["lyricsfile"]))
            if parsed.lines:
                tracks["orig"] = parsed.lines
        if "orig" not in tracks and data.get("syncedLyrics"):
            parsed = parse_lrc(str(data["syncedLyrics"]))
            if parsed.lines:
                tracks["orig"] = parsed.lines
                tags.update(parsed.tags)
        if "orig" not in tracks and data.get("plainLyrics"):
            parsed = parse_plaintext(str(data["plainLyrics"]))
            if parsed.lines:
                tracks["orig"] = parsed.lines

        if not tracks.get("orig"):
            raise LyricsNotFoundError(f"lrclib has no usable lyrics for {song.artist_title}")

        lyrics = Lyrics(song=song, tracks=tracks, tags=tags, meta={"source": "lrclib"})
        self.cache_set(cache_key, lyrics.to_dict())
        return lyrics

    def close(self) -> None:
        self.client.close()
