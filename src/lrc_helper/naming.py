"""Output file naming."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import LocalSong

_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(slots=True)
class NamingOptions:
    name: str = "same"
    output_dir: Path | None = None
    preserve_tree: bool = False
    extension: str = ".lrc"


def sanitize_filename(name: str) -> str:
    name = _INVALID_CHARS_RE.sub("_", name)
    name = name.strip().rstrip(". ")
    if not name:
        name = "untitled"
    stem = name.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        name = f"_{name}"
    if len(name) > 180:
        name = name[:180].rstrip(". ")
    return name


def template_fields(song: LocalSong, index: int, source: str = "") -> dict[str, Any]:
    return {
        "filename": song.stem,
        "stem": song.stem,
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "track": f"{song.track:02d}" if song.track else "",
        "index": index,
        "source": source,
    }


def render_output_path(
    audio_path: Path,
    song: LocalSong,
    options: NamingOptions,
    *,
    base_dir: Path | None = None,
    index: int = 1,
    source: str = "",
) -> Path:
    extension = options.extension if options.extension.startswith(".") else f".{options.extension}"

    if options.name == "same":
        filename = audio_path.stem + extension
    else:
        try:
            rendered = options.name.format_map(template_fields(song, index, source))
        except KeyError as exc:
            allowed = ", ".join(sorted(template_fields(song, index, source)))
            raise ValueError(f"未知的命名占位符 {exc}; 可用: {allowed}") from exc
        rendered = re.sub(r"\s+", " ", rendered).strip(" -_")
        if not rendered:
            rendered = audio_path.stem
        if not rendered.lower().endswith(extension.lower()):
            rendered += extension
        filename = sanitize_filename(rendered)

    if options.output_dir is None:
        return audio_path.with_name(filename)

    output_dir = options.output_dir
    if options.preserve_tree and base_dir is not None:
        try:
            relative = audio_path.parent.relative_to(base_dir)
        except ValueError:
            relative = Path()
        output_dir = output_dir / relative
    return output_dir / filename


def unique_path(path: Path, taken: set[Path]) -> Path:
    """Return a non-conflicting path within one batch run."""
    if path not in taken:
        return path
    stem, suffix = path.stem, path.suffix
    for counter in range(2, 10000):
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"无法为 {path} 找到唯一的文件名")
