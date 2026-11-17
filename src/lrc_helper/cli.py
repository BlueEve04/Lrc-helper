"""Command-line interface for Lrc-helper."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import string
import sys
import time
from pathlib import Path

from . import __version__
from .cache import Cache, default_cache_dir
from .media import iter_audio_files
from .naming import NamingOptions
from .pipeline import BatchOptions, FetchOptions, LibraryProcessor, WriteOptions
from .sources import DEFAULT_SOURCES, SOURCE_CLASSES, SOURCE_LABELS, SourceOptions

logger = logging.getLogger(__name__)

_CONTENT_ALIASES = {
    "orig": "orig",
    "original": "orig",
    "原词": "orig",
    "原文": "orig",
    "ts": "ts",
    "trans": "ts",
    "translation": "ts",
    "翻译": "ts",
    "译文": "ts",
    "roma": "roma",
    "romaji": "roma",
    "罗马音": "roma",
    "罗马": "roma",
}


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]


def _parse_contents(value: str) -> tuple[str, ...]:
    if value.strip().lower() == "all":
        return ("orig", "ts", "roma")
    result: list[str] = []
    for part in _split_list(value):
        key = _CONTENT_ALIASES.get(part.lower())
        if key is None:
            raise argparse.ArgumentTypeError(f"未知的歌词内容 {part!r}; 可用: orig, ts, roma")
        if key not in result:
            result.append(key)
    if not result:
        raise argparse.ArgumentTypeError("至少选择一种歌词内容")
    if "orig" not in result:
        logger.warning("原词是逐字与行时间的基础，已自动加入 orig")
        result.insert(0, "orig")
    return tuple(result)


def _parse_sources(value: str) -> tuple[str, ...]:
    if value.strip().lower() == "all":
        return DEFAULT_SOURCES
    result: list[str] = []
    for part in _split_list(value):
        key = part.lower()
        if key not in SOURCE_CLASSES:
            raise argparse.ArgumentTypeError(f"未知的歌词源 {part!r}; 可用: {', '.join(SOURCE_CLASSES)}")
        if key not in result:
            result.append(key)
    if not result:
        raise argparse.ArgumentTypeError("至少选择一个歌词源")
    return tuple(result)


def _parse_tracks(value: str) -> tuple[str, ...]:
    if value.strip().lower() in ("none", "无"):
        return ()
    result: list[str] = []
    for part in _split_list(value):
        key = _CONTENT_ALIASES.get(part.lower())
        if key is None:
            raise argparse.ArgumentTypeError(f"未知的歌词内容 {part!r}; 可用: orig, ts, roma")
        if key not in result:
            result.append(key)
    if not result:
        raise argparse.ArgumentTypeError("至少选择一种歌词内容")
    return tuple(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lrc-helper",
        description=(
            "为大曲库批量匹配歌词，并将逐字歌词保存为带 LX Music awlrc 容器的 LRC 文件。\n"
            "默认抓取原词、翻译、罗马音，默认与音频文件同名保存（覆盖已有文件）。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  lrc-helper \"D:\\Music\"\n"
            "  lrc-helper \"D:\\Music\" --contents orig,ts --name \"{artist} - {title}\" --output-dir \"D:\\Lyrics\"\n"
            "  lrc-helper album.flac --name same --no-overwrite\n"
            "  lrc-helper \"D:\\Music\" --dry-run --verbose\n"
        ),
    )
    parser.add_argument("paths", nargs="*", help="音频文件或目录（目录默认递归）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    content = parser.add_argument_group("歌词内容")
    content.add_argument(
        "--contents",
        type=_parse_contents,
        default=("orig", "ts", "roma"),
        metavar="LIST",
        help="保存的歌词轨: orig,ts,roma（默认全部）",
    )
    content.add_argument(
        "--sources",
        type=_parse_sources,
        default=DEFAULT_SOURCES,
        metavar="LIST",
        help=f"歌词源顺序: {','.join(SOURCE_CLASSES)}（默认 {','.join(DEFAULT_SOURCES)}）",
    )
    content.add_argument(
        "--prefer",
        choices=("word", "match"),
        default="word",
        help="word=优先逐字歌词（默认），match=优先元数据匹配度",
    )
    content.add_argument("--min-score", type=float, default=55.0, help="元数据匹配最低分 0-100（默认 55）")
    content.add_argument("--require-word", action="store_true", help="没有逐字歌词时视为失败")
    content.add_argument("--allow-plaintext", action="store_true", help="允许保存没有时间轴的纯文本歌词")
    content.add_argument("--try-per-source", type=int, default=2, help="每个源尝试的候选数（默认 2）")

    output = parser.add_argument_group("输出")
    output.add_argument(
        "--name",
        "--name-template",
        dest="name",
        default="same",
        help="same=与音频同名（默认），或模板: {filename} {title} {artist} {album} {track} {index} {source}",
    )
    output.add_argument("--output-dir", type=Path, help="输出目录（默认与音频同目录）")
    output.add_argument("--preserve-tree", action="store_true", help="配合 --output-dir 保留相对子目录结构")
    output.add_argument("--ext", default=".lrc", help="输出扩展名（默认 .lrc）")
    output.add_argument("--format", choices=("awlrc", "lrc"), default="awlrc", help="awlrc=带逐字容器（默认），lrc=普通行级 LRC")
    output.add_argument(
        "--visible-tracks",
        type=_parse_tracks,
        default=None,
        metavar="LIST",
        help="LRC 正文可见的歌词轨（默认 awlrc 格式仅 orig，lrc 格式为 --contents）",
    )
    output.add_argument("--offset-ms", type=int, default=0, help="整体时间偏移，正数延后（毫秒）")
    output.add_argument("--no-tags", action="store_true", help="不写入 [ti:]/[ar:]/[al:] 等标签")
    output.add_argument(
        "--drop-credits",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="去掉开头的作词/作曲/编曲等制作信息（默认去掉；--keep-credits 保留）",
    )
    output.add_argument("--keep-credits", dest="drop_credits", action="store_false", help="保留开头的制作信息")
    output.add_argument("--encoding", default="utf-8", help="输出编码（默认 utf-8，可选 utf-8-sig）")

    behavior = parser.add_argument_group("行为")
    behavior.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=True, help="覆盖已有 LRC（默认覆盖）")
    behavior.add_argument(
        "--on-collision",
        choices=("rename", "overwrite", "skip"),
        default="rename",
        help="同一批次输出重名时的处理（默认 rename）",
    )
    behavior.add_argument("--no-recursive", action="store_true", help="目录只处理第一层")
    behavior.add_argument("--limit", type=int, default=None, help="只处理前 N 个音频文件（测试用）")
    behavior.add_argument("--dry-run", action="store_true", help="只匹配和预览，不写文件")
    behavior.add_argument("--report", type=Path, help="把每个文件的结果写入 JSONL 报告")
    behavior.add_argument("--fail-on-error", action="store_true", help="有失败/未找到时返回非零退出码")

    performance = parser.add_argument_group("性能与网络")
    performance.add_argument("--workers", type=int, default=4, help="并行处理的文件数（默认 4）")
    performance.add_argument("--timeout", type=float, default=20.0, help="HTTP 超时秒数（默认 20）")
    performance.add_argument("--retries", type=int, default=2, help="请求失败重试次数（默认 2）")
    performance.add_argument("--delay", type=float, default=0.25, help="同一歌词源请求最小间隔秒数（默认 0.25）")
    performance.add_argument("--cache-dir", type=Path, default=None, help=f"缓存目录（默认 {default_cache_dir()}）")
    performance.add_argument("--no-cache", action="store_true", help="禁用缓存")
    performance.add_argument("--list-sources", action="store_true", help="列出支持的歌词源后退出")

    logging_group = parser.add_mutually_exclusive_group()
    logging_group.add_argument("-v", "--verbose", action="store_true", help="输出调试信息")
    logging_group.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    return parser


def _configure_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.ERROR if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)
    for noisy in ("httpx", "httpcore", "h2", "hpack", "hyperframe"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _expand_inputs(raw_inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_inputs:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidates: list[str]
        if any(char in expanded for char in "*?[") and not Path(expanded).exists():
            candidates = glob.glob(expanded, recursive=True)
        else:
            candidates = [expanded]
        for candidate in candidates:
            path = Path(candidate)
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)
    return paths


def _validate_name_template(template: str, files: list[Path]) -> None:
    if template == "same":
        return
    try:
        fields = {field_name for _text, field_name, _spec, _conv in string.Formatter().parse(template) if field_name}
    except ValueError as exc:
        raise SystemExit(f"命名模板格式错误: {exc}") from exc
    allowed = {"filename", "stem", "title", "artist", "album", "track", "index", "source"}
    unknown = fields - allowed
    if unknown:
        raise SystemExit(f"命名模板包含未知占位符: {', '.join(sorted(unknown))}; 可用: {', '.join(sorted(allowed))}")
    if not fields and len(files) > 1:
        raise SystemExit("固定文件名会覆盖多个文件；请使用带占位符的 --name 模板，或只处理一个文件")


def _write_report(path: Path, results) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for result in results:
            handle.write(
                json.dumps(
                    {
                        "input": str(result.path),
                        "output": str(result.output) if result.output else None,
                        "status": result.status,
                        "source": result.source or None,
                        "score": result.score,
                        "word": result.has_word,
                        "tracks": result.tracks,
                        "error": result.error or None,
                        "elapsed": round(result.elapsed, 3),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.quiet)

    if args.list_sources:
        for name, label in SOURCE_LABELS.items():
            print(f"{name:8} {label}")
        return 0

    if not args.paths:
        parser.error("至少需要一个音频文件或目录")

    inputs = _expand_inputs(args.paths)
    if not inputs:
        parser.error("没有找到输入路径")
    missing = [path for path in inputs if not path.exists()]
    if missing:
        parser.error("路径不存在: " + ", ".join(str(path) for path in missing))

    files_for_template = iter_audio_files(inputs, recursive=not args.no_recursive)
    if args.limit is not None:
        files_for_template = files_for_template[: args.limit]
    if not files_for_template:
        logger.error("没有找到可处理的音频文件")
        return 1
    _validate_name_template(args.name, files_for_template)

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    cache = Cache(args.cache_dir, enabled=not args.no_cache)
    source_options = SourceOptions(
        timeout=args.timeout,
        retries=args.retries,
        delay=args.delay,
        cache=cache,
    )
    naming = NamingOptions(
        name=args.name,
        output_dir=args.output_dir,
        preserve_tree=args.preserve_tree,
        extension=args.ext,
    )
    fetch = FetchOptions(
        contents=args.contents,
        sources=args.sources,
        prefer=args.prefer,
        min_score=args.min_score,
        require_word=args.require_word,
        allow_plaintext=args.allow_plaintext,
        try_per_source=max(1, args.try_per_source),
    )
    write = WriteOptions(
        contents=args.contents,
        visible_tracks=args.visible_tracks,
        output_format=args.format,
        offset_ms=args.offset_ms,
        include_tags=not args.no_tags,
        drop_credits=args.drop_credits,
        encoding=args.encoding,
    )
    batch = BatchOptions(
        naming=naming,
        fetch=fetch,
        write=write,
        overwrite=args.overwrite,
        on_collision=args.on_collision,
        dry_run=args.dry_run,
        limit=args.limit,
        workers=max(1, args.workers),
    )

    started = time.monotonic()
    try:
        processor = LibraryProcessor(batch, source_options)
    except Exception as exc:  # noqa: BLE001
        logger.error("初始化失败: %s", exc)
        return 1
    try:
        results = processor.run(inputs, recursive=not args.no_recursive)
    except KeyboardInterrupt:
        logger.error("已中断")
        return 130
    finally:
        processor.close()
    elapsed = time.monotonic() - started

    counts: dict[str, int] = {}
    sources: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
        if result.source:
            sources[result.source] = sources.get(result.source, 0) + 1

    print()
    print("完成:", "  ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "没有处理任何文件")
    if sources:
        print("来源:", "  ".join(f"{key}={value}" for key, value in sorted(sources.items())))
    print(f"耗时: {elapsed:.1f}s")

    if args.report:
        _write_report(args.report, results)
        logger.info("报告已写入 %s", args.report)

    if args.fail_on_error and (counts.get("failed") or counts.get("not_found")):
        return 1
    if counts.get("failed") and not counts.get("ok") and not counts.get("skipped"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
