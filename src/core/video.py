from abc import ABC, abstractmethod
from typing import Optional
from src.models.transcript import Transcript
from src.models.video import VideoMetadata

class VideoSource(ABC):
    @abstractmethod
    def extract_info(self, url: str, cookies_path: Optional[str] = None) -> VideoMetadata:
        """Extract video metadata."""
        pass

    @abstractmethod
    def get_transcript(self, url: str, allow_asr: bool = False, cookies_path: Optional[str] = None) -> Transcript:
        """Get video transcript."""
        pass
