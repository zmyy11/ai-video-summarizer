# AI Video Summarizer

一个面向 YouTube / Bilibili 的 AI 视频总结工具，支持字幕抓取（含 B 站 AI 字幕）、长视频 Map-Reduce 总结、关键帧截图、以及输出可阅读的 Markdown 学习笔记。

## 功能特性

- 多平台：支持 YouTube 链接与 Bilibili BV/URL
- 长视频高质量：长视频自动 Map-Reduce，总结更稳、更细
- 结构化输出：输出章节、时间戳、要点、金句等结构化数据
- 学习型笔记：生成 `summary.md`（摘要）与 `study.md`（讲解型学习笔记）
- 关键帧截图：可选生成 3–5 张关键帧并写入 Markdown
- 稳定性：内置重试、缓存（可关闭）、cookie 支持

## 环境要求

- Python：`>= 3.13`
- 包管理：推荐使用 `uv`
- `ffmpeg`：用于 Whisper 音频转写与关键帧截图（强烈建议安装）

macOS 安装 `ffmpeg`（任选其一）：

```bash
brew install ffmpeg
```

## 安装

```bash
git clone https://github.com/your-repo/ai-video-summarizer.git
cd ai-video-summarizer
uv sync
```

## 配置（.env）

复制示例配置并填写你的大模型参数：

```bash
cp .env.example .env
```

关键配置项：

- `LLM_API_KEY`：你的 API Key
- `LLM_BASE_URL`：OpenAI 兼容接口地址（例如 `https://api.openai.com/v1`，或你自建/第三方网关）
- `LLM_MODEL`：模型名（例如 `gpt-4o`）
- `LLM_TEMPERATURE`：建议从 `0` 或 `0.2` 开始，降低跑题概率
- 可选 `BILIBILI_COOKIES` / `YOUTUBE_COOKIES`：以 `key=value; key2=value2` 的形式填入，用于会员/限制视频

也可以通过 `COOKIES_PATH` 指定 `cookies.txt`（Netscape 格式）。

## 使用方法

### 基础用法

```bash
uv run ai-video-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"
```

B 站可直接传 BV：

```bash
uv run ai-video-summarizer BV12oLaztEkS
```

### 常用参数

- `--lang`：输出语言（`zh`/`en`），默认 `zh`
- `--cookies`：指定 `cookies.txt` 路径
- `--model`：覆盖 `.env` 的 `LLM_MODEL`
- `--no-save`：不落盘输出（默认会保存到 `outputs/`）
- `--use-whisper`：当没有字幕/字幕不可用时，自动下载音频并用 Whisper 转写（速度较慢）
- `--keyframes`：按章节/重点时间戳提取关键帧截图
- `--no-cache`：关闭总结缓存并强制重算（当出现“文不对题”/想更新结果时很有用）
- `--extractive`：额外生成 `study_extractive.md`（不调用 LLM 的提取式笔记，用于保证“严格对齐原文”）

### 推荐组合

- 想要最快速度的正常总结：
  - `uv run ai-video-summarizer <URL/BV>`
- 字幕不稳定（B 站只有弹幕 XML / 无字幕）：
  - `uv run ai-video-summarizer <URL/BV> --use-whisper --no-cache`
- 需要“图文复习”：
  - `uv run ai-video-summarizer <URL/BV> --keyframes --no-cache`
- 需要“绝不跑题”的学习记录（强对齐字幕/ASR 原文）：
  - `uv run ai-video-summarizer <URL/BV> --use-whisper --no-cache --extractive`

## 算法流程（实现细节）

本工具的“完整处理链路”可以理解为：先拿到可信的时间轴文本（字幕/ASR），再在其上做分块与 Map-Reduce 总结，最后把结果组织成可复习的 Markdown 输出。

### 0）总览（从命令到文件）

