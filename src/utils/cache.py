import hashlib
import json
import os
from typing import Any, Optional
from src.config import settings
from src.utils.logger import logger

class CacheManager:
    def __init__(self):
        self.cache_dir = settings.CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(os.path.join(self.cache_dir, "transcripts"), exist_ok=True)
        os.makedirs(os.path.join(self.cache_dir, "summaries"), exist_ok=True)

    def _get_hash(self, key_data: str) -> str:
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get_transcript(self, video_id: str) -> Optional[dict]:
        path = os.path.join(self.cache_dir, "transcripts", f"{video_id}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load transcript cache: {e}")
        return None

    def save_transcript(self, video_id: str, data: dict):
        path = os.path.join(self.cache_dir, "transcripts", f"{video_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_summary(self, key_data: str) -> Optional[dict]:
        key_hash = self._get_hash(key_data)
        path = os.path.join(self.cache_dir, "summaries", f"{key_hash}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    logger.info("Hit summary cache!")
                    return json.load(f)
            except Exception:
                pass
        return None

    def save_summary(self, key_data: str, data: dict):
        key_hash = self._get_hash(key_data)
        path = os.path.join(self.cache_dir, "summaries", f"{key_hash}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

cache_manager = CacheManager()
