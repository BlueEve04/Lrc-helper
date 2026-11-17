"""Search, match, fetch and write lyrics for one file or a whole library."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from .awlrc import OutputOptions, build_output
from .media import iter_audio_files, read_local_song
from .models import LocalSong, Lyrics, Song
from .naming import NamingOptions, render_output_path, unique_path
from .sources import SOURCE_CLASSES, BaseSource, LyricsNotFoundError, SourceError, SourceOptions
from .text import candidate_score, duration_ok

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FetchOptions:
    contents: tuple[str, ...] = ("orig", "ts", "roma")
    sources: tuple[str, ...] = ("qq", "kg", "ne", "lrclib")
    prefer: str = "word"  # "word" or "match"
    min_score: float = 55.0
    require_word: bool = False
    allow_plaintext: bool = False
    try_per_source: int = 2


@dataclass(slots=True)
class WriteOptions:
    contents: tuple[str, ...] = ("orig", "ts", "roma")
    visible_tracks: tuple[str, ...] | None = None
    output_format: str = "awlrc"
    offset_ms: int = 0
    include_tags: bool = True
    drop_credits: bool = True
    encoding: str = "utf-8"


@dataclass(slots=True)
class CandidateResult:
    source: str
    candidate: Song
    lyrics: Lyrics
    meta_score: float
    has_word: bool
    tracks: set[str]
    rank: float = 0.0


@dataclass(slots=True)
class FileResult:
    path: Path
    output: Path | None = None
    status: str = "failed"
    source: str = ""
    score: float | None = None
    has_word: bool = False
    tracks: list[str] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0


def _requested_extra_tracks(contents: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(track for track in contents if track != "orig")


def _rank(result: CandidateResult, contents: tuple[str, ...], prefer: str) -> float:
    requested = _requested_extra_tracks(contents)
    present = sum(1 for track in requested if track in result.tracks)
    all_present = present == len(requested)
    if prefer == "match":
        word_bonus = 40.0 if result.has_word else 0.0
        track_bonus = 35.0 * present + (35.0 if all_present and requested else 0.0)
    else:
        word_bonus = 300.0 if result.has_word else 0.0
        track_bonus = 70.0 * present + (70.0 if all_present and requested else 0.0)
    return result.meta_score + word_bonus + track_bonus


class Pipeline:
    def __init__(self, fetch_options: FetchOptions, source_options: SourceOptions) -> None:
        self.options = fetch_options
        self.sources: list[BaseSource] = []
        for name in fetch_options.sources:
            cls = SOURCE_CLASSES.get(name)
            if cls is None:
                logger.warning("未知歌词源 %s，忽略", name)
                continue
            try:
                self.sources.append(cls(source_options))
            except Exception as exc:  # noqa: BLE001 - one broken source must not stop the batch
                logger.warning("初始化歌词源 %s 失败: %s", name, exc)
        if not self.sources:
            raise RuntimeError("没有可用的歌词源")

    def close(self) -> None:
        for source in self.sources:
            try:
                source.close()
            except Exception:  # noqa: BLE001, S110
                pass

    def _search(self, local: LocalSong, source: BaseSource) -> list[tuple[float, Song]]:
        queries = local.search_queries()
        if not queries:
            return []
        filename_only = not local.artist and not local.album
        scored: dict[tuple[str, str], tuple[float, Song]] = {}
        for query in queries[:2]:
            try:
                candidates = source.search(query, limit=20)
            except Exception as exc:  # noqa: BLE001 - one source must not break the file
                logger.debug("[%s] 搜索失败 %r: %s", source.name, query, exc)
                candidates = []
            for candidate in candidates:
                if not duration_ok(local.duration, candidate.duration):
                    continue
                score = candidate_score(local, candidate, filename_only=filename_only)
                key = (candidate.source, candidate.id)
                if score > scored.get(key, (0.0, candidate))[0]:
                    scored[key] = (score, candidate)
            if scored:
                best = max(score for score, _candidate in scored.values())
                if best >= self.options.min_score:
                    break
        results = sorted(scored.values(), key=lambda item: item[0], reverse=True)
        return [(score, candidate) for score, candidate in results if score >= self.options.min_score]

    def _fetch_from_source(self, local: LocalSong, source: BaseSource) -> CandidateResult | None:
        matches = self._search(local, source)
        if not matches:
            logger.debug("[%s] 没有达到最低分的候选", source.name)
            return None
        logger.debug("[%s] %s 个候选, 最高 %.1f: %s", source.name, len(matches), matches[0][0], matches[0][1].artist_title)

        requested = _requested_extra_tracks(self.options.contents)
        best: CandidateResult | None = None
        for score, candidate in matches[: max(1, self.options.try_per_source)]:
            try:
                lyrics = source.fetch(candidate)
            except LyricsNotFoundError as exc:
                logger.debug("[%s] 未找到歌词 %s: %s", source.name, candidate.artist_title, exc)
                continue
            except SourceError as exc:
                logger.debug("[%s] 获取歌词失败 %s: %s", source.name, candidate.artist_title, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - unexpected source bug
                logger.debug("[%s] 获取歌词异常 %s: %s", source.name, candidate.artist_title, exc, exc_info=True)
                continue

            if not lyrics.has_timing and not self.options.allow_plaintext:
                logger.debug("[%s] 跳过无时间轴的纯文本歌词: %s", source.name, candidate.artist_title)
                continue
            has_word = lyrics.has_word
            if self.options.require_word and not has_word:
                continue
            tracks = set(lyrics.available_tracks)
            result = CandidateResult(
                source=source.name,
                candidate=candidate,
                lyrics=lyrics,
                meta_score=score,
                has_word=has_word,
                tracks=tracks,
            )
            result.rank = _rank(result, self.options.contents, self.options.prefer)
            if best is None or result.rank > best.rank:
                best = result
            if has_word and all(track in tracks for track in requested):
                break
        return best

    def fetch(self, local: LocalSong) -> CandidateResult | None:
        requested = _requested_extra_tracks(self.options.contents)
        results: list[CandidateResult] = []
        for source in self.sources:
            result = self._fetch_from_source(local, source)
            if result is not None:
                results.append(result)
                excellent = result.meta_score >= 99.0
                if excellent and result.has_word and all(track in result.tracks for track in requested):
                    break
        if not results:
            return None
        # Stable sort: source priority is the order in self.sources, which is
        # preserved by Python's sort.
        results.sort(key=lambda item: item.rank, reverse=True)
        chosen = results[0]
        logger.debug(
            "选择 %s: %s (元数据 %.1f, 逐字=%s, 轨=%s)",
            chosen.source,
            chosen.candidate.artist_title,
            chosen.meta_score,
            chosen.has_word,
            ",".join(sorted(chosen.tracks)),
        )
        return chosen


def write_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


@dataclass(slots=True)
class BatchOptions:
    naming: NamingOptions
    fetch: FetchOptions
    write: WriteOptions
    overwrite: bool = True
    on_collision: str = "rename"
    dry_run: bool = False
    limit: int | None = None
    workers: int = 4


class LibraryProcessor:
    def __init__(self, batch: BatchOptions, source_options: SourceOptions) -> None:
        self.batch = batch
        self.pipeline = Pipeline(batch.fetch, source_options)
        self._taken_lock = Lock()
        self._taken: set[Path] = set()

    def close(self) -> None:
        self.pipeline.close()

    def _provisional_output(self, audio: Path, local: LocalSong, index: int, base_dir: Path | None = None) -> Path:
        return render_output_path(
            audio,
            local,
            self.batch.naming,
            base_dir=base_dir or audio.parent,
            index=index,
        )

    def process_one(self, audio: Path, index: int, total: int, base_dir: Path | None = None) -> FileResult:
        started = time.monotonic()
        result = FileResult(path=audio)
        try:
            local = read_local_song(audio)
        except Exception as exc:  # noqa: BLE001
            result.error = f"读取音频信息失败: {exc}"
            return result

        provisional = self._provisional_output(audio, local, index, base_dir)
        if not self.batch.overwrite and provisional.exists() and provisional.stat().st_size > 0:
            result.output = provisional
            result.status = "skipped"
            return result

        logger.info("[%d/%d] %s", index, total, audio)
        candidate = self.pipeline.fetch(local)
        if candidate is None:
            result.error = "没有找到匹配的歌词"
            result.status = "not_found"
            result.elapsed = time.monotonic() - started
            return result

        lyrics = candidate.lyrics
        # Prefer the local file's metadata for the output tags.  The source's
        # title/artist may include platform-specific suffixes.
        if local.title:
            lyrics.song.title = local.title
        if local.artist:
            lyrics.song.artist = local.artist
        if local.album:
            lyrics.song.album = local.album
        output_path = render_output_path(
            audio,
            local,
            self.batch.naming,
            base_dir=base_dir or audio.parent,
            index=index,
            source=candidate.source,
        )
        if output_path != provisional and not self.batch.overwrite and output_path.exists() and output_path.stat().st_size > 0:
            result.output = output_path
            result.status = "skipped"
            return result

        with self._taken_lock:
            if output_path in self._taken:
                if self.batch.on_collision == "skip":
                    result.output = output_path
                    result.status = "skipped"
                    result.error = "同一批次中存在同名输出文件"
                    return result
                if self.batch.on_collision == "rename":
                    output_path = unique_path(output_path, self._taken)
            self._taken.add(output_path)

        visible = self.batch.write.visible_tracks
        if visible is None:
            visible = self.batch.write.contents if self.batch.write.output_format == "lrc" else ("orig",)
        output = build_output(
            lyrics,
            OutputOptions(
                contents=self.batch.write.contents,
                visible_tracks=visible,
                include_container=self.batch.write.output_format == "awlrc",
                offset_ms=self.batch.write.offset_ms,
                include_tags=self.batch.write.include_tags,
                drop_credits=self.batch.write.drop_credits,
            ),
        )
        if not output.text.strip():
            result.status = "failed"
            result.error = "生成的歌词为空"
            return result

        result.output = output_path
        result.source = candidate.source
        result.score = round(candidate.meta_score, 1)
        result.has_word = output.has_word
        result.tracks = output.tracks_written

        if self.batch.dry_run:
            result.status = "dry_run"
            result.elapsed = time.monotonic() - started
            return result

        try:
            write_atomic(output_path, output.text, self.batch.write.encoding)
            result.status = "ok"
        except OSError as exc:
            result.status = "failed"
            result.error = f"写入失败: {exc}"
        result.elapsed = time.monotonic() - started
        return result

    def run(self, inputs: list[Path], recursive: bool = True) -> list[FileResult]:
        with self._taken_lock:
            self._taken.clear()
        files = iter_audio_files(inputs, recursive=recursive)
        if self.batch.limit is not None:
            files = files[: self.batch.limit]
        if not files:
            return []

        base_dirs = _match_base_dirs(files, inputs)
        total = len(files)
        if self.batch.workers <= 1:
            results = []
            for index, path in enumerate(files, 1):
                result = self.process_one(path, index, total, base_dirs[path])
                results.append(result)
                self._log_result(result)
            return results

        results: list[FileResult] = []
        with ThreadPoolExecutor(max_workers=self.batch.workers) as executor:
            futures = {executor.submit(self.process_one, path, index, total, base_dirs[path]): path for index, path in enumerate(files, 1)}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001
                    result = FileResult(path=path, status="failed", error=f"未处理异常: {exc}")
                results.append(result)
                self._log_result(result)
        results.sort(key=lambda item: str(item.path).lower())
        return results

    @staticmethod
    def _log_result(result: FileResult) -> None:
        if result.status == "ok":
            word = "逐字" if result.has_word else "逐行"
            logger.info("  -> OK %s [%s, %s, %.1f] %s", result.output, result.source, word, result.score or 0, ",".join(result.tracks))
        elif result.status == "skipped":
            logger.info("  -> 跳过 %s (%s)", result.path, result.error or "已存在")
        elif result.status == "dry_run":
            logger.info("  -> 预览 %s [%s, %.1f]", result.output, result.source, result.score or 0)
        else:
            logger.warning("  -> 失败 %s: %s", result.path, result.error)


def _match_base_dirs(files: list[Path], inputs: list[Path]) -> dict[Path, Path]:
    """Map each file to the input directory it came from (for --preserve-tree)."""
    roots = [path for path in inputs if path.is_dir()]
    mapping: dict[Path, Path] = {}
    for file in files:
        best: Path | None = None
        for root in roots:
            try:
                file.resolve().relative_to(root.resolve())
            except (ValueError, OSError):
                continue
            if best is None or len(str(root)) > len(str(best)):
                best = root
        mapping[file] = best or file.parent
    return mapping
