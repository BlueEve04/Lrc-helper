"""QQ Music source.

The request flow follows LDDC's QQ Music client: obtain a lightweight session
from ``musicu.fcg``, search with ``DoSearchForQQMusicLite`` and fetch encrypted
QRC lyrics with ``GetPlayLyricInfo``.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import threading
import time

from ..crypto.qrc import QrcDecryptError, decrypt_qrc
from ..models import Line, Lyrics, Song
from ..net import RequestError, make_client, request
from ..parsers.qrc import parse_qrc_or_lrc
from .base import APIError, BaseSource, LyricsNotFoundError, SourceOptions

logger = logging.getLogger(__name__)

_SEARCH_TYPE_SONG = 0


class QQSource(BaseSource):
    name = "qq"
    label = "QQ Music"
    default_interval = 0.3

    def __init__(self, options: SourceOptions) -> None:
        super().__init__(options)
        self.client = make_client(
            timeout=options.timeout,
            headers={
                "cookie": "tmeLoginType=-1;",
                "content-type": "application/json",
                "accept-encoding": "gzip",
                "user-agent": "okhttp/3.14.9",
            },
        )
        self.comm: dict[str, object] = {
            "ct": 11,
            "cv": "1003006",
            "v": "1003006",
            "os_ver": "15",
            "phonetype": "24122RKC7C",
            "rom": f"Redmi/miro/miro:15/AE3A.240806.005/OS2.0.10{random.choice(['5', '4', '2'])}.0.VOMCNXM:user/release-keys",
            "tmeAppID": "qqmusiclight",
            "nettype": "NETWORK_WIFI",
            "udid": "0",
        }
        self._init_lock = threading.Lock()
        self._inited = False
        self._init()

    def _init(self) -> None:
        with self._init_lock:
            if self._inited:
                return
            data = self._request("GetSession", "music.getSession.session", {"caller": 0, "uid": "0", "vkey": 0}, allow_uninitialized=True)
            session = data["session"]
            self.comm.update({"uid": session["uid"], "sid": session["sid"], "userip": session["userip"]})
            self._inited = True

    def _request(self, method: str, module: str, param: dict, *, allow_uninitialized: bool = False) -> dict:
        if not self._inited and not allow_uninitialized:
            self._init()
        payload = json.dumps(
            {"comm": self.comm, "request": {"method": method, "module": module, "param": param}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.limiter.wait()
        try:
            response = request(
                self.client,
                "POST",
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                content=payload,
                retries=self.options.retries,
            )
            data = response.json()
        except (RequestError, ValueError) as exc:
            raise APIError(f"QQ Music request failed: {exc}") from exc

        if data.get("code") != 0 or data.get("request", {}).get("code") != 0:
            code = data.get("code") if data.get("code") != 0 else data.get("request", {}).get("code")
            raise APIError(f"QQ Music API error code {code}")
        return data["request"]["data"]

    def search(self, query: str, limit: int = 20) -> list[Song]:
        cache_key = f"search:{query}:{limit}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, list):
            return [Song.from_dict(item) for item in cached]

        pagesize = max(1, min(limit, 50))
        param = {
            "search_id": str(
                random.randint(1, 20) * 18014398509481984
                + random.randint(0, 4194304) * 4294967296
                + round(time.time() * 1000) % 86400000
            ),
            "remoteplace": "search.android.keyboard",
            "query": query,
            "search_type": _SEARCH_TYPE_SONG,
            "num_per_page": pagesize,
            "page_num": 1,
            "highlight": 0,
            "nqc_flag": 0,
            "page_id": 1,
            "grp": 1,
        }
        try:
            data = self._request("DoSearchForQQMusicLite", "music.search.SearchCgiService", param)
            items = data.get("body", {}).get("item_song") or []
        except (APIError, KeyError, TypeError) as exc:
            logger.debug("QQ search failed for %r: %s", query, exc)
            return []

        songs: list[Song] = []
        for item in items:
            try:
                songs.append(
                    Song(
                        source=self.name,
                        id=str(item["id"]),
                        title=str(item.get("title") or ""),
                        subtitle=str(item.get("subtitle") or ""),
                        artist="/".join(str(singer.get("name", "")) for singer in item.get("singer", []) if singer.get("name")),
                        album=str(item.get("album", {}).get("name") or ""),
                        duration=int(item.get("interval") or 0) * 1000 or None,
                        extra={"mid": item.get("mid")},
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self.cache_set(cache_key, [song.to_dict() for song in songs], ttl=7 * 24 * 3600)
        return songs

    def fetch(self, song: Song) -> Lyrics:
        if not song.title or not song.id:
            raise APIError("QQ Music song is missing title or id")
        cache_key = f"lyrics:{song.id}:{song.duration or 0}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, dict):
            return Lyrics.from_dict(cached)

        interval = int((song.duration or 0) / 1000)
        param = {
            "albumName": base64.b64encode((song.album or "").encode("utf-8")).decode("ascii"),
            "crypt": 1,
            "ct": 19,
            "cv": 2111,
            "interval": interval,
            "lrc_t": 0,
            "qrc": 1,
            "qrc_t": 0,
            "roma": 1,
            "roma_t": 0,
            "singerName": base64.b64encode((song.artist or "").encode("utf-8")).decode("ascii"),
            "songID": int(song.id),
            "songName": base64.b64encode(song.title.encode("utf-8")).decode("ascii"),
            "trans": 1,
            "trans_t": 0,
            "type": 0,
        }
        try:
            data = self._request("GetPlayLyricInfo", "music.musichallSong.PlayLyricInfo", param)
        except APIError as exc:
            raise LyricsNotFoundError(str(exc)) from exc

        tracks: dict[str, list[Line]] = {}
        tags: dict[str, str] = {}
        for track_name, field in (("orig", "lyric"), ("ts", "trans"), ("roma", "roma")):
            encrypted = data.get(field)
            if not isinstance(encrypted, str) or not encrypted.strip():
                continue
            try:
                plain = decrypt_qrc(encrypted)
            except QrcDecryptError as exc:
                logger.debug("QQ %s decrypt failed for %s: %s", field, song.artist_title, exc)
                continue
            parsed = parse_qrc_or_lrc(plain)
            if parsed.lines:
                tracks[track_name] = parsed.lines
                if track_name == "orig":
                    tags.update(parsed.tags)

        if not tracks.get("orig"):
            raise LyricsNotFoundError(f"QQ Music has no lyrics for {song.artist_title}")

        lyrics = Lyrics(song=song, tracks=tracks, tags=tags, meta={"source": "qq"})
        self.cache_set(cache_key, lyrics.to_dict())
        return lyrics

    def close(self) -> None:
        self.client.close()