```text
CLI 入口（src/cli.py）
  -> URL 规范化（YouTube: 只保留 v=VIDEO_ID）
  -> 平台识别（YouTube / Bilibili）
  -> cookies 选择（--cookies > COOKIES_PATH > 环境变量生成）
  -> 拉元数据 + 拉字幕/ASR（provider）
  -> 分块 + Map-Reduce 总结（SummarizerService）
  ->（可选）关键帧截图（ffmpeg）
  -> 生成 summary.md / study.md（以及可选的 study_extractive.md）
  -> 落盘 outputs/<video_id>/
```

### 1）输入 URL 规范化与平台识别

- 入口在 `src/cli.py`：会先做字符串清洗（去反引号/引号/首尾空白），并对 YouTube 链接做规范化（把 `&list=...` 等参数去掉，只保留 `watch?v=...`）。
- 平台识别规则：URL 包含 `bilibili` 或 `BV` 走 B 站，否则走 YouTube（对应 `src/providers/bilibili.py` / `src/providers/youtube.py`）。

### 2）Cookies 选择与生成（登录态支持）

cookies 来源优先级：

- `--cookies` 指定的 `cookies.txt`
- `.env` 里的 `COOKIES_PATH`
- `.env` 里的 `BILIBILI_COOKIES` / `YOUTUBE_COOKIES` 自动生成 `.cache/generated_cookies.txt`

实现位置：`src/utils/cookies.py` 与 `src/cli.py`。

### 3）元数据提取（标题、作者、时长等）

- `provider.extract_info(url, cookies_path=...)` 使用 `yt-dlp` 抽取元信息。
- 输出为 `VideoMetadata`（`src/models/video.py`），用于给总结文档写标题、作者、时长范围等。

### 4）字幕获取与回退策略（最关键的“对齐来源”）

目标是拿到带时间戳的 `Transcript(segments=[...])`（`src/models/transcript.py`），后续所有总结/学习笔记都建立在这份时间轴文本之上。

YouTube（`src/providers/youtube.py`）的回退顺序：

- 优先 `youtube-transcript-api`：拿到结构化字幕（包含 start/duration/text），并在可翻译时尝试翻译到中文。
- 回退 `yt-dlp` 字幕链接：从 `subtitles`/`automatic_captions` 里挑语言与格式最合适的一条，拉取后解析为分段（支持 `vtt/srt/json3/srv3`）。
- 最后回退 Whisper ASR：当 `--use-whisper` 开启且以上都失败时，用 `yt-dlp` 下载音频并调用 `openai-whisper` 转写（较慢，但覆盖面最强）。

Bilibili（`src/providers/bilibili.py`）的策略要点：

- 优先闭字幕/AI 字幕（更适合学习与总结），避免误用弹幕 XML（danmaku）。
- 必要时会组合多种候选来源并按“语言/格式”评分选最优。

### 5）分块（Chunking）

长视频字幕会先按 token 上限切块，避免一次性塞给模型导致截断或成本失控：

- 位置：`src/utils/chunker.py`
- 产物：一系列文本 chunk，每个 chunk 保持尽量完整的语义边界（尽可能不在句中间硬切）。

### 6）Map-Reduce 总结（章节化结构输出）

核心流程在 `src/services/summarizer.py`：

- Map：对每个 chunk 提取“要点 + 时间线线索”（Prompt 模板：`src/prompts/map.jinja2`）。
- Reduce：把所有 Map 结果合并，生成全局“一句话总结、关键要点、章节结构、金句”等（Prompt 模板：`src/prompts/reduce.jinja2`）。
- 输出结构：`SummaryResult`（`src/models/summary.py`），随后由 CLI 写入 `summary.json` 和 `summary.md`。

### 7）关键帧（可选）与时间戳对齐

开启 `--keyframes` 后，会在“章节时间范围/关键时间点”附近截图，用于复习时快速回忆画面：

- 位置：`src/utils/keyframes.py`
- 原理：用 `ffmpeg` 从视频流或下载的本地文件按时间点截图，并把图片路径写回到章节结构里，最终在 `summary.md` 里引用图片。

### 8）学习笔记生成：讲解型 vs 提取式

