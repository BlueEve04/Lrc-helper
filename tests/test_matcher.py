from __future__ import annotations

import unittest
from pathlib import Path

from lrc_helper.align import align_to_orig
from lrc_helper.models import Line, LocalSong, Song, Word
from lrc_helper.text import candidate_score, title_score


class TextScoreTest(unittest.TestCase):
    def test_title_versions(self) -> None:
        self.assertEqual(title_score("Song", "Song"), 100.0)
        self.assertGreater(title_score("Song", "Song (Live)"), 80.0)
        self.assertGreater(title_score("Song (TV Size)", "Song"), 80.0)

    def test_candidate_score(self) -> None:
        local = LocalSong(path=Path("x.mp3"), title="晴天", artist="周杰伦", album="叶惠美", duration=269000)
        good = Song(source="qq", id="1", title="晴天", artist="周杰伦", album="叶惠美", duration=269000)
        bad = Song(source="qq", id="2", title="晴天 (女声版)", artist="Someone", album="", duration=269000)
        self.assertGreater(candidate_score(local, good), 90.0)
        self.assertLess(candidate_score(local, bad), candidate_score(local, good))


class AlignTest(unittest.TestCase):
    def test_exact_count_preserves_order(self) -> None:
        orig = [
            Line(846, 1000, [Word(846, 1000, "a")]),
            Line(846, 1000, [Word(846, 1000, "b")]),
        ]
        other = [
            Line(846, 1000, [Word(846, 1000, "A")]),
            Line(846, 1000, [Word(846, 1000, "B")]),
        ]
        aligned = align_to_orig(orig, other)
        self.assertEqual([line.text for line in aligned], ["A", "B"])

    def test_time_match(self) -> None:
        orig = [Line(1000, 2000, [Word(1000, 2000, "a")]), Line(5000, 6000, [Word(5000, 6000, "b")])]
        other = [Line(1010, 2000, [Word(1010, 2000, "A")]), Line(5050, 6000, [Word(5050, 6000, "B")])]
        aligned = align_to_orig(orig, other)
        self.assertEqual([line.start for line in aligned], [1000, 5000])
        self.assertEqual([line.text for line in aligned], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
