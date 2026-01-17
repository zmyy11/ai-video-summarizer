from typing import List, Optional
from pydantic import BaseModel

class ChunkSummary(BaseModel):
    start_time: float
    end_time: float
    key_points: List[str]
    entities: Optional[List[str]] = []

class KeyFrame(BaseModel):
    timestamp: float
    description: str
    image_path: Optional[str] = None  # Local path to extracted image

class Chapter(BaseModel):
    title: str
    start_time: float
    end_time: float
    summary: List[str]  # Bullet points
    keyframes: Optional[List[KeyFrame]] = []

class Quote(BaseModel):
    text: str
    timestamp: float

class SummaryResult(BaseModel):
    one_sentence_summary: str
    key_points: List[str]
    chapters: List[Chapter]
    quotes: List[Quote]
