# NOTICE

Lrc-helper is licensed under GPL-3.0-only.

## Third-party code and references

- **LDDC** — https://github.com/chenmozhijin/LDDC
  - Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
  - License: GPL-3.0-only
  - The QRC 3DES implementation in `src/lrc_helper/crypto/triple_des.py` is adapted from LDDC's `LDDC/core/decryptor/tripledes.py`. The QQ Music, NetEase, Kugou and lrclib request flows and the lyric matching approach were also studied from LDDC.
- **QQMusicDecoder** — https://github.com/WXRIW/QQMusicDecoder
  - Original QRC decryption algorithm reference used by LDDC.
- **lx-music-desktop** — https://github.com/lyswhut/lx-music-desktop
  - Reference for the `[awlrc:lrc:...,tlrc:...,rlrc:...,awlrc:...]` container and the LX word-level lyric syntax `[mm:ss.mmm]<offset,duration>text`.

Lyrics fetched from third-party services remain the property of their respective
copyright holders. This tool only downloads and converts lyrics for local use;
users are responsible for complying with the services' terms.
