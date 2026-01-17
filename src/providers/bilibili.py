import os
# 移除顶层 whisper 以防未安装时报错
import requests
import json
import yt_dlp
import http.cookiejar as cookiejar
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs
from src.core.video import VideoSource
from src.models.video import VideoMetadata
from src.models.transcript import Transcript, Segment
from src.utils.logger import logger
from src.config import settings

class BilibiliProvider(VideoSource):
    def extract_info(self, url: str, cookies_path: Optional[str] = None) -> VideoMetadata:
        opts = {'quiet': True}
        if cookies_path:
            opts['cookiefile'] = cookies_path

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return VideoMetadata(
                    id=info.get('id'),
                    title=info.get('title'),
                    author=info.get('uploader', 'Unknown'),
                    duration=info.get('duration', 0),
                    platform='bilibili',
                    url=info.get('webpage_url', url),
                    description=info.get('description'),
                    thumbnail_url=info.get('thumbnail')
                )
        except Exception as e:
            if "KeyError" in str(e) and "bvid" in str(e):
                logger.warning(f"yt-dlp encountered a Bilibili specific error: {e}. Retrying with 'referer' header hack...")
                raise ValueError(f"Failed to extract video info. Bilibili API change or video unavailable. Error: {e}")
            raise e

    def get_transcript(self, url: str, allow_asr: bool = False, cookies_path: Optional[str] = None) -> Transcript:
        # 若显式要求使用 ASR，则直接走 Whisper
        if allow_asr:
            logger.info("Using Whisper ASR due to --use-whisper flag...")
            return self._transcribe_with_whisper(url, cookies_path)
        # 先尝试官方字幕；失败则自动回退到 Whisper
        try:
            return self._get_official_transcript(url, cookies_path)
        except Exception as e:
            logger.info(f"Official subtitles unavailable ({e}). Falling back to Whisper ASR...")
            return self._transcribe_with_whisper(url, cookies_path)

    def _get_official_transcript(self, url: str, cookies_path: Optional[str] = None) -> Transcript:
        # Parse page index from URL (Bilibili multi-part videos use ?p=2 for page 2)
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        page_index = int(qs.get('p', ['1'])[0])

        opts = {
            'quiet': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'skip_download': True,
        }
        if cookies_path:
            opts['cookiefile'] = cookies_path

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Select correct entry for multi-part videos
                info_selected = info
                if 'entries' in info and isinstance(info['entries'], list) and info['entries']:
                    entries = info['entries']
                    # Try match by playlist_index first
                    entry = next((e for e in entries if e.get('playlist_index') == page_index), None)
                    if not entry:
                        # Try match by url
                        entry = next((e for e in entries if e.get('webpage_url') == url), None)
                    if not entry:
                        # Default to first entry
                        entry = entries[0]
                    info_selected = entry

                # bvid determination
                bvid = (info.get('id') or info_selected.get('id') or parsed.path.rstrip('/').split('/')[-1].split('?')[0])

                # Check for subtitles on selected entry or top-level
                subs = info_selected.get('subtitles') or info_selected.get('automatic_captions')
                if not subs:
                    subs = info.get('subtitles') or info.get('automatic_captions')
                if not subs:
                    raise ValueError("No subtitles found for this Bilibili video.")

                logger.info(f"Found subtitle languages: {list(subs.keys())}")

                # Collect subtitle candidates from entire dictionary
                sub_url = None
                fmt = None
                selected_lang = 'unknown'
                fmt_prefs = ['json', 'json3', 'vtt', 'srt']

                candidates = []  # (lang, url, ext)

                # Helper to find url in nested structure
                def find_urls(items, lang):
                    items_list = items if isinstance(items, list) else [items]
                    for it in items_list:
                        if isinstance(it, dict) and it.get('url'):
                            ext = (it.get('ext') or '').lower()
                            candidates.append((lang, it['url'], ext))

                for lang, items in subs.items():
                    find_urls(items, lang)

                logger.info(f"Extracted {len(candidates)} subtitle candidates.")

                # Prefer non-XML candidates; if none, query Bilibili API for subtitle_url
                non_xml_candidates = [c for c in candidates if c[2] != 'xml']
                if not non_xml_candidates:
                    headers = {
                        'Referer': 'https://www.bilibili.com',
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                    session = requests.Session()
                    if cookies_path:
                        try:
                            cj = cookiejar.MozillaCookieJar()
                            cj.load(cookies_path, ignore_discard=True, ignore_expires=True)
                            session.cookies = cj
                            logger.info("Loaded cookies for Bilibili API requests")
                        except Exception as e:
                            logger.warning(f"Failed to load cookies from {cookies_path}: {e}")
                    # cid determination from selected info
                    cid = info_selected.get('cid') or info.get('cid')
                    if not cid:
                        view_resp = session.get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}', headers=headers)
                        view_resp.raise_for_status()
                        view_data = view_resp.json().get('data', {})
                        # If multi pages, try to map to correct page
                        if view_data.get('pages'):
                            if 1 <= page_index <= len(view_data['pages']):
                                cid = view_data['pages'][page_index - 1].get('cid')
                        cid = cid or view_data.get('cid')
                    if cid:
                        player_resp = session.get(f'https://api.bilibili.com/x/player/v2?cid={cid}&bvid={bvid}', headers=headers)
                        player_resp.raise_for_status()
                        pdata = player_resp.json().get('data', {})
                        subs_list = pdata.get('subtitle', {}).get('subtitles') or pdata.get('subtitle', {}).get('list') or []
                        added = 0
                        for s in subs_list:
                            lan = s.get('lan') or s.get('lan_doc') or 'unknown'
                            surl = s.get('subtitle_url') or s.get('url')
                            if surl:
                                if surl.startswith('//'):
                                    surl = 'https:' + surl
                                non_xml_candidates.append((lan, surl, 'json'))
                                candidates.append((lan, surl, 'json'))
                                added += 1
                        logger.info(f"Fetched {added} subtitles via Bilibili API")

                # Selection Logic
                lang_prefs = [
                    'zh-CN', 'zh-Hans', 'zh-Hant', 'zh-TW', 'zh-HK', 
                    'zh', 'ai-zh', 'zh_CN', 'zh_Hans',
                    'en-US', 'en'
                ]

                best_score = -1

                for lang, url2, ext in non_xml_candidates or candidates:
                    score = 0
                    # Language score
                    lang_score = 0
                    for i, pref in enumerate(lang_prefs):
                        if pref.lower() == lang.lower():
                            lang_score = 200 - i * 10
                            break
                    if lang_score == 0:
                        if 'zh' in lang.lower() or 'chinese' in lang.lower():
                            lang_score = 50
                        elif 'en' in lang.lower():
                            lang_score = 40
                        else:
                            lang_score = 10
                    score += lang_score

                    # Format score
                    fmt_score = 0
                    if ext in fmt_prefs:
                        fmt_score = 5 - fmt_prefs.index(ext)
                    score += fmt_score

                    if score > best_score:
                        best_score = score
                        sub_url = url2
                        fmt = ext
                        selected_lang = lang

                if not sub_url:
                    logger.warning(f"Could not extract subtitle URL. Candidates: {candidates}")
                    raise ValueError("Could not extract subtitle URL")

                logger.info(f"Fetching subtitles in {selected_lang} ({fmt})...")

                try:
                    headers = {
                        'Referer': 'https://www.bilibili.com',
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    }
                    session = requests.Session()
                    if cookies_path:
                        try:
                            cj = cookiejar.MozillaCookieJar()
                            cj.load(cookies_path, ignore_discard=True, ignore_expires=True)
                            session.cookies = cj
                        except Exception as e:
                            logger.warning(f"Failed to load cookies from {cookies_path}: {e}")
                    resp = session.get(sub_url, headers=headers)
                    resp.raise_for_status()

                    def _parse_timecode(t: str) -> float:
                        # Accept HH:MM:SS.mmm or MM:SS.mmm
                        parts = t.replace(',', '.').split(':')
                        parts = [p.strip() for p in parts]
                        try:
                            if len(parts) == 3:
                                h, m, s = parts
                                return int(h) * 3600 + int(m) * 60 + float(s)
                            elif len(parts) == 2:
                                m, s = parts
                                return int(m) * 60 + float(s)
                            return float(parts[-1])
                        except Exception:
                            return 0.0

                    def _parse_vtt(text: str) -> list:
                        segments = []
                        # Split cues by blank lines
                        for block in re.split(r"\n\s*\n", text.strip()):
                            lines = [l.strip() for l in block.splitlines() if l.strip()]
                            if not lines:
                                continue
                            # Optional cue identifier on first line
                            if '-->' in lines[0]:
                                timing_line = lines[0]
                                content_lines = lines[1:]
                            elif len(lines) > 1 and '-->' in lines[1]:
                                timing_line = lines[1]
                                content_lines = lines[2:]
                            else:
                                continue
                            m = re.search(r"(\d+:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})", timing_line)
                            if not m:
                                continue
                            start = _parse_timecode(m.group(1))
                            end = _parse_timecode(m.group(2))
                            text_content = ' '.join(content_lines).strip()
                            if text_content:
                                segments.append(Segment(start=start, end=end, text=text_content))
                        return segments

                    def _parse_srt(text: str) -> list:
                        segments = []
                        blocks = re.split(r"\n\s*\n", text.strip())
                        for block in blocks:
                            lines = [l.strip() for l in block.splitlines() if l.strip()]
                            if len(lines) < 2:
                                continue
                            # First line may be index
                            timing_idx = 0 if '-->' in lines[0] else 1
                            if timing_idx >= len(lines):
                                continue
                            timing_line = lines[timing_idx]
                            m = re.search(r"(\d+:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d+:\d{2}:\d{2}[\.,]\d{3}|\d{2}:\d{2}[\.,]\d{3})", timing_line)
                            if not m:
                                continue
                            start = _parse_timecode(m.group(1))
                            end = _parse_timecode(m.group(2))
                            content_lines = lines[timing_idx + 1:]
                            text_content = ' '.join(content_lines).strip()
                            if text_content:
                                segments.append(Segment(start=start, end=end, text=text_content))
                        return segments

                    segments = []
                    if fmt == 'json':
                        data = resp.json()
                        body = data.get('body', [])
                        for item in body:
                            segments.append(Segment(
                                start=float(item.get('from', 0.0)),
                                end=float(item.get('to', item.get('from', 0.0))),
                                text=(item.get('content') or '').strip()
                            ))
                    elif fmt == 'json3':
                        data = resp.json()
                        # Try YouTube-like json3 structure
                        events = data.get('events') or []
                        for ev in events:
                            start_ms = ev.get('tStartMs', 0)
                            dur_ms = ev.get('dDurationMs', 0)
                            seg_texts = []
                            for seg in ev.get('segs') or []:
                                if isinstance(seg, dict) and seg.get('utf8'):
                                    seg_texts.append(seg['utf8'].strip())
                            text_content = ' '.join(seg_texts).strip()
                            if text_content:
                                segments.append(Segment(start=start_ms/1000.0, end=(start_ms+dur_ms)/1000.0, text=text_content))
                    elif fmt == 'vtt':
                        segments = _parse_vtt(resp.text)
                    elif fmt == 'srt':
                        segments = _parse_srt(resp.text)
                    elif 'xml' in sub_url or fmt == 'xml':
                        logger.warning("Got an XML file (likely Danmaku) instead of subtitles. Skipping as it is not a proper transcript.")
                        raise ValueError("No valid closed captions found (only found Danmaku XML).")
                    else:
                        # 最后兜底尝试 vtt/srt 文本解析
                        parsed = _parse_vtt(resp.text)
                        if not parsed:
                            parsed = _parse_srt(resp.text)
                        segments = parsed

                    if not segments:
                        raise ValueError(f"Parsed zero subtitle segments for format {fmt}.")

                    return Transcript(
                        video_id=bvid,
                        language=selected_lang,
                        segments=segments
                    )

                except Exception as e:
                    logger.error(f"Failed to download/parse subtitles: {e}")
                    raise
        except Exception as e:
            raise e

    def _transcribe_with_whisper(self, url: str, cookies_path: Optional[str] = None) -> Transcript:
        """Download audio and transcribe using OpenAI Whisper."""
        try:
            import whisper
        except ImportError:
            raise ImportError("openai-whisper is not installed. Run `uv add openai-whisper`.")

        video_id = url.split('/')[-1] # Simple ID extraction
        # Normalize video ID to avoid path issues
        if "BV" in video_id:
            video_id = video_id.split('?')[0]

        audio_path = os.path.join(settings.CACHE_DIR, f"{video_id}.mp3")

        # A. Download Audio
        if not os.path.exists(audio_path):
            logger.info("Downloading audio for ASR...")
            opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(settings.CACHE_DIR, f"{video_id}.%(ext)s"),
                'quiet': True,
            }
            if cookies_path:
                opts['cookiefile'] = cookies_path

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        # B. Transcribe
        logger.info("Transcribing audio with Whisper (this may take a while)...")
        # Use 'base' or 'small' model for speed on CPU/Mac
        model = whisper.load_model("base") 
        result = model.transcribe(audio_path)

        # C. Convert to Segments
        segments = []
        for seg in result['segments']:
            segments.append(Segment(
                start=seg['start'],
                end=seg['end'],
                text=seg['text'].strip()
            ))

        return Transcript(
            video_id=video_id,
            language=result.get('language', 'unknown'),
            source="asr_whisper",
            segments=segments
        )
