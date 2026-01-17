import tiktoken
from typing import List
from src.models.transcript import Segment, Transcript
from src.utils.logger import logger

class Chunker:
    def __init__(self, model_name: str = "gpt-4o", max_tokens: int = 3000):
        self.max_tokens = max_tokens
        try:
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def pre_aggregate(self, segments: List[Segment], min_duration: float = 20.0) -> List[Segment]:
        """Merge small adjacent segments to reduce fragmentation."""
        if not segments:
            return []
        
        merged = []
        current = segments[0]

        for next_seg in segments[1:]:
            duration = current.end - current.start
            # If current is short or gap is small, merge
            if duration < min_duration:
                current = Segment(
                    start=current.start,
                    end=next_seg.end,
                    text=f"{current.text} {next_seg.text}".strip()
                )
            else:
                merged.append(current)
                current = next_seg
        
        merged.append(current)
        return merged

    def chunk(self, transcript: Transcript) -> List[List[Segment]]:
        """Split transcript into chunks of segments based on token limit."""
        segments = self.pre_aggregate(transcript.segments)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for seg in segments:
            seg_tokens = self.count_tokens(seg.text)
            
            if current_tokens + seg_tokens > self.max_tokens and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            
            current_chunk.append(seg)
            current_tokens += seg_tokens
        
        if current_chunk:
            chunks.append(current_chunk)
            
        logger.info(f"Split transcript into {len(chunks)} chunks.")
        return chunks
