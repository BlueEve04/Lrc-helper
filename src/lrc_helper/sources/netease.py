"""NetEase Cloud Music source.

Search uses the public ``/api/search/get`` endpoint.  Word-level lyrics (YRC)
are only exposed by the eapi endpoint, so lyrics are requested from
``/eapi/song/lyric/v1`` with AES-128-ECB encrypted parameters.
"""

from __future__ import annotations

import json
import logging
import secrets
import string

from ..crypto.eapi import eapi_params_encrypt, eapi_response_decrypt
from ..models import Line, Lyrics, Song
from ..net import RequestError, make_client, request
from ..parsers.lrc import parse_lrc, parse_plaintext
from ..parsers.yrc import parse_yrc
from .base import APIError, BaseSource, LyricsNotFoundError, SourceOptions

logger = logging.getLogger(__name__)

_API_BASE = "https://interface.music.163.com"
_SEARCH_URL = "https://music.163.com/api/search/get"


class NeteaseSource(BaseSource):
    name = "ne"
    label = "NetEase Cloud Music"
    default_interval = 0.45

    def __init__(self, options: SourceOptions) -> None:
        super().__init__(options)
        self.device_id = secrets.token_hex(32).upper()
        mac = ":".join(f"{secrets.randbelow(255):02X}" for _ in range(6))
        random_str = "".join(secrets.choice(string.ascii_uppercase) for _ in range(8))
        self.client_sign = f"{mac}@@@{random_str}@@@@@@{secrets.token_hex(32)}"
        self.osver = f"Microsoft-Windows-10--build-{secrets.randbelow(100) + 22600}-64bit"
        self.mode = "MS-iCraft B760M WIFI"
        self.appver = "3.1.3.203419"
        self.cookies = {
            "os": "pc",
            "deviceId": self.device_id,
            "osver": self.osver,
            "clientSign": self.client_sign,
            "channel": "netease",
            "mode": self.mode,
            "appver": self.appver,
        }
        self.client = make_client(
            timeout=options.timeout,
            headers={
                "Referer": "https://music.163.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/3.1.3.203419"
                ),
            },
        )

    def _params_header(self) -> str:
        return json.dumps(
            {
                "clientSign": self.cookies["clientSign"],
                "os": self.cookies["os"],
                "appver": self.cookies["appver"],
                "deviceId": self.cookies["deviceId"],
                "requestId": 0,
                "osver": self.cookies["osver"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "*/*",
            "content-type": "application/x-www-form-urlencoded",
            "cookie": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
            "mconfig-info": '{"IuRPVVmc3WWul9fT":{"version":733184,"appver":"3.1.3.203419"}}',
            "origin": "orpheus://orpheus",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/3.1.3.203419"
            ),
        }

    def _eapi_request(self, path: str, params: dict) -> dict:
        params = dict(params)
        params["e_r"] = True
        params["header"] = self._params_header()
        api_path = path.replace("eapi", "api", 1).encode("utf-8")
        body = eapi_params_encrypt(api_path, params)
        self.limiter.wait()
        try:
            response = request(
                self.client,
                "POST",
                _API_BASE + path,
                content=body.encode("ascii"),
                headers=self._headers(),
                retries=self.options.retries,
            )
            decrypted = eapi_response_decrypt(response.content)
            data = json.loads(decrypted)
        except (RequestError, ValueError) as exc:
            raise APIError(f"NetEase eapi request failed: {exc}") from exc
        if data.get("code") != 200:
            raise APIError(f"NetEase API error code {data.get('code')}: {data.get('message') or data.get('msg') or ''}")
        return data

    def search(self, query: str, limit: int = 20) -> list[Song]:
        cache_key = f"search:{query}:{limit}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, list):
            return [Song.from_dict(item) for item in cached]

        self.limiter.wait()
        try:
            response = request(
                self.client,
                "GET",
                _SEARCH_URL,
                params={"s": query, "type": 1, "limit": max(1, min(limit, 50)), "offset": 0},
                retries=self.options.retries,
            )
            data = response.json()
        except (RequestError, ValueError) as exc:
            logger.debug("NetEase search failed for %r: %s", query, exc)
            return []

        result = data.get("result") or {}
        items = result.get("songs") or []
        songs: list[Song] = []
        for item in items:
            try:
                songs.append(
                    Song(
                        source=self.name,
                        id=str(item["id"]),
                        title=str(item.get("name") or ""),
                        subtitle=str((item.get("alia") or [""])[0] or ""),
                        artist="/".join(str(artist.get("name", "")) for artist in item.get("artists", []) if artist.get("name")),
                        album=str((item.get("album") or {}).get("name") or ""),
                        duration=int(item.get("duration") or 0) or None,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self.cache_set(cache_key, [song.to_dict() for song in songs], ttl=7 * 24 * 3600)
        return songs

    def fetch(self, song: Song) -> Lyrics:
        if not song.id:
            raise APIError("NetEase song is missing an id")
        cache_key = f"lyrics:{song.id}"
        cached = self.cache_get(cache_key)
        if isinstance(cached, dict):
            return Lyrics.from_dict(cached)

        try:
            data = self._eapi_request(
                "/eapi/song/lyric/v1",
                {"id": int(song.id), "lv": "-1", "tv": "-1", "rv": "-1", "yv": "-1", "ytv": "-1", "yrv": "-1"},
            )
        except (APIError, ValueError) as exc:
            raise LyricsNotFoundError(str(exc)) from exc

        tracks: dict[str, list[Line]] = {}
        tags: dict[str, str] = {}

        yrc = data.get("yrc") or {}
        lrc = data.get("lrc") or {}
        if isinstance(yrc, dict) and str(yrc.get("lyric") or "").strip():
            parsed = parse_yrc(str(yrc["lyric"]))
            if parsed.lines:
                tracks["orig"] = parsed.lines
                tags.update(parsed.tags)
        if "orig" not in tracks and isinstance(lrc, dict):
            raw = str(lrc.get("lyric") or "").strip()
            if raw:
                parsed = parse_lrc(raw)
                if not parsed.lines:
                    parsed = parse_plaintext(raw)
                if parsed.lines:
                    tracks["orig"] = parsed.lines
                    tags.update(parsed.tags)

        for track_name, field in (("ts", "tlyric"), ("roma", "romalrc")):
            item = data.get(field) or {}
            raw = str(item.get("lyric") or "").strip() if isinstance(item, dict) else ""
            if raw:
                parsed = parse_lrc(raw)
                if parsed.lines:
                    tracks[track_name] = parsed.lines

        if not tracks.get("orig"):
            raise LyricsNotFoundError(f"NetEase has no lyrics for {song.artist_title}")

        lyric_user = data.get("lyricUser") or {}
        trans_user = data.get("transUser") or {}
        authors = []
        if isinstance(lyric_user, dict) and lyric_user.get("nickname"):
            authors.append(str(lyric_user["nickname"]))
        if isinstance(trans_user, dict) and trans_user.get("nickname") and str(trans_user["nickname"]) not in authors:
            authors.append(str(trans_user["nickname"]))
        if authors:
            tags["by"] = " & ".join(authors)

        lyrics = Lyrics(song=song, tracks=tracks, tags=tags, meta={"source": "ne"})
        self.cache_set(cache_key, lyrics.to_dict())
        return lyrics

    def close(self) -> None:
        self.client.close()
