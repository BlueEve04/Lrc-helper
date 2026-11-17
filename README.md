# Lrc-helper

为整个音乐库批量匹配歌词，并把**逐字歌词**保存为 **LX Music 可识别的 awlrc 内嵌 LRC**。

支持从 **QQ 音乐 / 酷狗音乐 / 网易云音乐 / lrclib.net** 抓取：

- 原词（逐字或逐行）
- 翻译
- 罗马音

默认三种全选；默认给每个音频文件生成**同名 `.lrc`**；默认覆盖已有文件。也可以按模板自定义文件名、输出目录和目录结构。

> 本项目的抓取思路、QRC 解密算法与部分匹配算法参考了 [LDDC](https://github.com/chenmozhijin/LDDC)。项目以 GPL-3.0-only 发布，详见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。

## 特性

- **逐字歌词优先**：QQ QRC、酷狗 KRC、网易云 YRC、lrclib `lyricsfile` 都能解析为逐字时间轴。
- **awlrc 容器**：生成 `[awlrc:lrc:...,tlrc:...,rlrc:...,awlrc:...]` 行，LX Music 直接读取逐字、翻译、罗马音。
- **大曲库批处理**：目录递归、多线程、每源限速、重试、断点缓存、JSONL 报告。
- **内容可选**：`--contents orig,ts,roma`，默认全部；缺哪条轨就自动跳过。
- **命名灵活**：`--name same`（默认同名）或 `{artist} - {title}` 等模板；`--output-dir`、`--preserve-tree`。
- **覆盖策略**：默认覆盖；`--no-overwrite` 跳过已有文件；批内重名自动 `(2)`。
- **纯 Python**：不依赖 GUI / PySide6；Windows、macOS、Linux 均可运行。

## 安装

需要 Python 3.10+。Windows 下建议用 `py` 创建虚拟环境：

```bash
git clone https://github.com/BlueEve04/Lrc-helper.git
cd Lrc-helper
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e .
```

也可以用：

```bash
python -m pip install -r requirements.txt
python -m lrc_helper --help
```

## 快速开始

处理一个文件（默认保存为同名 `.lrc`，默认抓原词+翻译+罗马音）：

```bash
lrc-helper "D:\Music\Song.flac"
```

处理整个目录（递归）：

```bash
lrc-helper "D:\Music"
```

先预览匹配结果，不写文件：

```bash
lrc-helper "D:\Music" --dry-run --verbose
```

只抓原词和翻译（不要罗马音）：

```bash
lrc-helper "D:\Music" --contents orig,ts
```

只要逐字歌词；没有逐字就视为失败：

```bash
lrc-helper "D:\Music" --require-word
```

按 `歌手 - 标题` 命名，输出到另一个目录并保留子目录结构：

```bash
lrc-helper "D:\Music" --name "{artist} - {title}" --output-dir "D:\Lyrics" --preserve-tree
```

不覆盖已有歌词：

```bash
lrc-helper "D:\Music" --no-overwrite
```

只使用网易云和 lrclib，8 个文件并行，并写报告：

```bash
lrc-helper "D:\Music" --sources ne,lrclib --workers 8 --report report.jsonl
```

查看支持的源：

```bash
lrc-helper --list-sources
```

## 常用参数

| 参数 | 说明 |
|---|---|
| `--contents orig,ts,roma` | 保存的歌词轨，默认全选；`orig` 是逐字/时间轴基础，省略时会自动加入 |
| `--sources qq,kg,ne,lrclib` | 歌词源及优先级，默认 `qq,kg,ne,lrclib` |
| `--prefer word\|match` | `word` 优先逐字（默认）；`match` 优先元数据匹配度 |
| `--min-score 55` | 元数据匹配最低分（0-100），默认 55 |
| `--require-word` | 没有逐字歌词时不保存 |
| `--allow-plaintext` | 允许保存无时间轴的纯文本歌词（默认跳过） |
| `--name same` | 默认与音频同名 `.lrc` |
| `--name "{artist} - {title}"` | 命名模板，可用 `{filename}` `{stem}` `{title}` `{artist}` `{album}` `{track}` `{index}` `{source}` |
| `--output-dir DIR` | 输出目录，默认与音频同目录 |
| `--preserve-tree` | 配合 `--output-dir` 保留相对子目录 |
| `--ext .lrc` | 输出扩展名，默认 `.lrc` |
| `--format awlrc\|lrc` | `awlrc` 带逐字容器（默认）；`lrc` 普通行级 LRC |
| `--visible-tracks orig,ts,roma` | LRC 正文可见的轨；awlrc 格式默认仅 `orig`，避免播放器重复显示 |
| `--drop-credits / --keep-credits` | 去掉/保留开头的作词、作曲、编曲等制作信息（默认去掉） |
| `--offset-ms N` | 整体时间偏移，正数延后 |
| `--overwrite / --no-overwrite` | 默认覆盖已有 LRC |
| `--on-collision rename\|overwrite\|skip` | 同批次输出重名处理，默认 `rename` |
| `--workers N` | 并行文件数，默认 4 |
| `--delay SEC` | 同一歌词源请求最小间隔，默认 0.25 秒 |
| `--retries N` | HTTP 重试次数，默认 2 |
| `--cache-dir DIR` / `--no-cache` | 缓存目录 / 禁用缓存（默认开启，30 天） |
| `--limit N` | 只处理前 N 个文件（测试用） |
| `--report FILE` | 输出 JSONL 报告 |
| `--dry-run` | 只匹配预览，不写文件 |
| `-v / -q` | 调试输出 / 只输出错误 |

## 输出格式

### 默认：awlrc 内嵌 LRC

正文是普通的行级 LRC，文件末尾附加一行 LX Music 容器：

```lrc
[ti:Song]
[ar:Artist]
[al:Album]
[tool:Lrc-helper 0.1.0]
[00:01.105]あの眩しさの中追いかけた
[00:06.205]君の背中まだ遠いけど

[awlrc:lrc:<base64>,tlrc:<base64>,rlrc:<base64>,awlrc:<base64>]
```

四个 base64 段分别是：

| 字段 | 内容 |
|---|---|
| `lrc` | 行级原词 |
| `tlrc` | 行级翻译（时间与主歌词对齐） |
| `rlrc` | 行级罗马音（时间与主歌词对齐） |
| `awlrc` | LX 逐字歌词 |

`awlrc` 段语法（LX Music）：

```lrc
[00:01.105]<0,297>あ<297,341>の<638,648>眩<1286,288>し<1574,223>さ...
```

- 行首 `[mm:ss.mmm]` 是整行开始时间。
- 每个字前的 `<offset,duration>` 中，`offset` 是**相对本行开始**的偏移，`duration` 是持续时间，单位毫秒。
- 没有逐字时间轴的来源（例如普通 LRC）只会写入 `lrc`，不会伪造 `awlrc` 段。

### `--format lrc`

不写 `[awlrc:...]` 容器，只写普通行级 LRC。默认正文包含 `--contents` 选择的所有轨，适合不支持 awlrc 的播放器。

## 来源能力

| 源 | 逐字 | 翻译 | 罗马音 | 说明 |
|---|---|---|---|---|
| QQ 音乐 `qq` | QRC | QRC/LRC | QRC | 多数歌曲有逐字；部分歌曲没有翻译/罗马音 |
| 酷狗音乐 `kg` | KRC | KRC 内嵌 | KRC 内嵌 | 逐字覆盖较好 |
| 网易云 `ne` | YRC | LRC | LRC | 部分歌曲有 YRC；其余为行级 |
| lrclib `lrclib` | `lyricsfile` | — | — | 无翻译/罗马音，作为兜底 |

匹配时会综合标题、歌手、专辑、时长打分；低于 `--min-score` 的候选直接丢弃。默认 `--prefer word` 会优先选择有逐字时间轴的候选，即使它的元数据分数略低；想更看重“就是这首歌”可以改用 `--prefer match`。

默认会去掉歌曲开头的制作信息（作词/作曲/编曲/录音/混音等），避免多条同时间戳的制作信息干扰逐字对齐；需要保留时加 `--keep-credits`。

## 大曲库建议

- 使用 SSD 和 `--workers 4`～`8`；各源有独立限速，不建议把 `--delay` 设得太小。
- 第一次跑会建立缓存；后续重跑基本不再请求网络。缓存目录默认在 `%LOCALAPPDATA%\lrc-helper\cache`（Windows）或 `~/.cache/lrc-helper`。
- 建议先 `--dry-run --limit 20 --verbose` 检查匹配质量。
- 若只需要逐字原词，用 `--contents orig` 减少无用的翻译/罗马音请求。
- 若只需要某一家平台的歌词，用 `--sources qq` 等限制请求量。
- 批处理中单个文件失败不会中断整个任务；用 `--report` 查看结果，`--fail-on-error` 让脚本在失败时返回非零。

## 命名模板

`--name` 支持以下占位符：

| 占位符 | 含义 |
|---|---|
| `{filename}` / `{stem}` | 音频文件名（不含扩展名） |
| `{title}` | 标签或文件名解析出的标题 |
| `{artist}` | 标签或文件名解析出的歌手 |
| `{album}` | 专辑 |
| `{track}` | 音轨号（两位，缺失为空） |
| `{index}` | 本次扫描的序号（从 1 开始） |
| `{source}` | 实际使用的歌词源（`qq`/`kg`/`ne`/`lrclib`） |

示例：`--name "{artist} - {title}"`。不含占位符的固定名字只能用于单个文件，否则会报错以避免互相覆盖。

## 常见问题

**1. 为什么生成的 LRC 只有原词，没有翻译/罗马音？**

该歌曲的歌词源没有提供对应轨。`--contents` 只是“允许抓取”，不是“强制存在”。可换源（`--sources`）或查看 `--dry-run --verbose` 的候选结果。

**2. 为什么选择了一个翻唱/现场版？**

匹配分低于 `--min-score` 会被丢弃；如果仍然选错，提高 `--min-score`，或使用 `--prefer match`。也可以先把文件标签整理准确（标题、歌手、专辑、时长）。

**3. 为什么不写音频标签？**

本项目只生成/覆盖同名 `.lrc`，不修改音频文件，避免破坏曲库。需要写入标签可以用 LDDC 等工具。

**4. 支持 CUE 分轨吗？**

目前按音频文件处理，不解析 `.cue`。CUE 分轨请先用其他工具拆分或导出为独立音频文件。

**5. 会不会请求太频繁？**

每个源有独立限速（默认 0.25～0.45 秒/请求），失败会指数退避重试。请遵守各平台的服务条款，不要用于大规模商业抓取。

## 开发

```bash
.venv\Scripts\python -m unittest discover -s tests
.venv\Scripts\ruff check src tests
.venv\Scripts\python -m lrc_helper --help
```

项目结构：

```
src/lrc_helper/
  cli.py            命令行
  pipeline.py       搜索、匹配、抓取、写文件
  awlrc.py          行级 LRC / LX 逐字轨 / awlrc 容器
  align.py          翻译/罗马音与原文时间对齐
  media.py          mutagen 元数据与时长
  naming.py         输出命名
  text.py           标题/歌手/专辑匹配打分
  parsers/          LRC、QRC、KRC、YRC、lrclib lyricsfile
  crypto/           QRC 3DES、网易 eapi AES
  sources/          QQ、酷狗、网易、lrclib
```

## 许可与致谢

- 本项目以 **GPL-3.0-only** 发布。
- QRC 解密实现改编自 [LDDC](https://github.com/chenmozhijin/LDDC)（沉默の金，GPL-3.0-only），原始算法参考 [WXRIW/QQMusicDecoder](https://github.com/WXRIW/QQMusicDecoder)。
- awlrc 容器与 LX 逐字语法参考 [lx-music-desktop](https://github.com/lyswhut/lx-music-desktop)。
- 歌词数据版权归各平台及原作者所有；本项目仅提供格式转换与本地保存工具。
