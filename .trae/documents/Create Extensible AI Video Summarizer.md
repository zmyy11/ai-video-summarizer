# AI Video Summarizer Professional Edition - Final Architecture Plan

This plan outlines the definitive architecture for the AI Video Summarizer, incorporating strict data modeling, structured Map-Reduce workflows, smart chunking, and future-proof interfaces.

## 1. Core Data Models (`src/models/`)

We will strictly enforce data structures using Pydantic to ensure consistency across the pipeline.

### A. Transcript Models
- **`Segment`**: `{ start: float, end: float, text: str }`
- **`Transcript`**:
  - `video_id`: str
  - `language`: str
  - `source`: Literal["platform_caption", "asr_whisper"]  # Future-proof
  - `segments`: List[Segment]

### B. Summarization Models
- **`ChunkSummary`** (Map Output):
  - `start_time`: float
  - `end_time`: float
  - `key_points`: List[str]
  - `entities`: List[str] (Optional)
- **`Chapter`**:
  - `title`: str
  - `start_time`: float
  - `end_time`: float
  - `summary`: List[str] (Bullets)
- **`SummaryResult`** (Reduce Output / Final Schema):
  - `one_sentence_summary`: str
  - `key_points`: List[str]
  - `chapters`: List[Chapter]
  - `quotes`: List[`{ text: str, timestamp: float }`]

## 2. Smart Chunking & Map-Reduce Strategy

### A. Pre-processing & Chunking (`src/utils/chunker.py`)
1.  **Pre-aggregation**: Merge tiny segments (< 5s) into logical blocks (e.g., 20-30s) to reduce noise and context switching.
2.  **Token-Aware Chunking**:
    - Iterate through segments.
    - Accumulate until `MAX_TOKENS` (e.g., 3000) is reached.
    - **Rule**: Never split a `Segment`. Always break at segment boundaries.
    - Overlap: Maintain a small overlap (e.g., 2 segments) if needed for continuity (optional for v1).

### B. Map-Reduce Workflow (`src/services/summarizer.py`)
1.  **Map Phase**:
    - Input: `List[Segment]` (Chunk)
    - Prompt: "Analyze this video segment..."
    - Output: `ChunkSummary` (JSON)
2.  **Reduce Phase**:
    - Input: `List[ChunkSummary]`
    - Prompt: "Synthesize these chunk summaries into a cohesive global summary with chapters..."
    - Output: `SummaryResult` (JSON)

## 3. Interfaces & Extensibility

### A. Video Source (`src/core/video.py`)
- `get_transcript(url, allow_asr=False, cookies_path=None) -> Transcript`
  - *Note*: `allow_asr` is present for v1.1 readiness but raises NotImplemented in v1.0.
- `get_metadata(url, cookies_path=None) -> VideoMetadata`

### B. Caching Strategy (`src/utils/cache.py`)
- **Cache Key Generation**:
  ```python
  key = sha256(
      f"{video_id}_{transcript_hash}_{model_name}_{template_name}_{prompt_version}".encode()
  ).hexdigest()
  ```
- Stores raw `summary.json` to avoid re-generating for the same config.

## 4. Engineering & Output

### A. Output Protocol
- **Machine**: `outputs/{video_id}/summary.json` (The source of truth).
- **Human**: `outputs/{video_id}/summary.md` (Rendered from JSON).
- **CLI**: Rich Panel rendering the JSON content.

### B. Dependencies
- `pydantic`, `yt-dlp`, `youtube-transcript-api`, `openai`, `tenacity`, `tiktoken`, `rich`, `jinja2`, `pydantic-settings`.

## 5. Implementation Steps
1.  **Setup**: Initialize project, `uv add` dependencies.
2.  **Models**: Define Pydantic models in `src/models/`.
3.  **Core**: Implement `VideoSource` interface and `Chunker` logic.
4.  **Providers**: Implement `YoutubeProvider` and `BilibiliProvider`.
5.  **Service**: Implement `SummarizerService` with Map-Reduce logic.
6.  **CLI**: Build `src/cli.py` with arguments and Rich UI.
7.  **Testing**: Verify with a short video (direct) and long video (chunked).