- `study.md`（讲解型）：基于字幕与总结结构，让模型按“讲解/类比/结构化复习”的方式写学习笔记（Prompt 模板：`src/prompts/study.jinja2`）。
- `study_extractive.md`（提取式）：当 `--extractive` 开启时生成，不调用 LLM，而是对字幕做“按时间段抽取 + 排版”，用于确保内容严格来自原文，适合你担心“文不对题”时对照复习。

### 9）缓存（避免重复计算）

- 总结缓存位于 `.cache/summaries/`（实现：`src/utils/cache.py`）。
- `--no-cache` 会强制重新计算，适合排查“字幕来源变化/命中旧结果/想更新输出”。

## 输出文件说明

默认会保存到 `outputs/<video_id>/`：

- `summary.json`：结构化总结（章节、时间戳、要点、金句、关键帧占位等）
- `transcript.json`：字幕/ASR 转写结果（含分段时间戳）
- `summary.md`：面向阅读的摘要 Markdown
- `study.md`：讲解型学习笔记（由 LLM 生成）
- `study_extractive.md`：提取式学习笔记（仅在 `--extractive` 时生成，不调用 LLM）

关键帧默认输出到 `outputs/keyframes/`，文件名形如 `VIDEOID_秒数.jpg`，并在 `summary.md` 中以图片链接引用。

## CLI 使用示例

- 基本总结（支持 B 站/YouTube）：
  - `uv run ai-video-summarizer "https://www.bilibili.com/video/BVxxxxxxx/"`
- 提取关键帧截图：
  - `uv run ai-video-summarizer "<URL>" --keyframes`
- 多模态视觉细化（使用关键帧图片参与总结）：
  - `uv run ai-video-summarizer "<URL>" --vision`
  - 说明：`--vision` 会自动启用关键帧提取，并在每个章节使用关键帧图片辅助生成更清晰的要点。
- 指定模型与识别：
  - `uv run ai-video-summarizer "<URL>" --model <MODEL_NAME> --use-whisper`

## 选项说明

- `--vision`：使用关键帧图片进行多模态细化总结（自动开启关键帧提取）。
- `--keyframes`：仅提取关键帧并在输出中展示图片路径，不进行视觉细化。
- `--use-whisper`：无字幕时启用语音识别。
- `--no-cache`：忽略缓存，强制重新计算。
- `--extractive`：生成提取式学习笔记（不依赖 LLM）。

关键帧默认输出到 `outputs/keyframes/`，文件名形如 `VIDEOID_秒数.jpg`，并在 `summary.md` 中以图片链接引用。

## 缓存机制

- 总结缓存位于 `.cache/summaries/`
- `--no-cache` 可关闭缓存并强制重算（对排查“结果不更新/不对题”非常关键）

## 项目结构（简述）

- `src/providers/`：平台适配（YouTube / Bilibili）
- `src/services/summarizer.py`：Map-Reduce 总结服务、学习笔记生成
- `src/prompts/`：Jinja2 Prompt 模板（`map.jinja2` / `reduce.jinja2` / `study.jinja2`）
- `src/utils/`：分块、缓存、重试、关键帧、cookie 处理等工具

## 常见问题（FAQ）

### 1）为什么会出现“文不对题”？

常见原因是：

- 字幕源波动/拿到的并非你以为的内容（建议打开 `outputs/<id>/transcript.json` 抽查对齐）
- 模型指令遵循较弱，出现幻觉（建议降低 `LLM_TEMPERATURE` 或更换模型）
- 命中旧缓存（用 `--no-cache` 强制重算）

### 2）B 站提示只有 Danmaku XML / 没有有效字幕？

说明该视频没有可用闭字幕，或需要登录态才能取到字幕。建议：

- 配置 `BILIBILI_COOKIES` 或 `--cookies`
- 或直接使用 `--use-whisper` 走语音转写

## License

未指定。你可以在仓库中添加 `LICENSE` 文件声明开源协议。
# ai-video-summarizer
# ai-video-summarizer
