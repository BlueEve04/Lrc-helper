"""Manual live check for all lyric sources.

Usage::

    python scripts/live_check.py "晴天 周杰伦"
    python scripts/live_check.py "鈴木このみ アスタロア" --sources qq,kg,ne
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from lrc_helper.cache import Cache
from lrc_helper.models import LocalSong, line_text
from lrc_helper.sources import SOURCE_CLASSES, SourceOptions
from lrc_helper.text import candidate_score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="搜索关键词")
    parser.add_argument("--sources", default="qq,kg,ne,lrclib")
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("httpx", "httpcore", "h2", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    local = LocalSong(path=Path("query.mp3"), title=args.query, filename=args.query)
    options = SourceOptions(delay=args.delay, cache=Cache(enabled=False))

    for name in args.sources.split(","):
        cls = SOURCE_CLASSES.get(name.strip())
        if cls is None:
            print(f"[{name}] unknown source")
            continue
        source = cls(options)
        try:
            results = source.search(args.query, limit=5)
            print(f"\n[{name}] {len(results)} search results")
            for candidate in results[:5]:
                score = candidate_score(local, candidate, filename_only=True)
                print(f"  {score:5.1f}  {candidate.artist_title}  ({candidate.duration} ms)")
            if not results:
                continue
            lyrics = source.fetch(results[0])
            print(f"  tracks: {[(key, len(value)) for key, value in lyrics.tracks.items()]}")
            print(f"  word-level: {lyrics.has_word}")
            for key, value in lyrics.tracks.items():
                print(f"  {key}: {line_text(value[0])[:80]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")
        finally:
            source.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
