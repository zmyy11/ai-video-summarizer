from typing import Optional
from pydantic import BaseModel

class VideoMetadata(BaseModel):
    id: str
    title: str
    author: str
    duration: float
    platform: str
    url: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
