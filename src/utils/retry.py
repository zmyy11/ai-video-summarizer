from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import openai
import requests
from src.config import settings

def api_retry():
    return retry(
        stop=stop_after_attempt(settings.MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            openai.APIConnectionError, 
            openai.RateLimitError, 
            openai.APITimeoutError,
            requests.exceptions.RequestException
        ))
    )
