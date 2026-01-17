# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Video Summarizer for YouTube and Bilibili - extracts subtitles/transcripts and generates structured summaries with chapters, timestamps, keyframes, and study notes using Map-Reduce LLM processing.

**Language**: Python 3.13+ with `uv` package manager
**Main Entry**: `src/cli.py` - CLI command handler
**Dependencies**: OpenAI API (or compatible), yt-dlp, Whisper (optional), ffmpeg (for keyframes)

## Key Commands

### Running the Tool
```bash
# Basic usage (YouTube or Bilibili)
uv run ai-video-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"
uv run ai-video-summarizer "BV12oLaztEkS"  # Bilibili BV ID

# With options
uv run ai-video-summarizer <URL> --keyframes --use-whisper --no-cache
uv run ai-video-summarizer <URL> --vision  # Multimodal summary using keyframes
uv run ai-video-summarizer <URL> --extractive  # Non-LLM extractive notes
```

### Development
```bash
# Install dependencies
uv sync

# Run main script
uv run python main.py

# Run basic tests (no test framework configured yet)
uv run python tests/test_basic.py
```

## Architecture Overview

### Processing Pipeline

The complete video-to-summary flow:

```
CLI Input (src/cli.py)
  ↓
Platform Detection (YouTube/Bilibili)
  ↓
Provider.extract_info() → VideoMetadata
Provider.get_transcript() → Transcript (with fallback: subtitles → yt-dlp → Whisper)
  ↓
SummarizerService.summarize()
  ├─ Chunking (long videos split by token limit)
  ├─ Map Phase (extract key points per chunk)
  ├─ Reduce Phase (merge into structured chapters/timestamps/quotes)
  ├─ Optional: Keyframe extraction (ffmpeg screenshots at AI-selected timestamps)
  └─ Optional: Vision refinement (multimodal chapter improvement with keyframes)
  ↓
SummarizerService.generate_study_notes() → study.md
Optional: generate_extractive_notes() → study_extractive.md
  ↓
Save to outputs/<video_id>/
  ├─ summary.json (structured data)
  ├─ transcript.json (timestamped segments)
  ├─ summary.md (readable Markdown)
  ├─ study.md (LLM-generated instructional notes)
  └─ study_extractive.md (extractive, no LLM)
```

### Core Components

**Providers** (`src/providers/`):
- `youtube.py` / `bilibili.py` - Platform-specific metadata & transcript extraction
- Fallback chain: platform subtitles → yt-dlp subtitles → Whisper ASR (if `--use-whisper`)
- Bilibili prioritizes AI/closed captions over danmaku XML

**Summarizer** (`src/services/summarizer.py`):
- **Map-Reduce Pattern**: Long videos chunked, each chunk summarized independently (Map), then merged into global structure (Reduce)
- **Single-Chunk Optimization**: Short videos skip Map phase, go direct to Reduce with full transcript
- **Prompt Templates**: Jinja2 templates in `src/prompts/` (`map.jinja2`, `reduce.jinja2`, `study.jinja2`)
- **Cache**: Summaries cached in `.cache/summaries/` by `<video_id>_<model>_<lang>_v2` (bypass with `--no-cache`)
- **Vision Mode**: If `--vision` enabled, refines chapter summaries using extracted keyframe images via multimodal API

**Models** (`src/models/`):
- `transcript.py` - Timestamped `Segment` and `Transcript`
- `summary.py` - `ChunkSummary`, `SummaryResult`, `Chapter`, `KeyFrame`
- `video.py` - `VideoMetadata`

**Utils** (`src/utils/`):
- `chunker.py` - Token-based splitting (preserves sentence boundaries)
- `cache.py` - Summary caching
- `cookies.py` - Cookie file generation from env vars (`BILIBILI_COOKIES` / `YOUTUBE_COOKIES`)
- `keyframes.py` - ffmpeg-based screenshot extraction
- `retry.py` - API retry decorator with exponential backoff
- `logger.py` - Logging setup

