"""Kugou Music source (KRC word-synced lyrics)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import zlib

from ..models import Lyrics, Song
from ..net import RequestError, make_client, request
from ..parsers.krc import parse_krc
from ..parsers.lrc import parse_lrc
from .base import APIError, BaseSource, LyricsNotFoundError, SourceOptions

logger = logging.getLogger(__name__)

_SIGN_KEY = "LnT6xpN3khm36zse0QzvmgTZ3waWdRSA"
_KRC_KEY = b"@Gaw^2tGQ61-\xce\xd2ni"
_SEARCH_URL = "http://complexsearch.kugou.com/v2/search/song"
_LYRIC_SEARCH_URL = "https://lyrics.kugou.com/v1/search"
_LYRIC_DOWNLOAD_URL = "http://lyrics.kugou.com/download"


def _mid() -> str:
    return hashlib.md5(str(int(time.time() * 1000)).encode("utf-8")).hexdigest()  # noqa: S324


def _sign(params: dict, data: str = "") -> str:
    joined = "".join(
        f"{key}={json.dumps(value) if isinstance(value, dict) else value}"
        for key, value in sorted(params.items())
    )
    return hashlib.md5((_SIGN_KEY + joined + data + _SIGN_KEY).encode()).hexdigest()  # noqa: S324


def decrypt_krc(encrypted: bytes) -> str:
    """Decrypt KRC bytes (``krc18`` magic + XOR + zlib)."""
    if encrypted[:5] != b"krc18":
        # Some downloads already contain plain text.
        return encrypted.decode("utf-8", errors="replace")
    data = bytearray(encrypted[4:])
    for index in range(len(data)):
        data[index] ^= _KRC_KEY[index % len(_KRC_KEY)]
    return zlib.decompress(bytes(data)).decode("utf-8")


class KugouSource(BaseSource):
    name = "kg"
    label = "Kugou Music"
    default_interval = 0.3

    def __init__(self, options: SourceOptions) -> None:
        super().__init__(options)
        self.client = make_client(timeout=options.timeout)
        self.mid = _mid()

    def _headers(self, module: str) -> dict[str, str]:
        return {
            "User-Agent": f"Android14-1070-11070-201-0-{module}-wifi",
            "Connection": "Keep-Alive",
            "KG-Rec": "1",
            "KG-RC": "1",
            "KG-CLIENTTIMEMS": str(int(time.time() * 1000)),
            "mid": self.mid,
        }

    def _signed_params(self, params: dict, module: str) -> dict[str, str]:
        if module == "Lyric":
            values = {"appid": "3116", "clientver": "11070", **params}
        else:
            values = {
                "userid": "0",
                "appid": "3116",
                "token": "",
                "clienttime": int(time.time()),
                "iscorrection": "1",
                "uuid": "-",
                "mid": self.mid,
                "dfid": "-",
                "clientver": "11070",
                "platform": "AndroidFilter",
                **params,
            }
        values["signature"] = _sign(values)
        return {key: str(value) for key, value in values.items()}

    def search(self, query: str, limit: int = 20) -> list[Song]:
        cache_key = f"search:{query}:{limit}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, list):
            return [Song.from_dict(item) for item in cached]

        params = {
            "sorttype": "0",
            "keyword": query,
            "pagesize": max(1, min(limit, 50)),
            "page": 1,
        }
        self.limiter.wait()
        try:
            response = request(
                self.client,
                "GET",
                _SEARCH_URL,
                params=self._signed_params(params, "SearchSong"),
                headers={**self._headers("SearchSong"), "x-router": "complexsearch.kugou.com"},
                retries=self.options.retries,
            )
            data = response.json()
        except (RequestError, ValueError) as exc:
            logger.debug("Kugou search failed for %r: %s", query, exc)
            return []

        items = (data.get("data") or {}).get("lists") or []
        songs: list[Song] = []
        for item in items:
            try:
                songs.append(
                    Song(
                        source=self.name,
                        id=str(item["ID"]),
                        title=str(item.get("SongName") or ""),
                        subtitle=str(item.get("Auxiliary") or ""),
                        artist="/".join(str(singer.get("name", "")) for singer in item.get("Singers", []) if singer.get("name")),
                        album=str(item.get("AlbumName") or ""),
                        duration=int(item.get("Duration") or 0) * 1000 or None,
                        extra={"hash": item.get("FileHash")},
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self.cache_set(cache_key, [song.to_dict() for song in songs], ttl=7 * 24 * 3600)
        return songs

    def _lyric_candidates(self, song: Song) -> list[dict]:
        keyword = song.artist_title
        params = {
            "album_audio_id": song.id,
            "duration": song.duration or 0,
            "hash": song.extra.get("hash") or "",
            "keyword": keyword,
            "lrctxt": "1",
            "man": "no",
        }
        self.limiter.wait()
        try:
            response = request(
                self.client,
                "GET",
                _LYRIC_SEARCH_URL,
                params=self._signed_params(params, "Lyric"),
                headers=self._headers("Lyric"),
                retries=self.options.retries,
            )
            data = response.json()
        except (RequestError, ValueError) as exc:
            logger.debug("Kugou lyric search failed for %s: %s", keyword, exc)
            return []
        return list(data.get("candidates") or [])

    def _download(self, candidate: dict) -> tuple[str, str]:
        """Return ``(format, text)`` for a lyric candidate."""
        lyrics_id = str(candidate.get("id", ""))
        accesskey = str(candidate.get("accesskey", ""))
        if not lyrics_id or not accesskey:
            raise APIError("Kugou lyric candidate is missing id/accesskey")
        fmt = "krc" if int(candidate.get("krctype") or 0) == 1 and int(candidate.get("contenttype") or 0) != 1 else "lrc"
        params = {
            "accesskey": accesskey,
            "charset": "utf8",
            "client": "mobi",
            "fmt": fmt,
            "id": lyrics_id,
            "ver": "1",
        }
        self.limiter.wait()
        try:
            response = request(
                self.client,
                "GET",
                _LYRIC_DOWNLOAD_URL,
                params=self._signed_params(params, "Lyric"),
                headers=self._headers("Lyric"),
                retries=self.options.retries,
            )
            data = response.json()
        except (RequestError, ValueError) as exc:
            raise APIError(f"Kugou lyric download failed: {exc}") from exc

        content = data.get("content") or ""
        if not content:
            raise APIError("Kugou returned an empty lyric payload")
        raw = base64.b64decode(content)
        content_type = int(data.get("contenttype") or 0)
        actual_fmt = str(data.get("fmt") or fmt)
        if content_type == 2:
            return "lrc", raw.decode("utf-8", errors="replace")
        if actual_fmt == "krc" or raw[:5] == b"krc18":
            return "krc", decrypt_krc(raw)
        return "lrc", raw.decode("utf-8", errors="replace")

    def fetch(self, song: Song) -> Lyrics:
        if not song.id or not song.title:
            raise APIError("Kugou song is missing id or title")
        cache_key = f"lyrics:{song.id}:{song.extra.get('hash') or ''}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, dict):
            return Lyrics.from_dict(cached)

        candidates = self._lyric_candidates(song)
        if not candidates:
            raise LyricsNotFoundError(f"Kugou has no lyric candidates for {song.artist_title}")

        candidates.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
        last_error: Exception | None = None
        for candidate in candidates[:3]:
            candidate_duration = int(candidate.get("duration") or 0)
            if song.duration and candidate_duration and abs(song.duration - candidate_duration) > 5000:
                continue
            try:
                fmt, text = self._download(candidate)
                if fmt == "krc":
                    parsed = parse_krc(text)
                    tracks = parsed.tracks
                else:
                    parsed = parse_lrc(text)
                    tracks = {"orig": parsed.lines} if parsed.lines else {}
                if not tracks.get("orig"):
                    continue
                lyrics = Lyrics(song=song, tracks=tracks, tags=parsed.tags, meta={"source": "kg", "format": fmt})
                self.cache_set(cache_key, lyrics.to_dict())
                return lyrics
            except (APIError, ValueError, zlib.error) as exc:
                last_error = exc
                continue

        raise LyricsNotFoundError(f"Kugou has no usable lyrics for {song.artist_title}: {last_error or ''}")

    def close(self) -> None:
        self.client.close()
