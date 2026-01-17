from src.providers.bilibili import BilibiliProvider
from src.utils.logger import logger

if __name__ == "__main__":
    url = "https://www.bilibili.com/video/BV1gKiEBZEHq?p=1"
    cookies = ".cache/generated_cookies.txt"
    p = BilibiliProvider()
    try:
        t = p.get_transcript(url, allow_asr=False, cookies_path=cookies)
        print("language:", t.language)
        print("segments:", len(t.segments))
        for s in t.segments[:5]:
            print(f"[{s.start:.2f} -> {s.end:.2f}] {s.text}")
    except Exception as e:
        logger.error(f"Transcript fetch failed: {e}")
        raise