**Config** (`src/config.py`):
- Pydantic settings from `.env`: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TEMPERATURE`
- Cookie paths: `COOKIES_PATH` (file) or `BILIBILI_COOKIES`/`YOUTUBE_COOKIES` (raw string)

### Important Behavioral Details

**URL Normalization** (src/cli.py:101-114):
- YouTube links stripped of playlist/tracking params (keeps only `?v=VIDEO_ID`)
- Bilibili BV IDs auto-wrapped to full URL

**Cookie Priority** (src/cli.py:142-144):
1. `--cookies` arg
2. `COOKIES_PATH` env var
3. Auto-generated from `BILIBILI_COOKIES`/`YOUTUBE_COOKIES` to `.cache/generated_cookies.txt`

**Transcript Fallback Strategy** (platform-specific):
- YouTube: `youtube-transcript-api` → yt-dlp subtitle links (vtt/srt/json3/srv3) → Whisper ASR
- Bilibili: Closed/AI captions (scored by language/format) → yt-dlp → Whisper

**Map-Reduce vs Direct** (src/services/summarizer.py:168-206):
- Multi-chunk videos: Full Map-Reduce pipeline
- Single-chunk (short) videos: Skip Map, feed raw transcript to Reduce for efficiency

**Anti-Hallucination Check** (src/services/summarizer.py:211-233):
- If summary doesn't mention title keywords, re-run Reduce with raw transcript at temperature=0

**Keyframe Extraction** (src/services/summarizer.py:242-266):
- LLM selects timestamps during Reduce phase
- If none selected, fallback to chapter midpoints (max 5 longest chapters)
- ffmpeg extracts frames → saved to `outputs/keyframes/VIDEOID_seconds.jpg`

**Vision Refinement** (src/services/summarizer.py:269-305):
- Enabled via `--vision` (auto-enables `--keyframes`)
- For each chapter with keyframe images: send images (up to 6) + existing bullets to multimodal API
- Replaces chapter summary with vision-grounded output

**Study Notes** (`generate_study_notes()`):
- LLM rewrites summary as instructional/explanatory Markdown (`study.md`)
- `--extractive` mode: Non-LLM time-bucketed extraction from raw transcript (`study_extractive.md`)

## Configuration

**.env File**:
```bash
# Required
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1  # or compatible gateway
LLM_MODEL=gpt-4o

# Optional
LLM_TEMPERATURE=0.7  # Lower = less hallucination
OUTPUT_LANG=zh       # zh/en
COOKIES_PATH=./cookies.txt  # or use raw cookies below
BILIBILI_COOKIES=key=value; key2=value2
YOUTUBE_COOKIES=key=value; key2=value2
```

**ffmpeg Requirement**:
- **Whisper ASR**: Requires ffmpeg for audio extraction
- **Keyframes**: Requires ffmpeg for screenshot extraction
- Install: `brew install ffmpeg` (macOS)

## Output Files

Saved to `outputs/<video_id>/`:
- `summary.json` - Structured JSON (chapters, timestamps, keyframes, quotes)
- `transcript.json` - Timestamped segments
- `summary.md` - Human-readable Markdown
- `study.md` - LLM-generated study notes
- `study_extractive.md` - Extractive notes (if `--extractive`)

Keyframes: `outputs/keyframes/VIDEOID_seconds.jpg`

## Testing

Currently minimal testing infrastructure (`tests/test_basic.py` - manual import/init checks).

To add tests, use `pytest`:
```bash
uv add --dev pytest
uv run pytest tests/
```

## Troubleshooting Patterns

**"Summary is off-topic"**:
- Check `outputs/<video_id>/transcript.json` to verify transcript source
- Lower `LLM_TEMPERATURE` in `.env` (try 0.0-0.2)
- Use `--no-cache` to force re-computation
- Anti-hallucination check (src/services/summarizer.py:211-233) already retries with temperature=0 if title keywords missing

**"No subtitles found" for Bilibili**:
- Video may lack closed captions → configure `BILIBILI_COOKIES` for auth
- Or use `--use-whisper` for ASR fallback

**Cache not refreshing**:
- Use `--no-cache` flag
- Cache key includes model + lang + version (src/services/summarizer.py:86)

**Keyframes not extracted**:
- Verify ffmpeg installed: `which ffmpeg`
- Check logs for ffmpeg errors in `src/utils/keyframes.py`
