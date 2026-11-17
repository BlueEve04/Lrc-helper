"""Text normalisation and fuzzy matching used to pick the right search result."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import LocalSong, Song

# Bracketed suffixes such as "(Live)", "[TV Size]", "（インスト）".
_BRACKET_RE = re.compile(r"[(\[（【][^\])）】]*[\])）】]")
_VERSION_RE = re.compile(
    r"(?:\b(?:live|tv[\s_-]*size|anime|game|short|full|inst(?:rumental)?|off[\s_-]*vocal|"
    r"remix|acoustic|cover|ver(?:sion)?|edit|mix|solo|size)\b|伴奏|纯音乐|インスト|カラオケ|"
    r"オフボーカル|ライブ|テレビサイズ)",
    re.IGNORECASE,
)
_ARTIST_SPLIT_RE = re.compile(r"\s*(?:/|,|，|、|;|；|&|＆|\b(?:feat|ft|vs)\.?\s*)\s*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_TRANSLATION = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "：": ":",
        "！": "!",
        "？": "?",
        "／": "/",
        "＆": "&",
        "＊": "*",
        "＠": "@",
        "＃": "#",
        "＄": "$",
        "％": "%",
        "＼": "\\",
        "｜": "|",
        "＝": "=",
        "＋": "+",
        "－": "-",
        "＜": "<",
        "＞": ">",
        "［": "[",
        "］": "]",
        "｛": "{",
        "｝": "}",
        "～": "~",
        "—": "-",
        "–": "-",
    },
)


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).translate(_PUNCT_TRANSLATION).lower()
    text = text.replace("　", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def text_similarity(a: str | None, b: str | None) -> float:
    """Return a 0..1 similarity ratio (spaces are ignored by the matcher)."""
    a_n, b_n = normalize(a), normalize(b)
    if not a_n or not b_n:
        return 0.0
    if a_n == b_n:
        return 1.0
    return SequenceMatcher(lambda ch: ch == " ", a_n, b_n).ratio()


def strip_version_tags(text: str) -> str:
    text = _BRACKET_RE.sub(" ", normalize(text))
    text = _VERSION_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def title_score(title: str | None, result_title: str | None) -> float:
    """Score two song titles, tolerating version suffixes and punctuation."""
    a, b = normalize(title), normalize(result_title)
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0

    full = text_similarity(a, b) * 100.0
    base_a, base_b = strip_version_tags(a), strip_version_tags(b)
    base = 0.0
    if base_a and base_b:
        if base_a == base_b:
            base = 90.0
        else:
            base = text_similarity(base_a, base_b) * 100.0
            if base_a in base_b or base_b in base_a:
                base = max(base, 85.0)

    return max(full, base)


def _artist_parts(artist: str | None) -> list[str]:
    if not artist:
        return []
    parts = [normalize(part) for part in _ARTIST_SPLIT_RE.split(artist)]
    return [part for part in parts if part]


def artist_score(artist: str | None, result_artist: str | None) -> float:
    """Compare artist strings, including multi-artist and ``feat.`` forms."""
    a_parts, b_parts = _artist_parts(artist), _artist_parts(result_artist)
    if not a_parts or not b_parts:
        return 0.0

    full = text_similarity(artist, result_artist) * 100.0
    if set(a_parts) == set(b_parts):
        return 100.0

    # Greedy best pairing, like LDDC's list_max_difference.
    scores = sorted(
        ((text_similarity(a, b), i, j) for i, a in enumerate(a_parts) for j, b in enumerate(b_parts)),
        reverse=True,
    )
    used_a: set[int] = set()
    used_b: set[int] = set()
    total = 0.0
    for score, i, j in scores:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        total += score
        if len(used_a) == len(a_parts) or len(used_b) == len(b_parts):
            break

    paired = total / max(len(a_parts), len(b_parts)) * 100.0
    return max(full, paired)


def album_score(album: str | None, result_album: str | None) -> float:
    return text_similarity(album, result_album) * 100.0


def candidate_score(local: LocalSong, cand: Song, filename_only: bool = False) -> float:
    """Return a 0..100 metadata match score between a local file and a candidate."""
    if filename_only:
        title = local.title or local.filename
        options = [
            text_similarity(title, cand.title) * 100.0,
            text_similarity(title, f"{cand.artist} - {cand.title}") * 100.0,
            text_similarity(title, f"{cand.title} - {cand.artist}") * 100.0,
        ]
        if local.filename:
            options.append(text_similarity(local.filename, cand.title) * 100.0)
        return max(options)

    t = title_score(local.title, cand.title)
    a = artist_score(local.artist, cand.artist) if local.artist and cand.artist else None
    al = album_score(local.album, cand.album) if local.album and cand.album else None

    if a is not None:
        if al is not None:
            score = max(t * 0.5 + a * 0.5, t * 0.5 + a * 0.35 + al * 0.15)
        else:
            score = t * 0.5 + a * 0.5
    elif al is not None:
        score = max(t * 0.7 + al * 0.3, t * 0.8)
    else:
        score = t

    if t < 30:
        score = max(0.0, score - 35.0)
    return max(0.0, min(100.0, score))


def duration_ok(local_duration: int | None, candidate_duration: int | None, tolerance_ms: int = 4000) -> bool:
    if not local_duration or not candidate_duration:
        return True
    return abs(local_duration - candidate_duration) <= tolerance_ms
