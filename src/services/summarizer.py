import json
from typing import List
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
from src.config import settings
from src.models.transcript import Transcript, Segment
from src.models.summary import ChunkSummary, SummaryResult
from src.models.video import VideoMetadata
from src.utils.chunker import Chunker
from src.utils.retry import api_retry
from src.utils.logger import logger
from src.utils.cache import cache_manager
from src.utils.keyframes import keyframe_extractor
from src.models.summary import KeyFrame
import base64

class SummarizerService:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.chunker = Chunker(model_name=settings.LLM_MODEL)
        self.env = Environment(loader=FileSystemLoader("src/prompts"))
        self.map_template = self.env.get_template("map.jinja2")
        self.reduce_template = self.env.get_template("reduce.jinja2")
        self.study_template = self.env.get_template("study.jinja2")

    @api_retry()
    def _call_llm(self, prompt: str, output_schema: dict = None, temperature: float = None) -> str:
        response = self.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You output JSON strictly grounded in provided content. Do not include anything not present in the transcript or chunk summaries."},
                {"role": "user", "content": prompt}
            ],
            temperature=(temperature if temperature is not None else settings.LLM_TEMPERATURE),
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    @api_retry()
    def _call_llm_text(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful instructor that writes high-quality Markdown."},
                {"role": "user", "content": prompt}
            ],
            temperature=settings.LLM_TEMPERATURE
        )
        return response.choices[0].message.content

    @api_retry()
    def _call_llm_vision(self, messages: list, temperature: float = None) -> str:
        response = self.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=(temperature if temperature is not None else settings.LLM_TEMPERATURE),
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    def _process_chunk(self, chunk: List[Segment]) -> ChunkSummary:
        start_time = chunk[0].start
        end_time = chunk[-1].end
        text = "\n".join([s.text for s in chunk])
        
        prompt = self.map_template.render(
            start_time=start_time,
            end_time=end_time,
            text=text
        )
        
        response_json = self._call_llm(prompt)
        try:
            data = json.loads(response_json)
            return ChunkSummary(**data)
        except Exception as e:
            logger.error(f"Failed to parse chunk summary: {e}")
            # Fallback for empty/failed chunk
            return ChunkSummary(start_time=start_time, end_time=end_time, key_points=[])

    def summarize(self, transcript: Transcript, metadata: VideoMetadata, extract_keyframes: bool = False, cookies_path: str = None, force_refresh: bool = False, use_vision: bool = False) -> SummaryResult:
        # Check cache
        cache_key_data = f"{metadata.id}_{settings.LLM_MODEL}_{settings.OUTPUT_LANG}_v2"
        cached = None if force_refresh else cache_manager.get_summary(cache_key_data)
        result = None
        
        if cached:
            result = SummaryResult(**cached)
        else:
            # 1. Chunking
            logger.info("Chunking transcript...")
            chunks = self.chunker.chunk(transcript)
            
            # 2. Map Phase
            chunk_summaries = []
            if len(chunks) > 1:
                logger.info(f"Starting Map phase for {len(chunks)} chunks...")
                for i, chunk in enumerate(chunks):
                    logger.info(f"Processing chunk {i+1}/{len(chunks)}...")
                    summary = self._process_chunk(chunk)
                    chunk_summaries.append(summary)
            else:
                # For short videos (single chunk), skip Map phase to save tokens/time
                # Just wrap the transcript into a simple structure for Reduce
                logger.info("Short video detected (single chunk). Skipping Map phase.")
                chunk = chunks[0]
                chunk_summaries.append(ChunkSummary(
                    start_time=chunk[0].start,
                    end_time=chunk[-1].end,
                    key_points=["(Full transcript content)"],
                    entities=[]
                ))
                # Note: For Reduce phase, we might need to adjust the prompt slightly if 'text' is raw transcript
                # But our current Reduce prompt expects 'key_points'.
                # Actually, if we skip Map, we should just feed the raw transcript to Reduce?
                # Or we can just let Reduce handle the "summary of summaries" logic, 
                # but here "summary" is the full text. 
                # Let's adjust: if single chunk, we pass the raw text as "key_points" or "text" 
                # Our Reduce prompt takes `chunks` which has `key_points`. 
                # A better approach for single chunk: 
                # Modify ChunkSummary to carry full text if needed, OR 
                # Just run Map on it? 
                # Actually, running Map on single chunk is fine, but Reduce on top of it is redundant?
                # No, Map extracts points, Reduce formats structure. 
                # If we skip Map, Reduce needs to do Extraction AND Formatting.
                # Let's keep Map for consistency unless it's extremely short.
                # Actually user asked: "video smaller than min chunk, do we need map-reduce?"
                # Answer: No, just one pass.
                
                # So if len(chunks) == 1, we should call a "Direct Summary" method instead of Map-Reduce.
                pass 

            # Refined Logic:
            if len(chunks) == 1:
                logger.info("Short video detected. Using Direct Summary (One-Pass)...")
                # We can reuse Reduce prompt but feed it raw text? 
                # Or use a separate "Direct" prompt?
                # For simplicity and quality, let's use the Reduce prompt but adapt the input.
                # We need to construct a "fake" chunk summary that contains the full text?
                # No, Reduce prompt expects list of summaries.
                
                # Let's call _process_chunk but with a special flag or just use a one-shot prompt?
                # Actually, the Reduce prompt is designed to take "Existing Summaries". 
                # If we give it raw text, it might get confused.
                
                # Let's stick to Map-Reduce for now for consistency, OR implement a proper "Direct" mode.
                # Given the user's question, they implied it's redundant.
                # Let's try to optimize:
                # If single chunk, we can just run the Reduce prompt directly on the raw transcript text?
                # We need to change the Reduce template to accept 'text' OR 'chunks'.
                
                # Implementation:
                # 1. Modify Reduce template to handle raw text.
                # 2. Pass raw text here.
                pass
            else:
                # Normal Map-Reduce
                pass
                
            # Wait, let's just do Map -> Reduce for single chunk for now to ensure structured output (Chapters etc).
            # The Map step extracts points, Reduce organizes them. 
            # If we skip Map, Reduce has to do both. GPT-4o can handle it.
            
            # Let's implement the optimization:
            if len(chunks) == 1:
                logger.info("Short video detected. Running One-Pass Summarization...")
                # We need a One-Pass prompt that does extraction + formatting
                # We can reuse Reduce template but pass the full text as "context"
                chunk = chunks[0]
                full_text = "\n".join([s.text for s in chunk])
                
                # We need to modify Reduce template or use a new one. 
                # Let's use a new "direct.jinja2" or reuse "reduce.jinja2" with a flag.
                # Let's modify Reduce template to support 'transcript' input.
                prompt = self.reduce_template.render(
                    title=metadata.title,
                    author=metadata.author,
                    transcript=full_text, # New variable
                    chunks=None,
                    language=settings.OUTPUT_LANG,
                    extract_keyframes=extract_keyframes, # Hint for LLM to pick timestamps
                    required_terms=[t for t in metadata.title.replace('（',' ').replace('）',' ').replace('(', ' ').replace(')', ' ').split() if t]
                )
            else:
                # Map Phase
                logger.info(f"Starting Map phase for {len(chunks)} chunks...")
                for i, chunk in enumerate(chunks):
                    logger.info(f"Processing chunk {i+1}/{len(chunks)}...")
                    summary = self._process_chunk(chunk)
                    chunk_summaries.append(summary)
                
                # Reduce Phase
                logger.info("Starting Reduce phase...")
                prompt = self.reduce_template.render(
                    title=metadata.title,
                    author=metadata.author,
                    chunks=chunk_summaries,
                    transcript=None,
                    language=settings.OUTPUT_LANG,
                    extract_keyframes=extract_keyframes,
                    required_terms=[t for t in metadata.title.replace('（',' ').replace('）',' ').replace('(', ' ').replace(')', ' ').split() if t]
                )
            
            response_json = self._call_llm(prompt)
            try:
                data = json.loads(response_json)
                result = SummaryResult(**data)
                def mentions_title_terms(text: str, terms: list) -> bool:
                    if not terms:
                        return True
                    t = (text or "").lower()
                    for term in terms:
                        if term.lower() in t:
                            return True
                    return False
                combined_text = " ".join([result.one_sentence_summary] + result.key_points)
                req_terms = [t for t in metadata.title.replace('（',' ').replace('）',' ').replace('(', ' ').replace(')', ' ').split() if t]
                if not mentions_title_terms(combined_text, req_terms):
                    prompt2 = self.reduce_template.render(
                        title=metadata.title,
                        author=metadata.author,
                        transcript="\n".join([s.text for s in transcript.segments]),
                        chunks=None,
                        language=settings.OUTPUT_LANG,
                        extract_keyframes=False,
                        required_terms=req_terms
                    )
                    response_json2 = self._call_llm(prompt2, temperature=0.0)
                    data2 = json.loads(response_json2)
                    result = SummaryResult(**data2)
                
                # Save to cache
                cache_manager.save_summary(cache_key_data, data)
            except Exception as e:
                logger.error(f"Failed to parse final summary: {e}")
                raise

        # 4. Keyframe Extraction (Optional)
        if extract_keyframes and result:
            logger.info("Extracting keyframes based on AI selection...")
            # Collect all keyframe requests from chapters
            all_kf_requests = []
            for chapter in result.chapters:
                if chapter.keyframes:
                    for kf in chapter.keyframes:
                        all_kf_requests.append((kf, chapter))
            if not all_kf_requests:
                logger.warning("AI did not select any keyframes. Falling back to default chapter midpoints (max 5).")
                sorted_chapters = sorted(result.chapters, key=lambda c: c.end_time - c.start_time, reverse=True)[:5]
                sorted_chapters.sort(key=lambda c: c.start_time)
                for chapter in sorted_chapters:
                    ts = chapter.start_time + (chapter.end_time - chapter.start_time) / 2
                    kf = KeyFrame(timestamp=ts, description=f"Overview of {chapter.title}")
                    chapter.keyframes = [kf]
                    all_kf_requests.append((kf, chapter))
            timestamps = [req[0].timestamp for req in all_kf_requests]
            if timestamps:
                logger.info(f"Extracting {len(timestamps)} keyframes...")
                paths = keyframe_extractor.extract_batch(metadata.url, timestamps, metadata.id, cookies_path=cookies_path)
                for i, path in enumerate(paths):
                    if i < len(all_kf_requests):
                        kf, _ = all_kf_requests[i]
                        kf.image_path = path

        # 5. Vision refine (Optional)
        if use_vision and result:
            any_images = any(
                getattr(kf, "image_path", None) for c in result.chapters for kf in (c.keyframes or [])
            )
            if any_images:
                logger.info("Refining chapter summaries using vision keyframes...")
                for chapter in result.chapters:
                    images = [kf.image_path for kf in (chapter.keyframes or []) if getattr(kf, "image_path", None)]
                    if not images:
                        continue
                    # Build multimodal messages
                    user_content = [
                        {"type": "text", "text": f"Title: {chapter.title}\nTime: {int(chapter.start_time)}-{int(chapter.end_time)}\nExisting bullets:\n" + "\n".join([f"- {p}" for p in chapter.summary])}
                    ]
                    # Attach up to 6 images as data URLs
                    for path in images[:6]:
                        try:
                            with open(path, "rb") as f:
                                b64 = base64.b64encode(f.read()).decode("utf-8")
                            data_url = f"data:image/jpeg;base64,{b64}"
                            user_content.append({"type": "input_image", "image_url": {"url": data_url, "detail": "low"}})
                        except Exception as e:
                            logger.warning(f"Skip image {path}: {e}")
                    vision_msgs = [
                        {"role": "system", "content": [
                            {"type": "text", "text": "You output JSON: {\"summary\": [bullets...]}. Use images to improve clarity. Keep concise, factual, and grounded in visuals and text."}
                        ]},
                        {"role": "user", "content": user_content}
                    ]
                    resp_json = self._call_llm_vision(vision_msgs, temperature=0.0)
                    try:
                        data = json.loads(resp_json)
                        new_bullets = data.get("summary") or []
                        if isinstance(new_bullets, list) and new_bullets:
                            chapter.summary = new_bullets
                    except Exception as e:
                        logger.warning(f"Vision refine failed for chapter '{chapter.title}': {e}")

        return result

    def generate_study_notes(self, transcript: Transcript, metadata: VideoMetadata, summary: SummaryResult) -> str:
        full_text = "\n".join([s.text for s in transcript.segments])
        prompt = self.study_template.render(
            title=metadata.title,
            author=metadata.author,
            transcript=full_text,
            one_sentence_summary=summary.one_sentence_summary,
            key_points=summary.key_points,
            chapters=[{
                "title": c.title,
                "start_time": c.start_time,
                "end_time": c.end_time,
                "summary": c.summary
            } for c in summary.chapters]
        )
        md = self._call_llm_text(prompt)
        text = md.strip()
        if text.startswith("```"):
            end_idx = text.rfind("```")
            if end_idx != -1:
                inner = text[text.find("\n")+1:end_idx]
                return inner.strip()
        return text

    def generate_extractive_notes(self, transcript: Transcript, metadata: VideoMetadata) -> str:
        lines = []
        lines.append(f"# {metadata.title}")
        lines.append(f"\n> 作者：{metadata.author}\n")
        lines.append("## 提取式要点（基于原文）")
        total = len(transcript.segments)
        if total == 0:
            return "\n".join(lines)
        window = max(1, total // 8)
        key_points = []
        for i in range(0, total, window):
            segs = transcript.segments[i:i+window]
            if not segs:
                continue
            snippet = "，".join([s.text.strip() for s in segs[:3] if s.text.strip()])
            if snippet:
                key_points.append(snippet)
        for kp in key_points[:10]:
            lines.append(f"- {kp}")
        lines.append("\n## 分段摘要（按时序）")
        current_start = transcript.segments[0].start
        bucket = []
        bucket_dur = 180
        for s in transcript.segments:
            if (s.start - current_start) > bucket_dur and bucket:
                part = "；".join([b.text.strip() for b in bucket if b.text.strip()])
                lines.append(f"- {part}")
                current_start = s.start
                bucket = []
            bucket.append(s)
        if bucket:
            part = "；".join([b.text.strip() for b in bucket if b.text.strip()])
            lines.append(f"- {part}")
        return "\n".join(lines)
