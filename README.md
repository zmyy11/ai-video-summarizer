# AI Video Summarizer

面向 YouTube 与 Bilibili 的视频总结工具：自动抓取字幕/转写、分块 Map-Reduce 总结、输出结构化摘要与学习笔记，并可选抽取关键帧与视觉增强总结。

## 功能亮点

- 多平台支持：YouTube 链接、B 站 BV/链接
- 字幕优先 + ASR 兜底：优先官方字幕，必要时 Whisper 语音转写
- 结构化总结：一句话摘要、关键要点、章节时间线、金句
- 学习笔记：生成 `summary.md` 与 `study.md`（可选生成提取式笔记）
- 关键帧截图：按章节高亮时间点自动截帧
- 视觉强化（可选）：用关键帧图片精炼章节要点
- 缓存与重试：减少重复调用，提升稳定性

## 环境要求

- Python 3.13+
- 包管理：推荐 `uv`
- `ffmpeg`：用于 Whisper 音频转写与关键帧截图

macOS 安装 ffmpeg：

```bash
brew install ffmpeg
```

## 安装

```bash
git clone <repo-url>
cd ai-video-summarizer
uv sync
```

## 配置（.env）

项目通过环境变量配置模型与密钥（必填 `LLM_API_KEY`）。在项目根目录创建 `.env`：

```bash
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
LLM_TEMPERATURE=0.7
OUTPUT_LANG=zh
COOKIES_PATH=./cookies.txt
BILIBILI_COOKIES=key=value; key2=value2
YOUTUBE_COOKIES=key=value; key2=value2
```

说明：

- `LLM_API_KEY` 必填。
- `LLM_BASE_URL` 支持 OpenAI 兼容接口。
- `OUTPUT_LANG` 影响结构化总结语言（`zh`/`en`）。
- Cookies 可选：`--cookies` > `COOKIES_PATH` > `BILIBILI_COOKIES/YOUTUBE_COOKIES` 自动生成。

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

- `--lang`：输出语言（默认 `zh`）
- `--cookies`：指定 `cookies.txt`（Netscape 格式）
- `--model`：覆盖 `LLM_MODEL`
- `--no-save`：只在控制台展示，不写入 `outputs/`
- `--use-whisper`：字幕不可用时启用 Whisper ASR
- `--keyframes`：抽取关键帧截图
- `--vision`：基于关键帧图片精炼章节总结（自动启用 `--keyframes`）
- `--no-cache`：跳过缓存并强制重算
- `--extractive`：生成提取式笔记 `study_extractive.md`（不调用 LLM）

### 推荐组合

- 常规总结：
  - `uv run ai-video-summarizer <URL/BV>`
- 字幕不可用：
  - `uv run ai-video-summarizer <URL/BV> --use-whisper --no-cache`
- 需要关键帧：
  - `uv run ai-video-summarizer <URL/BV> --keyframes`
- 视觉增强：
  - `uv run ai-video-summarizer <URL/BV> --vision`
- 强对齐原文：
  - `uv run ai-video-summarizer <URL/BV> --extractive`

## 输出内容

默认输出到 `outputs/<video_id>/`：

- `summary.json`：结构化总结（章节/时间戳/要点/金句）
- `transcript.json`：字幕或 ASR 结果（含时间戳）
- `summary.md`：可阅读摘要
- `study.md`：讲解型学习笔记
- `study_extractive.md`：提取式笔记（仅 `--extractive`）

关键帧图片：`outputs/keyframes/<video_id>_<秒数>.jpg`

## 处理流程概览

```text
CLI -> 识别平台 -> 拉取元数据/字幕
    -> 分块 -> Map-Reduce 总结
    -> (可选) 关键帧截取/视觉精炼
    -> 输出 summary/study/transcript
```

## 字幕与转写策略

### YouTube

1. `youtube-transcript-api`（优先）
2. `yt-dlp` 字幕链接（vtt/srt/json3/srv3）
3. Whisper ASR（需 `--use-whisper`）

### Bilibili

- 优先闭字幕/AI 字幕，避免误用弹幕 XML
- 如果官方字幕不可用，自动回退 Whisper ASR

## 关键帧与视觉模式

- `--keyframes`：让模型在 Reduce 阶段挑选关键时间点，再用 `ffmpeg` 截图
- `--vision`：把关键帧图片作为多模态输入，细化章节摘要
- 需要使用支持图像输入的模型，否则会报错

## 缓存策略

- 总结缓存位于 `.cache/summaries/`
- 缓存键包含 `video_id + model + lang + v2`
- `--no-cache` 强制重新计算

## 开发与测试

```bash
uv run python tests/test_basic.py
```

仅包含基础导入与初始化检查。

## 已知限制

- `study.md` 的提示词为中文模板，设置 `--lang en` 时仍可能输出中文。
- 未提供标准化测试套件，建议自行补充 `pytest` 用例。

## License

当前仓库未指定开源协议。
