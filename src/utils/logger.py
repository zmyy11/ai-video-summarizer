import logging
import sys
from rich.logging import RichHandler
from src.config import settings

def setup_logger(name: str = "ai_video_summarizer") -> logging.Logger:
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)]
    )
    return logging.getLogger(name)

logger = setup_logger()
