from __future__ import annotations

import unittest
from pathlib import Path

from lrc_helper.models import LocalSong
from lrc_helper.naming import NamingOptions, render_output_path, sanitize_filename, unique_path


class NamingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.song = LocalSong(
            path=Path("/music/01 - Song.flac"),
            title="Song",
            artist="Artist",
            album="Album",
            track=1,
            filename="01 - Song",
        )

    def test_same_name(self) -> None:
        path = render_output_path(self.song.path, self.song, NamingOptions())
        self.assertEqual(path, Path("/music/01 - Song.lrc"))

    def test_template(self) -> None:
        options = NamingOptions(name="{artist} - {title}", output_dir=Path("/lyrics"))
        path = render_output_path(self.song.path, self.song, options)
        self.assertEqual(path, Path("/lyrics/Artist - Song.lrc"))

    def test_bad_chars(self) -> None:
        self.assertEqual(sanitize_filename('a<b>c:d"e/f'), "a_b_c_d_e_f")
        self.assertEqual(sanitize_filename("CON"), "_CON")

    def test_unique(self) -> None:
        taken = {Path("/lyrics/a.lrc")}
        self.assertEqual(unique_path(Path("/lyrics/a.lrc"), taken), Path("/lyrics/a (2).lrc"))


if __name__ == "__main__":
    unittest.main()
