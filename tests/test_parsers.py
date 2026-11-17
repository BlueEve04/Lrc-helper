from __future__ import annotations

import base64
import json
import unittest

from lrc_helper.models import line_text
from lrc_helper.parsers.krc import parse_krc
from lrc_helper.parsers.lrc import parse_lrc
from lrc_helper.parsers.lrclib import parse_lyricsfile
from lrc_helper.parsers.qrc import parse_qrc, parse_qrc_or_lrc
from lrc_helper.parsers.yrc import parse_yrc


class LrcParserTest(unittest.TestCase):
    def test_standard_and_enhanced(self) -> None:
        text = """[ti:Test Song]
[ar:Artist]
[00:01.00]first line
[00:02.500]<00:02.500>Hello <00:03.000>world
"""
        parsed = parse_lrc(text)
        self.assertEqual(parsed.tags["ti"], "Test Song")
        self.assertEqual(parsed.tags["ar"], "Artist")
        self.assertEqual(len(parsed.lines), 2)
        self.assertEqual(line_text(parsed.lines[0]), "first line")
        self.assertEqual([word.text for word in parsed.lines[1].words], ["Hello ", "world"])
        self.assertEqual(parsed.lines[1].words[1].start, 3000)

    def test_multiple_line_timestamps(self) -> None:
        parsed = parse_lrc("[00:01.00][00:10.00]chorus\n")
        self.assertEqual(len(parsed.lines), 2)
        self.assertEqual([line.start for line in parsed.lines], [1000, 10000])

    def test_offset_tag(self) -> None:
        parsed = parse_lrc("[offset:500]\n[00:02.00]hello\n")
        self.assertEqual(parsed.lines[0].start, 1500)


class QrcParserTest(unittest.TestCase):
    def test_qrc(self) -> None:
        text = (
            '<QrcInfos><LyricInfo><Lyric_1 LyricType="1" '
            'LyricContent="[ti:Test]\n'
            '[1000,2000]你(1000,400)好(1400,600)\n'
            '[3000,1000]world"/></LyricInfo></QrcInfos>'
        )
        parsed = parse_qrc(text)
        self.assertEqual(parsed.tags["ti"], "Test")
        self.assertEqual([word.text for word in parsed.lines[0].words], ["你", "好"])
        self.assertEqual(parsed.lines[0].words[0].start, 1000)
        self.assertEqual(parsed.lines[0].words[1].start, 1400)

    def test_qrc_line_level_translation(self) -> None:
        text = "[ti:T]\n[00:01.00]translated\n"
        parsed = parse_qrc_or_lrc(text)
        self.assertEqual(line_text(parsed.lines[0]), "translated")


class KrcParserTest(unittest.TestCase):
    def test_krc_with_language(self) -> None:
        language = {
            "content": [
                {"type": 0, "lyricContent": [["he", "llo"], ["wor", "ld"]]},
                {"type": 1, "lyricContent": [["你好"], ["世界"]]},
            ]
        }
        encoded = base64.b64encode(json.dumps(language, ensure_ascii=False).encode("utf-8")).decode("ascii")
        text = (
            f"[ti:Test]\n[language:{encoded}]\n"
            "[1000,2000]<0,400,0>he<400,600,0>llo\n"
            "[3000,2000]<0,800,0>wor<800,1200,0>ld\n"
        )
        parsed = parse_krc(text)
        self.assertEqual([word.text for word in parsed.tracks["orig"][0].words], ["he", "llo"])
        self.assertEqual([word.start for word in parsed.tracks["orig"][0].words], [1000, 1400])
        self.assertEqual(line_text(parsed.tracks["roma"][0]), "hello")
        self.assertEqual(line_text(parsed.tracks["ts"][1]), "世界")

    def test_krc_translation_placeholders_stay_index_aligned(self) -> None:
        from lrc_helper.align import align_to_orig

        language = {"content": [{"type": 1, "lyricContent": [[" "], ["translated"]]}]}
        encoded = base64.b64encode(json.dumps(language, ensure_ascii=False).encode("utf-8")).decode("ascii")
        text = f"[language:{encoded}]\n[1000,1000]<0,1000,0>credit\n[1000,1000]<0,1000,0>lyric\n"
        parsed = parse_krc(text)
        self.assertEqual(len(parsed.tracks["orig"]), 2)
        self.assertEqual(len(parsed.tracks["ts"]), 2)
        aligned = align_to_orig(parsed.tracks["orig"], parsed.tracks["ts"])
        self.assertEqual([line_text(line) for line in aligned], ["translated"])


class YrcParserTest(unittest.TestCase):
    def test_yrc(self) -> None:
        text = "[1000,2000](1000,400,0)你(1400,600,0)好\n"
        parsed = parse_yrc(text)
        self.assertEqual([word.text for word in parsed.lines[0].words], ["你", "好"])
        self.assertEqual(parsed.lines[0].words[0].start, 1000)


class LrclibParserTest(unittest.TestCase):
    def test_lyricsfile(self) -> None:
        text = """version: '1.0'
metadata:
  title: Song
  artist: Singer
  album: Album
lines:
- text: hello world
  start_ms: 1000
  end_ms: 2000
  words:
  - text: hello
    start_ms: 1000
  - text: ' world'
    start_ms: 1500
"""
        parsed = parse_lyricsfile(text)
        self.assertEqual(parsed.tags["ti"], "Song")
        self.assertEqual([word.text for word in parsed.lines[0].words], ["hello", " world"])
        self.assertEqual(parsed.lines[0].words[1].start, 1500)


if __name__ == "__main__":
    unittest.main()
