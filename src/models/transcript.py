from typing import List, Literal, Optional
from pydantic import BaseModel

class Segment(BaseModel):
    start: float
    end: float
    text: str

class Transcript(BaseModel):
    video_id: str
    language: str
    source: Literal["platform_caption", "asr_whisper"] = "platform_caption"
    segments: List[Segment]
