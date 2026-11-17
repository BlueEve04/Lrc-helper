from __future__ import annotations

import unittest

from lrc_helper.awlrc import OutputOptions, build_output, build_word_track, parse_container
from lrc_helper.models import Line, Lyrics, Song, Word


def sample_lyrics() -> Lyrics:
    song = Song(source="test", id="1", title="Song", artist="Artist", album="Album", duration=10000)
    lyrics = Lyrics(song=song)
    lyrics.tracks["orig"] = [
        Line(1000, 2000, [Word(1000, 1400, "Hello "), Word(1400, 2000, "world")]),
        Line(2000, 3000, [Word(2000, 3000, "Second line")]),
    ]
    lyrics.tracks["ts"] = [
        Line(1000, 2000, [Word(1000, 2000, "你好世界")]),
        Line(2000, 3000, [Word(2000, 3000, "第二行")]),
    ]
    lyrics.tracks["roma"] = [
        Line(1000, 2000, [Word(1000, 2000, "hello world")]),
    ]
    return lyrics


class AwlrcTest(unittest.TestCase):
    def test_word_track(self) -> None:
        track = build_word_track(sample_lyrics().tracks["orig"])
        self.assertIn("[00:01.000]<0,400>Hello <400,600>world", track)
        self.assertIn("[00:02.000]<0,1000>Second line", track)

    def test_container_roundtrip(self) -> None:
        result = build_output(sample_lyrics(), OutputOptions())
        container = parse_container(result.text)
        self.assertEqual(set(container), {"lrc", "tlrc", "rlrc", "awlrc"})
        self.assertIn("[00:01.000]Hello world", container["lrc"])
        self.assertIn("[00:01.000]你好世界", container["tlrc"])
        self.assertIn("[00:02.000]第二行", container["tlrc"])
        self.assertTrue(container["awlrc"].startswith("[00:01.000]<0,400>Hello "))

        # Same checks LX Music applies to local LRC files.
        self.assertRegex(container["lrc"], r"(?m)^\[\d+:\d+(?:\.\d+)].+$")
        self.assertRegex(container["awlrc"], r"(?m)^\[\d+:\d+(?:\.\d+)]<\d+,\d+>.+$")
        self.assertRegex(result.text, r"(?s)\[awlrc:lrc:[^,\]]+,tlrc:[^,\]]+,rlrc:[^,\]]+,awlrc:[^\]]+]")

    def test_contents_selection(self) -> None:
        result = build_output(sample_lyrics(), OutputOptions(contents=("orig",)))
        container = parse_container(result.text)
        self.assertEqual(set(container), {"lrc", "awlrc"})
        self.assertNotIn("tlrc", result.text)

    def test_plain_lrc(self) -> None:
        result = build_output(
            sample_lyrics(),
            OutputOptions(contents=("orig", "ts"), visible_tracks=("orig", "ts"), include_container=False),
        )
        self.assertNotIn("[awlrc:", result.text)
        self.assertIn("[00:01.000]Hello world", result.text)
        self.assertIn("[00:01.000]你好世界", result.text)

    def test_offset(self) -> None:
        result = build_output(sample_lyrics(), OutputOptions(offset_ms=-500))
        self.assertIn("[00:00.500]Hello world", result.text)

    def test_drop_credits(self) -> None:
        lyrics = sample_lyrics()
        lyrics.tracks["orig"] = [
            Line(0, 1000, [Word(0, 1000, "Song - Artist")]),
            Line(1000, 2000, [Word(1000, 2000, "作词：Someone")]),
            Line(2000, 3000, [Word(2000, 3000, "作曲：Someone")]),
        ] + lyrics.tracks["orig"]
        lyrics.tracks["ts"] = [
            Line(0, 1000, [Word(0, 1000, "Song - Artist")]),
            Line(1000, 2000, [Word(1000, 2000, "Lyrics: Someone")]),
            Line(2000, 3000, [Word(2000, 3000, "Music: Someone")]),
        ] + lyrics.tracks["ts"]

        result = build_output(lyrics, OutputOptions())
        container = parse_container(result.text)
        self.assertNotIn("作词", container["lrc"])
        self.assertTrue(container["lrc"].startswith("[00:01.000]Hello world"))

        kept = build_output(lyrics, OutputOptions(drop_credits=False))
        self.assertIn("作词", parse_container(kept.text)["lrc"])


if __name__ == "__main__":
    unittest.main()
